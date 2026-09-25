package dev.moto.plasma;

import android.os.Handler;
import android.view.MotionEvent;

/**
 * A laptop touchpad over the host's second output (docs/66), after libinput's tap state machine:
 *
 *   one finger moves        the pointer (PointerTransfer: 1:1 as seen, accelerating when fast)
 *   tap                     left click; two-finger tap right click; three-finger tap middle click
 *   tap, tap                double click
 *   tap, then touch & move  drag (the button stays down until the finger lifts); a touch held
 *   (or hold past the tap   past the tap timeout after a tap also starts a drag
 *    timeout)
 *   two fingers move        scroll, content following the fingers; kinetic after the lift
 *
 * Shared by the phone as the TV's touchpad (CastControls) and the touchpad mode of the assistant's
 * screen fullscreen (AgentFullscreen).
 */
final class TouchpadGestures {
    private enum State { IDLE, TOUCH, TAPPED, DRAG_OR_DOUBLETAP, DRAGGING }

    private final PointerOutput out;
    private final PointerTransfer transfer;
    private final Handler handler;
    private final float[] point = new float[2], delta = new float[2];
    private final Runnable tapReleased = this::tapReleased;
    private final Runnable holdToDrag = this::holdToDrag;
    private State state = State.IDLE;
    private int maxFingers;
    private boolean moved, scrolling;
    private long downTime;
    private float startX, startY, lastX, lastY;

    TouchpadGestures(PointerOutput out, PointerTransfer transfer, Handler handler) {
        this.out = out;
        this.transfer = transfer;
        this.handler = handler;
    }

    /** Let go of anything held: a gesture was cut short, or the mode changed. */
    void reset() {
        handler.removeCallbacks(tapReleased);
        handler.removeCallbacks(holdToDrag);
        if (state == State.TAPPED || state == State.DRAG_OR_DOUBLETAP || state == State.DRAGGING)
            out.button(PointerOutput.BTN_LEFT, false);
        if (scrolling) out.scrollStop();
        state = State.IDLE;
        scrolling = false;
    }

    private void tapReleased() {
        // No second touch in time: the tap was a single click.
        if (state == State.TAPPED) {
            out.button(PointerOutput.BTN_LEFT, false);
            state = State.IDLE;
        }
    }

    private void holdToDrag() {
        // The second touch stayed down past the tap timeout: it is a drag, not a double click.
        if (state == State.DRAG_OR_DOUBLETAP && !scrolling) state = State.DRAGGING;
    }

    private boolean pastTapMove(float x, float y) {
        return Math.hypot(x - startX, y - startY) * transfer.mmPerInputPx() > GestureRules.TAP_MOVE_MM;
    }

    boolean onTouchEvent(MotionEvent e) {
        switch (e.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                maxFingers = 1;
                moved = scrolling = false;
                downTime = e.getEventTime();
                startX = lastX = e.getX();
                startY = lastY = e.getY();
                transfer.start(e.getX(), e.getY(), e.getEventTime());
                if (state == State.TAPPED) {
                    // Touched again soon after a tap: the button stays down; a quick lift makes it a
                    // double click, moving (or holding past the tap timeout) makes it a drag.
                    handler.removeCallbacks(tapReleased);
                    state = State.DRAG_OR_DOUBLETAP;
                    handler.postDelayed(holdToDrag, GestureRules.TAP_TIMEOUT_MS);
                } else {
                    state = State.TOUCH;
                }
                return true;
            case MotionEvent.ACTION_POINTER_DOWN:
            case MotionEvent.ACTION_POINTER_UP:
                maxFingers = Math.max(maxFingers, e.getPointerCount());
                // Re-anchor on finger changes so the centroid does not jump, and the pointer does
                // not jump when the first finger lifts and another becomes the first.
                GestureRules.centroid(e, point);
                lastX = point[0];
                lastY = point[1];
                if (e.getActionMasked() == MotionEvent.ACTION_POINTER_UP) {
                    int keep = e.getActionIndex() == 0 ? 1 : 0;
                    transfer.start(e.getX(keep), e.getY(keep), e.getEventTime());
                }
                return true;
            case MotionEvent.ACTION_MOVE: {
                GestureRules.centroid(e, point);
                if (!moved && pastTapMove(point[0], point[1])) {
                    moved = true;
                    if (state == State.DRAG_OR_DOUBLETAP) state = State.DRAGGING;
                }
                if (e.getPointerCount() >= 2) {
                    if (moved) {
                        // Natural scrolling at unity: the content follows the fingers as seen.
                        float k = transfer.mmPerInputPx() * transfer.outputPxPerMm();
                        out.scroll(-(point[0] - lastX) * k, -(point[1] - lastY) * k);
                        scrolling = true;
                    }
                } else if (!scrolling) {
                    // From the first sample, as libinput does: the slow end of the curve (1/3 below
                    // 7 mm/s) keeps a tap's jitter to a fraction of a pixel.
                    transfer.motion(e, 0, delta);
                    out.moveBy(delta[0], delta[1]);
                }
                lastX = point[0];
                lastY = point[1];
                return true;
            }
            case MotionEvent.ACTION_UP: {
                handler.removeCallbacks(holdToDrag);
                boolean tap = !moved && e.getEventTime() - downTime < GestureRules.TAP_TIMEOUT_MS;
                if (scrolling) out.scrollStop();
                scrolling = false;
                switch (state) {
                    case DRAG_OR_DOUBLETAP:  // tap, tap: the first click ends, the second is a click
                        out.button(PointerOutput.BTN_LEFT, false);
                        state = State.IDLE;
                        if (tap && maxFingers == 1) out.click(PointerOutput.BTN_LEFT);
                        break;
                    case DRAGGING:
                        out.button(PointerOutput.BTN_LEFT, false);
                        state = State.IDLE;
                        break;
                    default:
                        state = State.IDLE;
                        if (!tap) break;
                        if (maxFingers == 1) {
                            // Press now; release unless a touch follows within the drag timeout.
                            out.button(PointerOutput.BTN_LEFT, true);
                            state = State.TAPPED;
                            handler.postDelayed(tapReleased, GestureRules.DRAG_TIMEOUT_MS);
                        } else {
                            out.click(GestureRules.tapButton(maxFingers));
                        }
                }
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
