package dev.moto.plasma;

import android.app.Activity;
import android.app.Presentation;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.hardware.display.DisplayManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Display;
import android.view.Gravity;
import android.view.View;
import android.widget.FrameLayout;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import org.json.JSONObject;

/**
 * Cast prototype (docs/58 step 1): shows a test pattern on a Presentation-class
 * display (Wi-Fi Display) and the same millisecond clock on the phone, so one
 * photo of both screens gives the end-to-end latency. Controlled through the
 * platform bridge op "cast-test".
 */
final class CastTest implements DisplayManager.DisplayListener {
    private final Activity activity;
    private final FrameLayout phoneFrame;
    private final DisplayManager displays;
    private boolean enabled;
    private Presentation presentation;
    private View overlay;
    private int overlayDisplay = -1;
    private PatternView pattern;
    private PatternView phoneClock;

    CastTest(Activity activity, FrameLayout phoneFrame) {
        this.activity = activity;
        this.phoneFrame = phoneFrame;
        displays = activity.getSystemService(DisplayManager.class);
        displays.registerDisplayListener(this, new Handler(Looper.getMainLooper()));
    }

    JSONObject request(JSONObject request) throws Exception {
        if (request.has("enabled")) {
            enabled = request.getBoolean("enabled");
            update();
        }
        return status();
    }

    void release() {
        enabled = false;
        update();
        displays.unregisterDisplayListener(this);
    }

    private Display target() {
        for (Display d : displays.getDisplays(DisplayManager.DISPLAY_CATEGORY_PRESENTATION)) {
            if (d.getDisplayId() != Display.DEFAULT_DISPLAY) return d;
        }
        return null;
    }

