package com.rungic.plasma;

import android.app.Activity;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.RectF;
import android.os.Handler;
import android.os.Looper;
import android.view.Display;
import android.view.View;
import android.view.WindowManager;
import com.winland.server.NativeBridge;
import java.util.ArrayList;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * The director (导播台, docs/58): the assistant's screens (agent workspaces) seen together, one of
 * them in focus. Its state is one, shared by the phone's director window (Linux, through the
 * platform bridge op "director") and the TV: the focus, and how large it is (`level`):
 * 0 standard (the other screens in a column on its right, about a quarter of the width), 1
 * enlarged (a narrow column), 2 solo (the focus only). Members are the workspaces running now (the host's liveSources).
 *
 * It is laid out large where there is room: fullscreen on the phone (AgentFullscreen, entered from
 * the director's floating window) and on a TV, the same picture there and there. A TV shows the
 * director, or the user's desktop in computer mode ("desktop"): chosen in the cast controls; a new
 * TV shows the director while there is one. The host puts each tile on a layer of its own in the
 * presenter's window (NativeBridge.setDirector); the labels are drawn above it (on the TV a window
 * of its own, fullscreen AgentFullscreen's layer). A change of focus or level puts the tiles in
 * place at once; the new focus then brightens in from a light dim (`settle()`), drawn on those
 * layers only: moving the tiles frame by frame made the host present every screen anew each
 * frame, and stuttered.
 */
final class Director {
    static final int STANDARD = 0, ENLARGED = 1, SOLO = 2;
    private static final long POLL_MS = 1000, BANNER_MS = 2500;

    private final Activity activity;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private List<Integer> members = new ArrayList<>();
    private int focus = 1, level = STANDARD;
    /** What a TV shows: the director, or the user's desktop. */
    private boolean tvDirector = true;
    private boolean bound;
    private float[][] tiles = new float[0][];
    private int[] tileSlots = new int[0];
    private Labels labels;
    private WindowManager windowManager;
    private Display display;
    private long bannerUntil;
    /** Fullscreen on the phone shows the director (it then owns the presenter, not a TV). */
    private boolean fullscreen;
    private final List<Runnable> listeners = new ArrayList<>();
    private android.animation.ValueAnimator animation;
    private static final long SETTLE_MS = 180;
    private long settleStart;
    /** Width over height of the window the director is laid out in (the TV, the phone turned). */
    private float aspect = 16f / 9f;
    /** Bumped at every change: the phone's director window follows it. */
    private int version;

    Director(Activity activity) {
        this.activity = activity;
        level = activity.getPreferences(Context.MODE_PRIVATE).getInt("director_level", STANDARD);
        handler.post(poll);
    }

    List<Integer> members() { return members; }
    int focus() { return focus; }
    int level() { return level; }
    boolean bound() { return bound; }
    /** The TV shows the director now (else the user's desktop, or no TV). */
    boolean onTv() { return bound && tvDirector && !members.isEmpty(); }

    /** Fullscreen on the phone shows the director, or no longer. */
    void setFullscreen(boolean value, float windowAspect) {
        // Bound again (a new window): laid out anew all the same.
        if (fullscreen == value && !value) return;
        fullscreen = value;
        if (value && windowAspect > 0) aspect = windowAspect;
        version++;
        if (value) { tiles = new float[0][]; tileSlots = new int[0]; apply(false); }
    }
    boolean fullscreen() { return fullscreen; }

    /** Laid out in tiles now: on the TV, or fullscreen on the phone. */
    private boolean laidOut() { return (onTv() || fullscreen) && !members.isEmpty(); }

    /** The tiles as shown now (fractions of the 16:9 picture), the focus first; `tileSlots` their screens. */
    float[][] tiles() { return tiles; }
    int[] tileSlots() { return tileSlots; }

    /** Called after every change of the tiles (fullscreen's touches and labels follow them). */
    void addListener(Runnable listener) { listeners.add(listener); }
    void removeListener(Runnable listener) { listeners.remove(listener); }

    /** The source the TV's presenter shows first (0 the user's desktop, n workspace n). */
    int tvSource() { return onTv() ? focus : 0; }

    /** Workspaces on the TV now (the focus first). */
    List<Integer> shown() {
        List<Integer> out = new ArrayList<>();
        if (!onTv()) return out;
        out.add(focus);
        if (level != SOLO) for (int slot : members) if (slot != focus) out.add(slot);
        return out;
    }

    /** A TV's window is bound (on `display`) or gone. A new TV shows the director while there is one. */
    void bound(boolean value, Display on) {
        bound = value;
        display = on;
        if (value) {
            if (on != null) {
                Display.Mode mode = on.getMode();
                aspect = mode.getPhysicalWidth() / (float) Math.max(1, mode.getPhysicalHeight());
            }
            refreshMembers();
            tvDirector = true;
            tiles = new float[0][]; tileSlots = new int[0];
            apply(false);
            showBanner();
        } else {
            tiles = new float[0][]; tileSlots = new int[0];
            try { NativeBridge.setDirector(tileSlots, new float[0], 0); } catch (UnsatisfiedLinkError e) { /* an older host */ }
            removeLabels();
        }
        version++;
    }

    void setFocus(int slot) {
        if (slot <= 0) return;
        focus = slot;
        changed(true);
    }

    /** The next (+1) or previous (-1) member in focus. */
    void step(int delta) {
        refreshMembers();
        if (members.isEmpty()) return;
        int at = Math.max(0, members.indexOf(focus));
        setFocus(members.get(Math.floorMod(at + delta, members.size())));
    }

    void setLevel(int value) {
        level = Math.max(STANDARD, Math.min(SOLO, value));
        activity.getPreferences(Context.MODE_PRIVATE).edit().putInt("director_level", level).apply();
        changed(false);
    }

    /** What a TV shows: the director (true) or the user's desktop. */
    void setTvDirector(boolean value) {
        tvDirector = value;
        changed(true);
    }

    boolean tvDirector() { return tvDirector && !members.isEmpty(); }

    JSONObject state() throws Exception {
        JSONArray all = new JSONArray(), on = new JSONArray();
        for (int slot : members) all.put(slot);
        for (int slot : shown()) on.put(slot);
        return new JSONObject().put("members", all).put("focus", focus).put("level", level)
            .put("version", version)
            .put("tv", new JSONObject().put("connected", bound).put("content", onTv() ? "director" : bound ? "desktop" : JSONObject.NULL)
                .put("shown", on).put("heard", onTv() ? focus : -1));
    }

    String label(int slot) {
        return slot == 0 ? activity.getString(R.string.tv_desktop) : activity.getString(R.string.tv_workspace, slot);
    }

    private void changed(boolean banner) {
        version++;
        if (laidOut()) apply(true);
        else if (bound) apply(false);
        if (bound && banner) showBanner();
    }

    private final Runnable poll = new Runnable() {
        @Override public void run() {
            List<Integer> before = members;
            refreshMembers();
            if (!before.equals(members)) {
                version++;
                if (bound || fullscreen) apply(true);
            }
            handler.postDelayed(this, POLL_MS);
        }
    };

    private void refreshMembers() {
        int mask = 0;
        try { mask = NativeBridge.liveSources(); } catch (UnsatisfiedLinkError e) { /* an older host */ }
        List<Integer> found = new ArrayList<>();
        for (int slot = 1; slot < 31; slot++) if ((mask & (1 << slot)) != 0) found.add(slot);
        members = found;
        // A focus that closed: the first member left.
        if (!members.isEmpty() && !members.contains(focus)) focus = members.get(0);
    }

    /**
     * The host's layout and the labels for the current state, at once; `animate`: a new focus
     * brightens in (settle()).
     */
    private void apply(boolean animate) {
        if (animation != null) animation.cancel();
        if (!laidOut()) {
            tiles = new float[0][]; tileSlots = new int[0];
            send(tiles, tileSlots);
            return;
        }
        int[] slots;
        float[][] to;
        if (level == SOLO || members.size() == 1) {
            // 16:9 and as large as fits, centred: the picture is never stretched.
            float w = Math.min(aspect, 16f / 9f), h = w * 9f / 16f;
            slots = new int[] {focus};
            to = new float[][] {{(aspect - w) / 2f / aspect, (1 - h) / 2f, w / aspect, h}};
        } else {
            Object[] laid = layout();
            to = (float[][]) laid[0];
            slots = (int[]) laid[1];
        }
        boolean newFocus = tileSlots.length > 0 && tileSlots[0] != slots[0];
        tiles = to; tileSlots = slots;
        if (animate && newFocus) settleStart = android.os.SystemClock.uptimeMillis();
        send(tiles, tileSlots);
        if (animate && newFocus) {
            if (animation != null) animation.cancel();
            animation = android.animation.ValueAnimator.ofFloat(0f, 1f).setDuration(SETTLE_MS);
            animation.addUpdateListener(a -> {
                if (labels != null) labels.invalidate();
                for (Runnable listener : new ArrayList<>(listeners)) listener.run();
            });
            animation.start();
        }
    }

    /** How dim the focus is drawn over now, 0..1: a new focus starts lightly dimmed and clears. */
    float settle() {
        float t = (android.os.SystemClock.uptimeMillis() - settleStart) / (float) SETTLE_MS;
        return t >= 1 ? 0 : 0.45f * (1 - t) * (1 - t);
    }

    /** The tiles to the host, the labels and the listeners. */
    private void send(float[][] rects, int[] slots) {
        float[] flat = new float[rects.length * 4];
        for (int i = 0; i < rects.length; i++) System.arraycopy(rects[i], 0, flat, 4 * i, 4);
        int presented = slots.length > 0 ? slots[0] : tvSource();
        try { NativeBridge.setDirector(slots, flat, presented); }
        catch (UnsatisfiedLinkError e) { NativeBridge.presentWorkspace(presented); }
        if (labels != null) labels.invalidate();
        else if (bound && onTv() && rects.length > 1) addLabels();
        for (Runnable listener : new ArrayList<>(listeners)) listener.run();
    }

    /**
     * Fractions of the window (`aspect` wide, 1 high): the other screens 16:9 in a column on the
     * right, about a quarter of the width (standard) or an eighth (enlarged), stacked and centred;
     * the focus 16:9 and as large as fits in the rest, centred there. A wide window (the phone
     * turned, 20:9) gives the column the room beside a full-height focus.
     */
    private Object[] layout() {
        List<Integer> others = new ArrayList<>();
        for (int slot : members) if (slot != focus) others.add(slot);
        float a = aspect, gap = level == ENLARGED ? 0.012f : 0.02f;
        int k = others.size();
        float tw = (level == ENLARGED ? 0.12f : 0.24f) * a;
        float th = Math.min(tw * 9f / 16f, (1 - (k + 1) * gap) / k);
        tw = th * 16f / 9f;
        float restW = a - tw - 3 * gap;
        float fh = Math.min(1 - 2 * gap, restW * 9f / 16f), fw = fh * 16f / 9f;
        float fx = gap + (restW - fw) / 2f, fy = (1 - fh) / 2f;
        float colX = a - gap - tw, colY = (1 - (k * th + (k - 1) * gap)) / 2f;
        float[][] rects = new float[k + 1][];
        int[] slots = new int[k + 1];
        slots[0] = focus;
        rects[0] = new float[] {fx / a, fy, fw / a, fh};
        for (int i = 0; i < k; i++) {
            slots[i + 1] = others.get(i);
            rects[i + 1] = new float[] {colX / a, colY + i * (th + gap), tw / a, th};
        }
        return new Object[] {rects, slots};
    }

    /** The name of what the TV shows, for a moment (a switch of focus or content). */
    private void showBanner() {
        bannerUntil = android.os.SystemClock.uptimeMillis() + BANNER_MS;
        if (labels == null) addLabels();
        else labels.invalidate();
        handler.postDelayed(() -> { if (labels != null) labels.invalidate(); }, BANNER_MS + 50);
    }

    /** A window above the cast picture on the TV: never touched or focused, see-through. */
    private void addLabels() {
        if (labels != null || display == null || !bound) return;
        try {
            Context context = activity.createDisplayContext(display)
                .createWindowContext(WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY, null);
            windowManager = context.getSystemService(WindowManager.class);
            labels = new Labels(context);
            WindowManager.LayoutParams lp = new WindowManager.LayoutParams(-1, -1,
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                    | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT);
            lp.setFitInsetsTypes(0);
            lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
            lp.setTitle("PlasmaCastLabels");
            windowManager.addView(labels, lp);
        } catch (Exception e) {
            android.util.Log.w("RungicCast", "TV labels: " + e.getMessage());
            labels = null;
        }
    }

    private void removeLabels() {
        if (labels == null) return;
        try { windowManager.removeView(labels); } catch (Exception ignored) {}
        labels = null;
    }

    /** Each tile's name (the focus outlined), or a passing banner with the screen shown alone. */
    private final class Labels extends View {
        private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG), text = new Paint(Paint.ANTI_ALIAS_FLAG),
            outline = new Paint(Paint.ANTI_ALIAS_FLAG);

        Labels(Context context) {
            super(context);
            fill.setColor(0xCC15181A);
            text.setColor(0xFFFCFCFC);
            outline.setStyle(Paint.Style.STROKE);
            outline.setColor(0xFF3DAEE9);
        }

        @Override protected void onDraw(Canvas canvas) {
            float w = getWidth(), h = getHeight(), unit = h / 1080f;
            outline.setStrokeWidth(4 * unit);
            boolean small = level == ENLARGED;
            for (int i = 0; tiles.length > 1 && i < tiles.length; i++) {
                float[] t = tiles[i];
                RectF r = new RectF(t[0] * w, t[1] * h, (t[0] + t[2]) * w, (t[1] + t[3]) * h);
                if (i == 0) {
                    float dim = settle();
                    if (dim > 0) { fill.setAlpha(Math.round(255 * dim)); canvas.drawRect(r, fill); fill.setAlpha(0xCC); }
                    canvas.drawRoundRect(r.left - 3 * unit, r.top - 3 * unit, r.right + 3 * unit, r.bottom + 3 * unit, 6 * unit, 6 * unit, outline);
                }
                if (i == 0 || !small) chip(canvas, label(tileSlots[i]), r.left + 12 * unit, r.bottom - 12 * unit, unit, i == 0 ? 26 : 22);
            }
            if (android.os.SystemClock.uptimeMillis() < bannerUntil && tiles.length <= 1) {
                chip(canvas, onTv() ? label(focus) : activity.getString(R.string.cast_tv_desktop), 32 * unit, h - 32 * unit, unit, 30);
            }
        }

        /** A rounded chip with `value`, its bottom-left corner at (x, y). */
        private void chip(Canvas canvas, String value, float x, float y, float unit, float size) {
            text.setTextSize(size * unit);
            float pad = 12 * unit, tw = text.measureText(value);
            Paint.FontMetrics m = text.getFontMetrics();
            float th = m.descent - m.ascent;
            RectF box = new RectF(x, y - th - 2 * pad * 0.6f, x + tw + 2 * pad, y);
            canvas.drawRoundRect(box, 10 * unit, 10 * unit, fill);
            canvas.drawText(value, x + pad, box.bottom - pad * 0.6f - m.descent, text);
        }
    }
}
