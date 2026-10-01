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
 * What the TV shows (docs/58 "电视显示"): one screen, the user's desktop (0) or an agent workspace
 * (n), or the director view ("导播台"): every screen at once, the focused one large on top, the
 * others as a row of thumbnails below. The host puts each screen on a layer of its own in the
 * cast window (NativeBridge.setDirector); this class chooses the layout and draws the labels in
 * a window above it on the TV.
 *
 * The cast button (the floating windows', fullscreen's, the quick setting's) means: no TV yet,
 * pick one (CastControls.pickTv); a TV, the next screen (in the director view, the next focus).
 */
final class TvScreens {
    private static final long POLL_MS = 1500, BANNER_MS = 2500;

    private final Activity activity;
    private final Handler handler = new Handler(Looper.getMainLooper());
    /** The screen shown alone, or the focus of the director view. */
    private int source;
    private boolean director;
    private boolean bound;
    private List<Integer> sources = new ArrayList<>(List.of(0));
    private float[][] tiles = new float[0][];
    private int[] tileSlots = new int[0];
    private Labels labels;
    private WindowManager windowManager;
    private Display display;
    private long bannerUntil;

    TvScreens(Activity activity) {
        this.activity = activity;
        director = activity.getPreferences(Context.MODE_PRIVATE).getBoolean("tv_director", false);
    }

    int source() { return source; }
    boolean director() { return director; }
    List<Integer> sources() { return sources; }

    /** Screens the TV shows now (the focus first). */
    List<Integer> shown() {
        List<Integer> out = new ArrayList<>();
        if (!bound) return out;
        out.add(source);
        if (director) for (int slot : sources) if (slot != source) out.add(slot);
        return out;
    }

    /** A TV's window is bound (on `display`) or gone. */
    void bound(boolean value, Display on) {
        bound = value;
        display = on;
        handler.removeCallbacks(poll);
        if (value) {
            refreshSources();
            apply();
            handler.postDelayed(poll, POLL_MS);
            showBanner();
        } else {
            source = 0;                     // the next TV shows the desktop first
            tiles = new float[0][]; tileSlots = new int[0];
            try { NativeBridge.setDirector(tileSlots, new float[0], 0); } catch (UnsatisfiedLinkError e) { /* an older host */ }
            removeLabels();
        }
    }

    /** Show `slot` alone, or focus it in the director view. */
    void show(int slot) {
        source = Math.max(0, slot);
        if (bound) { refreshSources(); apply(); showBanner(); }
    }

    /** The cast button with a TV: the next screen (or focus), in order desktop, workspaces 1..4. */
    void next() {
        refreshSources();
        int at = sources.indexOf(source);
        show(sources.get((at + 1) % sources.size()));
    }

    void setDirector(boolean on) {
        director = on;
        activity.getPreferences(Context.MODE_PRIVATE).edit().putBoolean("tv_director", on).apply();
        if (bound) { refreshSources(); apply(); showBanner(); }
    }

    JSONObject state() throws Exception {
        JSONArray all = new JSONArray(), on = new JSONArray();
        for (int slot : sources) all.put(slot);
        for (int slot : shown()) on.put(slot);
        return new JSONObject().put("connected", bound).put("source", source).put("director", director)
            .put("sources", all).put("shown", on).put("heard", bound ? source : JSONObject.NULL);
    }

    String label(int slot) {
        return slot == 0 ? activity.getString(R.string.tv_desktop) : activity.getString(R.string.tv_workspace, slot);
    }

    private final Runnable poll = new Runnable() {
        @Override public void run() {
            if (!bound) return;
            List<Integer> before = sources;
            refreshSources();
            // A screen that closed: the desktop instead (the host shows it already).
            if (!sources.contains(source)) source = 0;
            if (!before.equals(sources)) apply();
            handler.postDelayed(this, POLL_MS);
        }
    };

    private void refreshSources() {
        int mask = 1;
        try { mask = NativeBridge.liveSources() | 1; } catch (UnsatisfiedLinkError e) { /* an older host */ }
        List<Integer> found = new ArrayList<>();
        for (int slot = 0; slot < 31; slot++) if ((mask & (1 << slot)) != 0) found.add(slot);
        // A screen asked for before its workspace connected stays in the list (the host shows it when it does).
        if (!found.contains(source)) found.add(source);
        found.sort(Integer::compare);
        sources = found;
    }

    /** The host's layout and the labels for the current choice. */
    private void apply() {
        List<Integer> others = new ArrayList<>();
        for (int slot : sources) if (slot != source) others.add(slot);
        if (director && !others.isEmpty()) layout(others);
        else { tiles = new float[0][]; tileSlots = new int[0]; }
        float[] flat = new float[tiles.length * 4];
        for (int i = 0; i < tiles.length; i++) System.arraycopy(tiles[i], 0, flat, 4 * i, 4);
        try { NativeBridge.setDirector(tileSlots, flat, source); }
        catch (UnsatisfiedLinkError e) { NativeBridge.presentWorkspace(source); }
        if (labels != null) labels.invalidate();
        else if (bound && tiles.length > 0) addLabels();
    }

    /**
     * The focus 16:9 and as large as fits above a row of thumbnails (16:9, at most a fifth of
     * the height), everything centred, as fractions of the TV (assumed 16:9 like every source).
     */
    private void layout(List<Integer> others) {
        float w = 16f, h = 9f, gap = 0.02f * h;
        int k = others.size();
        float th = Math.min(0.2f * h, ((w - (k + 1) * gap) / k) * 9f / 16f);
        float tw = th * 16f / 9f;
        float rowY = h - gap - th;
        float rowX = (w - (k * tw + (k - 1) * gap)) / 2f;
        float avail = rowY - 2 * gap;
        float fh = Math.min(avail, (w - 2 * gap) * 9f / 16f), fw = fh * 16f / 9f;
        tiles = new float[k + 1][];
        tileSlots = new int[k + 1];
        tileSlots[0] = source;
        tiles[0] = new float[] {(w - fw) / 2f / w, (gap + (avail - fh) / 2f) / h, fw / w, fh / h};
        for (int i = 0; i < k; i++) {
            tileSlots[i + 1] = others.get(i);
            tiles[i + 1] = new float[] {(rowX + i * (tw + gap)) / w, rowY / h, tw / w, th / h};
        }
    }

    private void showBanner() {
        bannerUntil = android.os.SystemClock.uptimeMillis() + BANNER_MS;
        if (labels == null) addLabels();
        else labels.invalidate();
        handler.postDelayed(() -> { if (labels != null) labels.invalidate(); if (tiles.length == 0) removeLabels(); }, BANNER_MS + 50);
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
            text.setTextSize(26 * unit);
            outline.setStrokeWidth(4 * unit);
            for (int i = 0; i < tiles.length; i++) {
                float[] t = tiles[i];
                RectF r = new RectF(t[0] * w, t[1] * h, (t[0] + t[2]) * w, (t[1] + t[3]) * h);
                if (i == 0) canvas.drawRoundRect(r.left - 3 * unit, r.top - 3 * unit, r.right + 3 * unit, r.bottom + 3 * unit, 6 * unit, 6 * unit, outline);
                chip(canvas, label(tileSlots[i]), r.left + 12 * unit, r.bottom - 12 * unit, unit, i == 0 ? 26 : 22);
            }
            if (tiles.length == 0 && android.os.SystemClock.uptimeMillis() < bannerUntil) {
                chip(canvas, label(source), 32 * unit, h - 32 * unit, unit, 30);
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
