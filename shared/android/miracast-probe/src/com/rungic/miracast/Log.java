// SPDX-License-Identifier: MIT
package com.rungic.miracast;

/** Logcat tag RungicMiracast; a command-line run also echoes to stdout. */
final class Log {
    static volatile boolean echo;

    private Log() {}

    static void i(String message) {
        android.util.Log.i("RungicMiracast", message);
        if (echo) System.out.println(stamp() + " " + message);
    }

    static void d(String message) {
        android.util.Log.d("RungicMiracast", message);
        if (echo) System.out.println(stamp() + " " + message);
    }

    static void w(String message, Throwable error) {
        android.util.Log.w("RungicMiracast", message, error);
        if (echo) System.out.println(stamp() + " WARN " + message + (error == null ? "" : ": " + error));
    }

    private static String stamp() {
        return new java.text.SimpleDateFormat("HH:mm:ss.SSS", java.util.Locale.ROOT).format(new java.util.Date());
    }
}