    private void update() {
        Display display = enabled ? target() : null;
        if (presentation != null && (display == null || presentation.getDisplay().getDisplayId() != display.getDisplayId())) {
            presentation.dismiss();
            presentation = null;
            pattern = null;
        }
        if (overlay != null && (display == null || overlayDisplay != display.getDisplayId())) {
            overlay.getContext().getSystemService(android.view.WindowManager.class).removeView(overlay);
            overlay = null;
            overlayDisplay = -1;
            pattern = null;
        }
        if (display != null && overlay == null && presentation == null && android.provider.Settings.canDrawOverlays(activity)) {
            // Above the vendor desktop's taskbar (a navigation bar window on the cast
            // display) and never focusable, so input focus stays on the phone.
            Context windowContext = activity.createDisplayContext(display)
                .createWindowContext(android.view.WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY, null);
            pattern = new PatternView(windowContext, true);
            android.view.WindowManager.LayoutParams lp = new android.view.WindowManager.LayoutParams(
                -1, -1, android.view.WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                // Not FLAG_NOT_TOUCHABLE: Android caps such overlays at 0.8 opacity
                // (untrusted-touch occlusion); the cast display has no touch input anyway.
                android.view.WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                    | android.view.WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                    | android.view.WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                android.graphics.PixelFormat.OPAQUE);
            lp.setFitInsetsTypes(0);
            lp.layoutInDisplayCutoutMode = android.view.WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
            lp.setTitle("PlasmaCast");
            windowContext.getSystemService(android.view.WindowManager.class).addView(pattern, lp);
            overlay = pattern;
            overlayDisplay = display.getDisplayId();
        }
        if (display != null && overlay == null && presentation == null) {
            pattern = new PatternView(activity, true);
            presentation = new Presentation(activity, display) {
                @Override protected void onCreate(Bundle state) {
                    super.onCreate(state);
                    setContentView(pattern);
                    // The vendor desktop puts a taskbar (navigation bar) on the cast display;
                    // take the whole display like an immersive app.
                    android.view.Window w = getWindow();
                    w.setDecorFitsSystemWindows(false);
                    w.getAttributes().layoutInDisplayCutoutMode = android.view.WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
                    android.view.WindowInsetsController c = w.getInsetsController();
                    if (c != null) {
                        c.setSystemBarsBehavior(android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                        c.hide(android.view.WindowInsets.Type.systemBars());
                    }
                }
            };
            presentation.setOnDismissListener(d -> { if (presentation != null && !presentation.isShowing()) presentation = null; });
            presentation.show();
        }
        if (enabled && phoneClock == null) {
            phoneClock = new PatternView(activity, false);
            FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(-1, dp(120), Gravity.CENTER);
            phoneFrame.addView(phoneClock, lp);
        } else if (!enabled && phoneClock != null) {
            phoneFrame.removeView(phoneClock);
            phoneClock = null;
        }
    }

    private int dp(int value) {
        return Math.round(value * activity.getResources().getDisplayMetrics().density);
    }

    private JSONObject status() throws Exception {
        JSONObject out = new JSONObject().put("enabled", enabled);
        Display d = target();
        if (d != null) {
            Display.Mode mode = d.getMode();
            out.put("display", new JSONObject().put("id", d.getDisplayId()).put("name", d.getName())
                .put("width", mode.getPhysicalWidth()).put("height", mode.getPhysicalHeight())
                .put("refresh", mode.getRefreshRate()).put("flags", d.getFlags()));
        }
        out.put("showing", overlay != null || (presentation != null && presentation.isShowing()));
        out.put("window", overlay != null ? "overlay" : presentation != null ? "presentation" : "none");
        out.put("overlayAllowed", android.provider.Settings.canDrawOverlays(activity));
        if (pattern != null) out.put("presentationFps", pattern.fps);
        return out;
    }

    @Override public void onDisplayAdded(int id) { update(); }
    @Override public void onDisplayRemoved(int id) { update(); }
    @Override public void onDisplayChanged(int id) {}

    /** Wall-clock milliseconds, frame counter, moving bar and colour bars, redrawn every vsync. */
    private static final class PatternView extends View {
        private final boolean full;
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final SimpleDateFormat clock = new SimpleDateFormat("HH:mm:ss.SSS", Locale.ROOT);
        private long frames, sampleStart, sampleFrames;
        volatile double fps;

        PatternView(Context context, boolean full) {
            super(context);
            this.full = full;
            paint.setTypeface(Typeface.MONOSPACE);
        }

        @Override protected void onDraw(Canvas canvas) {
            long now = System.currentTimeMillis();
            long up = SystemClock.uptimeMillis();
            int w = getWidth(), h = getHeight();
            canvas.drawColor(full ? Color.BLACK : 0xCC000000);
            if (full) {
                int[] bars = {Color.WHITE, Color.YELLOW, Color.CYAN, Color.GREEN, Color.MAGENTA, Color.RED, Color.BLUE, Color.BLACK};
                for (int i = 0; i < bars.length; i++) {
                    paint.setColor(bars[i]);
                    canvas.drawRect(w * i / bars.length, 0, w * (i + 1) / bars.length, h / 6f, paint);
                }
                paint.setColor(Color.WHITE);
                float x = (up % 2000) / 2000f * w;
                canvas.drawRect(x, h * 0.8f, x + w / 40f, h * 0.95f, paint);
            }
            paint.setColor(Color.WHITE);
            paint.setTextAlign(Paint.Align.CENTER);
            paint.setTextSize(full ? h / 6f : h / 2.2f);
            canvas.drawText(clock.format(new Date(now)), w / 2f, full ? h * 0.5f : h * 0.62f, paint);
            if (full) {
                paint.setTextSize(h / 18f);
                canvas.drawText(String.format(Locale.ROOT, "frame %d   %dx%d   %.1f fps", frames, w, h, fps), w / 2f, h * 0.68f, paint);
            }
            frames++;
            if (up - sampleStart >= 1000) {
                fps = (frames - sampleFrames) * 1000.0 / Math.max(1, up - sampleStart);
                sampleStart = up;
                sampleFrames = frames;
            }
            postInvalidateOnAnimation();
        }
    }
}
