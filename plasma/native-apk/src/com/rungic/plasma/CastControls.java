package com.rungic.plasma;

import android.app.Activity;
import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.hardware.display.DisplayManager;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.util.TypedValue;
import android.view.Display;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import com.winland.server.NativeBridge;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Phone controls while the desktop is cast to a TV (docs/58 step 3). The phone
 * keeps the Plasma Mobile shell; a floating pill names the TV in use. It can be
 * dragged anywhere and snaps to the nearer left or right edge (kept across sessions);
 * after a few idle seconds it shrinks to a small tab on that edge. Tapped, either
 * opens a panel: the TV and its resolution, what the phone serves as ("手机"
 * normal touch, "触控板" the TV's touchpad, "键盘" touchpad plus the Android keyboard,
 * whose keys reach the focused Linux window), "更换设备" and "断开".
 * Touchpad gestures: one finger moves, tap clicks, tap then touch again drags,
 * two fingers scroll, two-finger tap right-clicks, three-finger tap middle-clicks.
 * While casting the phone screen stays on (screen off stops the desktop's
 * rendering, freezing the TV) and is dimmed in touchpad and keyboard modes.
 * The pill stays while the phone switches to another TV or rungic-cast-watch
 * reconnects a TV that dropped the session (the phone is a phone again meanwhile).
 */
final class CastControls {
    enum Mode { PHONE, TOUCHPAD, KEYBOARD }

    /** What the pill shows: the TV in use, a switch in progress or a reconnect. */
    private enum Session { NONE, CASTING, SWITCHING, RECONNECTING }

    private static final int BTN_LEFT = 0x110, BTN_RIGHT = 0x111, BTN_MIDDLE = 0x112;
    private static final String[] LABELS = {"手机", "触控板", "键盘"};
    private static final String TOOL = "/data/adb/rungic-wfd/rungic-cast";

    // The design's palette (docs/58): dark surfaces, a blue that carries white text.
    private static final int SURFACE = 0xF2202326, RAISED = 0xFF33383C, SUNKEN = 0xFF15181A;
    private static final int TEXT = 0xFFFCFCFC, TEXT_DIM = 0xFFA1A9B1, ACCENT = 0xFF1B6FA8;
    private static final int ACCENT_TEXT = 0xFF7FC3EC, DANGER = 0xFFF4A59D, DANGER_LINE = 0xFF7A3A34;
    private static final int WARN = 0xFFF0B35E;

    /** Phone screen brightness while it serves as touchpad or keyboard. */
    private static final float PAD_BRIGHTNESS = 0.08f;

    private final Activity context;
    private final FrameLayout frame;
    private final Consumer<Boolean> keyboard;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final TouchpadView touchpad;
    private final Pill pill;
    private final Panel panel;
    private DeviceSheet sheet;
    private boolean available, imeShown, userEnded;
    private Mode mode = Mode.PHONE;
    private Session session = Session.NONE;
    /** The TV in use (or being reconnected) and the one a switch goes to. */
    private String tvName = "", target = "", resolution = "";
    /** The pill shrinks to its edge tab after this long without a touch or a change. */
    private static final long SHRINK_AFTER_MS = 4000;
    private final Runnable shrink;
    private int statusPolls, connectionGeneration;

    CastControls(Activity context, FrameLayout frame, Consumer<Boolean> keyboard) {
        this.context = context;
        this.frame = frame;
        this.keyboard = keyboard;
        touchpad = new TouchpadView(context);
        pill = new Pill(context);
        shrink = () -> pill.setMini(true);
        panel = new Panel(context);
    }

    /** The cast window is bound (TV showing the desktop) or gone. */
    void setAvailable(boolean value) {
        if (available == value) return;
        available = value;
        if (!value) setMode(Mode.PHONE);
        ((MainActivity) context).setKeepAwake(MainActivity.AWAKE_CAST, value);
        if (value) {
            readDisplay();
            session = Session.CASTING;
            userEnded = false;
            handler.removeCallbacks(pollStatus);
        } else if (session == Session.CASTING) {
            // The phone ended the session, or the TV did: rungic-cast-watch then reconnects.
            session = Session.NONE;
            if (!userEnded) {
                statusPolls = 0;
                handler.postDelayed(pollStatus, 2000);
            }
        }
        if (sheet != null && !value) closeSheet();
        refresh();
    }

    Mode mode() { return mode; }

    boolean available() { return available; }

    void setMode(Mode next) {
        if (!available) next = Mode.PHONE;
        if (next == mode) return;
        Mode previous = mode;
        mode = next;
        boolean pad = next != Mode.PHONE;
        if (pad && touchpad.getParent() == null) {
            // Below the controls, above the desktop.
            int below = pill.getParent() == null ? frame.getChildCount() : frame.indexOfChild(pill);
            frame.addView(touchpad, below, new FrameLayout.LayoutParams(-1, -1));
        } else if (!pad && touchpad.getParent() != null) {
            touchpad.reset();
            frame.removeView(touchpad);
        }
        if (pad != (previous != Mode.PHONE)) {
            NativeBridge.castPointer(0, pad ? 1 : 0, 0);
            WindowManager.LayoutParams attrs = context.getWindow().getAttributes();
            attrs.screenBrightness = pad ? PAD_BRIGHTNESS : WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE;
            context.getWindow().setAttributes(attrs);
        }
        if ((next == Mode.KEYBOARD) != (previous == Mode.KEYBOARD)) keyboard.accept(next == Mode.KEYBOARD);
        refresh();
        touchpad.invalidate();
    }

