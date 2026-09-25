package dev.moto.plasma;

import android.os.Handler;
import com.winland.server.NativeBridge;

/**
 * Pointer input into the host's second output (the TV or the assistant's screen, docs/58, docs/65),
 * in that output's pixels. The one place the gesture code reaches the host (castPointer ops).
 */
final class PointerOutput {
    static final int BTN_LEFT = 0x110, BTN_RIGHT = 0x111, BTN_MIDDLE = 0x112;
    /** Between the press and the release of a click: a release in the same instant as its press was
     *  ignored by some controls (the panel's application launcher, docs/65). */
    private static final long CLICK_MS = 40;
    private final Handler handler;

    PointerOutput(Handler handler) { this.handler = handler; }

    /** The host pointer goes to the output (and leaves the phone's desktop), or back. */
    void attach(boolean on) { NativeBridge.castPointer(0, on ? 1 : 0, 0); }
    void moveTo(float x, float y) { NativeBridge.castPointer(5, x, y); }
    void moveBy(float dx, float dy) { NativeBridge.castPointer(1, dx, dy); }
    void button(int button, boolean pressed) { NativeBridge.castPointer(2, button, pressed ? 1 : 0); }
    /** Finger scroll; positive values scroll the content up and left, as a finger moving up would. */
    void scroll(float dx, float dy) { NativeBridge.castPointer(3, dx, dy); }
    /** The fingers left: kinetic scrolling may carry on from here. */
    void scrollStop() { NativeBridge.castPointer(4, 0, 0); }

    void click(int button) {
        button(button, true);
        handler.postDelayed(() -> button(button, false), CLICK_MS);
    }
}
