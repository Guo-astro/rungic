package com.rungic.plasma;

import android.app.Activity;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.LinearLayout;

/**
 * The assistant's screen fullscreen on the phone (docs/65). The host presents the output's frames
 * straight into this SurfaceView, turned a quarter clockwise and fitted (zero-copy, as on a TV), so
 * nothing records or draws them again: the Linux floating window recorded the output and drew it
 * in a full-screen layer, which KWin composited once more, at about 29 fps.
 *
 * Above the picture lies a transparent layer turned the same way, so touches and the toolbar work
 * in the landscape view the user holds. It is a panel window of its own: the host's zero-copy layer
 * sits above everything else drawn in the activity's window, which covered a toolbar there.
 * Two ways to touch it, switched on the toolbar and remembered: DirectGestures (the finger is the
 * pointer) or TouchpadGestures (the finger moves the pointer, 1:1 under it when slow; docs/66). A
 * swipe up starting in its bottom strip (the phone's left edge) shows the toolbar (leave, touchpad,
 * TV, close) for three seconds, while a tap there still clicks.
 *
 * The director fullscreen (docs/58): the assistant's screens together, laid out as on a TV (the
 * host puts each in its tile, Director), its focus large. Touches in the focus work it as above;
 * a tap on another screen puts that one in focus; the toolbar's zoom button makes the focus
 * larger (standard, enlarged, solo). The names of the screens are drawn on this layer.
 */
final class AgentFullscreen implements SurfaceHolder.Callback {
    interface Host {
        void bindPresenter(String owner, android.view.Surface surface, int width, int height, int rotation);
        void releasePresenter(String owner);
        void leaveFullscreen();
        void castToTv();
        void closeAgentScreen();
        /** The director, shown fullscreen when `show(true)`. */
        Director director();
    }

    private final Activity activity;
    private final FrameLayout parent;
    private final Host host;
    private final int agentWidth, agentHeight;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final PointerOutput pointer = new PointerOutput(main);
    private FrameLayout root;
    private SurfaceView surface;
    private FrameLayout panel;
    private Landscape landscape;
    private boolean bound;
    private boolean touchpad;
    /** Fullscreen shows the director (all the assistant's screens), not one. */
    private boolean directing;
    private final Runnable layoutChanged = () -> { if (landscape != null) landscape.directorChanged(); };

    AgentFullscreen(Activity activity, FrameLayout parent, int agentWidth, int agentHeight, Host host) {
        this.activity = activity;
        this.parent = parent;
        this.host = host;
        this.agentWidth = agentWidth;
        this.agentHeight = agentHeight;
        touchpad = activity.getPreferences(Context.MODE_PRIVATE).getBoolean("agent_fullscreen_touchpad", false);
    }

    boolean shown() { return root != null; }
    boolean directing() { return root != null && directing; }

    void show() { show(false); }

    void show(boolean director) {
        if (root != null) return;
        directing = director;
        if (directing) host.director().addListener(layoutChanged);
        root = new FrameLayout(activity);
        root.setBackgroundColor(Color.BLACK);
        surface = new SurfaceView(activity);
        surface.setZOrderMediaOverlay(true);  // above the desktop's own SurfaceView
        surface.getHolder().addCallback(this);
        root.addView(surface, new FrameLayout.LayoutParams(-1, -1));
        parent.addView(root, new FrameLayout.LayoutParams(-1, -1));
        panel = new FrameLayout(activity);
        landscape = new Landscape(activity);
        panel.addView(landscape, new FrameLayout.LayoutParams(-1, -1));
        // The turned layer is sized once the phone's size is known.
        panel.addOnLayoutChangeListener((v, l, t, r, b, ol, ot, or, ob) -> landscape.fit(r - l, b - t));
        android.view.WindowManager.LayoutParams lp = new android.view.WindowManager.LayoutParams(-1, -1,
            android.view.WindowManager.LayoutParams.TYPE_APPLICATION_PANEL,
            android.view.WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN | android.view.WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            android.graphics.PixelFormat.TRANSLUCENT);
        lp.setFitInsetsTypes(0);
        lp.layoutInDisplayCutoutMode = android.view.WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
        lp.setTitle("PlasmaAgentFullscreen");
        activity.getWindowManager().addView(panel, lp);  // a sub-window of the activity's
    }

    void hide() {
        if (root == null) return;
        if (directing) host.director().removeListener(layoutChanged);
        main.removeCallbacksAndMessages(null);
        activity.getWindowManager().removeView(panel);
        parent.removeView(root);  // surfaceDestroyed releases the presenter
        root = null;
        surface = null;
        panel = null;
        landscape = null;
    }

