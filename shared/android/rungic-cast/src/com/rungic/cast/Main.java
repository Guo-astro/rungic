// SPDX-License-Identifier: MIT
package com.rungic.cast;

import android.hardware.display.DisplayManager;
import android.os.Handler;
import android.os.Looper;
import java.io.File;
import java.lang.reflect.Array;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Locale;
import java.util.concurrent.Executor;

/**
 * Root-side Wi-Fi Display (Miracast) control through Android's own WFD stack.
 *
 * Runs as root through app_process: DisplayManagerService lets root through the
 * CONFIGURE_WIFI_DISPLAY check, and DisplayManagerGlobal registers the display
 * callback that a WFD scan requires. Every command prints one JSON object.
 *
 *   rungic-cast status
 *   rungic-cast scan [seconds]
 *   rungic-cast connect [address|name|last] [seconds]   default: the TV used last
 *   rungic-cast disconnect [seconds]
 *   rungic-cast decor <display-id> [on|off]   system decorations (vendor taskbar,
 *                                            secondary launcher) on a display
 */
public final class Main {
    private static final int CONNECTED = 2; // WifiDisplayStatus.DISPLAY_STATE_CONNECTED
    private static Object dmg;
    private static final File DIR = new File("/data/adb/rungic-wfd");
    /** Address and name of the sink connected last, for "connect" without a target. */
    private static final File LAST_SINK = new File(DIR, "last-sink");
    /** PID of rungic-cast-watch while it reconnects after the TV dropped the session. */
    private static final File RECONNECTING = new File(DIR, "run/reconnecting");
    private static final boolean DEBUG = System.getenv("RUNGIC_CAST_DEBUG") != null;

    private static void debug(String message) {
        if (DEBUG) System.err.println(SystemClockNow() + " " + message);
    }

    private static String SystemClockNow() {
        return String.format(Locale.ROOT, "%.3f", android.os.SystemClock.uptimeMillis() / 1000.0);
    }

    public static void main(String[] args) throws Exception {
        Looper.prepareMainLooper();
        dmg = Class.forName("android.hardware.display.DisplayManagerGlobal").getMethod("getInstance").invoke(null);
        String cmd = args.length > 0 ? args[0] : "status";
        try {
            run(cmd, args);
        } catch (Throwable e) {
            Throwable cause = e instanceof java.lang.reflect.InvocationTargetException ? e.getCause() : e;
            fail(cause.getClass().getSimpleName() + ": " + cause.getMessage());
        }
        System.exit(0);
    }

    private static void run(String cmd, String[] args) throws Exception {
        switch (cmd) {
            case "status":
                System.out.println(status());
                break;
            case "scan":
                System.out.println(scan(seconds(args, 1, 8)));
                break;
            case "connect": {
                // "connect 40" (seconds only) and "connect last" use the TV connected last.
                boolean named = args.length > 1 && !args[1].equals("last") && !args[1].matches("\\d+");
                int secondsAt = named || (args.length > 1 && args[1].equals("last")) ? 2 : 1;
                System.out.println(connect(named ? args[1] : lastSink(), seconds(args, secondsAt, 30)));
                break;
            }
            case "disconnect":
                System.out.println(disconnect(seconds(args, 1, 10)));
                break;
            case "decor":
                if (args.length < 2) fail("decor needs a display id");
                System.out.println(decor(Integer.parseInt(args[1]), args.length > 2 ? args[2] : null));
                break;
            default:
                fail("unknown command " + cmd);
        }
    }

