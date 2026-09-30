package com.rungic.plasma;

import android.app.Activity;
import android.content.Context;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Display;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.WindowManager;
import com.winland.server.NativeBridge;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;
import org.json.JSONObject;

/**
 * Linux desktop on a cast display (docs/58 step 2). A non-focusable overlay on
 * the Presentation-class display (Wi-Fi Display) holds a SurfaceView; its window
 * is handed to the compositor, which offers KWin a second output for it.
 * On by default (docs/58 step 4): a cast display that appears, or is already
 * there when the desktop starts, gets the desktop; the platform bridge op
 * "cast-desktop" turns it off or on and the choice is remembered.
 */
final class CastDesktop implements DisplayManager.DisplayListener, SurfaceHolder.Callback {
    private final Activity activity;
    private final BooleanSupplier ready;
    private final Consumer<Boolean> bound;
    private final DisplayManager displays;
    private boolean enabled;
    private SurfaceView view;
    private WindowManager windowManager;
    private int displayId = -1;
    private int boundWidth, boundHeight;
    private boolean overlayRequested;
    private int preparedDisplay = -1;
    private int preparingDisplay = -1;

    private final java.util.function.Supplier<int[]> fixedSize;

    /** `fixedSize` gives the assistant's screen size while it is on (docs/65): the TV then presents that output, scaled. */
    CastDesktop(Activity activity, BooleanSupplier ready, java.util.function.Supplier<int[]> fixedSize, Consumer<Boolean> bound) {
        this.activity = activity;
        this.ready = ready;
        this.fixedSize = fixedSize;
        this.bound = bound;
        enabled = activity.getPreferences(Context.MODE_PRIVATE).getBoolean("cast_desktop", true);
        displays = activity.getSystemService(DisplayManager.class);
        displays.registerDisplayListener(this, new Handler(Looper.getMainLooper()));
    }

    boolean enabled() { return enabled; }

    JSONObject request(JSONObject request) throws Exception {
        if (request.has("enabled")) {
            enabled = request.getBoolean("enabled");
            activity.getPreferences(Context.MODE_PRIVATE).edit().putBoolean("cast_desktop", enabled).apply();
            update();
        }
        JSONObject out = new JSONObject().put("enabled", enabled).put("displayId", displayId)
            .put("bound", boundWidth > 0 ? boundWidth + "x" + boundHeight : JSONObject.NULL);
        return out;
    }

    void release() {
        enabled = false;
        update();
        displays.unregisterDisplayListener(this);
    }

    /** The desktop became ready (compositor up): take a cast display that is already there. */
    void refresh() { update(); }

    private Display target() {
        for (Display d : displays.getDisplays(DisplayManager.DISPLAY_CATEGORY_PRESENTATION)) {
            if (d.getDisplayId() != Display.DEFAULT_DISPLAY) return d;
        }
        return null;
    }

    private void update() {
        Display display = enabled && ready.getAsBoolean() ? target() : null;
        if (view != null && (display == null || display.getDisplayId() != displayId)) {
            windowManager.removeView(view);
            view = null;
            displayId = -1;
            unbind();
        }
        if (display == null || view != null) return;
        if (preparedDisplay != display.getDisplayId()) {
            prepareDisplay(display.getDisplayId());
            return;
        }
        if (!android.provider.Settings.canDrawOverlays(activity)) {
            requestOverlay();
            return;
        }
        Context windowContext = activity.createDisplayContext(display)
            .createWindowContext(WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY, null);
        windowManager = windowContext.getSystemService(WindowManager.class);
        Display.Mode mode = display.getMode();
        view = new SurfaceView(windowContext);
        int[] size = fixedSize.get();
        if (size != null) view.getHolder().setFixedSize(size[0], size[1]);
        else view.getHolder().setFixedSize(mode.getPhysicalWidth(), mode.getPhysicalHeight());
        view.getHolder().addCallback(this);
        // Above the vendor desktop, never focused (input stays with the phone), fully
        // opaque (not FLAG_NOT_TOUCHABLE, which Android caps at 0.8 opacity).
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(-1, -1,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                // The cast display is its own display group with its own screen-off
                // timeout; input reaches Linux through the host, so Android saw no
                // activity there and switched the TV off after 5 minutes. Each
                // display holds its own keep-screen-on wake lock (Android 14+).
                | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
            PixelFormat.OPAQUE);
        lp.setFitInsetsTypes(0);
        lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
        lp.setTitle("PlasmaCastDesktop");
        windowManager.addView(view, lp);
        displayId = display.getDisplayId();
        Log.i("RungicCast", "cast desktop on display " + displayId + " " + mode.getPhysicalWidth() + "x" + mode.getPhysicalHeight());
    }

