package dev.moto.plasma;

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

    /** Fingers still down after this event. */
    static int fingers(MotionEvent e) {
        int action = e.getActionMasked();
        boolean lifting = action == MotionEvent.ACTION_POINTER_UP || action == MotionEvent.ACTION_UP
            || action == MotionEvent.ACTION_CANCEL;
        return e.getPointerCount() - (lifting ? 1 : 0);
    }
}
