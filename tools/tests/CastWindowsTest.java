// SPDX-License-Identifier: MIT
package com.rungic.cast;

import java.util.List;

/** Run with CastWindows.java on a host JVM; no Android runtime or installed device needed. */
public final class CastWindowsTest {
    private static String window(String title, String owner, int uid, int display, String type, int layer) {
        return "  Window #0 Window{abcdef u0 " + title + "}:\n"
            + "    mDisplayId=" + display + " mSession=Session{test}\n"
            + "    mOwnerUid=" + uid + " showForAllUsers=false package=" + owner + " appop=NONE\n"
            + "    mAttrs={(0,0)(fillxfill) ty=" + type + " fmt=TRANSLUCENT\n"
            + "    mBaseLayer=" + layer + " mSubLayer=0\n"
            + "    mHasSurface=true isReadyForDisplay()=true\n"
            + "    isVisible=true\n";
    }

    private static boolean conflict(String dump, int display) {
        List<CastWindows.Window> windows = CastWindows.parse(dump);
        CastWindows.Window desktop = CastWindows.desktop(windows, display, 10220);
        for (CastWindows.Window w : windows) {
            if (CastWindows.matches(w, desktop, "com.motorola.mobiledesktop", 10352, "MotoDesktopSplash: ", "2938")) return true;
        }
        return false;
    }

    private static void check(boolean expected, String dump, int display) {
        if (conflict(dump, display) != expected) throw new AssertionError(dump);
    }

    public static void main(String[] args) {
        String desktop = window("PlasmaCastDesktop", "com.rungic.plasma", 10220, 7, "APPLICATION_OVERLAY", 111000);
        String splash = window("MotoDesktopSplash: 7", "com.motorola.mobiledesktop", 10352, 7, "2938", 161000);
        check(true, splash + desktop, 7);
        check(false, splash, 7); // Android-only casting must remain Android-only.
        check(false, splash + desktop, 0);
        check(false, splash + desktop, 8);
        check(false, splash.replace("mDisplayId=7", "mDisplayId=0") + desktop, 7);
        check(false, splash.replace("mOwnerUid=10352", "mOwnerUid=12000") + desktop, 7);
        check(false, splash.replace("package=com.motorola.mobiledesktop", "package=com.example.app") + desktop, 7);
        check(false, splash.replace("isVisible=true", "isVisible=false") + desktop, 7);
        check(false, splash.replace("mHasSurface=true", "mHasSurface=false") + desktop, 7);
        check(false, splash.replace("mBaseLayer=161000", "mBaseLayer=110000") + desktop, 7);
        check(false, splash.replace("ty=2938", "ty=APPLICATION") + desktop, 7);
        check(false, splash.replace("MotoDesktopSplash: 7", "Other dialog") + desktop, 7);
        check(false, splash.replace("mOwnerUid=10352", "unrecognizedUid=10352") + desktop, 7);
        check(false, splash + desktop.replace("mOwnerUid=10220", "mOwnerUid=12000"), 7);
        check(false, splash + desktop.replace("isVisible=true", "isVisible=false"), 7);
        check(true, (splash + desktop).replace("mDisplayId=7", "mDisplayId=42"), 42);
        System.out.println("16 window conflict checks passed");
    }
}