    /**
     * startWifiDisplayScan requires a display callback registered by this process
     * (Android 16 DisplayManagerGlobal no longer registers one implicitly). The
     * registerDisplayListener overloads differ between releases, so fill the
     * parameters by type.
     */
    private static void registerListener() throws Exception {
        DisplayManager.DisplayListener listener = new DisplayManager.DisplayListener() {
            @Override public void onDisplayAdded(int id) {}
            @Override public void onDisplayRemoved(int id) {}
            @Override public void onDisplayChanged(int id) {}
        };
        Handler handler = new Handler(Looper.getMainLooper());
        for (Method m : dmg.getClass().getMethods()) {
            Class<?>[] types = m.getParameterTypes();
            if (!m.getName().equals("registerDisplayListener") || types.length == 0
                    || types[0] != DisplayManager.DisplayListener.class) continue;
            Object[] values = new Object[types.length];
            for (int i = 0; i < types.length; i++) {
                Class<?> t = types[i];
                if (t == DisplayManager.DisplayListener.class) values[i] = listener;
                else if (t == Handler.class) values[i] = handler;
                else if (t == Executor.class) values[i] = (Executor) Runnable::run;
                else if (t == long.class) values[i] = 7L; // added | removed | changed
                else if (t == int.class) values[i] = 7;
                else if (t == boolean.class) values[i] = false;
                else if (t == String.class) values[i] = "com.android.shell";
                else values[i] = null;
            }
            m.invoke(dmg, values);
            return;
        }
        throw new NoSuchMethodException("registerDisplayListener");
    }

    private static int seconds(String[] args, int index, int fallback) {
        return args.length > index ? Integer.parseInt(args[index]) : fallback;
    }

    private static void fail(String message) {
        System.out.println("{\"error\":" + quote(message) + "}");
        System.exit(2);
    }

    private static Object call(Object target, String name, Object... args) throws Exception {
        for (Method m : target.getClass().getMethods()) {
            if (m.getName().equals(name) && m.getParameterCount() == args.length) {
                return m.invoke(target, args);
            }
        }
        throw new NoSuchMethodException(name);
    }

    private static Object wfdStatus() throws Exception {
        return call(dmg, "getWifiDisplayStatus");
    }

    private static String scan(int secs) throws Exception {
        registerListener();
        call(dmg, "startWifiDisplayScan");
        try {
            Thread.sleep(secs * 1000L);
            return status();
        } finally {
            call(dmg, "stopWifiDisplayScan");
        }
    }

    /**
     * WifiDisplayController connects only to a peer in its current discovery list.
     * That list is cleared when a scan starts or stops, while the reported status can
     * still show the sink as available from the previous scan; so the request is made
     * during the scan and repeated until the controller starts connecting.
     */
    private static String connect(String target, int secs) throws Exception {
        String address = target.contains(":") && target.length() == 17 ? target : null;
        long deadline = System.currentTimeMillis() + secs * 1000L;
        registerListener();
        call(dmg, "startWifiDisplayScan");
        try {
            long lastRequest = 0;
            while (System.currentTimeMillis() < deadline) {
                Object s = wfdStatus();
                Object active = call(s, "getActiveDisplay");
                if ((int) call(s, "getActiveDisplayState") == CONNECTED && active != null
                        && (target.equalsIgnoreCase((String) call(active, "getDeviceAddress"))
                            || target.equals(call(active, "getDeviceName"))
                            || (address != null && address.equalsIgnoreCase((String) call(active, "getDeviceAddress"))))) {
                    Files.write(LAST_SINK.toPath(), (call(active, "getDeviceAddress") + "\n"
                            + call(active, "getDeviceName") + "\n").getBytes(StandardCharsets.UTF_8));
                    return status();
                }
                String found = findAvailable(address != null ? address : target);
                debug("state=" + call(s, "getActiveDisplayState") + " scan=" + call(s, "getScanState") + " found=" + found);
                long now = System.currentTimeMillis();
                if ((int) call(s, "getActiveDisplayState") == 0 && found != null && now - lastRequest > 3000) {
                    address = found;
                    debug("connectWifiDisplay " + address);
                    call(dmg, "connectWifiDisplay", address);
                    lastRequest = now;
                }
                Thread.sleep(250);
            }
        } finally {
            call(dmg, "stopWifiDisplayScan");
        }
        fail("timed out connecting to " + (address != null ? address : target));
        return null;
    }

    /**
     * Target of a plain "connect": the sink connected last, else the only sink
     * Android remembers from its own cast settings.
     */
    private static String lastSink() throws Exception {
        if (LAST_SINK.exists()) {
            String address = new String(Files.readAllBytes(LAST_SINK.toPath()), StandardCharsets.UTF_8).split("\n")[0].trim();
            if (!address.isEmpty()) return address;
        }
        String found = null;
        Object displays = call(wfdStatus(), "getDisplays");
        for (int i = 0; i < Array.getLength(displays); i++) {
            Object d = Array.get(displays, i);
            if (!(boolean) call(d, "isRemembered")) continue;
            if (found != null) fail("several TVs are known; name one (rungic-cast scan lists them)");
            found = (String) call(d, "getDeviceAddress");
        }
        if (found == null) fail("no TV used before; name one (rungic-cast scan lists them)");
        return found;
    }