    /** The Android keyboard was dismissed (back key or its own button). */
    void imeVisible(boolean visible) {
        boolean dismissed = imeShown && !visible;
        imeShown = visible;
        if (dismissed && mode == Mode.KEYBOARD) {
            mode = Mode.TOUCHPAD;
            refresh();
            touchpad.invalidate();
        }
    }

    JSONObject status() throws Exception {
        return new JSONObject().put("available", available).put("mode", mode.name().toLowerCase())
            .put("session", session.name().toLowerCase()).put("tv", tvName)
            .put("expanded", panel.getParent() != null).put("devices", sheet != null)
            .put("pill", pill.getParent() == null ? "hidden" : pill.mini ? "tab" : "full")
            .put("edge", pill.right ? "right" : "left")
            .put("keepScreenOn", (context.getWindow().getAttributes().flags & WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) != 0)
            .put("brightness", context.getWindow().getAttributes().screenBrightness);
    }

    /** Name and size of the cast display (Android names a Wi-Fi Display after the TV). */
    private void readDisplay() {
        for (Display d : context.getSystemService(DisplayManager.class).getDisplays(DisplayManager.DISPLAY_CATEGORY_PRESENTATION)) {
            if (d.getDisplayId() == Display.DEFAULT_DISPLAY) continue;
            tvName = receiverName(d.getName());
            Display.Mode m = d.getMode();
            resolution = m.getPhysicalWidth() + "×" + m.getPhysicalHeight();
            return;
        }
    }

    /** "TCL 85Q6H-9E92[R2]" -> "TCL 85Q6H-9E92", as rungic-cast names receivers. */
    private static String receiverName(String name) {
        return name == null ? "" : name.replaceFirst("\\s*\\[[^\\]]*\\]$", "");
    }

