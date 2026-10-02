package com.rungic.plasma;

import android.graphics.Canvas;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Shader;
import android.text.TextPaint;
import android.text.TextUtils;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * How the director's tiles are labelled (docs/58, the design "导播台设计"), on the TV (Director's
 * label window) and fullscreen on the phone (AgentFullscreen), the same there and there. Over each
 * tile: a status capsule at its top left (a dot: green at work, grey waiting, amber needs an
 * answer; the role or screen name; the state), and a dark band at its bottom with what its agent
 * is doing: one line on a small tile; on the focus, a ticker of the last three lines, older ones
 * smaller and fainter. A milestone (team_post) shows with a coloured tag for a few seconds before
 * the murmur comes back. A member whose workspace is not open yet gets a placeholder tile.
 * The team's board (Director.BOARD) is a tile drawn whole here: the phase, the brief, each
 * member's state and latest words, the lead's decision or result; small, the phase, the brief and
 * a dot for each member. Sizes are in units of the window's height over 1080.
 */
final class DirectorArt {
    static final int BLUE = 0xFF3DAEE9, GREEN = 0xFF63D471, AMBER = 0xFFF0B35E, GREY = 0xFF8B97A3, RED = 0xFFE0606D;

    private final Paint capsule = new Paint(Paint.ANTI_ALIAS_FLAG), dot = new Paint(Paint.ANTI_ALIAS_FLAG),
        outline = new Paint(Paint.ANTI_ALIAS_FLAG), band = new Paint(), tag = new Paint(Paint.ANTI_ALIAS_FLAG),
        glass = new Paint(Paint.ANTI_ALIAS_FLAG), ring = new Paint(Paint.ANTI_ALIAS_FLAG),
        sheet = new Paint(Paint.ANTI_ALIAS_FLAG), rule = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final TextPaint text = new TextPaint(Paint.ANTI_ALIAS_FLAG);

    DirectorArt() {
        capsule.setColor(0xC7101418);
        outline.setStyle(Paint.Style.STROKE);
        glass.setColor(0x0DFFFFFF);
        ring.setStyle(Paint.Style.STROKE);
        ring.setColor(0x47FFFFFF);
        sheet.setColor(0xB80E1216);
        rule.setColor(0x1FFFFFFF);
    }

    /**
     * Every tile of `d` in a `w` x `h` window; tiles are fractions of it. `zoom` scales the text:
     * 1 on a TV seen from the sofa, more on the phone held in the hand (its pixels are far denser).
     */
    void paint(Canvas canvas, float w, float h, Director d, float zoom) {
        float u = h / 1080f * zoom;
        float[][] tiles = d.tiles();
        int[] slots = d.tileSlots();
        boolean many = tiles.length > 1;
        boolean thin = d.level() == Director.ENLARGED;
        for (int i = tiles.length - 1; i >= 0; i--) {
            float[] t = tiles[i];
            RectF r = new RectF(t[0] * w, t[1] * h, (t[0] + t[2]) * w, (t[1] + t[3]) * h);
            boolean focus = i == 0;
            float scale = focus ? 1f : thin ? 0.7f : 0.75f;
            int slot = slots[i];
            canvas.save();
            canvas.clipRect(r.left - 8 * u, r.top - 8 * u, r.right + 8 * u, r.bottom + 8 * u);
            if (slot == Director.BOARD) {
                board(canvas, r, focus ? u : u * scale, focus, d);
                if (focus && many) {
                    outline.setColor(BLUE);
                    outline.setStrokeWidth(4 * u);
                    canvas.drawRoundRect(r.left - 2 * u, r.top - 2 * u, r.right + 2 * u, r.bottom + 2 * u, 14 * u, 14 * u, outline);
                }
                canvas.restore();
                continue;
            }
            if (!d.live(slot)) placeholder(canvas, r, u * scale, d.initial(slot), d.notOpenText());
            if (focus && many) {
                outline.setColor(d.needsAttention(slot) ? AMBER : BLUE);
                outline.setStrokeWidth(4 * u);
                canvas.drawRoundRect(r.left - 2 * u, r.top - 2 * u, r.right + 2 * u, r.bottom + 2 * u, 14 * u, 14 * u, outline);
            }
            if (!(thin && !focus)) {
                band(canvas, r, u, focus, d.murmur(slot), d.milestone(slot), d);
                capsule(canvas, r, u * scale, focus, d.screenName(slot), d.stateName(slot), dotColor(d.stateKind(slot)));
            } else {
                dot.setColor(dotColor(d.stateKind(slot)));
                canvas.drawCircle(r.right - 10 * u, r.top + 10 * u, 5 * u, dot);
            }
            canvas.restore();
        }
    }

