// SPDX-License-Identifier: MIT
package com.rungic.cast;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Read-only WindowManager observations. Unknown/incomplete dump formats never match. */
final class CastWindows {
    static final class Window {
        String title, owner, type;
        int display = -1, uid = -1, layer = -1;
        boolean visible, surface;

        boolean shownOn(int id) {
            return id > 0 && display == id && uid >= 0 && layer >= 0 && visible && surface;
        }

        boolean covers(Window desktop) {
            return shownOn(desktop.display) && desktop.shownOn(display) && layer > desktop.layer;
        }
    }

    private static final Pattern HEADER = Pattern.compile("^\\s*Window #\\d+ Window\\{\\S+ u\\d+ (.+)\\}:\\s*$");
    private static final Pattern DISPLAY = Pattern.compile("^\\s*mDisplayId=(\\d+)\\b");
    private static final Pattern OWNER = Pattern.compile("^\\s*mOwnerUid=(\\d+)\\b.*?\\bpackage=(\\S+)");
    private static final Pattern TYPE = Pattern.compile("\\bty=([^\\s}]+)");
    private static final Pattern LAYER = Pattern.compile("^\\s*mBaseLayer=(\\d+)\\b");

    static List<Window> parse(String dump) {
        List<Window> windows = new ArrayList<>();
        Window window = null;
        for (String line : dump.split("\\n")) {
            Matcher match = HEADER.matcher(line);
            if (match.matches()) {
                window = new Window();
                window.title = match.group(1);
                windows.add(window);
                continue;
            }
            if (window == null) continue;
            if ((match = DISPLAY.matcher(line)).find()) window.display = Integer.parseInt(match.group(1));
            else if ((match = OWNER.matcher(line)).find()) {
                window.uid = Integer.parseInt(match.group(1));
                window.owner = match.group(2);
            } else if (line.trim().startsWith("mAttrs=")) {
                match = TYPE.matcher(line);
                if (match.find()) window.type = match.group(1);
            } else if ((match = LAYER.matcher(line)).find()) window.layer = Integer.parseInt(match.group(1));
            else if (line.trim().startsWith("mHasSurface=")) window.surface = line.trim().startsWith("mHasSurface=true ");
            else if (line.trim().equals("isVisible=true")) window.visible = true;
        }
        return windows;
    }

    static Window desktop(List<Window> windows, int display, int uid) {
        for (Window window : windows) {
            if (window.shownOn(display) && window.uid == uid && "com.rungic.plasma".equals(window.owner)
                    && "PlasmaCastDesktop".equals(window.title) && "APPLICATION_OVERLAY".equals(window.type)) return window;
        }
        return null;
    }

    static boolean matches(Window window, Window desktop, String owner, int uid, String prefix, String type) {
        return desktop != null && window.covers(desktop) && owner.equals(window.owner) && uid == window.uid
                && window.title.startsWith(prefix) && type.equals(window.type);
    }
}
