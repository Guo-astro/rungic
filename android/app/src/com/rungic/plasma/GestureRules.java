package com.rungic.plasma;

import android.view.MotionEvent;

/**
 * Thresholds shared by the pointer gestures (docs/66), in physical units so that they mean the same
 * on any screen. The tap numbers are libinput's (1.32.0, evdev-mt-touchpad-tap.c).
 */
final class GestureRules {
    private GestureRules() {}

    /** A touch that ends within this and moved less than TAP_MOVE_MM is a tap. */
    static final long TAP_TIMEOUT_MS = 180;
    /** After a one-finger tap, a new touch within this starts a drag or a double click. */
    static final long DRAG_TIMEOUT_MS = 160;
    /** Travel below which a touch has not moved (a tap, or a press that is not yet a drag). */
    static final float TAP_MOVE_MM = 1.3f;

    /** Tap buttons by finger count: one left, two right, three middle (libinput's lrm map). */
    static int tapButton(int fingers) {
        return fingers >= 3 ? PointerOutput.BTN_MIDDLE : fingers == 2 ? PointerOutput.BTN_RIGHT : PointerOutput.BTN_LEFT;
    }

    /** Centroid of the fingers still down (a lifting one excluded), into `out`. */
    static void centroid(MotionEvent e, float[] out) {
        float x = 0, y = 0;
        int skip = e.getActionMasked() == MotionEvent.ACTION_POINTER_UP ? e.getActionIndex() : -1;
        int count = 0;
        for (int i = 0; i < e.getPointerCount(); i++) {
            if (i == skip) continue;
            x += e.getX(i);
            y += e.getY(i);
            count++;
        }
        out[0] = count > 0 ? x / count : 0;
        out[1] = count > 0 ? y / count : 0;
    }

    /**
     * Whether a touch has moved: any finger further than TAP_MOVE_MM from where that finger went
     * down (libinput's per-touch tap threshold; Flutter's slop of each pointer from its own down
     * position). The centroid is no measure of it: a finger landing or lifting moves the centroid
     * by half the distance between the fingers, and no finger has moved.
     */
    static final class Travel {
        private static final int MAX_ID = 32;
        private final float mmPerPx;
        private final float[] downX = new float[MAX_ID], downY = new float[MAX_ID];
        private final boolean[] down = new boolean[MAX_ID];

        /** `pxPerMm`: pixels per millimetre of the surface the fingers are on. */
        Travel(float pxPerMm) { mmPerPx = 1f / pxPerMm; }

        /** Follow the fingers of `e`: call with every event of the touch. True once any has moved. */
        boolean moved(MotionEvent e) {
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    java.util.Arrays.fill(down, false);
                    // fall through
                case MotionEvent.ACTION_POINTER_DOWN: {
                    int i = e.getActionIndex(), id = e.getPointerId(i);
                    if (id < MAX_ID) {
                        down[id] = true;
                        downX[id] = e.getX(i);
                        downY[id] = e.getY(i);
                    }
                    return false;
                }
                case MotionEvent.ACTION_MOVE:
                    for (int i = 0; i < e.getPointerCount(); i++) {
                        int id = e.getPointerId(i);
                        if (id < MAX_ID && down[id]
                                && Math.hypot(e.getX(i) - downX[id], e.getY(i) - downY[id]) * mmPerPx > TAP_MOVE_MM)
                            return true;
                    }
                    return false;
                default:
                    return false;
            }
        }
    }

    /** Fingers still down after this event. */
    static int fingers(MotionEvent e) {
        int action = e.getActionMasked();
        boolean lifting = action == MotionEvent.ACTION_POINTER_UP || action == MotionEvent.ACTION_UP
            || action == MotionEvent.ACTION_CANCEL;
        return e.getPointerCount() - (lifting ? 1 : 0);
    }
}