    @Override public void surfaceCreated(SurfaceHolder holder) {}

    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
        host.bindPresenter("fullscreen", holder.getSurface(), width, height, 90);
        bound = true;
        pointer.attach(true);  // the host pointer lives on the assistant's screen
        // KWin binds its pointer only after seeing the new capability, and the first motion
        // enters: a first tap's press came before that and was lost. Enter now, in the centre.
        main.postDelayed(() -> { if (bound) pointer.moveTo(agentWidth / 2f, agentHeight / 2f); }, 300);
    }

    @Override public void surfaceDestroyed(SurfaceHolder holder) {
        if (!bound) return;
        bound = false;
        pointer.attach(false);
        host.releasePresenter("fullscreen");
    }

    private float dp(float value) {
        return TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, activity.getResources().getDisplayMetrics());
    }

    /** The landscape view: the phone's size turned, over the picture, taking the touches. */
    private final class Landscape extends FrameLayout {
        private final LinearLayout toolbar;
        private final IconView modeButton;
        private final Runnable hideToolbar = this::fadeToolbar;
        private final float swipeZone = dp(56), swipeDistance = dp(20);
        private final PointerOutput out = pointer;
        private DirectGestures direct;
        private TouchpadGestures pad;
        // A touch from the bottom strip is held back until it shows its way: up, the toolbar;
        // anything else, the gestures (from where it started); a tap there still clicks.
        private boolean fromStrip, stripDecided, toToolbar;
        private float downX, downY;

        Landscape(Context context) {
            super(context);
            toolbar = new LinearLayout(context);
            toolbar.setOrientation(LinearLayout.HORIZONTAL);
            toolbar.setGravity(Gravity.CENTER);
            int pad = (int) dp(6);
            toolbar.setPadding(pad, pad, pad, pad);
            GradientDrawable capsule = new GradientDrawable();
            capsule.setColor(Color.argb(214, 28, 31, 38));
            capsule.setStroke((int) Math.max(1, dp(0.7f)), Color.argb(41, 255, 255, 255));
            capsule.setCornerRadius(dp(23));
            toolbar.setBackground(capsule);
            toolbar.addView(button(Icon.LEAVE, host::leaveFullscreen));
            if (directing) toolbar.addView(button(Icon.ZOOM, () -> {
                Director d = host.director();
                d.setLevel((d.level() + 1) % 3);
            }));
            modeButton = new IconView(context, Icon.TOUCHPAD);
            modeButton.setOnClickListener(v -> { showToolbar(); setTouchpad(!touchpad); });
            modeButton.setLayoutParams(new LinearLayout.LayoutParams((int) dp(42), (int) dp(34)));
            modeButton.setSelected(touchpad);
            toolbar.addView(modeButton);
            toolbar.addView(button(Icon.TV, host::castToTv));
            toolbar.addView(button(Icon.CLOSE, host::closeAgentScreen));
            toolbar.setVisibility(View.GONE);
            FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(-2, (int) dp(46), Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
            lp.bottomMargin = (int) dp(20);
            addView(toolbar, lp);
            setWillNotDraw(false);
            label.setColor(Color.WHITE);
            label.setTextSize(dp(12));
            chip.setColor(Color.argb(214, 21, 24, 26));
            outline.setStyle(Paint.Style.STROKE);
            outline.setStrokeWidth(dp(2));
            outline.setColor(0xFF3DAEE9);
        }

        private final Paint label = new Paint(Paint.ANTI_ALIAS_FLAG), chip = new Paint(Paint.ANTI_ALIAS_FLAG),
            outline = new Paint(Paint.ANTI_ALIAS_FLAG), dimPaint = new Paint();
        private boolean touching, regesture;
        /** A tap on another screen of the director: which, or -1. */
        private int tapSlot = -1;

        /** The director's tile in this layer's pixels (its fractions are of the whole turned window). */
        private RectF tileRect(float[] t) {
            float w = getWidth(), h = getHeight();
            return new RectF(t[0] * w, t[1] * h, (t[0] + t[2]) * w, (t[1] + t[3]) * h);
        }

        /** The director moved its tiles: names redrawn, the focus's touches mapped anew. */
        private float[][] mappedTiles;

        void directorChanged() {
            invalidate();
            // Only a new layout maps the touches anew (the settling focus only redraws).
            float[][] tiles = host.director().tiles();
            if (tiles == mappedTiles) return;
            mappedTiles = tiles;
            if (touching) regesture = true;
            else gestures(getWidth(), getHeight());
        }

        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            if (!directing) return;
            Director d = host.director();
            float[][] tiles = d.tiles();
            int[] slots = d.tileSlots();
            if (tiles.length == 1 && d.settle() > 0) {
                dimPaint.setAlpha(Math.round(255 * d.settle()));
                canvas.drawRect(tileRect(tiles[0]), dimPaint);
            }
            if (tiles.length < 2) return;
            for (int i = 0; i < tiles.length; i++) {
                RectF r = tileRect(tiles[i]);
                if (i == 0) {
                    // A new focus brightens in (Director.settle()).
                    float dim = d.settle();
                    if (dim > 0) { dimPaint.setAlpha(Math.round(255 * dim)); canvas.drawRect(r, dimPaint); }
                    canvas.drawRoundRect(r.left - dp(2), r.top - dp(2), r.right + dp(2), r.bottom + dp(2), dp(4), dp(4), outline);
                }
                if (i > 0 && d.level() == Director.ENLARGED) continue;   // the strip is too thin for names
                String name = d.label(slots[i]);
                float pad = dp(6), tw = label.measureText(name);
                Paint.FontMetrics m = label.getFontMetrics();
                RectF box = new RectF(r.left + dp(6), r.bottom - dp(6) - (m.descent - m.ascent) - pad, r.left + dp(6) + tw + 2 * pad, r.bottom - dp(6));
                canvas.drawRoundRect(box, dp(8), dp(8), chip);
                canvas.drawText(name, box.left + pad, box.bottom - pad / 2 - m.descent, label);
            }
        }

        private int fitWidth, fitHeight;

        /** Size and turn this layer to cover the phone's `width` x `height` in landscape. */
        void fit(int width, int height) {
            if (width <= 0 || height <= 0 || (width == fitWidth && height == fitHeight)) return;
            fitWidth = width;
            fitHeight = height;
            FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(height, width);
            setLayoutParams(lp);
            setPivotX(0);
            setPivotY(0);
            setRotation(90);
            setTranslationX(width);  // after turning about the top-left corner, back onto the screen
            gestures(height, width);
        }

        /**
         * The gestures for a `width` x `height` landscape view: the picture is fitted and centred;
         * in the director, the focus's tile is the picture.
         */
        private void gestures(int width, int height) {
            if (width <= 0 || height <= 0) return;
            float scale = Math.min(width / (float) agentWidth, height / (float) agentHeight);
            float left = (width - agentWidth * scale) / 2, top = (height - agentHeight * scale) / 2;
            float[][] tiles = directing ? host.director().tiles() : new float[0][];
            if (tiles.length > 0 && getWidth() > 0) {
                RectF focus = tileRect(tiles[0]);
                scale = focus.width() / agentWidth;
                left = focus.left;
                top = focus.top;
            }
            final float mapScale = scale, mapLeft = left, mapTop = top;
            float phonePxPerMm = activity.getResources().getDisplayMetrics().xdpi / 25.4f;
            DirectGestures.Mapper mapper = (x, y, mapped) -> {
                mapped[0] = Math.max(0, Math.min(agentWidth - 1, (x - mapLeft) / mapScale));
                mapped[1] = Math.max(0, Math.min(agentHeight - 1, (y - mapTop) / mapScale));
            };
            if (direct != null) direct.reset();
            if (pad != null) pad.reset();
            direct = new DirectGestures(out, mapper, main, phonePxPerMm, 1 / scale);
            // Touchpad on the picture itself: unity is 1:1 under the finger.
            pad = new TouchpadGestures(out, new PointerTransfer(phonePxPerMm, phonePxPerMm / scale), main);
        }

        private View button(Icon icon, Runnable action) {
            View view = new IconView(getContext(), icon);
            view.setOnClickListener(v -> { showToolbar(); action.run(); });
            view.setLayoutParams(new LinearLayout.LayoutParams((int) dp(42), (int) dp(34)));
            return view;
        }

        /** Touchpad (the finger moves the pointer) or direct (the finger is the pointer). */
        private void setTouchpad(boolean on) {
            if (pad != null) pad.reset();
            if (direct != null) direct.reset();
            touchpad = on;
            modeButton.setSelected(on);
            activity.getPreferences(Context.MODE_PRIVATE).edit().putBoolean("agent_fullscreen_touchpad", on).apply();
        }

        private void fadeToolbar() {
            toolbar.animate().alpha(0f).setDuration(180).withEndAction(() -> toolbar.setVisibility(View.GONE)).start();
        }

        private void showToolbar() {
            main.removeCallbacks(hideToolbar);
            if (toolbar.getVisibility() != View.VISIBLE) {
                toolbar.setAlpha(0f);
                toolbar.setTranslationY(dp(8));
                toolbar.setVisibility(View.VISIBLE);
            }
            toolbar.animate().alpha(1f).translationY(0).setDuration(180).start();
            main.postDelayed(hideToolbar, 3000);
        }

        @Override public boolean onTouchEvent(MotionEvent e) {
            if (direct == null) return true;  // not laid out yet
            int action = e.getActionMasked();
            touching = action != MotionEvent.ACTION_UP && action != MotionEvent.ACTION_CANCEL;
            if (!touching && regesture) {
                regesture = false;
                main.post(() -> gestures(getWidth(), getHeight()));
            }
            // The director: a tap on another screen puts it in focus.
            if (directing && action == MotionEvent.ACTION_DOWN) {
                tapSlot = -1;
                float[][] tiles = host.director().tiles();
                int[] slots = host.director().tileSlots();
                for (int i = 1; i < tiles.length; i++)
                    if (tileRect(tiles[i]).contains(e.getX(), e.getY())) tapSlot = slots[i];
                if (tapSlot >= 0) { downX = e.getX(); downY = e.getY(); return true; }
            }
            if (tapSlot >= 0) {
                if (action == MotionEvent.ACTION_UP && Math.hypot(e.getX() - downX, e.getY() - downY) < swipeDistance)
                    host.director().setFocus(tapSlot);
                if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) tapSlot = -1;
                return true;
            }
            if (action == MotionEvent.ACTION_DOWN) {
                downX = e.getX();
                downY = e.getY();
                fromStrip = downY > getHeight() - swipeZone;
                stripDecided = !fromStrip;
                toToolbar = false;
            }
            if (toToolbar) return true;
            if (!stripDecided && action == MotionEvent.ACTION_MOVE) {
                float up = downY - e.getY(), side = Math.abs(e.getX() - downX);
                if (e.getPointerCount() == 1 && up > swipeDistance && up > side) {
                    toToolbar = true;
                    showToolbar();
                    if (touchpad) pad.reset(); else direct.reset();
                    return true;
                }
                if (e.getPointerCount() == 1 && Math.hypot(up, side) <= swipeDistance) return true;
                stripDecided = true;  // not the toolbar: the gestures take it from here
            }
            return touchpad ? pad.onTouchEvent(e) : direct.onTouchEvent(e);
        }
    }

    private enum Icon { LEAVE, ZOOM, TOUCHPAD, TV, CLOSE }

    /** A white line icon on a round press highlight. */
    private final class IconView extends View {
        private final Icon icon;
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint pressedPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

        IconView(Context context, Icon icon) {
            super(context);
            this.icon = icon;
            paint.setColor(Color.WHITE);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(dp(1.8f));
            paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setStrokeJoin(Paint.Join.ROUND);
            pressedPaint.setColor(Color.argb(56, 255, 255, 255));
            setClickable(true);
        }

        @Override protected void drawableStateChanged() {
            super.drawableStateChanged();
            invalidate();
        }

        @Override protected void onDraw(Canvas c) {
            float cx = getWidth() / 2f, cy = getHeight() / 2f, s = dp(9);
            // Pressed, or a mode that is on (the touchpad toggle): a round highlight.
            if (isPressed() || isSelected()) c.drawCircle(cx, cy, Math.min(cx, cy), pressedPaint);
            switch (icon) {
                case LEAVE: {  // four corners pointing inwards
                    float a = s * 0.45f;
                    for (int dx = -1; dx <= 1; dx += 2) {
                        for (int dy = -1; dy <= 1; dy += 2) {
                            float x = cx + dx * s * 0.35f, y = cy + dy * s * 0.35f;
                            c.drawLine(x, y, x + dx * a, y, paint);
                            c.drawLine(x, y, x, y + dy * a, paint);
                        }
                    }
                    break;
                }
                case TOUCHPAD:  // a touchpad with its two buttons
                    c.drawRoundRect(new RectF(cx - s, cy - s * 0.75f, cx + s, cy + s * 0.75f), dp(2.5f), dp(2.5f), paint);
                    c.drawLine(cx - s, cy + s * 0.3f, cx + s, cy + s * 0.3f, paint);
                    c.drawLine(cx, cy + s * 0.3f, cx, cy + s * 0.75f, paint);
                    break;
                case ZOOM:  // a magnifier
                    c.drawCircle(cx - s * 0.2f, cy - s * 0.2f, s * 0.6f, paint);
                    c.drawLine(cx + s * 0.25f, cy + s * 0.25f, cx + s * 0.8f, cy + s * 0.8f, paint);
                    break;
                case TV:
                    c.drawRoundRect(new RectF(cx - s, cy - s * 0.7f, cx + s, cy + s * 0.5f), dp(2), dp(2), paint);
                    c.drawLine(cx - s * 0.45f, cy + s * 0.85f, cx + s * 0.45f, cy + s * 0.85f, paint);
                    break;
                case CLOSE:
                    c.drawLine(cx - s * 0.7f, cy - s * 0.7f, cx + s * 0.7f, cy + s * 0.7f, paint);
                    c.drawLine(cx + s * 0.7f, cy - s * 0.7f, cx - s * 0.7f, cy + s * 0.7f, paint);
                    break;
            }
        }
    }
}