    private static boolean reconnecting() {
        try {
            String pid = new String(Files.readAllBytes(RECONNECTING.toPath()), StandardCharsets.UTF_8).trim();
            return !pid.isEmpty() && new File("/proc/" + pid).exists();
        } catch (Exception e) {
            return false;
        }
    }

    private static String disconnect(int secs) throws Exception {
        call(dmg, "disconnectWifiDisplay");
        long deadline = System.currentTimeMillis() + secs * 1000L;
        while (System.currentTimeMillis() < deadline && (int) call(wfdStatus(), "getActiveDisplayState") != 0) {
            Thread.sleep(250);
        }
        return status();
    }

    /** IWindowManager.setShouldShowSystemDecors: root passes its INTERNAL_SYSTEM_WINDOW check. */
    private static String decor(int displayId, String value) throws Exception {
        Object wm = Class.forName("android.view.WindowManagerGlobal").getMethod("getWindowManagerService").invoke(null);
        if (value != null) call(wm, "setShouldShowSystemDecors", displayId, !value.equals("off"));
        return "{\"display\":" + displayId + ",\"system_decors\":" + call(wm, "shouldShowSystemDecors", displayId) + "}";
    }

    /** Address of an available sink matching an address or a (prefix of a) name. */
    private static String findAvailable(String key) throws Exception {
        Object displays = call(wfdStatus(), "getDisplays");
        for (int i = 0; i < Array.getLength(displays); i++) {
            Object d = Array.get(displays, i);
            if (!(boolean) call(d, "isAvailable")) continue;
            String address = (String) call(d, "getDeviceAddress");
            String device = (String) call(d, "getDeviceName");
            String alias = (String) call(d, "getDeviceAlias");
            if (key.equalsIgnoreCase(address) || key.equals(device) || key.equals(alias)
                    || (device != null && device.startsWith(key))) {
                return address;
            }
        }
        return null;
    }

    private static String status() throws Exception {
        Object s = wfdStatus();
        StringBuilder out = new StringBuilder("{");
        out.append("\"feature_state\":").append(call(s, "getFeatureState"));
        out.append(",\"scan_state\":").append(call(s, "getScanState"));
        out.append(",\"active_state\":").append(call(s, "getActiveDisplayState"));
        Object active = call(s, "getActiveDisplay");
        out.append(",\"active\":").append(active == null ? "null" : display(active));
        out.append(",\"android_display_id\":").append(activeDisplayId(active));
        out.append(",\"reconnecting\":").append(reconnecting());
        out.append(",\"displays\":[");
        Object displays = call(s, "getDisplays");
        for (int i = 0; i < Array.getLength(displays); i++) {
            if (i > 0) out.append(',');
            out.append(display(Array.get(displays, i)));
        }
        return out.append("]}").toString();
    }

    /** The logical display Android created for the connected sink, or -1. */
    private static int activeDisplayId(Object active) throws Exception {
        if (active == null) return -1;
        String unique = "wifi:" + ((String) call(active, "getDeviceAddress")).toLowerCase(Locale.ROOT);
        for (int id : (int[]) call(dmg, "getDisplayIds")) {
            Object info = call(dmg, "getDisplayInfo", id);
            if (info != null && unique.equals(info.getClass().getField("uniqueId").get(info))) return id;
        }
        return -1;
    }

    private static String display(Object d) throws Exception {
        return "{\"name\":" + quote((String) call(d, "getDeviceName"))
                + ",\"address\":" + quote((String) call(d, "getDeviceAddress"))
                + ",\"available\":" + call(d, "isAvailable")
                + ",\"remembered\":" + call(d, "isRemembered") + "}";
    }

    private static String quote(String s) {
        if (s == null) return "null";
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') b.append('\\').append(c);
            else if (c < 0x20) b.append(String.format(Locale.ROOT, "\\u%04x", (int) c));
            else b.append(c);
        }
        return b.append('"').toString();
    }
}
