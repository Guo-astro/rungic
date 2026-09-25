package dev.moto.plasma;

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
import android.view.ViewConfiguration;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import com.winland.server.NativeBridge;

/**
 * The assistant's screen fullscreen on the phone (docs/65). The host presents the output's frames
 * straight into this SurfaceView, turned a quarter clockwise and fitted (zero-copy, as on a TV), so
 * nothing records or draws them again: the Linux floating window recorded the output and drew it
 * in a full-screen layer, which KWin composited once more, at about 29 fps.
 *
 * Above the picture lies a transparent layer turned the same way, so touches and the toolbar work
 * in the landscape view the user holds. It is a panel window of its own: the host's zero-copy layer
 * sits above everything else drawn in the activity's window, which covered a toolbar there. tap = click, long press = right click, drag = drag, two
 * fingers = scroll; a swipe up starting in its bottom strip (the phone's left edge) shows the
 * toolbar (leave, TV, close) for three seconds, while a tap there still clicks.
 */
final class AgentFullscreen implements SurfaceHolder.Callback {
    interface Host {
        void bindPresenter(String owner, android.view.Surface surface, int width, int height, int rotation);
        void releasePresenter(String owner);
        void leaveFullscreen();
        void castToTv();
        void closeAgentScreen();
    }

    private static final int BTN_LEFT = 0x110, BTN_RIGHT = 0x111;
    private final Activity activity;
    private final FrameLayout parent;
    private final Host host;
    private final int agentWidth, agentHeight;
    private final Handler main = new Handler(Looper.getMainLooper());
    private FrameLayout root;
    private SurfaceView surface;
    private FrameLayout panel;
    private Landscape landscape;
    private boolean bound;

    AgentFullscreen(Activity activity, FrameLayout parent, int agentWidth, int agentHeight, Host host) {
        this.activity = activity;
        this.parent = parent;
        this.host = host;
        this.agentWidth = agentWidth;
        this.agentHeight = agentHeight;
    }

    boolean shown() { return root != null; }

    void show() {
        if (root != null) return;
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
        NativeBridge.castPointer(0, 1, 0);  // the host pointer lives on the assistant's screen
        // KWin binds its pointer only after seeing the new capability, and the first motion
        // enters: a first tap's press came before that and was lost. Enter now, in the centre.
        main.postDelayed(() -> { if (bound) NativeBridge.castPointer(5, agentWidth / 2f, agentHeight / 2f); }, 300);
    }

    @Override public void surfaceDestroyed(SurfaceHolder holder) {
        if (!bound) return;
        bound = false;
        NativeBridge.castPointer(0, 0, 0);
        host.releasePresenter("fullscreen");
    }