    /** Shows the pill (and panel) that fits the session, or nothing. */
    private void refresh() {
        boolean shown = session != Session.NONE;
        Session shownBefore = pill.shownSession;
        if (shown && pill.getParent() == null) {
            frame.addView(pill, new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.LEFT));
        } else if (!shown && pill.getParent() != null) {
            handler.removeCallbacks(shrink);
            frame.removeView(pill);
        }
        if (!shown) collapse();
        pill.refresh();
        // A new pill or a new state shows in full for a while.
        if (shown && shownBefore != session) pill.setMini(false);
        if (panel.getParent() != null) panel.refresh();
    }

    private void expand() {
        if (panel.getParent() != null) { collapse(); return; }
        handler.removeCallbacks(shrink);
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(-1, -2, Gravity.TOP);
        lp.topMargin = (int) Math.max(dp(56), Math.min(pill.getY() - dp(8), frame.getHeight() - dp(360)));
        lp.leftMargin = lp.rightMargin = dp(16);
        panel.refresh();
        if (available) tool(new String[] {"modes"},20,result -> {
            if (!available || result.has("error")) return;
            resolution=result.optString("actual",resolution);
            refresh();
        });
        frame.addView(panel, lp);
        pill.setVisibility(View.INVISIBLE);
    }

    /** Closes the panel; the pill comes back in full, then shrinks again. */
    private void collapse() {
        if (panel.getParent() == null && pill.getVisibility() == View.VISIBLE) return;
        if (panel.getParent() != null) frame.removeView(panel);
        pill.setVisibility(View.VISIBLE);
        if (pill.getParent() != null) pill.setMini(false);
    }

    private void disconnect() {
        connectionGeneration++;
        userEnded = true;
        handler.removeCallbacks(pollStatus);
        if (!available) session = Session.NONE;
        collapse();
        refresh();
        tool(new String[] {"disconnect"}, 20, result -> {
            if (result.has("error")) Toast.makeText(context, "断开失败：" + result.optString("error"), Toast.LENGTH_LONG).show();
        });
    }

    private void switchTo(String name) {
        closeSheet();
        collapse();
        if (name.equals(tvName) && available) return;
        final int generation = ++connectionGeneration;
        target = name;
        userEnded = true; // the session this ends is not the TV's doing
        handler.removeCallbacks(pollStatus);
        setMode(Mode.PHONE);
        session = Session.SWITCHING;
        refresh();
        tool(new String[] {"connect", name}, 180, result -> {
            if (generation != connectionGeneration) return;
            if (result.has("error") && !available) {
                session = Session.NONE;
                Toast.makeText(context, "没有连上“" + name + "”，接收端未能完成网络连接和协商，请重试", Toast.LENGTH_LONG).show();
            }
            target = "";
            refresh();
        });
    }

    private void openResolution() {
        tool(new String[] {"modes"}, 20, result -> {
            if (!available || context.isFinishing()) return;
            if (!result.optBoolean("adjustable")) {
                Toast.makeText(context, "当前系统暂不支持调整分辨率与帧率", Toast.LENGTH_LONG).show(); return;
            }
            JSONArray options = result.optJSONArray("options");
            if (options == null || options.length() == 0) return;
            String[] labels = new String[options.length()];
            int[] selected = {0};
            for (int i=0; i<labels.length; i++) {
                JSONObject option = options.optJSONObject(i);
                labels[i] = option.optString("label");
                if (option.optString("id").equals(result.optString("requested"))) selected[0] = i;
            }
            String address = result.optString("address");
            new android.app.AlertDialog.Builder(context)
                .setTitle("分辨率与帧率 · 当前 " + result.optString("actual", resolution))
                .setSingleChoiceItems(labels, selected[0], (dialog, which) -> selected[0] = which)
                .setNegativeButton("取消", null)
                .setPositiveButton("应用", (dialog, which) -> {
                    final int generation = ++connectionGeneration;
                    target = tvName; userEnded = true;
                    setMode(Mode.PHONE); session = Session.SWITCHING; collapse(); refresh();
                    tool(new String[] {"resolution", address+"/"+options.optJSONObject(selected[0]).optString("id")}, 330, done -> {
                        if (generation != connectionGeneration) return;
                        JSONObject mode = done.optJSONObject("resolution");
                        if (done.has("error")) {
                            session = available ? Session.CASTING : Session.NONE;
                            Toast.makeText(context, done.optBoolean("restored") ? "所选模式未生效，已恢复可用模式" : "切换失败，请重试或选择自动", Toast.LENGTH_LONG).show();
                        } else if (mode != null) {
                            resolution = mode.optString("actual", resolution);
                            Toast.makeText(context, "实际投屏："+resolution, Toast.LENGTH_LONG).show();
                        }
                        session = available ? Session.CASTING : Session.NONE;
                        target = ""; refresh();
                    });
                }).show();
        });
    }

    /** After the TV went away: is rungic-cast-watch reconnecting it? Follows it until it is done. */
    private final Runnable pollStatus = new Runnable() {
        @Override public void run() {
            tool(new String[] {"status"}, 15, result -> {
                if (available) return;
                boolean reconnecting = result.optBoolean("reconnecting");
                if (reconnecting) {
                    JSONObject last = lastReceiver(result);
                    if (last != null && tvName.isEmpty()) tvName = last.optString("name");
                    session = Session.RECONNECTING;
                } else if (session == Session.RECONNECTING || ++statusPolls >= 3) {
                    session = Session.NONE;
                    refresh();
                    return;
                }
                refresh();
                handler.postDelayed(this, reconnecting ? 3000 : 2500);
            });
        }
    };

    private static JSONObject lastReceiver(JSONObject status) {
        JSONArray list = status.optJSONArray("receivers");
        for (int i = 0; list != null && i < list.length(); i++) {
            if (list.optJSONObject(i).optBoolean("last")) return list.optJSONObject(i);
        }
        return null;
    }

    /** Runs the root tool rungic-cast off the UI thread; the callback gets its JSON on the UI thread. */
    private void tool(String[] args, int seconds, Consumer<JSONObject> callback) {
        Thread thread = new Thread(() -> {
            JSONObject result;
            try {
                StringBuilder line = new StringBuilder(TOOL);
                for (String arg : args) line.append(" '").append(arg.replace("'", "'\\''")).append('\'');
                Process process = new ProcessBuilder("su", "-c", line.toString()).redirectErrorStream(true).start();
                if (!process.waitFor(seconds, TimeUnit.SECONDS)) {
                    process.destroy();
                    throw new java.io.IOException("rungic-cast timed out");
                }
                String out = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8).trim();
                String last = out.substring(out.lastIndexOf('\n') + 1);
                result = last.startsWith("{") ? new JSONObject(last) : new JSONObject().put("error", out.isEmpty() ? "no output" : out);
            } catch (Exception e) {
                Log.w("RungicCast", "rungic-cast " + args[0] + ": " + e.getMessage());
                result = new JSONObject();
                try { result.put("error", String.valueOf(e.getMessage())); } catch (Exception ignored) {}
            }
            JSONObject done = result;
            handler.post(() -> callback.accept(done));
        }, "rungic-cast-" + args[0]);
        thread.setDaemon(true);
        thread.start();
    }

    private void openSheet() {
        collapse();
        if (sheet != null) return;
        sheet = new DeviceSheet(context);
        frame.addView(sheet, new FrameLayout.LayoutParams(-1, -1));
        tool(new String[] {"status"}, 15, result -> { if (sheet != null) sheet.show(result); });
    }

    private void closeSheet() {
        if (sheet == null) return;
        frame.removeView(sheet);
        sheet = null;
    }

    private int dp(float value) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, context.getResources().getDisplayMetrics()));
    }

    private GradientDrawable round(int color, float radiusDp) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(dp(radiusDp));
        return d;
    }

    /**
     * Pressed feedback: a ripple over the view's own fill, clipped to its shape (a
     * transparent fill still shows the press).
     */
    private void pressable(View v, GradientDrawable fill) {
        GradientDrawable mask = new GradientDrawable();
        mask.setColor(Color.WHITE);
        mask.setCornerRadii(fill.getCornerRadii() != null ? fill.getCornerRadii() : radii(fill.getCornerRadius()));
        v.setBackground(new RippleDrawable(ColorStateList.valueOf(0x40FFFFFF), fill, mask));
        v.setClickable(true);
        v.setFocusable(true);
    }

    private static float[] radii(float r) {
        return new float[] {r, r, r, r, r, r, r, r};
    }

    private TextView text(String value, float sp, int color, boolean bold) {
        TextView t = new TextView(context);
        t.setText(value);
        t.setTextColor(color);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        if (bold) t.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        return t;
    }

    private ProgressBar spinner(int sizeDp, int color) {
        ProgressBar p = new ProgressBar(context);
        p.setIndeterminate(true);
        p.setIndeterminateTintList(ColorStateList.valueOf(color));
        p.setLayoutParams(new LinearLayout.LayoutParams(dp(sizeDp), dp(sizeDp)));
        return p;
    }

    /** A 48 dp pill button; danger ones are outlined. */
    private TextView button(String label, boolean danger, View.OnClickListener click) {
        TextView b = text(label, 14, danger ? DANGER : TEXT, false);
        b.setGravity(Gravity.CENTER);
        b.setMinHeight(dp(48));
        GradientDrawable bg = round(danger ? Color.TRANSPARENT : RAISED, 24);
        if (danger) bg.setStroke(dp(1), DANGER_LINE);
        pressable(b, bg);
        b.setOnClickListener(click);
        b.setContentDescription(label);
        return b;
    }

    /** TV outline, stroked like the rest of the shell's icons; "live" adds the cast arc. */
    private final class TvIcon extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final boolean live;

        TvIcon(Context context, int color, boolean live) {
            super(context);
            this.live = live;
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setColor(color);
        }

        @Override protected void onDraw(Canvas canvas) {
            float u = Math.min(getWidth(), getHeight()) / 24f;
            float ox = (getWidth() - 24 * u) / 2, oy = (getHeight() - 24 * u) / 2;
            paint.setStrokeWidth(1.8f * u);
            canvas.drawRoundRect(ox + 3 * u, oy + 4 * u, ox + 21 * u, oy + 16 * u, 2 * u, 2 * u, paint);
            canvas.drawLine(ox + 8 * u, oy + 20 * u, ox + 16 * u, oy + 20 * u, paint);
            canvas.drawLine(ox + 12 * u, oy + 16 * u, ox + 12 * u, oy + 20 * u, paint);
            if (live) canvas.drawArc(ox + 9 * u, oy + 7 * u, ox + 15 * u, oy + 13 * u, 180, 180, false, paint);
        }
    }

    /** The TV icon on a round badge. */
    private FrameLayout badge(int sizeDp, int fill, int iconColor, boolean live) {
        FrameLayout f = new FrameLayout(context);
        f.setBackground(round(fill, sizeDp / 2f));
        f.addView(new TvIcon(context, iconColor, live), new FrameLayout.LayoutParams(dp(sizeDp * 0.55f), dp(sizeDp * 0.55f), Gravity.CENTER));
        return f;
    }

    /**
     * The pill, in four states: full (TV icon, name and a line of state) when it
     * appears, when the session changes (switching, reconnecting) and after a touch;
     * the edge tab (the icon alone, flat against the edge) after SHRINK_AFTER_MS idle;
     * lifted while dragged (anywhere on the screen); hidden while the panel is open.
     * Released, it snaps to the nearer left or right edge, between the status bar and
     * the bottom gesture area, and remembers that place. The tab and the full pill are
     * both 48 dp tall, so a shrink never moves it vertically. A tap on either opens
     * the panel. Pending states (switching, reconnecting) tint the icon orange.
     */
    private final class Pill extends LinearLayout {
        private final FrameLayout icon;
        private final GradientDrawable iconFill;
        private final LinearLayout texts;
        private final TextView title, subtitle;
        private final ProgressBar busy;
        private final int slop = ViewConfiguration.get(context).getScaledTouchSlop();
        private float downRawX, downRawY, startX, startY;
        private boolean dragging, mini, right;
        private float yFraction;
        Session shownSession = Session.NONE;

        Pill(Context context) {
            super(context);
            setOrientation(HORIZONTAL);
            setGravity(Gravity.CENTER_VERTICAL);
            setMinimumHeight(dp(48));
            setElevation(dp(6));
            android.content.SharedPreferences prefs = ((Activity) context).getPreferences(Context.MODE_PRIVATE);
            right = prefs.getBoolean("cast_pill_right", true);
            yFraction = prefs.getFloat("cast_pill_y", 0.33f);
            icon = badge(32, ACCENT, Color.WHITE, true);
            iconFill = (GradientDrawable) icon.getBackground();
            addView(icon, new LayoutParams(dp(32), dp(32)));
            busy = spinner(20, WARN);
            ((LayoutParams) busy.getLayoutParams()).leftMargin = dp(8);
            addView(busy);
            texts = new LinearLayout(context);
            texts.setOrientation(VERTICAL);
            texts.setPadding(dp(10), 0, 0, 0);
            title = text("", 14, TEXT, true);
            title.setMaxWidth(dp(170));
            title.setSingleLine(true);
            title.setEllipsize(android.text.TextUtils.TruncateAt.END);
            subtitle = text("", 11, TEXT_DIM, false);
            texts.addView(title);
            texts.addView(subtitle);
            addView(texts);
            setOnClickListener(v -> expand());
            // Width changes (full <-> tab, a longer name) keep it against its edge. On the edge it
            // sits where Android's back gesture starts: its own area is excluded from that gesture.
            addOnLayoutChangeListener((v, l, t, r, b, ol, ot, or, ob) -> {
                setSystemGestureExclusionRects(java.util.Collections.singletonList(new android.graphics.Rect(0, 0, r - l, b - t)));
                if (!dragging && r - l != or - ol) pin(false);
            });
            frame.addOnLayoutChangeListener((v, l, t, r, b, ol, ot, or, ob) -> { if (getParent() != null && !dragging) pin(false); });
            shape();
        }

        void refresh() {
            shownSession = session;
            boolean pending = session == Session.SWITCHING || session == Session.RECONNECTING;
            iconFill.setColor(pending ? 0xFF8A5A1C : ACCENT);
            busy.setVisibility(pending && !mini ? VISIBLE : GONE);
            switch (session) {
                case SWITCHING:
                    title.setText(target);
                    subtitle.setText("正在切换…");
                    subtitle.setTextColor(WARN);
                    break;
                case RECONNECTING:
                    title.setText(tvName.isEmpty() ? "电视" : tvName);
                    subtitle.setText("电视断开，正在重连…");
                    subtitle.setTextColor(WARN);
                    break;
                default:
                    title.setText(tvName.isEmpty() ? "电视" : tvName);
                    subtitle.setText(mode == Mode.PHONE ? "投屏控制" : "手机用作" + LABELS[mode.ordinal()]);
                    subtitle.setTextColor(TEXT_DIM);
            }
            setContentDescription("投屏控制：" + title.getText() + "，" + subtitle.getText());
        }

        /** Full pill or edge tab; full ones shrink again after a while. */
        void setMini(boolean value) {
            handler.removeCallbacks(shrink);
            if (!value) handler.postDelayed(shrink, SHRINK_AFTER_MS);
            if (mini == value) return;
            mini = value;
            texts.setVisibility(value ? GONE : VISIBLE);
            refresh();
            shape();
        }

        /** Full: a rounded pill off the edge. Tab: flat on the edge side, round on the other. */
        private void shape() {
            GradientDrawable bg = new GradientDrawable();
            bg.setColor(SURFACE);
            float r = dp(24);
            if (mini) {
                bg.setCornerRadii(right ? new float[] {r, r, 0, 0, 0, 0, r, r} : new float[] {0, 0, r, r, r, r, 0, 0});
                setPadding(right ? dp(8) : dp(6), dp(8), right ? dp(6) : dp(8), dp(8));
            } else {
                bg.setCornerRadius(r);
                setPadding(dp(8), dp(8), dp(16), dp(8));
            }
            pressable(this, bg);
        }

        private float edgeGap() { return mini ? 0 : dp(12); }

        private float minY() { return dp(56); }

        private float maxY() { return Math.max(minY(), frame.getHeight() - getHeight() - dp(96)); }

        /** To its edge at its remembered height. */
        void pin(boolean animate) {
            if (frame.getWidth() == 0 || getWidth() == 0) { post(() -> pin(animate)); return; }
            float x = right ? frame.getWidth() - getWidth() - edgeGap() : edgeGap();
            float y = Math.max(minY(), Math.min(maxY(), yFraction * frame.getHeight()));
            if (animate) {
                animate().x(x).y(y).scaleX(1).scaleY(1).translationZ(0)
                    .setDuration(220).setInterpolator(new android.view.animation.DecelerateInterpolator()).start();
            } else {
                animate().cancel();
                setX(x);
                setY(y);
            }
        }

        // A drag moves it freely; a tap opens the panel.
        @Override public boolean onInterceptTouchEvent(MotionEvent e) {
            if (e.getActionMasked() == MotionEvent.ACTION_DOWN) start(e);
            else if (e.getActionMasked() == MotionEvent.ACTION_MOVE && moved(e)) dragging = true;
            return dragging;
        }

        private void start(MotionEvent e) {
            downRawX = e.getRawX();
            downRawY = e.getRawY();
            startX = getX();
            startY = getY();
            dragging = false;
            handler.removeCallbacks(shrink);
        }

        private boolean moved(MotionEvent e) {
            return Math.hypot(e.getRawX() - downRawX, e.getRawY() - downRawY) > slop;
        }

        @Override public boolean onTouchEvent(MotionEvent e) {
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    start(e);
                    super.onTouchEvent(e); // pressed state
                    return true;
                case MotionEvent.ACTION_MOVE:
                    if (!dragging && moved(e)) {
                        dragging = true;
                        setPressed(false);
                        animate().scaleX(1.06f).scaleY(1.06f).translationZ(dp(6)).setDuration(120).start();
                    }
                    if (dragging) {
                        setX(Math.max(0, Math.min(frame.getWidth() - getWidth(), startX + e.getRawX() - downRawX)));
                        setY(Math.max(0, Math.min(frame.getHeight() - getHeight(), startY + e.getRawY() - downRawY)));
                    }
                    return true;
                case MotionEvent.ACTION_UP:
                    if (dragging) {
                        dragging = false;
                        right = getX() + getWidth() / 2f > frame.getWidth() / 2f;
                        yFraction = Math.max(minY(), Math.min(maxY(), getY())) / frame.getHeight();
                        ((Activity) context).getPreferences(Context.MODE_PRIVATE).edit()
                            .putBoolean("cast_pill_right", right).putFloat("cast_pill_y", yFraction).apply();
                        shape();
                        pin(true);
                        handler.postDelayed(shrink, SHRINK_AFTER_MS);
                        return true;
                    }
                    return super.onTouchEvent(e); // a tap: performClick
                case MotionEvent.ACTION_CANCEL:
                    if (dragging) { dragging = false; pin(true); }
                    handler.postDelayed(shrink, SHRINK_AFTER_MS);
                    return super.onTouchEvent(e);
                default:
                    return true;
            }
        }
    }

    /** Expanded: the TV, what the phone serves as, change TV and disconnect. */
    private final class Panel extends LinearLayout {
        Panel(Context context) {
            super(context);
            setOrientation(VERTICAL);
            setPadding(dp(16), dp(16), dp(16), dp(16));
            setBackground(round(0xFF202326, 24));
            setElevation(dp(10));
            setClickable(true);
        }

        void refresh() {
            removeAllViews();
            boolean pending = session == Session.SWITCHING || session == Session.RECONNECTING;

            LinearLayout header = new LinearLayout(context);
            header.setGravity(Gravity.CENTER_VERTICAL);
            header.addView(badge(44, pending ? 0xFF6B4A1F : ACCENT, Color.WHITE, true), new LayoutParams(dp(44), dp(44)));
            LinearLayout texts = new LinearLayout(context);
            texts.setOrientation(VERTICAL);
            texts.setPadding(dp(12), 0, dp(8), 0);
            String caption = session == Session.SWITCHING ? "正在切换到"
                : session == Session.RECONNECTING ? "电视断开，正在重连…" : "正在投屏";
            texts.addView(text(caption, 12, pending ? WARN : TEXT_DIM, false));
            TextView name = text(session == Session.SWITCHING ? target : (tvName.isEmpty() ? "电视" : tvName), 17, TEXT, true);
            texts.addView(name);
            String detail = session == Session.CASTING ? resolution
                : session == Session.RECONNECTING ? "等待电视重新接受连接" : "正在等待接收端联网和协商，最多两分钟";
            if (!detail.isEmpty()) texts.addView(text(detail, 12, TEXT_DIM, false));
            header.addView(texts, new LayoutParams(0, -2, 1));
            TextView close = text("︿", 16, 0xFFD0D5D9, false);
            close.setGravity(Gravity.CENTER);
            pressable(close, round(0xFF2D3236, 22));
            close.setContentDescription("收起投屏控制");
            close.setOnClickListener(v -> collapse());
            header.addView(close, new LayoutParams(dp(44), dp(44)));
            addView(header);

            if (session == Session.CASTING) {
                TextView label = text("手机用作", 12, TEXT_DIM, true);
                label.setPadding(0, dp(14), 0, dp(6));
                addView(label);
                LinearLayout segments = new LinearLayout(context);
                segments.setPadding(dp(4), dp(4), dp(4), dp(4));
                segments.setBackground(round(SUNKEN, 16));
                for (int i = 0; i < 3; i++) {
                    final Mode m = Mode.values()[i];
                    boolean on = mode == m;
                    TextView seg = text(LABELS[i], 14, on ? Color.WHITE : 0xFFD0D5D9, on);
                    seg.setGravity(Gravity.CENTER);
                    seg.setMinHeight(dp(48));
                    pressable(seg, round(on ? ACCENT : Color.TRANSPARENT, 12));
                    seg.setContentDescription("手机用作" + LABELS[i] + (on ? "，已选中" : ""));
                    seg.setOnClickListener(v -> { setMode(m); refresh(); });
                    LayoutParams lp = new LayoutParams(0, -2, 1);
                    if (i > 0) lp.leftMargin = dp(4);
                    segments.addView(seg, lp);
                }
                addView(segments);
                TextView modeButton = button("分辨率与帧率…", false, v -> openResolution());
                LayoutParams mlp = new LayoutParams(-1,-2); mlp.topMargin = dp(12);
                addView(modeButton, mlp);
                TextView note = text("优先直接切换，必要时重新连接；未能应用时恢复可用模式。",12,TEXT_DIM,false);
                note.setPadding(0,dp(6),0,0); addView(note);
            } else if (session == Session.RECONNECTING) {
                TextView note = text("重连期间手机恢复为普通触控。电视回到等待画面后会自动接上。", 13, 0xFFC4CACE, false);
                note.setLineSpacing(0, 1.3f);
                note.setPadding(dp(12), dp(10), dp(12), dp(10));
                note.setBackground(round(SUNKEN, 12));
                LayoutParams lp = new LayoutParams(-1, -2);
                lp.topMargin = dp(14);
                addView(note, lp);
            }

            LinearLayout actions = new LinearLayout(context);
            LayoutParams alp = new LayoutParams(-1, -2);
            alp.topMargin = dp(14);
            actions.addView(button("更换设备", false, v -> openSheet()), new LayoutParams(0, -2, 1));
            String stop = session == Session.RECONNECTING ? "停止重连" : session == Session.SWITCHING ? "取消" : "断开";
            LayoutParams slp = new LayoutParams(0, -2, 1);
            slp.leftMargin = dp(10);
            actions.addView(button(stop, true, v -> disconnect()), slp);
            addView(actions, alp);
        }
    }

    /** "更换投屏设备": the TV in use and the others rungic-cast knows (Android cannot scan while casting). */
    private final class DeviceSheet extends FrameLayout {
        private final LinearLayout list;

        DeviceSheet(Context context) {
            super(context);
            setBackgroundColor(0x8C000000);
            setElevation(dp(16)); // above the pill and panel
            setOnClickListener(v -> closeSheet());
            LinearLayout sheet = new LinearLayout(context);
            sheet.setOrientation(LinearLayout.VERTICAL);
            GradientDrawable bg = new GradientDrawable();
            bg.setColor(0xFF25292C);
            float r = dp(24);
            bg.setCornerRadii(new float[] {r, r, r, r, 0, 0, 0, 0});
            sheet.setBackground(bg);
            sheet.setPadding(0, dp(8), 0, dp(20));
            sheet.setClickable(true);

            View handle = new View(context);
            handle.setBackground(round(0xFF4D5358, 2));
            LinearLayout.LayoutParams hlp = new LinearLayout.LayoutParams(dp(36), dp(4));
            hlp.gravity = Gravity.CENTER_HORIZONTAL;
            hlp.bottomMargin = dp(8);
            sheet.addView(handle, hlp);

            LinearLayout header = new LinearLayout(context);
            header.setGravity(Gravity.CENTER_VERTICAL);
            header.setPadding(dp(20), 0, dp(12), dp(8));
            LinearLayout texts = new LinearLayout(context);
            texts.setOrientation(LinearLayout.VERTICAL);
            texts.addView(text("更换投屏设备", 20, TEXT, true));
            texts.addView(text("投屏时无法搜索新电视，列出最近发现的电视", 13, TEXT_DIM, false));
            header.addView(texts, new LinearLayout.LayoutParams(0, -2, 1));
            TextView close = text("✕", 18, 0xFFD0D5D9, false);
            close.setGravity(Gravity.CENTER);
            close.setContentDescription("关闭");
            pressable(close, round(Color.TRANSPARENT, 22));
            close.setOnClickListener(v -> closeSheet());
            header.addView(close, new LinearLayout.LayoutParams(dp(44), dp(44)));
            sheet.addView(header);

            list = new LinearLayout(context);
            list.setOrientation(LinearLayout.VERTICAL);
            ScrollView scroll = new ScrollView(context);
            scroll.addView(list);
            sheet.addView(scroll, new LinearLayout.LayoutParams(-1, -2));
            list.addView(loadingRow());

            TextView note = text("切换时会先断开当前电视，新电视出现画面前会中断几秒，桌面上打开的应用不受影响。", 13, 0xFFC4CACE, false);
            note.setLineSpacing(0, 1.3f);
            note.setPadding(dp(14), dp(12), dp(14), dp(12));
            note.setBackground(round(0xFF1B1E20, 12));
            LinearLayout.LayoutParams nlp = new LinearLayout.LayoutParams(-1, -2);
            nlp.leftMargin = nlp.rightMargin = dp(20);
            nlp.topMargin = dp(12);
            sheet.addView(note, nlp);

            addView(sheet, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));
        }

        private View loadingRow() {
            LinearLayout row = new LinearLayout(context);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setPadding(dp(20), dp(12), dp(20), dp(12));
            row.addView(spinner(18, ACCENT_TEXT));
            TextView t = text("正在读取设备…", 14, TEXT_DIM, false);
            t.setPadding(dp(10), 0, 0, 0);
            row.addView(t);
            return row;
        }

        void show(JSONObject status) {
            list.removeAllViews();
            JSONArray receivers = status.optJSONArray("receivers");
            int others = 0;
            for (int i = 0; receivers != null && i < receivers.length(); i++) {
                JSONObject r = receivers.optJSONObject(i);
                boolean current = r.optBoolean("active");
                if (!current && !r.optBoolean("last") && r.isNull("seen_ms_ago")) continue;
                if (current && others == 0 && i + 1 < receivers.length()) {
                    list.addView(row(r, true));
                    View divider = new View(context);
                    divider.setBackgroundColor(0xFF373C40);
                    LinearLayout.LayoutParams dlp = new LinearLayout.LayoutParams(-1, dp(1));
                    dlp.leftMargin = dlp.rightMargin = dp(20);
                    list.addView(divider, dlp);
                    continue;
                }
                if (!current) others++;
                list.addView(row(r, current));
            }
            if (others == 0) {
                TextView none = text("没有其他最近发现的电视。断开后，在快捷设置的“投屏”里可以重新搜索。", 14, TEXT_DIM, false);
                none.setLineSpacing(0, 1.3f);
                none.setPadding(dp(20), dp(12), dp(20), dp(4));
                list.addView(none);
            }
        }

        private View row(JSONObject r, boolean current) {
            String name = r.optString("name");
            LinearLayout row = new LinearLayout(context);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setMinimumHeight(dp(68));
            row.setPadding(dp(20), dp(10), dp(20), dp(10));
            row.addView(badge(44, current ? ACCENT : RAISED, current ? Color.WHITE : 0xFFD0D5D9, current), new LinearLayout.LayoutParams(dp(44), dp(44)));
            LinearLayout texts = new LinearLayout(context);
            texts.setOrientation(LinearLayout.VERTICAL);
            texts.setPadding(dp(14), 0, dp(8), 0);
            LinearLayout line = new LinearLayout(context);
            line.setGravity(Gravity.CENTER_VERTICAL);
            TextView title = text(name, 16, TEXT, false);
            title.setSingleLine(true);
            title.setEllipsize(android.text.TextUtils.TruncateAt.END);
            line.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
            if (current) {
                TextView tag = text("当前", 11, Color.WHITE, true);
                tag.setPadding(dp(8), dp(2), dp(8), dp(2));
                tag.setBackground(round(ACCENT, 10));
                LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(-2, -2);
                tlp.leftMargin = dp(8);
                line.addView(tag, tlp);
            }
            texts.addView(line, new LinearLayout.LayoutParams(-1, -2));
            String sub = current ? "正在投屏" + (resolution.isEmpty() ? "" : " · " + resolution)
                : r.optBoolean("last") ? "上次使用" : "最近发现";
            texts.addView(text(sub, 13, current ? ACCENT_TEXT : TEXT_DIM, false));
            row.addView(texts, new LinearLayout.LayoutParams(0, -2, 1));
            row.addView(text(current ? "✓" : "›", 20, current ? ACCENT_TEXT : 0xFF8A939B, false));
            row.setContentDescription(name + "，" + sub);
            if (!current) {
                pressable(row, round(Color.TRANSPARENT, 0));
                row.setOnClickListener(v -> switchTo(name));
            }
            return row;
        }
    }

    /** Full-screen touchpad over the phone desktop (gestures: TouchpadGestures). */
    private final class TouchpadView extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final TouchpadGestures gestures;

        TouchpadView(Context context) {
            super(context);
            paint.setTextAlign(Paint.Align.CENTER);
            // The TV at the same visual angle as the finger: 1:1 as seen when slow (docs/66).
            float phonePxPerMm = context.getResources().getDisplayMetrics().xdpi / 25.4f;
            gestures = new TouchpadGestures(new PointerOutput(handler),
                new PointerTransfer(phonePxPerMm, PointerTransfer.TOUCHPAD_TV_PX_PER_MM), handler);
        }

        void reset() { gestures.reset(); }

        @Override protected void onDraw(Canvas canvas) {
            canvas.drawColor(0xB0101214);
            int w = getWidth(), h = getHeight();
            float cy = mode == Mode.KEYBOARD ? h * 0.22f : h * 0.42f;
            paint.setColor(Color.WHITE);
            paint.setTextSize(dp(22));
            canvas.drawText(mode == Mode.KEYBOARD ? "键盘" : "触控板", w / 2f, cy, paint);
            paint.setColor(0xB0FFFFFF);
            paint.setTextSize(dp(14));
            String[] lines = {"单指移动光标，轻点单击", "轻点后再按住拖动", "双指滚动，双指轻点右键"};
            for (int i = 0; i < lines.length; i++) canvas.drawText(lines[i], w / 2f, cy + dp(34) + i * dp(24), paint);
        }

        @Override public boolean onTouchEvent(MotionEvent e) { return gestures.onTouchEvent(e); }
    }
}