    static int dotColor(String kind) {
        switch (kind) {
            case "working": case "review": case "done": return GREEN;
            case "blocked": case "question": return AMBER;
            case "failed": return RED;
            default: return GREY;
        }
    }

    private static int[] tagColors(String kind) {
        switch (kind) {
            case "blocked": case "question": return new int[] {AMBER, 0xFF3A2405};
            case "done": return new int[] {GREEN, 0xFF08260F};
            case "failed": return new int[] {RED, 0xFF2A0A0D};
            default: return new int[] {BLUE, 0xFF06263A};
        }
    }

    static int phaseColor(String phase) {
        switch (phase) {
            case "working": case "done": return GREEN;
            case "failed": return RED;
            default: return BLUE;
        }
    }

    /** The team's board in `r`; `focus`: in full, else the phase, the brief and the members' dots. */
    private void board(Canvas c, RectF r, float u, boolean focus, Director d) {
        JSONObject b = d.board();
        c.drawRoundRect(r, 12 * u, 12 * u, sheet);
        if (b == null) return;
        float pad = (focus ? 34 : 12) * u, x = r.left + pad, right = r.right - pad;
        String phase = b.optString("phase");
        // The header: the board's name, the phase as a coloured chip.
        float label = (focus ? 17 : 11) * u;
        text.setTextSize(label);
        text.setFakeBoldText(true);
        text.setColor(0x99F3F6F8);
        String name = d.screenName(Director.BOARD).toUpperCase();
        float y = r.top + pad + label;
        c.drawText(name, x, y, text);
        float after = x + text.measureText(name) + (focus ? 14 : 7) * u;
        String phaseName = d.phaseName(phase);
        if (!phaseName.isEmpty()) {
            text.setTextSize(label * 0.95f);
            float w = text.measureText(phaseName) + (focus ? 20 : 10) * u, h = label * 1.55f;
            RectF chip = new RectF(after, y - label * 1.12f, after + w, y - label * 1.12f + h);
            tag.setColor(phaseColor(phase));
            c.drawRoundRect(chip, h / 2, h / 2, tag);
            text.setColor(0xFF0A1016);
            c.drawText(phaseName, chip.left + (focus ? 10 : 5) * u, baseline(chip), text);
        }
        text.setFakeBoldText(false);
        // The brief.
        float titleSize = (focus ? 34 : 15) * u;
        y += titleSize * (focus ? 1.75f : 1.6f);
        line(c, b.optString("title"), x, y, right, titleSize, 0xFFFFFFFF, true);
        JSONArray members = b.optJSONArray("members");
        if (members == null) members = new JSONArray();
        if (!focus) {
            // Small: a dot for each member, by its state.
            float dotR = 5 * u, cx = x + dotR;
            float cy = Math.min(r.bottom - pad - dotR, y + titleSize * 1.1f);
            for (int i = 0; i < members.length(); i++) {
                JSONObject m = members.optJSONObject(i);
                if (m == null) continue;
                dot.setColor(dotColor(stateOf(m.optString("kind"))));
                c.drawCircle(cx, cy, dotR, dot);
                cx += dotR * 3.2f;
            }
            return;
        }
        // The members: a row each, the lead first.
        float rowH = 58 * u;
        y += 26 * u;
        c.drawRect(x, y, right, y + Math.max(1, u), rule);
        String footer = footer(b);
        float bottom = r.bottom - pad - (footer.isEmpty() ? 0 : 58 * u);
        int shown = 0;
        for (int i = 0; i < members.length(); i++) {
            JSONObject m = members.optJSONObject(i);
            if (m == null) continue;
            float rowTop = y + shown * rowH;
            if (rowTop + rowH > bottom) break;
            float mid = rowTop + rowH / 2;
            String kind = m.optString("kind");
            dot.setColor(dotColor(stateOf(kind)));
            c.drawCircle(x + 7 * u, mid, 7 * u, dot);
            float tx = x + 28 * u;
            text.setTextSize(25 * u);
            text.setFakeBoldText(true);
            text.setColor(0xFFFFFFFF);
            String role = m.optString("role");
            c.drawText(role, tx, mid + 9 * u, text);
            tx += text.measureText(role) + 12 * u;
            text.setFakeBoldText(false);
            String state = d.kindName(kind);
            if (!state.isEmpty()) {
                text.setTextSize(19 * u);
                text.setColor(0xFFA9B4BD);
                c.drawText(state, tx, mid + 8 * u, text);
                tx += text.measureText(state) + 22 * u;
            }
            float column = x + 300 * u;
            line(c, m.optString("text"), Math.max(tx, column), mid + 8 * u, right, 21 * u, 0xC7F3F6F8, false);
            shown++;
        }
        if (!footer.isEmpty()) {
            boolean result = !b.optString("result").isEmpty();
            String tagText = d.boardText(result ? R.string.board_result : R.string.board_decision);
            float fy = r.bottom - pad;
            c.drawRect(x, fy - 52 * u, right, fy - 52 * u + Math.max(1, u), rule);
            text.setTextSize(16 * u);
            text.setFakeBoldText(true);
            float w = text.measureText(tagText) + 18 * u, h = 28 * u;
            RectF box = new RectF(x, fy - h + 2 * u, x + w, fy + 2 * u);
            tag.setColor(result ? phaseColor(phase) : BLUE);
            c.drawRoundRect(box, 7 * u, 7 * u, tag);
            text.setColor(0xFF0A1016);
            c.drawText(tagText, box.left + 9 * u, baseline(box), text);
            text.setFakeBoldText(false);
            line(c, footer, box.right + 14 * u, fy - 3 * u, right, 23 * u, 0xFFFFFFFF, false);
        }
    }

