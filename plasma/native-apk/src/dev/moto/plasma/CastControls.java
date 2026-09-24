package dev.moto.plasma;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import com.winland.server.NativeBridge;
import java.util.function.Consumer;
import org.json.JSONObject;

/**
 * Phone controls while the desktop is cast to a TV (docs/58 step 3). The phone
 * keeps the Plasma Mobile shell; a floating control switches it between
 * "手机" (normal touch), "触控板" (the screen is the TV's touchpad) and "键盘"
 * (touchpad plus the Android keyboard, whose keys reach the focused Linux window).
 * Touchpad gestures: one finger moves, tap clicks, tap then touch again drags,
 * two fingers scroll, two-finger tap right-clicks, three-finger tap middle-clicks.
 */
final class CastControls {
    enum Mode { PHONE, TOUCHPAD, KEYBOARD }

    private static final int BTN_LEFT = 0x110, BTN_RIGHT = 0x111, BTN_MIDDLE = 0x112;
    private static final String[] LABELS = {"手机", "触控板", "键盘"};

    private final Context context;
    private final FrameLayout frame;
    private final Consumer<Boolean> keyboard;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final TouchpadView touchpad;
    private final ControlBar bar;
    private boolean available, imeShown;
    private Mode mode = Mode.PHONE;

    CastControls(Context context, FrameLayout frame, Consumer<Boolean> keyboard) {
        this.context = context;
        this.frame = frame;
        this.keyboard = keyboard;
        touchpad = new TouchpadView(context);
        bar = new ControlBar(context);
    }

    /** The cast window is bound (TV showing the desktop) or gone. */
    void setAvailable(boolean value) {
        if (available == value) return;
        available = value;
        if (!value) setMode(Mode.PHONE);
        if (value) {
            FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(-2, -2, Gravity.END | Gravity.TOP);
            lp.topMargin = frame.getHeight() / 3;
            lp.rightMargin = dp(8);
            frame.addView(bar, lp);
        } else {
            frame.removeView(bar);
        }
        bar.refresh();
    }

    Mode mode() { return mode; }

    void setMode(Mode next) {
        if (!available) next = Mode.PHONE;
        if (next == mode) return;
        Mode previous = mode;
        mode = next;
        boolean pad = next != Mode.PHONE;
        if (pad && touchpad.getParent() == null) {
            // Below the control bar, above the desktop.
            frame.addView(touchpad, frame.indexOfChild(bar) < 0 ? frame.getChildCount() : frame.indexOfChild(bar),
                new FrameLayout.LayoutParams(-1, -1));
        } else if (!pad && touchpad.getParent() != null) {
            touchpad.reset();
            frame.removeView(touchpad);
        }
        if (pad != (previous != Mode.PHONE)) NativeBridge.castPointer(0, pad ? 1 : 0, 0);
        if ((next == Mode.KEYBOARD) != (previous == Mode.KEYBOARD)) keyboard.accept(next == Mode.KEYBOARD);
        bar.refresh();
        touchpad.invalidate();
    }

    /** The Android keyboard was dismissed (back key or its own button). */
    void imeVisible(boolean visible) {
        boolean dismissed = imeShown && !visible;
        imeShown = visible;
        if (dismissed && mode == Mode.KEYBOARD) {
            mode = Mode.TOUCHPAD;
            bar.refresh();
            touchpad.invalidate();
        }
    }

    JSONObject status() throws Exception {
        return new JSONObject().put("available", available).put("mode", mode.name().toLowerCase());
    }

