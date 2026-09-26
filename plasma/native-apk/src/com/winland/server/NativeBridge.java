package com.winland.server;

import android.view.Surface;
import android.util.Log;

/** JNI ABI of Winland release asset updated 2026-09-07. The package name is part of the upstream ABI. */
public final class NativeBridge {
    static {
        System.loadLibrary("c++_shared");
        System.loadLibrary("xkbcommon");
        System.loadLibrary("uniffi_winland_core");
    }
    public static native boolean startGpuAllocator(String path);
    public static native boolean initWaylandConnection(Surface surface, Object context, String distroId);
    public static native void rebindSurface(Surface surface);
    public static native void onSurfaceChanged(int width, int height, int widthMm, int heightMm);
    public static native void releaseWaylandConnection();
    public static native void suspendRendering();
    public static native void resumeRendering();
    public static native void sendTouchEvent(int action, int id, float x, float y);
    public static native void sendKeyEvent(int keycode, boolean down);
    public static native void sendTextInput(String text);
    public static native void setInputMode(int mode);
    public static native void setResolution(int width, int height);
    public static native void setScale(float scale);
    public static native void setRefreshRate(float rate);
    public static native void frameTick(long frameTimeNanos);
    public static native long getPresentedFrames();
    /** False while the compositor is parked on a static desktop (on-demand vsync). */
    public static native boolean wantsVsync();
    /** eventfd that becomes readable when the compositor wants vsync again. */
    public static native int vsyncWakeFd();
    /** Cast display (Miracast TV) window, in pixels; refresh in mHz (docs/58). */
    public static native void bindCastSurface(Surface surface, int width, int height, int refreshMhz, int rotation);
    public static native void releaseCastSurface();
    /** The assistant's screen (docs/65): the second output exists while enabled, with or without a TV. */
    public static native void setAgentScreen(boolean enabled, int width, int height, int refreshMhz);
    /** Phone as the TV's touchpad: 0 enable, 1 motion, 2 button, 3 scroll, 4 scroll stop (docs/58). */
    public static native void castPointer(int op, float x, float y);
    /** Whether a Wayland client (KWin, for an idle-inhibiting window) inhibits idle (docs/72). */
    public static native boolean idleInhibited();
    /** eventfd that becomes readable when idleInhibited() changes; the reader drains it. */
    public static native int idleInhibitFd();
    public static native String getLastNativeError();
    public static native String getWaylandRuntimeStats();
    public static native void sendClipboardTextToWayland(String text);
    public static void onKeyboardInitFailed(String reason) { Log.e("MotoWayland", reason); }
    public static void onWaylandClipboardChanged(String text) { }
    public static void onWaylandShowSoftKeyboard() { }
    public static void onWaylandHideSoftKeyboard() { }
}