    /** The board's last line: the lead's result, else its decision. */
    private static String footer(JSONObject b) {
        String result = b.optString("result");
        return !result.isEmpty() ? result : b.optString("decision");
    }

    private static String stateOf(String kind) {
        return "progress".equals(kind) ? "working" : kind.isEmpty() ? "waiting" : kind;
    }

    private void placeholder(Canvas c, RectF r, float u, String initial, String note) {
        c.drawRoundRect(r, 12 * u, 12 * u, glass);
        float radius = Math.min(r.width(), r.height()) * 0.11f;
        float cx = r.centerX(), cy = r.centerY() - radius * 0.35f;
        ring.setStrokeWidth(2 * u);
        c.drawCircle(cx, cy, radius, ring);
        text.setColor(0xCCFFFFFF);
        text.setFakeBoldText(true);
        text.setTextSize(radius * 0.85f);
        Paint.FontMetrics m = text.getFontMetrics();
        c.drawText(initial, cx - text.measureText(initial) / 2, cy - (m.ascent + m.descent) / 2, text);
        text.setFakeBoldText(false);
        text.setColor(0x8CF3F6F8);
        text.setTextSize(Math.max(12 * u, radius * 0.36f));
        c.drawText(note, cx - text.measureText(note) / 2, cy + radius + text.getTextSize() * 1.4f, text);
    }

