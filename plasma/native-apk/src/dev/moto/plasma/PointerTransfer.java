package dev.moto.plasma;

import android.view.MotionEvent;

/**
 * Finger motion to pointer motion (docs/66): physical units in, the display's pixels out.
 *
 * Unity is "the pointer moves as far as the finger, as seen": `pxPerMm` is the display's pixels per
 * millimetre of finger travel. On the phone's own screen that is the picture's pixels per phone
 * millimetre (1:1 under the finger); on a TV it is the same visual angle (TOUCHPAD_TV_PX_PER_MM).
 *
 * The acceleration curve is libinput's touchpad profile (1.32.0, filter-touchpad.c,
 * touchpad_accel_profile_linear) with its plateau normalised to 1: slower than 7 mm/s it slows down
 * to 1/3 for pixel-exact positioning, from 7 to 130 mm/s it is exactly 1:1, faster it rises until
 * 520 mm/s (5.3x), so a flick crosses the screen without lifting the finger. Velocity comes from
 * the samples' own timestamps, including the historical ones Android batches per frame, and the
 * factor is averaged over the change of velocity (Simpson's rule, as libinput does).
 */
final class PointerTransfer {
    /** A 1920-pixel-wide TV filling ~35 degrees of view, against a finger at ~30 cm from the eye:
     *  the same visual angle is 1920 / 35 * 0.191 = 10.5 px per mm. libinput's touchpad plateau
     *  also comes to ~10.5 logical px per mm (0.9 * 0.2968 * 1000 dpi / 25.4). */
    static final float TOUCHPAD_TV_PX_PER_MM = 10.5f;
    private static final double SLOW = 7, THRESHOLD = 130, CEILING = 4 * THRESHOLD, BASELINE = 0.9;
    private static final long WINDOW_MS = 60;  // velocity over the last samples within this window

    private final float pxPerMm;
    private final float mmPerInputPx;
    private boolean accelerated = true;
    private final long[] times = new long[16];
    private final float[] xs = new float[16], ys = new float[16];
    private int count, head;
    private double lastVelocity;

    /** `inputPxPerMm`: pixels per millimetre of the surface the finger is on (the phone's dpi / 25.4). */
    PointerTransfer(float inputPxPerMm, float outputPxPerMm) {
        this.mmPerInputPx = 1f / inputPxPerMm;
        this.pxPerMm = outputPxPerMm;
    }

    void setAccelerated(boolean on) { accelerated = on; }
    float outputPxPerMm() { return pxPerMm; }
    float mmPerInputPx() { return mmPerInputPx; }

    /** The unitless factor libinput's profile gives at `speed` mm/s, with its plateau as 1. */
    static double factor(double speed) {
        if (speed < SLOW) return Math.min(BASELINE, 0.1 * speed + 0.3) / BASELINE;
        if (speed < THRESHOLD) return 1;
        double v = Math.min(speed, CEILING);
        return (0.0025 * (v / THRESHOLD) * (v - THRESHOLD) + BASELINE) / BASELINE;
    }

    void reset() {
        count = 0;
        lastVelocity = 0;
    }

    /** Start of a movement at (x, y) input pixels. */
    void start(float x, float y, long timeMs) {
        reset();
        add(x, y, timeMs);
    }

    private void add(float x, float y, long t) {
        head = (head + 1) % times.length;
        times[head] = t;
        xs[head] = x * mmPerInputPx;
        ys[head] = y * mmPerInputPx;
        if (count < times.length) count++;
    }

    /** mm/s from the newest sample back to the oldest one within the window. */
    private double velocity() {
        if (count < 2) return 0;
        int oldest = head;
        for (int i = 1; i < count; i++) {
            int j = (head - i + times.length) % times.length;
            if (times[head] - times[j] > WINDOW_MS) break;
            oldest = j;
        }
        if (oldest == head) oldest = (head - 1 + times.length) % times.length;
        long dt = Math.max(1, times[head] - times[oldest]);
        return Math.hypot(xs[head] - xs[oldest], ys[head] - ys[oldest]) * 1000.0 / dt;
    }

    /** Output pixels for the move from the previous sample to (x, y). */
    private void step(float x, float y, long t, float[] out) {
        float px = xs[head], py = ys[head];
        add(x, y, t);
        double v = velocity();
        double f = accelerated
            ? (factor(lastVelocity) + 4 * factor((lastVelocity + v) / 2) + factor(v)) / 6
            : 1;
        lastVelocity = v;
        out[0] += (float) ((xs[head] - px) * f * pxPerMm);
        out[1] += (float) ((ys[head] - py) * f * pxPerMm);
    }

    /** The pointer motion, in output pixels, for all samples of pointer `index` in `e`. */
    void motion(MotionEvent e, int index, float[] out) {
        out[0] = out[1] = 0;
        for (int h = 0; h < e.getHistorySize(); h++)
            step(e.getHistoricalX(index, h), e.getHistoricalY(index, h), e.getHistoricalEventTime(h), out);
        step(e.getX(index), e.getY(index), e.getEventTime(), out);
    }
}
