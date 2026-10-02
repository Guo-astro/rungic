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
 * place at once; the new focus then breathes in, from a little smaller to its size, eased out
 * (a spring's overshoot drew the eye away, the user found). Only its layer moves (NativeBridge.placeTile, no new frame): moving
 * every tile through a new layout each frame made the host present every screen anew, and
 * stuttered.
 */
final class Director {
    static final int STANDARD = 0, ENLARGED = 1, SOLO = 2;
    /** The team's board (rungic_cua.team): a tile of the director's own, drawn here, no workspace's. */
    static final int BOARD = 100;
    /** A finished team's board stays this long after its last post. */
    private static final long BOARD_KEPT_MS = 10 * 60_000;
    private static final long POLL_MS = 1000, BANNER_MS = 2500;

    private final Activity activity;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private List<Integer> members = new ArrayList<>();
    /** The workspaces running now (the host's liveSources); members also has team members not open yet. */
    private List<Integer> live = new ArrayList<>();
    private final DirectorArt art = new DirectorArt();
    /** The last few lines each workspace's agent said or did (the tiles' murmur), oldest first. */
    private final java.util.Map<Integer, java.util.ArrayDeque<String>> murmurs = new java.util.HashMap<>();
    private static final int MURMUR_KEPT = 3;
    private static final long MILESTONE_MS = 8000;
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
    /** What each workspace's agent is doing (rungic_cua.activity): state, caption, when. */
    private final java.util.Map<Integer, String[]> captions = new java.util.HashMap<>();
    private final java.util.Map<Integer, Long> captionTimes = new java.util.HashMap<>();
    private static final long CAPTION_STALE_MS = 120_000, ENDING_MS = 4000;
    /** Fullscreen on the phone shows the director (it then owns the presenter, not a TV). */
    private boolean fullscreen;
    private final List<Runnable> listeners = new ArrayList<>();
    private android.animation.ValueAnimator animation;
    private static final long BREATHE_MS = 260;
    private static final float BREATHE_FROM = 0.95f;
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

    private String backgroundKey = "";
    private int[] presenterShape = {0, 0, 0};

    /** The Linux side sent the background (a JPEG): kept in the app's files, shown at once if bound. */
    void setBackground(byte[] jpeg) {
        java.io.File file = new java.io.File(activity.getFilesDir(), "director-background.jpg");
        try (java.io.FileOutputStream out = new java.io.FileOutputStream(file)) { out.write(jpeg); }
        catch (java.io.IOException e) { android.util.Log.w("RungicCast", "director background: " + e.getMessage()); return; }
        backgroundKey = "";
        if (presenterShape[0] > 0) prepareBackground(presenterShape[0], presenterShape[1], presenterShape[2]);
    }

    /**
     * The picture under the tiles of a presenter window `width` x `height` turned `rotation` (90:
     * fullscreen on the portrait phone): the user's wallpaper, blurred and dimmed by the Linux side
     * (rungic-agent-screen background, kept as files/director-background.jpg), cropped to the
     * window's shape and handed to the host; black without it.
     */
    void prepareBackground(int width, int height, int rotation) {
        presenterShape = new int[] {width, height, rotation};
        java.io.File file = new java.io.File(activity.getFilesDir(), "director-background.jpg");
        String key = file.lastModified() + ":" + width + "x" + height + "@" + rotation;
        if (key.equals(backgroundKey)) return;
        backgroundKey = key;
        int[] pixels = new int[0];
        int w = 0, h = 0;
        android.graphics.Bitmap source = file.isFile() ? android.graphics.BitmapFactory.decodeFile(file.getPath()) : null;
        if (source != null && width > 0 && height > 0) {
            // The picture's shape upright: the window turned back for fullscreen.
            int uw = rotation == 90 ? height : width, uh = rotation == 90 ? width : height;
            float scale = Math.max(uw / (float) source.getWidth(), uh / (float) source.getHeight());
            int sw = Math.round(source.getWidth() * scale), sh = Math.round(source.getHeight() * scale);
            android.graphics.Bitmap scaled = android.graphics.Bitmap.createScaledBitmap(source, sw, sh, true);
            android.graphics.Bitmap upright = android.graphics.Bitmap.createBitmap(scaled, (sw - uw) / 2, (sh - uh) / 2, uw, uh);
            android.graphics.Bitmap shown = upright;
            if (rotation == 90) {
                android.graphics.Matrix turn = new android.graphics.Matrix();
                turn.postRotate(90);
                shown = android.graphics.Bitmap.createBitmap(upright, 0, 0, uw, uh, turn, true);
            }
            w = shown.getWidth(); h = shown.getHeight();
            pixels = new int[w * h];
            shown.getPixels(pixels, 0, w, 0, 0, w, h);
            // ARGB ints to RGBA_8888 memory order (little-endian 0xAABBGGRR).
            for (int i = 0; i < pixels.length; i++) {
                int c = pixels[i];
                pixels[i] = (c & 0xFF00FF00) | ((c >> 16) & 0xFF) | ((c & 0xFF) << 16);
            }
        }
        try { NativeBridge.setCastBackground(pixels, w, h); } catch (UnsatisfiedLinkError e) { /* an older host */ }
    }

    /** Fullscreen on the phone shows the director, or no longer. */
    void setFullscreen(boolean value, float windowAspect) {
        // Bound again (a new window): laid out anew all the same.
        if (fullscreen == value && !value) return;
        fullscreen = value;
        if (value && windowAspect > 0) aspect = windowAspect;
        changedVersion();
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
    int tvSource() { return onTv() ? picture(focus) : 0; }

    /** The focus's picture: the focus, or for the board the first screen beside it. */
    int focusPicture() { return picture(focus); }

    /**
     * `slot` if the host has its picture, else the first screen beside it that it has (the board,
     * a headless workspace and a member not open yet have none here).
     */
    private int picture(int slot) {
        if (live.contains(slot)) return slot;
        for (int m : members) if (live.contains(m)) return m;
        return slot == BOARD ? 0 : slot;
    }

    // ---- headless workspaces (KWin's virtual backend, docs/research/97) -----------------------------
    /** When each headless workspace last said it runs (its keeper, op "director" {"alive": n}). */
    private final java.util.Map<Integer, Long> headless = new java.util.HashMap<>();
    private static final long HEADLESS_FRESH_MS = 10_000;

    /** Workspace `slot` runs with no surface on the host: a member all the same. */
    void alive(int slot) {
        if (slot <= 0 || slot >= 31) return;
        boolean known = headless.containsKey(slot);
        headless.put(slot, android.os.SystemClock.uptimeMillis());
        if (!known) {
            List<Integer> before = members;
            refreshMembers();
            if (!before.equals(members)) {
                changedVersion();
                if (bound || fullscreen) apply(true);
                redraw();
            }
        }
    }

    /** A member running headless: its picture is not here (the Linux side records it). */
    boolean headless(int slot) {
        Long at = headless.get(slot);
        return at != null && !live.contains(slot) && android.os.SystemClock.uptimeMillis() - at < HEADLESS_FRESH_MS;
    }

    /** Workspaces on the TV now (the focus first). */
    List<Integer> shown() {
        List<Integer> out = new ArrayList<>();
        if (!onTv()) return out;
        out.add(focus);
        if (level != SOLO) for (int slot : members) if (slot != focus) out.add(slot);
        return out;
    }

    /**
     * A TV's window is bound (on `display`) or gone. A new TV shows the director while there is one,
     * unless it was asked for something else before it came (desktop mode's cast button: computer
     * mode, 2026-10-02; forcing the director here sent the assistant's screens instead): the choice
     * goes back to the director when a TV goes.
     */
    void bound(boolean value, Display on) {
        bound = value;
        display = on;
        if (value) {
            if (on != null) {
                Display.Mode mode = on.getMode();
                aspect = mode.getPhysicalWidth() / (float) Math.max(1, mode.getPhysicalHeight());
            }
            refreshMembers();
            tiles = new float[0][]; tileSlots = new int[0];
            apply(false);
            showBanner();
        } else {
            tvDirector = true;
            tiles = new float[0][]; tileSlots = new int[0];
            try { NativeBridge.setDirector(tileSlots, new float[0], 0); } catch (UnsatisfiedLinkError e) { /* an older host */ }
            removeLabels();
        }
        changedVersion();
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
                .put("shown", on).put("heard", onTv() && focus != BOARD ? focus : -1))
            .put("board", board());
    }

    // ---- the team's board ---------------------------------------------------------------------
    private JSONObject board;

    /** The team's board (op "director" {"board": …}): brief, phase, members, decision, result. */
    void setBoard(JSONObject value) {
        board = value;
        List<Integer> before = members;
        refreshMembers();
        // A new version either way: the phone's director window draws the board too.
        changedVersion();
        if (!before.equals(members) && (bound || fullscreen)) apply(true);
        redraw();
        // A finished board leaves once it is old.
        handler.postDelayed(this::refreshBoard, BOARD_KEPT_MS + 1000);
    }

    private void refreshBoard() {
        List<Integer> before = members;
        refreshMembers();
        if (!before.equals(members)) { changedVersion(); if (bound || fullscreen) apply(true); redraw(); }
    }

    /** The board while its team works, and for a while after it finished. */
    JSONObject board() {
        if (board == null) return null;
        String phase = board.optString("phase");
        boolean over = "done".equals(phase) || "failed".equals(phase);
        long updated = (long) (board.optDouble("updated", 0) * 1000);
        if (over && System.currentTimeMillis() - updated > BOARD_KEPT_MS) return null;
        return board;
    }

    String phaseName(String phase) {
        int id = PHASE_NAMES.getOrDefault(phase, 0);
        return id == 0 ? "" : activity.getString(id);
    }

    private static final java.util.Map<String, Integer> PHASE_NAMES = java.util.Map.of(
        "brief", R.string.phase_brief, "review", R.string.phase_review, "working", R.string.phase_working,
        "done", R.string.phase_done, "failed", R.string.phase_failed);

    /** A member's kind on the board, as a state's name (as the tiles name it). */
    String kindName(String kind) {
        int id = STATE_NAMES.getOrDefault("progress".equals(kind) ? "working" : kind, 0);
        return id == 0 ? "" : activity.getString(id);
    }

    String boardText(int id) { return activity.getString(id); }

    /** A new version of the state; the Linux side waiting for it hears at once (HostEvents). */
    private void changedVersion() {
        version++;
        HostEvents.bump(HostEvents.SCREENS);
    }

    /** A team member's latest post (rungic_cua.team): role, kind, text, when; by its workspace. */
    private final java.util.Map<Integer, String[]> membersSaid = new java.util.HashMap<>();
    private final java.util.Map<Integer, Long> memberTimes = new java.util.HashMap<>();

    /** A member posted (op "director" {"member": {slot, role, kind, text}}); an empty role: gone. */
    void setMember(int slot, String role, String kind, String text) {
        if (role.isEmpty()) { membersSaid.remove(slot); memberTimes.remove(slot); murmurs.remove(slot); }
        else {
            // A silent state change (the tools inferred it) keeps the last words.
            String[] before = membersSaid.get(slot);
            boolean said = !text.isEmpty();
            membersSaid.put(slot, new String[] {role, kind, said ? text : before != null ? before[2] : ""});
            if (said) {
                memberTimes.put(slot, android.os.SystemClock.uptimeMillis());
                remember(slot, text);
                // The milestone's tag goes after a few seconds: redraw then.
                handler.postDelayed(this::redraw, MILESTONE_MS + 50);
            } else if (!memberTimes.containsKey(slot)) {
                memberTimes.put(slot, 0L);
            }
        }
        // A member that just spoke joins the layout at once (the poll compares with what this saw).
        List<Integer> before = members;
        refreshMembers();
        if (!before.equals(members)) {
            changedVersion();
            if (bound || fullscreen) apply(true);
        }
        redraw();
    }

    private void redraw() {
        if (labels != null) labels.invalidate();
        for (Runnable listener : new ArrayList<>(listeners)) listener.run();
    }

    private void remember(int slot, String line) {
        java.util.ArrayDeque<String> lines = murmurs.computeIfAbsent(slot, k -> new java.util.ArrayDeque<>());
        if (line.equals(lines.peekLast())) return;
        lines.addLast(line);
        while (lines.size() > MURMUR_KEPT) lines.removeFirst();
    }

    /** Whether `slot`'s workspace is open (its picture is there). */
    boolean live(int slot) { return live.contains(slot); }

    /** The last lines of `slot`'s murmur, oldest first. */
    List<String> murmur(int slot) {
        java.util.ArrayDeque<String> lines = murmurs.get(slot);
        if (lines == null) return new ArrayList<>();
        String[] c = captions.get(slot);
        Long at = captionTimes.get(slot);
        // A long silence: the murmur is old news.
        long newest = Math.max(at == null ? 0 : at, memberTimes.getOrDefault(slot, 0L));
        if (android.os.SystemClock.uptimeMillis() - newest > CAPTION_STALE_MS && !(c != null && !"working".equals(c[0]))) return new ArrayList<>();
        return new ArrayList<>(lines);
    }

    /** {kind, text} of `slot`'s member's post while it is fresh (its tag shows), or null. */
    String[] milestone(int slot) {
        String[] m = membersSaid.get(slot);
        Long at = memberTimes.get(slot);
        if (m == null || at == null || m[2].isEmpty() || android.os.SystemClock.uptimeMillis() - at > MILESTONE_MS) return null;
        return new String[] {m[1], m[2]};
    }

    /**
     * What `slot` is at: a member's latest kind, "working" once its tools act after a review, else
     * "working" while its agent is at work, "waiting" otherwise.
     */
    String stateKind(int slot) {
        String[] m = membersSaid.get(slot);
        String[] c = captions.get(slot);
        Long at = captionTimes.get(slot);
        boolean acting = c != null && at != null && "working".equals(c[0])
            && android.os.SystemClock.uptimeMillis() - at < CAPTION_STALE_MS;
        if (m != null) {
            boolean early = "review".equals(m[1]) || "brief".equals(m[1]) || "decision".equals(m[1]);
            if (early && acting && at > memberTimes.getOrDefault(slot, 0L)) return "working";
            return "progress".equals(m[1]) ? "working" : m[1];
        }
        return acting ? "working" : "waiting";
    }

    String stateName(int slot) {
        int id = STATE_NAMES.getOrDefault(stateKind(slot), 0);
        return id == 0 ? "" : activity.getString(id);
    }

    /** A tile's name: a member's role, else the screen's. */
    String screenName(int slot) {
        if (slot == BOARD) return activity.getString(R.string.board_name);
        String[] m = membersSaid.get(slot);
        if (m != null) return m[0];
        return slot == 0 ? activity.getString(R.string.tv_desktop) : activity.getString(R.string.tv_workspace, slot);
    }

    String initial(int slot) {
        String name = screenName(slot);
        return membersSaid.containsKey(slot) && !name.isEmpty() ? name.substring(0, Math.min(1, name.length())).toUpperCase() : String.valueOf(slot);
    }

    String notOpenText(int slot) {
        return activity.getString(headless(slot) ? R.string.tile_headless : R.string.tile_not_open);
    }

    String tagName(String kind) {
        int id = TAG_NAMES.getOrDefault(kind, R.string.tag_progress);
        return activity.getString(id);
    }

    private static final java.util.Map<String, Integer> TAG_NAMES = java.util.Map.of(
        "brief", R.string.tag_brief, "review", R.string.tag_review, "decision", R.string.tag_decision,
        "progress", R.string.tag_progress, "blocked", R.string.tag_blocked, "question", R.string.tag_question,
        "done", R.string.tag_done, "failed", R.string.tag_failed);

    /** Needs the user or the lead: blocked or a question (its tile turns amber). */
    boolean needsAttention(int slot) {
        String[] m = membersSaid.get(slot);
        return m != null && ("blocked".equals(m[1]) || "question".equals(m[1]));
    }

    /** A workspace's agent says what it is doing (op "director" {"caption": {slot, state, text}}). */
    void setCaption(int slot, String state, String text) {
        captions.put(slot, new String[] {state, text});
        captionTimes.put(slot, android.os.SystemClock.uptimeMillis());
        if (!text.isEmpty()) remember(slot, text);
        if (labels != null) labels.invalidate();
        for (Runnable listener : new ArrayList<>(listeners)) listener.run();
        // An ending shows a few seconds, then goes.
        if (!"working".equals(state)) handler.postDelayed(() -> {
            if (labels != null) labels.invalidate();
            for (Runnable listener : new ArrayList<>(listeners)) listener.run();
        }, ENDING_MS + 50);
    }

    /**
     * {state, text} of what `slot`'s agent is doing now, or null (none, stale, an ending past): the
     * newer of its desktop tools' caption and, in a team, its own latest words.
     */
    String[] caption(int slot) {
        String[] c = captions.get(slot);
        Long at = captionTimes.get(slot);
        long now = android.os.SystemClock.uptimeMillis();
        if (c != null && at != null && ("working".equals(c[0]) ? now - at > CAPTION_STALE_MS : now - at > ENDING_MS)) c = null;
        String[] m = membersSaid.get(slot);
        Long said = memberTimes.get(slot);
        if (m != null && !m[2].isEmpty() && (c == null || said > at)) {
            boolean final_ = "done".equals(m[1]) || "failed".equals(m[1]) || "ended".equals(m[1]);
            return new String[] {final_ ? m[1] : "working", m[2]};
        }
        return c;
    }

    /** A tile's name: a team member's role and state ("art · 评审中"), else the screen's name. */
    String label(int slot) {
        String[] m = membersSaid.get(slot);
        if (m != null) {
            int state = STATE_NAMES.getOrDefault(m[1], 0);
            return state == 0 ? m[0] : m[0] + " · " + activity.getString(state);
        }
        return slot == 0 ? activity.getString(R.string.tv_desktop) : activity.getString(R.string.tv_workspace, slot);
    }

    private static final java.util.Map<String, Integer> STATE_NAMES = java.util.Map.of(
        "review", R.string.team_reviewing, "blocked", R.string.team_blocked,
        "question", R.string.team_question, "done", R.string.team_done, "failed", R.string.team_failed,
        "ended", R.string.team_ended, "working", R.string.team_working, "waiting", R.string.team_waiting,
        "brief", R.string.team_briefing, "decision", R.string.team_deciding);

    private void changed(boolean banner) {
        changedVersion();
        if (laidOut()) apply(true);
        else if (bound) apply(false);
        if (bound && banner) showBanner();
    }

    private final Runnable poll = new Runnable() {
        @Override public void run() {
            List<Integer> before = members, liveBefore = live;
            refreshMembers();
            // A headless member's picture arriving (its presenter, docs/research/97 §13) changes what
            // the host presents and the placeholder, with the members the same.
            if (!before.equals(members) || !liveBefore.equals(live)) {
                changedVersion();
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
        live = new ArrayList<>(found);
        // A headless workspace, heard from lately.
        long now = android.os.SystemClock.uptimeMillis();
        headless.values().removeIf(at -> now - at >= HEADLESS_FRESH_MS);
        for (int slot : headless.keySet()) if (!found.contains(slot)) found.add(slot);
        // A team member that spoke shows before its workspace opens (a placeholder tile).
        for (java.util.Map.Entry<Integer, String[]> m : membersSaid.entrySet())
            if (!found.contains(m.getKey()) && !"ended".equals(m.getValue()[1])) found.add(m.getKey());
        found.sort(Integer::compare);
        if (board() != null && !found.isEmpty()) found.add(BOARD);
        members = found;
        // A focus that closed: the first member left.
        if (!members.isEmpty() && !members.contains(focus)) focus = members.get(0);
    }

    /**
     * The host's layout and the labels for the current state, at once; `animate`: a new focus
     * breathes in (spring(), eased).
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
        send(tiles, tileSlots);
        if (animate && newFocus) spring(slots[0], to[0]);
    }

    /** The new focus `slot` breathes in: from BREATHE_FROM of its size, about its centre, eased out. */
    private void spring(int slot, float[] rect) {
        final float cx = rect[0] + rect[2] / 2, cy = rect[1] + rect[3] / 2;
        animation = android.animation.ValueAnimator.ofFloat(BREATHE_FROM, 1f).setDuration(BREATHE_MS);
        animation.setInterpolator(new android.view.animation.DecelerateInterpolator(1.5f));
        animation.addUpdateListener(a -> {
            if (tileSlots.length == 0 || tileSlots[0] != slot) { a.cancel(); return; }
            float scale = (float) a.getAnimatedValue();
            float w = rect[2] * scale, h = rect[3] * scale;
            float[] now = {cx - w / 2, cy - h / 2, w, h};
            float[][] shown = tiles.clone();
            shown[0] = now;
            tiles = shown;
            if (slot != BOARD)
                try { NativeBridge.placeTile(slot, now[0], now[1], now[2], now[3]); } catch (UnsatisfiedLinkError e) { a.cancel(); }
            if (labels != null) labels.invalidate();
            for (Runnable listener : new ArrayList<>(listeners)) listener.run();
        });
        animation.start();
    }

    /** The tiles to the host, the labels and the listeners. */
    private void send(float[][] rects, int[] slots) {
        // The board is drawn by the labels: the host lays out the workspaces only.
        int n = 0;
        for (int slot : slots) if (slot != BOARD) n++;
        int[] hostSlots = new int[n];
        float[] flat = new float[n * 4];
        for (int i = 0, j = 0; i < slots.length; i++) {
            if (slots[i] == BOARD) continue;
            hostSlots[j] = slots[i];
            System.arraycopy(rects[i], 0, flat, 4 * j++, 4);
        }
        int presented = hostSlots.length > 0 ? hostSlots[0] : tvSource();
        try { NativeBridge.setDirector(hostSlots, flat, presented); }
        catch (UnsatisfiedLinkError e) { NativeBridge.presentWorkspace(presented); }
        if (labels != null) labels.invalidate();
        else if (bound && onTv()) addLabels();
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
            if (onTv()) art.paint(canvas, w, h, Director.this, 1f);
            // Computer mode, for a moment after a switch: which screen the TV shows.
            if (android.os.SystemClock.uptimeMillis() < bannerUntil && !onTv()) {
                chip(canvas, activity.getString(R.string.cast_tv_desktop), 32 * unit, h - 32 * unit, unit, 30);
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