    private void capsule(Canvas c, RectF r, float u, boolean focus, String name, String state, int color) {
        float big = focus ? 22 : 15, small = focus ? 18 : 13, d = focus ? 10 : 8;
        float x = r.left + (focus ? 18 : 10) * u, y = r.top + (focus ? 18 : 10) * u;
        text.setFakeBoldText(true);
        text.setTextSize(big * u);
        float nameW = text.measureText(name);
        text.setFakeBoldText(false);
        text.setTextSize(small * u);
        String rest = state.isEmpty() ? "" : " · " + state;
        float restW = rest.isEmpty() ? 0 : text.measureText(rest);
        float padL = (focus ? 12 : 9) * u, padR = (focus ? 16 : 11) * u, gap = (focus ? 10 : 7) * u;
        float height = big * u * 1.7f;
        float width = padL + d * u + gap + nameW + restW + padR;
        width = Math.min(width, r.width() - 2 * (x - r.left));
        RectF box = new RectF(x, y, x + width, y + height);
        c.drawRoundRect(box, height / 2, height / 2, capsule);
        dot.setColor(color);
        c.drawCircle(x + padL + d * u / 2, box.centerY(), d * u / 2, dot);
        float tx = x + padL + d * u + gap;
        text.setColor(0xFFFFFFFF);
        text.setFakeBoldText(true);
        text.setTextSize(big * u);
        CharSequence fit = TextUtils.ellipsize(name, text, box.right - padR - tx, TextUtils.TruncateAt.END);
        c.drawText(fit, 0, fit.length(), tx, baseline(box), text);
        float after = tx + text.measureText(fit, 0, fit.length());
        text.setFakeBoldText(false);
        if (!rest.isEmpty() && after < box.right - padR) {
            text.setTextSize(small * u);
            text.setColor(0xFFC6D0D8);
            CharSequence fitRest = TextUtils.ellipsize(rest, text, box.right - padR - after, TextUtils.TruncateAt.END);
            c.drawText(fitRest, 0, fitRest.length(), after, baseline(box), text);
        }
    }

    private float baseline(RectF box) {
        Paint.FontMetrics m = text.getFontMetrics();
        return box.centerY() - (m.ascent + m.descent) / 2;
    }

    /**
     * The bottom band: the focus's ticker (the last three lines, the newest largest at the bottom)
     * or a small tile's newest line. A line that is a fresh milestone carries its tag, where it
     * falls in time (a milestone is no newer than what was done after it).
     */
    private void band(Canvas c, RectF r, float u, boolean focus, List<String> murmur, String[] milestone, Director d) {
        if (murmur.isEmpty()) return;
        int shown = focus ? Math.min(3, murmur.size()) : 1;
        float pad = (focus ? 24 : 12) * u;
        float latestSize = (focus ? 25 : 15) * u;
        float height = latestSize * 1.5f + (shown - 1) * 24 * u + (focus ? 46 : 26) * u;
        band.setShader(new LinearGradient(0, r.bottom - height, 0, r.bottom, 0x000A0D11, 0xE60A0D11, Shader.TileMode.CLAMP));
        c.drawRect(r.left, Math.max(r.top, r.bottom - height), r.right, r.bottom, band);
        float y = r.bottom - (focus ? 20 : 10) * u;
        float x = r.left + pad, right = r.right - pad;
        for (int k = 0; k < shown; k++) {
            String value = murmur.get(murmur.size() - 1 - k);
            float size = k == 0 ? latestSize : (19 - 2 * (k - 1)) * u;
            int color = k == 0 ? 0xFFFFFFFF : ((k == 1 ? 0x9E : 0x61) << 24) | 0xF3F6F8;
            float start = x;
            if (milestone != null && value.equals(milestone[1])) {
                int[] colors = tagColors(milestone[0]);
                String name = d.tagName(milestone[0]);
                text.setFakeBoldText(true);
                text.setTextSize(size * 0.62f);
                float tagW = text.measureText(name) + 16 * u, tagH = size * 1.05f;
                RectF box = new RectF(x, y - tagH + 2 * u, x + tagW, y + 2 * u);
                tag.setColor(k == 0 ? colors[0] : (colors[0] & 0x00FFFFFF) | 0xB0000000);
                c.drawRoundRect(box, 6 * u, 6 * u, tag);
                text.setColor(colors[1]);
                c.drawText(name, box.left + 8 * u, baseline(box), text);
                text.setFakeBoldText(false);
                start = box.right + 10 * u;
            }
            line(c, value, start, y, right, size, color, k == 0 && focus);
            y -= (k == 0 ? latestSize * 1.35f : size * 1.45f);
        }
    }

    private void line(Canvas c, String value, float x, float y, float right, float size, int color, boolean medium) {
        text.setTextSize(size);
        text.setColor(color);
        text.setFakeBoldText(medium);
        CharSequence fit = TextUtils.ellipsize(value, text, Math.max(0, right - x), TextUtils.TruncateAt.END);
        c.drawText(fit, 0, fit.length(), x, y, text);
        text.setFakeBoldText(false);
    }
}
