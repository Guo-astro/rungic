package dev.moto.plasma;

import android.os.Handler;
import android.view.MotionEvent;
import android.view.ViewConfiguration;

/**
 * A touchscreen over a picture of the host's second output (docs/66): the finger is the pointer.
 * The mouse conventions of touch screens (Windows, remote-desktop clients' touch mode):
 *
 *   tap                  left click where the finger is; two taps in a row a double click
 *   long press           right click (at the long-press timeout, as Android's context menus)
 *   press and move       drag with the left button from where the finger went down
 *   two-finger tap       right click; three-finger tap middle click (as on the touchpad)
 *   two fingers move     scroll, the content following the fingers; kinetic after the lift
 *
 * The movement thresholds are the touchpad's (GestureRules), in millimetres.
 */
final class DirectGestures {
    /** Picture position (input pixels) to the output's pixels. */
    interface Mapper { void map(float x, float y, float[] out); }

    private final PointerOutput out;
    private final Mapper mapper;
    private final Handler handler;
    private final float outputPerInputPx;
    private final long longPressMs = ViewConfiguration.getLongPressTimeout();
    private final float[] point = new float[2], mapped = new float[2];
    private final GestureRules.Travel travel;
    private final Runnable longPress = this::longPress;
    private int maxFingers;
    private boolean moved, dragging, scrolling, longPressed;
    private long downTime;
    private float startX, startY, lastX, lastY;

    /** `outputPerInputPx`: output pixels per input pixel of the picture (its scale on the phone). */
    DirectGestures(PointerOutput out, Mapper mapper, Handler handler, float inputPxPerMm, float outputPerInputPx) {
        this.out = out;
        this.mapper = mapper;
        this.handler = handler;
        this.travel = new GestureRules.Travel(inputPxPerMm);
        this.outputPerInputPx = outputPerInputPx;
    }

    void reset() {
        handler.removeCallbacks(longPress);
        if (dragging) out.button(PointerOutput.BTN_LEFT, false);
        if (scrolling) out.scrollStop();
        dragging = scrolling = false;
    }

    private void pointTo(float x, float y) {
        mapper.map(x, y, mapped);
        out.moveTo(mapped[0], mapped[1]);
    }

    private void longPress() {
        if (moved || maxFingers > 1) return;
        longPressed = true;
        pointTo(startX, startY);
        out.click(PointerOutput.BTN_RIGHT);
    }

    boolean onTouchEvent(MotionEvent e) {
        boolean travelled = travel.moved(e);
        switch (e.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                maxFingers = 1;
                moved = dragging = scrolling = longPressed = false;
                downTime = e.getEventTime();
                startX = lastX = e.getX();
                startY = lastY = e.getY();
                handler.postDelayed(longPress, longPressMs);
                return true;
            case MotionEvent.ACTION_POINTER_DOWN:
                handler.removeCallbacks(longPress);
                if (dragging) {  // a second finger ends a drag: it is becoming a scroll or a tap
                    out.button(PointerOutput.BTN_LEFT, false);
                    dragging = false;
                }
                // fall through
            case MotionEvent.ACTION_POINTER_UP:
                maxFingers = Math.max(maxFingers, e.getPointerCount());
                GestureRules.centroid(e, point);
                lastX = point[0];
                lastY = point[1];
                return true;
            case MotionEvent.ACTION_MOVE: {
                GestureRules.centroid(e, point);
                if (!moved && travelled) {
                    moved = true;
                    handler.removeCallbacks(longPress);
                    if (e.getPointerCount() == 1 && maxFingers == 1 && !longPressed) {
                        // A drag starts where the finger went down, not where it crossed the threshold.
                        pointTo(startX, startY);
                        out.button(PointerOutput.BTN_LEFT, true);
                        dragging = true;
                    }
                }
                if (e.getPointerCount() >= 2 && moved) {
                    // Natural scrolling at unity: the content follows the fingers.
                    out.scroll(-(point[0] - lastX) * outputPerInputPx, -(point[1] - lastY) * outputPerInputPx);
                    scrolling = true;
                    pointTo(point[0], point[1]);
                } else if (dragging) {
                    pointTo(e.getX(), e.getY());
                }
                lastX = point[0];
                lastY = point[1];
                return true;
            }
            case MotionEvent.ACTION_UP: {
                handler.removeCallbacks(longPress);
                if (dragging) out.button(PointerOutput.BTN_LEFT, false);
                if (scrolling) out.scrollStop();
                boolean tap = !moved && !longPressed && e.getEventTime() - downTime < longPressMs;
                if (tap) {
                    // One finger clicks under it; two or three click between them.
                    if (maxFingers == 1) pointTo(e.getX(), e.getY());
                    else pointTo(lastX, lastY);
                    out.click(GestureRules.tapButton(maxFingers));
                }
                dragging = scrolling = false;
                return true;
            }
            case MotionEvent.ACTION_CANCEL:
                reset();
                return true;
            default:
                return true;
        }
    }
}