    private int dp(float value) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, context.getResources().getDisplayMetrics()));
    }

    /** Draggable pill: one "投屏" button in phone mode, three segments otherwise. */
    private final class ControlBar extends LinearLayout {
        private final TextView[] segments = new TextView[3];
        private final int slop = ViewConfiguration.get(context).getScaledTouchSlop();
        private float downRawY, startMargin;
        private boolean dragging;

        ControlBar(Context context) {
            super(context);
            setOrientation(VERTICAL);
            setPadding(dp(4), dp(4), dp(4), dp(4));
            GradientDrawable background = new GradientDrawable();
            background.setColor(0xE0202326);
            background.setCornerRadius(dp(22));
            setBackground(background);
            setElevation(dp(6));
            for (int i = 0; i < 3; i++) {
                final Mode target = Mode.values()[i];
                TextView segment = new TextView(context);
                segment.setTextColor(Color.WHITE);
                segment.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
                segment.setGravity(Gravity.CENTER);
                segment.setMinWidth(dp(64));
                segment.setMinHeight(dp(40));
                segment.setPadding(dp(10), 0, dp(10), 0);
                segment.setOnClickListener(v -> setMode(mode == Mode.PHONE ? Mode.TOUCHPAD : target));
                segments[i] = segment;
                addView(segment, new LayoutParams(-2, -2));
            }
        }

        void refresh() {
            boolean phone = mode == Mode.PHONE;
            for (int i = 0; i < 3; i++) {
                TextView segment = segments[i];
                if (phone) {
                    segment.setVisibility(i == 0 ? VISIBLE : GONE);
                    segment.setText("投屏控制");
                    segment.setBackground(null);
                    continue;
                }
                segment.setVisibility(VISIBLE);
                segment.setText(LABELS[i]);
                boolean selected = mode.ordinal() == i;
                GradientDrawable chip = new GradientDrawable();
                chip.setColor(selected ? 0xFF3DAEE9 : Color.TRANSPARENT);
                chip.setCornerRadius(dp(18));
                segment.setBackground(chip);
            }
        }

        // Vertical drag moves the bar; a tap reaches the segment.
        @Override public boolean onInterceptTouchEvent(MotionEvent e) {
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    downRawY = e.getRawY();
                    startMargin = ((FrameLayout.LayoutParams) getLayoutParams()).topMargin;
                    dragging = false;
                    return false;
                case MotionEvent.ACTION_MOVE:
                    if (Math.abs(e.getRawY() - downRawY) > slop) dragging = true;
                    return dragging;
                default:
                    return false;
            }
        }

        @Override public boolean onTouchEvent(MotionEvent e) {
            if (e.getActionMasked() == MotionEvent.ACTION_DOWN) {
                downRawY = e.getRawY();
                startMargin = ((FrameLayout.LayoutParams) getLayoutParams()).topMargin;
            }
            if (e.getActionMasked() == MotionEvent.ACTION_MOVE) {
                FrameLayout.LayoutParams lp = (FrameLayout.LayoutParams) getLayoutParams();
                int max = Math.max(0, frame.getHeight() - getHeight());
                lp.topMargin = (int) Math.max(0, Math.min(max, startMargin + e.getRawY() - downRawY));
                setLayoutParams(lp);
            }
            return true;
        }
    }

    /** Full-screen touchpad over the phone desktop. */
    private final class TouchpadView extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final float slop = ViewConfiguration.get(context).getScaledTouchSlop();
        // Tap-and-drag: a tap presses at once and releases after this unless touched again.
        private static final long TAP_RELEASE_MS = 180, TAP_MAX_MS = 250;
        private final Runnable tapRelease = () -> { tapHeld = false; NativeBridge.castPointer(2, BTN_LEFT, 0); };
        private boolean tapHeld, dragging, moved, scrolling;
        private int maxFingers;
        private long downTime, lastMoveTime;
        private float startX, startY, lastX, lastY;

        TouchpadView(Context context) {
            super(context);
            paint.setTextAlign(Paint.Align.CENTER);
        }

        void reset() {
            handler.removeCallbacks(tapRelease);
            if (tapHeld || dragging) NativeBridge.castPointer(2, BTN_LEFT, 0);
            if (scrolling) NativeBridge.castPointer(4, 0, 0);
            tapHeld = dragging = scrolling = false;
        }

        @Override protected void onDraw(Canvas canvas) {
            canvas.drawColor(0xB0101214);
            int w = getWidth(), h = getHeight();
            float cy = mode == Mode.KEYBOARD ? h * 0.22f : h * 0.42f;
            paint.setColor(Color.WHITE);
            paint.setTextSize(dp(22));
            canvas.drawText(mode == Mode.KEYBOARD ? "键盘" : "触控板", w / 2f, cy, paint);
            paint.setColor(0xB0FFFFFF);
            paint.setTextSize(dp(14));
            String[] lines = {"单指移动光标，轻点单击", "轻点后再按住拖动", "双指滚动，双指轻点右键"};
            for (int i = 0; i < lines.length; i++) canvas.drawText(lines[i], w / 2f, cy + dp(34) + i * dp(24), paint);
        }

        private void centroid(MotionEvent e, float[] out) {
            float x = 0, y = 0;
            int n = e.getPointerCount();
            int skip = e.getActionMasked() == MotionEvent.ACTION_POINTER_UP ? e.getActionIndex() : -1;
            int count = 0;
            for (int i = 0; i < n; i++) {
                if (i == skip) continue;
                x += e.getX(i);
                y += e.getY(i);
                count++;
            }
            out[0] = count > 0 ? x / count : 0;
            out[1] = count > 0 ? y / count : 0;
        }

        private final float[] point = new float[2];

        @Override public boolean onTouchEvent(MotionEvent e) {
            long now = SystemClock.uptimeMillis();
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    maxFingers = 1;
                    moved = scrolling = false;
                    downTime = lastMoveTime = now;
                    startX = lastX = e.getX();
                    startY = lastY = e.getY();
                    if (tapHeld) {
                        // Touched again right after a tap: keep the button down and drag.
                        handler.removeCallbacks(tapRelease);
                        tapHeld = false;
                        dragging = true;
                    }
                    return true;
                case MotionEvent.ACTION_POINTER_DOWN:
                case MotionEvent.ACTION_POINTER_UP:
                    maxFingers = Math.max(maxFingers, e.getPointerCount());
                    // Re-anchor on finger changes so the centroid does not jump.
                    centroid(e, point);
                    lastX = point[0];
                    lastY = point[1];
                    return true;
                case MotionEvent.ACTION_MOVE: {
                    centroid(e, point);
                    float dx = point[0] - lastX, dy = point[1] - lastY;
                    lastX = point[0];
                    lastY = point[1];
                    if (!moved && Math.hypot(point[0] - startX, point[1] - startY) > slop) moved = true;
                    if (!moved) return true;
                    long dt = Math.max(1, now - lastMoveTime);
                    lastMoveTime = now;
                    if (e.getPointerCount() >= 2) {
                        // Natural scrolling: content follows the fingers.
                        scrolling = true;
                        NativeBridge.castPointer(3, -dx * 1.5f, -dy * 1.5f);
                    } else if (e.getPointerCount() == 1 && !scrolling) {
                        float speed = (float) Math.hypot(dx, dy) / dt; // px per ms
                        float gain = 1.3f + Math.min(speed * 0.9f, 2.7f);
                        NativeBridge.castPointer(1, dx * gain, dy * gain);
                    }
                    return true;
                }
                case MotionEvent.ACTION_UP: {
                    boolean tap = !moved && now - downTime < TAP_MAX_MS;
                    if (scrolling) NativeBridge.castPointer(4, 0, 0);
                    if (dragging) {
                        NativeBridge.castPointer(2, BTN_LEFT, 0);
                        dragging = false;
                        // Second tap without movement: that was a double click.
                        if (tap && maxFingers == 1) click(BTN_LEFT);
                    } else if (tap && maxFingers == 1) {
                        NativeBridge.castPointer(2, BTN_LEFT, 1);
                        tapHeld = true;
                        handler.postDelayed(tapRelease, TAP_RELEASE_MS);
                    } else if (tap && maxFingers == 2) {
                        click(BTN_RIGHT);
                    } else if (tap && maxFingers >= 3) {
                        click(BTN_MIDDLE);
                    }
                    scrolling = false;
                    return true;
                }
                case MotionEvent.ACTION_CANCEL:
                    reset();
                    return true;
                default:
                    return true;
            }
        }

        private void click(int button) {
            NativeBridge.castPointer(2, button, 1);
            NativeBridge.castPointer(2, button, 0);
        }
    }
}