    /**
     * The TV needs the overlay app op, which the first boot grants (tools/ci/rungic-firstboot.sh)
     * but may not have. Once per run: grant it through root, else open Android's page for it; the
     * desktop goes on the TV as soon as it is allowed.
     */
    private void requestOverlay() {
        if (overlayRequested) return;
        overlayRequested = true;
        Handler main = new Handler(Looper.getMainLooper());
        Thread grant = new Thread(() -> {
            try {
                Process p = new ProcessBuilder("su", "-c",
                    "appops set " + activity.getPackageName() + " SYSTEM_ALERT_WINDOW allow").redirectErrorStream(true).start();
                if (!p.waitFor(10, java.util.concurrent.TimeUnit.SECONDS)) p.destroy();
            } catch (Exception e) {
                Log.w("RungicCast", "overlay grant through root failed: " + e.getMessage());
            }
            main.post(() -> {
                if (android.provider.Settings.canDrawOverlays(activity)) {
                    Log.i("RungicCast", "overlay allowed through root");
                    update();
                    return;
                }
                Log.i("RungicCast", "overlay not allowed; asking the user");
                try {
                    activity.startActivity(new android.content.Intent(android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        android.net.Uri.parse("package:" + activity.getPackageName())).addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK));
                } catch (Exception e) {
                    Log.w("RungicCast", "cannot open the overlay permission page: " + e.getMessage());
                }
                // Returning from that page raises no display event: look again for a minute.
                for (int i = 1; i <= 60; i++) {
                    main.postDelayed(() -> { if (view == null && android.provider.Settings.canDrawOverlays(activity)) update(); }, i * 1000L);
                }
            });
        }, "rungic-overlay");
        grant.setDaemon(true);
        grant.start();
    }

    private void unbind() {
        if (boundWidth > 0) {
            ((MainActivity) activity).releasePresenter("tv");
            boundWidth = boundHeight = 0;
            bound.accept(false);
        }
    }

    @Override public void surfaceCreated(SurfaceHolder holder) {}

    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
        Display display = displays.getDisplay(displayId);
        int refresh = display == null ? 60000 : Math.round(display.getRefreshRate() * 1000);
        ((MainActivity) activity).bindPresenter("tv", holder.getSurface(), width, height, refresh, 0);
        boundWidth = width;
        boundHeight = height;
        bound.accept(true);
    }

    @Override public void surfaceDestroyed(SurfaceHolder holder) { unbind(); }

    @Override public void onDisplayAdded(int id) { update(); }
    @Override public void onDisplayRemoved(int id) { update(); }
    @Override public void onDisplayChanged(int id) {
        if (id != displayId || view == null || fixedSize.get() != null) return;
        Display display = displays.getDisplay(id);
        if (display != null) {
            Display.Mode mode = display.getMode();
            view.getHolder().setFixedSize(mode.getPhysicalWidth(), mode.getPhysicalHeight());
        }
    }

    private void prepareDisplay(int id) {
        if (preparingDisplay == id) return;
        preparingDisplay = id;
        new Thread(() -> {
            try {
                Process process = new ProcessBuilder("su", "-c", "/data/adb/rungic-wfd/rungic-cast claim")
                        .redirectErrorStream(true).start();
                if (!process.waitFor(15, java.util.concurrent.TimeUnit.SECONDS)) process.destroyForcibly();
                else if (process.exitValue() != 0) Log.w("RungicCast", "cast adapter did not prepare display " + id);
            } catch (Exception e) { Log.w("RungicCast", "cast adapter: " + e.getMessage()); }
            activity.runOnUiThread(() -> {
                preparedDisplay = id;
                if (preparingDisplay == id) preparingDisplay = -1;
                update();
            });
        }, "rungic-cast-prepare").start();
    }
}