    private float dp(float value) {
        return TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, activity.getResources().getDisplayMetrics());
    }

    /** The landscape view: the phone's size turned, over the picture, taking the touches. */
    private final class Landscape extends FrameLayout {
        private final LinearLayout toolbar;
        private final Runnable hideToolbar = this::fadeToolbar;
        private final int touchSlop = ViewConfiguration.get(getContext()).getScaledTouchSlop();
        private final float swipeZone = dp(56);
        private float downX, downY, lastX, lastY;
        private boolean moved, dragging, scrolling, swipe, longPressed;
        private final Runnable longPress = () -> {
            longPressed = true;
            click(downX, downY, BTN_RIGHT);
        };

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
            toolbar.addView(button(Icon.TV, host::castToTv));
            toolbar.addView(button(Icon.CLOSE, host::closeAgentScreen));
            toolbar.setVisibility(View.GONE);
            FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(-2, (int) dp(46), Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
            lp.bottomMargin = (int) dp(20);
            addView(toolbar, lp);
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
        }

        private View button(Icon icon, Runnable action) {
            View view = new IconView(getContext(), icon);
            view.setOnClickListener(v -> { showToolbar(); action.run(); });
            view.setLayoutParams(new LinearLayout.LayoutParams((int) dp(42), (int) dp(34)));
            return view;
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

        /** Landscape position -> the assistant's screen, in its pixels (the picture is fitted, centred). */
        private float[] toAgent(float x, float y) {
            float scale = Math.min(getWidth() / (float) agentWidth, getHeight() / (float) agentHeight);
            float left = (getWidth() - agentWidth * scale) / 2, top = (getHeight() - agentHeight * scale) / 2;
            return new float[] {
                Math.max(0, Math.min(agentWidth - 1, (x - left) / scale)),
                Math.max(0, Math.min(agentHeight - 1, (y - top) / scale))};
        }

        private void pointTo(float x, float y) {
            float[] p = toAgent(x, y);
            NativeBridge.castPointer(5, p[0], p[1]);
        }

        /** A press and, a moment later, its release: a release in the same instant as the press was
         *  ignored by some controls (the panel's application launcher). */
        private void click(float x, float y, int button) {
            pointTo(x, y);
            NativeBridge.castPointer(2, button, 1);
            main.postDelayed(() -> NativeBridge.castPointer(2, button, 0), 40);
        }

        @Override public boolean onTouchEvent(MotionEvent e) {
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    downX = lastX = e.getX();
                    downY = lastY = e.getY();
                    moved = dragging = scrolling = longPressed = false;
                    // From the bottom strip an upward swipe shows the toolbar; a tap or a long
                    // press there still reaches the screen (its taskbar lies there).
                    swipe = downY > getHeight() - swipeZone;
                    main.postDelayed(longPress, ViewConfiguration.getLongPressTimeout());
                    return true;
                case MotionEvent.ACTION_POINTER_DOWN:
                    main.removeCallbacks(longPress);
                    if (dragging) { NativeBridge.castPointer(2, BTN_LEFT, 0); dragging = false; }
                    scrolling = true;
                    pointTo(centroidX(e), centroidY(e));
                    lastX = centroidX(e);
                    lastY = centroidY(e);
                    return true;
                case MotionEvent.ACTION_MOVE: {
                    float x = scrolling ? centroidX(e) : e.getX(), y = scrolling ? centroidY(e) : e.getY();
                    if (!moved && Math.hypot(x - downX, y - downY) > touchSlop) {
                        moved = true;
                        main.removeCallbacks(longPress);
                        if (!scrolling && !swipe && !longPressed) {
                            pointTo(downX, downY);
                            NativeBridge.castPointer(2, BTN_LEFT, 1);
                            dragging = true;
                        }
                    }
                    if (swipe) {
                        if (downY - y > dp(20)) showToolbar();
                    } else if (scrolling) {
                        float scale = Math.min(getWidth() / (float) agentWidth, getHeight() / (float) agentHeight);
                        // Natural scrolling, as the TV touchpad does (CastControls).
                        NativeBridge.castPointer(3, -(x - lastX) / scale * 1.5f, -(y - lastY) / scale * 1.5f);
                    } else if (dragging) {
                        pointTo(x, y);
                    }
                    lastX = x;
                    lastY = y;
                    return true;
                }
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    main.removeCallbacks(longPress);
                    if (dragging) NativeBridge.castPointer(2, BTN_LEFT, 0);
                    if (scrolling) NativeBridge.castPointer(4, 0, 0);
                    if (!moved && !longPressed && !scrolling && e.getActionMasked() == MotionEvent.ACTION_UP)
                        click(e.getX(), e.getY(), BTN_LEFT);
                    dragging = scrolling = false;
                    return true;
                default:
                    return true;
            }
        }

        private float centroidX(MotionEvent e) {
            float sum = 0;
            for (int i = 0; i < e.getPointerCount(); i++) sum += e.getX(i);
            return sum / e.getPointerCount();
        }

        private float centroidY(MotionEvent e) {
            float sum = 0;
            for (int i = 0; i < e.getPointerCount(); i++) sum += e.getY(i);
            return sum / e.getPointerCount();
        }
    }

    private enum Icon { LEAVE, TV, CLOSE }

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
            if (isPressed()) c.drawCircle(cx, cy, Math.min(cx, cy), pressedPaint);
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
