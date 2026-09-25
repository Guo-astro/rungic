package dev.moto.plasma;

import android.content.Context;
import android.os.Handler;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.ViewConfiguration;
import com.winland.server.NativeBridge;

/**
 * Laptop touchpad gestures on the host's second output (docs/58, docs/65): one finger moves the
 * pointer (accelerated), a tap clicks, tap then touch again drags, two fingers scroll, a two-finger
 * tap right-clicks, a three-finger tap middle-clicks. Shared by the phone as the TV's touchpad
 * (CastControls) and the touchpad mode of the assistant's screen fullscreen (AgentFullscreen).
 */
final class TouchpadGestures {
    private static final int BTN_LEFT = 0x110, BTN_RIGHT = 0x111, BTN_MIDDLE = 0x112;
    // Tap-and-drag: a tap presses at once and releases after this unless touched again.
    private static final long TAP_RELEASE_MS = 180, TAP_MAX_MS = 250;
    private final Handler handler;
    private final float slop;
    private final Runnable tapRelease = () -> { tapHeld = false; NativeBridge.castPointer(2, BTN_LEFT, 0); };
    private final float[] point = new float[2];
    private boolean tapHeld, dragging, moved, scrolling;
    private int maxFingers;
    private long downTime, lastMoveTime;
    private float startX, startY, lastX, lastY;

    TouchpadGestures(Context context, Handler handler) {
        this.handler = handler;
        slop = ViewConfiguration.get(context).getScaledTouchSlop();
    }

    /** Let go of anything held (a gesture was cut short or the mode changed). */
    void reset() {
        handler.removeCallbacks(tapRelease);
        if (tapHeld || dragging) NativeBridge.castPointer(2, BTN_LEFT, 0);
        if (scrolling) NativeBridge.castPointer(4, 0, 0);
        tapHeld = dragging = scrolling = false;
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

    boolean onTouchEvent(MotionEvent e) {
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
