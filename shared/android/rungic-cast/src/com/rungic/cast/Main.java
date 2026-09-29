// SPDX-License-Identifier: MIT
package com.rungic.cast;

import android.hardware.display.DisplayManager;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
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
 *   rungic-cast connect [address|name|last] [seconds]   default: the TV used last; another
 *                                            TV while casting switches to it
 *   rungic-cast disconnect [seconds]
 *
 * status (and scan) list "receivers": one entry per TV, however many Wi-Fi Display
 * entries it offers (a TCL TV advertises "NAME[R1]" and "NAME[R2]"), with the TVs a
 * scan saw in the last ten minutes, since Android cannot scan while it casts.
 *   rungic-cast decor <display-id> [on|off]   system decorations (vendor taskbar,
 *                                            secondary launcher) on a display
 *   rungic-cast wfd-config <vendor.xml> <out.xml>   the vendor WFD video offer, limited
 *                                            to this phone's hardware encoder (WfdConfig)
 */
public final class Main {
    private static final int CONNECTED = 2; // WifiDisplayStatus.DISPLAY_STATE_CONNECTED
    private static Object dmg;
    private static boolean connecting;
    private static final File DIR = new File("/data/adb/rungic-wfd");
    /** Address and name of the sink connected last, for "connect" without a target. */
    private static final File LAST_SINK = new File(DIR, "last-sink");
    /** PID of rungic-cast-watch while it reconnects after the TV dropped the session. */
    private static final File RECONNECTING = new File(DIR, "run/reconnecting");
    /** Sinks the last scans saw: address, name, epoch milliseconds per line. */
    private static final File SEEN = new File(DIR, "run/seen");
    private static final long SEEN_FOR = 10 * 60 * 1000L;
    private static final boolean DEBUG = System.getenv("RUNGIC_CAST_DEBUG") != null;

    private static void debug(String message) {
        if (DEBUG) System.err.println(SystemClockNow() + " " + message);
    }

    private static String SystemClockNow() {
        return String.format(Locale.ROOT, "%.3f", android.os.SystemClock.uptimeMillis() / 1000.0);
    }

    public static void main(String[] args) throws Exception {
        Looper.prepareMainLooper();
        String cmd = args.length > 0 ? args[0] : "status";
        try {
            dmg = Class.forName("android.hardware.display.DisplayManagerGlobal").getMethod("getInstance").invoke(null);
            run(cmd, args);
        } catch (Throwable e) {
            if (connecting) {
                try { call(dmg, "disconnectWifiDisplay"); CastAdapter.release(true); }
                catch (Exception cleanup) { System.err.println("cast cleanup: " + cleanup); }
            }
            Throwable cause = e instanceof java.lang.reflect.InvocationTargetException ? e.getCause() : e;
            String code = cause instanceof CastFailure ? ((CastFailure) cause).code
                    : cause instanceof SecurityException ? "permission-required"
                    : cause instanceof ReflectiveOperationException ? "backend-incompatible" : "operation-failed";
            System.out.println("{\"error\":" + quote(cause.getMessage()) + ",\"code\":" + quote(code) + "}");
            System.exit(2);
        }
        System.exit(0);
    }

    private static void run(String cmd, String[] args) throws Exception {
        switch (cmd) {
            case "status":
            case "capabilities":
                System.out.println(status());
                break;
            case "configure":
                CastResolution.configure(args.length > 1 ? args[1] : "auto");
                System.out.println("{\"configured\":true}");
                break;
            case "modes":
                System.out.println(resolution());
                break;
            case "resolution": {
                if (args.length != 2 || !args[1].matches("(?i)[0-9a-f:]{17}/(auto|[0-9]+x[0-9]+@[0-9]+)"))
                    throw new CastFailure("invalid-argument", "resolution needs receiver-address/auto|WIDTHxHEIGHT@FPS");
                String[] selection = args[1].split("/");
                Object active = call(wfdStatus(), "getActiveDisplay");
                if (connectedDisplayId() < 0 || active == null || !matches(active, selection[0]))
                    throw new CastFailure("receiver-changed", "The selected receiver is no longer connected");
                if (!CastResolution.supported(selection[0], selection[1]))
                    throw new CastFailure("unsupported", "The receiver, encoder and installed mode control do not share this mode");
                ModeHistory history=ModeHistory.open(selection[0],WfdCapture.read(selection[0]));
                String previous = CastResolution.preference(selection[0]);
                org.json.JSONObject before = resolution();
                CastResolution.save(selection[0], selection[1]);
                org.json.JSONObject result;
                try {
                    if (CastResolution.applyOnline(selection[0],selection[1])) result = new org.json.JSONObject(status());
                    else { disconnect(10); result = new org.json.JSONObject(connect(selection[0], 120)); }
                    org.json.JSONObject actual = result.getJSONObject("resolution");
                    if (!selection[1].equals("auto") && (!selection[1].equals(videoId(actual)) || !displayMatches(CastResolution.mode(selection[1]))))
                        throw new CastFailure("mode-not-applied", "The sender did not negotiate the requested video mode");
                    WfdFormats.Mode verified=CastResolution.verify(selection[1]);
                    if(verified==null)throw new CastFailure("mode-not-applied","Video mode and display did not remain consistent");
                    if(history!=null)history.record(verified.id(),"passed","Negotiated video mode and Android display matched for five seconds");
                    result=new org.json.JSONObject(status()).put("mode_applied",true);
                } catch (Exception failure) {
                    if(history!=null)history.record(selection[1],failure instanceof CastFailure && ((CastFailure)failure).code.equals("mode-not-applied")?"rejected":"failed",failure.getMessage());
                    CastResolution.save(selection[0],previous);
                    boolean restored = false;
                    try {
                        if (connectedDisplayId() >= 0 && videoId(before).equals(videoId(resolution()))) {
                            CastResolution.configure(previous);
                            result = new org.json.JSONObject(status());
                        } else if(CastResolution.applyOnline(selection[0],videoId(before))) {
                            result = new org.json.JSONObject(status());
                        } else { disconnect(10); result = new org.json.JSONObject(connect(selection[0],120)); }
                        restored = connectedDisplayId() >= 0;
                    } catch (Exception recovery) { result = new org.json.JSONObject(status()); }
                    result.put("error",failure.getMessage()).put("code","mode-not-applied").put("restored",restored)
                            .put("requested_mode",selection[1]);
                }
                System.out.println(result);
                break;
            }
            case "settings":
                command("am", "start", "--user", "current", "-a", "android.settings.CAST_SETTINGS");
                System.out.println("{\"opened\":true}");
                break;
            case "claim":
                CastAdapter.claim(connectedDisplayId());
                System.out.println("{\"adapter\":" + quote(CastAdapter.selected().getString("id")) + "}");
                break;
            case "adapter":
                System.out.println(CastAdapter.selected());
                break;
            case "release":
                if ((int) call(wfdStatus(), "getActiveDisplayState") == 0) CastAdapter.release(true);
                System.out.println("{\"released\":true}");
                break;
            case "watch":
                watch();
                break;
            case "scan":
                System.out.println(scan(seconds(args, 1, 8)));
                break;
            case "connect": {
                // "connect 40" (seconds only) and "connect last" use the TV connected last.
                boolean named = args.length > 1 && !args[1].equals("last") && !args[1].matches("\\d+");
                int secondsAt = named || (args.length > 1 && args[1].equals("last")) ? 2 : 1;
                System.out.println(connect(named ? args[1] : lastSink(), seconds(args, secondsAt, 120, 180)));
                break;
            }
            case "disconnect":
                System.out.println(disconnect(seconds(args, 1, 10)));
                break;
            case "decor":
                if (args.length < 2) fail("decor needs a display id");
                System.out.println(decor(Integer.parseInt(args[1]), args.length > 2 ? args[2] : null));
                break;
            case "wfd-config":
                if (args.length < 3) fail("wfd-config needs <vendor wfdconfig.xml> <output>");
                System.out.println(WfdConfig.generate(new File(args[1]), new File(args[2])));
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
        return seconds(args, index, fallback, 45);
    }

    private static int seconds(String[] args, int index, int fallback, int max) {
        int value = args.length > index ? Integer.parseInt(args[index]) : fallback;
        if (value < 1 || value > max) throw new CastFailure("invalid-argument", "Duration must be 1.." + max + " seconds");
        return value;
    }

    private static final class CastFailure extends RuntimeException {
        final String code;
        CastFailure(String code, String message) { super(message); this.code = code; }
    }

    private static void fail(String message) {
        throw new CastFailure("operation-failed", message);
    }

    static void command(String... args) throws Exception {
        Process process = new ProcessBuilder(args).redirectErrorStream(true).start();
        if (!process.waitFor(5, java.util.concurrent.TimeUnit.SECONDS)) {
            process.destroyForcibly();
            throw new CastFailure("timeout", "Android command timed out");
        }
        String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        if (process.exitValue() != 0 || output.contains("Error:") || output.contains("Exception")) {
            throw new CastFailure("permission-required", output.trim());
        }
    }

    /** Only an explicit scan/connect enables wireless display. Status and boot never do. */
    private static void ensureEnabled() throws Exception {
        int feature = (int) call(wfdStatus(), "getFeatureState");
        if (feature == 0) throw new CastFailure("unsupported", "This Android system has no Wi-Fi Display backend");
        if (feature == 1) throw new CastFailure("wifi-unavailable", "Enable Wi-Fi before casting");
        if (feature == 3) return;
        command("settings", "put", "global", "wifi_display_on", "1");
        long deadline = SystemClock.elapsedRealtime() + 5000;
        while (SystemClock.elapsedRealtime() < deadline) {
            if ((int) call(wfdStatus(), "getFeatureState") == 3) return;
            Thread.sleep(100);
        }
        throw new CastFailure("disabled", "Enable wireless display in Android cast settings");
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
        ensureEnabled();
        registerListener();
        call(dmg, "startWifiDisplayScan");
        try {
            Thread.sleep(secs * 1000L);
            remember();
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
        ensureEnabled();
        String address = target.contains(":") && target.length() == 17 ? target : null;
        // Casting to another TV: Android neither scans nor connects elsewhere while a
        // sink is connected, so end that session first (the TV goes blank for a while).
        Object current = call(wfdStatus(), "getActiveDisplay");
        if (current != null && !matches(current, target)) {
            debug("switching from " + call(current, "getDeviceName"));
            call(dmg, "disconnectWifiDisplay");
            long until = SystemClock.elapsedRealtime() + 10000;
            while (SystemClock.elapsedRealtime() < until && (int) call(wfdStatus(), "getActiveDisplayState") != 0) {
                Thread.sleep(250);
            }
        }
        connecting = true;
        long started = SystemClock.elapsedRealtime();
        long deadline = started + secs * 1000L;
        progress(target, started, secs, 0, 0);
        registerListener();
        call(dmg, "startWifiDisplayScan");
        try (WfdCapture capture = new WfdCapture()) {
            long lastRequest = 0, lastProgress = 0, stableSince = 0;
            int attempts = 0;
            String configuredFor = null;
            while (SystemClock.elapsedRealtime() < deadline) {
                Object s = wfdStatus();
                Object active = call(s, "getActiveDisplay");
                if ((int) call(s, "getActiveDisplayState") == CONNECTED && active != null
                        && (matches(active, target)
                            || (address != null && address.equalsIgnoreCase((String) call(active, "getDeviceAddress"))))) {
                    if (stableSince == 0) stableSince = SystemClock.elapsedRealtime();
                    if (SystemClock.elapsedRealtime() - stableSince < 2000 || activeDisplayId(active) < 0) { Thread.sleep(250); continue; }
                    Files.write(LAST_SINK.toPath(), (call(active, "getDeviceAddress") + "\n"
                            + call(active, "getDeviceName") + "\n").getBytes(StandardCharsets.UTF_8));
                    String connectedAddress=(String)call(active,"getDeviceAddress");
                    capture.record(connectedAddress);
                    String preferred=CastResolution.preference(connectedAddress);
                    if(!preferred.equals("auto")) {
                        try { CastResolution.applyOnline(connectedAddress,preferred); }
                        catch(Exception e) { System.err.println("Requested WFD mode not applied: "+e.getMessage()); }
                    }
                    return status();
                }
                stableSince = 0;
                String found = findAvailable(address != null ? address : target);
                if (found == null && address != null) found = findAvailable(sibling(address));
                debug("state=" + call(s, "getActiveDisplayState") + " scan=" + call(s, "getScanState") + " found=" + found);
                long now = SystemClock.elapsedRealtime();
                if (now - lastProgress >= 1000) { progress(target, started, secs, attempts, (int)call(s,"getActiveDisplayState")); lastProgress = now; }
                if ((int) call(s, "getActiveDisplayState") == 0 && found != null && now - lastRequest > 5000) {
                    address = found;
                    if (!address.equals(configuredFor)) {
                        String preferred=CastResolution.preference(address);
                        try { CastResolution.configure(preferred); }
                        catch(Exception unavailable) {
                            // Optional mode adapter must not block native casting on an unknown backend.
                            // Exact-mode requests are checked again after connection and rolled back by their caller.
                            System.err.println("WFD offer control unavailable: "+unavailable.getMessage());
                            if(!preferred.equals("auto"))try {CastResolution.configure("auto");}
                            catch(Exception ignored){}
                        }
                        configuredFor = address;
                    }
                    attempts++;
                    debug("connectWifiDisplay " + address);
                    call(dmg, "connectWifiDisplay", address);
                    lastRequest = now;
                }
                Thread.sleep(250);
            }
        } finally {
            call(dmg, "stopWifiDisplayScan");
        }
        call(dmg, "disconnectWifiDisplay"); // Do not leave an orphan connection after timeout.
        CastAdapter.release(true);
        throw new CastFailure("timeout", "Receiver did not complete network setup and negotiation within the connection budget: "
                + (address != null ? address : target));
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
            if (found != null) throw new CastFailure("receiver-required", "Choose a TV in cast settings");
            found = (String) call(d, "getDeviceAddress");
        }
        if (found == null) throw new CastFailure("receiver-required", "Choose your first TV in cast settings");
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
        long deadline = SystemClock.elapsedRealtime() + secs * 1000L;
        while (SystemClock.elapsedRealtime() < deadline && (int) call(wfdStatus(), "getActiveDisplayState") != 0) {
            Thread.sleep(250);
        }
        if ((int) call(wfdStatus(), "getActiveDisplayState") != 0)
            throw new CastFailure("timeout", "Timed out disconnecting Wi-Fi Display");
        CastAdapter.release(true);
        return status();
    }

    /** One inexpensive resident process restores vendor UI after disconnect/crash, also after reboot. */
    private static void watch() throws Exception {
        DIR.mkdirs();
        try (java.io.RandomAccessFile file = new java.io.RandomAccessFile(new File(DIR, "watch.lock"), "rw");
                java.nio.channels.FileLock lock = file.getChannel().tryLock()) {
            if (lock == null) return;
            Files.write(new File(DIR, "watch.pid").toPath(),
                    Integer.toString(android.os.Process.myPid()).getBytes(StandardCharsets.UTF_8));
            Handler handler = new Handler(Looper.getMainLooper());
            handler.post(new Runnable() {
                @Override public void run() {
                    WfdCapture.reap();
                    try {
                        if ((int) call(wfdStatus(), "getActiveDisplayState") == 0) {
                            CastAdapter.release(false);
                            if (connectionProgress() == null) CastResolution.restoreIdle();
                        }
                        else CastAdapter.claim(connectedDisplayId());
                    } catch (Exception e) { System.err.println("cast cleanup: " + e); }
                    handler.postDelayed(this, 2000);
                }
            });
            Looper.loop();
        }
    }

    /** IWindowManager.setShouldShowSystemDecors: root passes its INTERNAL_SYSTEM_WINDOW check. */
    private static String decor(int displayId, String value) throws Exception {
        Object wm = Class.forName("android.view.WindowManagerGlobal").getMethod("getWindowManagerService").invoke(null);
        if (value != null) call(wm, "setShouldShowSystemDecors", displayId, !value.equals("off"));
        return "{\"display\":" + displayId + ",\"system_decors\":" + call(wm, "shouldShowSystemDecors", displayId) + "}";
    }

    /**
     * Address of an available sink matching an address, a name, a receiver (the name
     * without its "[R1]" suffix) or a name prefix; a sink with a free session first.
     */
    private static String findAvailable(String key) throws Exception {
        if (key == null) return null;
        Object displays = call(wfdStatus(), "getDisplays");
        String busy = null;
        for (int i = 0; i < Array.getLength(displays); i++) {
            Object d = Array.get(displays, i);
            if (!(boolean) call(d, "isAvailable")) continue;
            String address = (String) call(d, "getDeviceAddress");
            String device = (String) call(d, "getDeviceName");
            String alias = (String) call(d, "getDeviceAlias");
            if (matches(d, key) || key.equals(alias) || (device != null && device.startsWith(key))) {
                if ((boolean) call(d, "canConnect")) return address;
                if (busy == null) busy = address;
            }
        }
        return busy;
    }

    /** A sink is named by its address, its name or its receiver name. */
    private static boolean matches(Object d, String key) throws Exception {
        String device = (String) call(d, "getDeviceName");
        return key.equalsIgnoreCase((String) call(d, "getDeviceAddress")) || key.equals(device)
                || key.equals(receiverName(device));
    }

    /** "TCL 85Q6H-9E92[R2]" -> "TCL 85Q6H-9E92": the entries one TV offers share it. */
    static String receiverName(String device) {
        return device == null ? "" : device.replaceFirst("\\s*\\[[^\\]]*\\]$", "");
    }

    /** The receiver name of a known sink address, for another entry of the same TV. */
    private static String sibling(String address) throws Exception {
        for (String[] sink : knownSinks()) {
            if (sink[0].equalsIgnoreCase(address)) return receiverName(sink[1]);
        }
        return null;
    }

    private static String videoId(org.json.JSONObject value) {
        return value.optInt("video_width",-1)+"x"+value.optInt("video_height",-1)+"@"+value.optInt("video_fps",-1);
    }
    private static org.json.JSONObject resolution() throws Exception {
        Object active = call(wfdStatus(), "getActiveDisplay");
        int id = connectedDisplayId();
        return CastResolution.modes(id < 0 ? null : call(dmg, "getDisplayInfo", id),
                active == null ? null : (String)call(active, "getDeviceAddress"));
    }

    private static final File PROGRESS = new File(DIR, "run/connection.json");
    private static void progress(String target, long start, int budget, int attempt, int state) throws Exception {
        PROGRESS.getParentFile().mkdirs();
        org.json.JSONObject value = new org.json.JSONObject().put("pid", android.os.Process.myPid())
                .put("target", target).put("started_ms", start).put("budget_seconds", budget)
                .put("attempt", attempt).put("phase", state == 2 ? "connected" : state == 1 ? "negotiating" : "waiting-receiver");
        android.util.AtomicFile file = new android.util.AtomicFile(PROGRESS);
        java.io.FileOutputStream stream = file.startWrite();
        try { stream.write(value.toString().getBytes(StandardCharsets.UTF_8)); file.finishWrite(stream); }
        catch (Exception e) { file.failWrite(stream); throw e; }
    }
    private static org.json.JSONObject connectionProgress() {
        try {
            org.json.JSONObject value = new org.json.JSONObject(new String(new android.util.AtomicFile(PROGRESS).readFully(), StandardCharsets.UTF_8));
            long age = SystemClock.elapsedRealtime() - value.getLong("started_ms");
            String process = new String(Files.readAllBytes(new File("/proc/"+value.getInt("pid")+"/cmdline").toPath()), StandardCharsets.UTF_8);
            if (age < 0 || age > 210000 || !process.contains("com.rungic.cast.Main")) return null;
            return value.put("elapsed_seconds", age / 1000);
        } catch (Exception ignored) { return null; }
    }

    private static String status() throws Exception {
        Object s = wfdStatus();
        StringBuilder out = new StringBuilder("{");
        out.append("\"feature_state\":").append(call(s, "getFeatureState"));
        out.append(",\"backend\":\"android-wfd\",\"supported\":")
                .append((int) call(s, "getFeatureState") != 0);
        out.append(",\"adapter\":").append(quote(CastAdapter.selected().getString("id")));
        out.append(",\"ui_policy\":").append(CastAdapter.uiStatus());
        out.append(",\"scan_state\":").append(call(s, "getScanState"));
        out.append(",\"active_state\":").append(call(s, "getActiveDisplayState"));
        Object active = call(s, "getActiveDisplay");
        out.append(",\"active\":").append(active == null ? "null" : display(active));
        out.append(",\"android_display_id\":").append(activeDisplayId(active));
        out.append(",\"reconnecting\":").append(reconnecting());
        out.append(",\"connection\":").append(connectionProgress());
        out.append(",\"resolution\":").append(resolution());
        out.append(",\"receivers\":").append(receivers(s, active));
        out.append(",\"displays\":[");
        Object displays = call(s, "getDisplays");
        for (int i = 0; i < Array.getLength(displays); i++) {
            if (i > 0) out.append(',');
            out.append(display(Array.get(displays, i)));
        }
        return out.append("]}").toString();
    }

    static boolean displayMatches(WfdFormats.Mode requested) throws Exception {
        int id=connectedDisplayId();
        if(id<0)return false;
        Object info=call(dmg,"getDisplayInfo",id);
        return info!=null && info.getClass().getField("logicalWidth").getInt(info)==requested.width
                && info.getClass().getField("logicalHeight").getInt(info)==requested.height;
    }

    static int connectedDisplayId() throws Exception {
        Object s = wfdStatus();
        return (int) call(s, "getActiveDisplayState") == CONNECTED ? activeDisplayId(call(s, "getActiveDisplay")) : -1;
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
                + ",\"can_connect\":" + call(d, "canConnect")
                + ",\"remembered\":" + call(d, "isRemembered") + "}";
    }

    /** One TV: its Wi-Fi Display entries merged under the receiver name. */
    private static final class Receiver {
        final String name;
        String address;
        boolean active, available, free, remembered, last, addressFree;
        long seen;
        Receiver(String name) { this.name = name; }

        /** The entry to connect to: the one used last, else one with a free session. */
        void offer(String candidate, boolean isFree, boolean isLast) {
            if (address == null || isLast || (isFree && !addressFree)) {
                address = candidate;
                addressFree = isFree;
            }
        }

        int rank() { return active ? 0 : last ? 1 : available && free ? 2 : available ? 3 : 4; }

        String json() {
            return "{\"name\":" + quote(name) + ",\"address\":" + quote(address)
                    + ",\"active\":" + active + ",\"available\":" + available
                    + ",\"can_connect\":" + free + ",\"remembered\":" + remembered
                    + ",\"last\":" + last + ",\"seen_ms_ago\":"
                    + (seen > 0 ? Long.toString(Math.max(0, System.currentTimeMillis() - seen)) : "null") + "}";
        }
    }

    /**
     * The TVs to offer: the connected one, those available now, those a scan saw in
     * the last ten minutes, those Android remembers and the one connected last.
     */
    private static String receivers(Object s, Object active) throws Exception {
        java.util.Map<String, Receiver> byName = new java.util.LinkedHashMap<>();
        String[] lastSink = lastSinkEntry();
        String lastAddress = lastSink == null ? null : lastSink[0];
        String lastName = lastSink == null ? null : receiverName(lastSink[1]);
        Object displays = call(s, "getDisplays");
        for (int i = 0; i < Array.getLength(displays); i++) {
            Object d = Array.get(displays, i);
            String address = (String) call(d, "getDeviceAddress");
            Receiver r = byName.computeIfAbsent(receiverName((String) call(d, "getDeviceName")), Receiver::new);
            boolean available = (boolean) call(d, "isAvailable");
            boolean free = available && (boolean) call(d, "canConnect");
            r.available |= available;
            r.free |= free;
            r.remembered |= (boolean) call(d, "isRemembered");
            r.offer(address, free, address.equalsIgnoreCase(lastAddress));
        }
        for (String[] sink : knownSinks()) {
            long at = Long.parseLong(sink[2]);
            Receiver r = byName.computeIfAbsent(receiverName(sink[1]), Receiver::new);
            r.seen = Math.max(r.seen, at);
            r.offer(sink[0], false, sink[0].equalsIgnoreCase(lastAddress));
        }
        if (lastSink != null) byName.computeIfAbsent(lastName, Receiver::new).offer(lastAddress, false, true);
        if (active != null) {
            Receiver r = byName.computeIfAbsent(receiverName((String) call(active, "getDeviceName")), Receiver::new);
            r.active = true;
            r.address = (String) call(active, "getDeviceAddress");
        }
        java.util.List<Receiver> list = new java.util.ArrayList<>(byName.values());
        for (Receiver r : list) r.last = r.name.equals(lastName);
        list.sort((a, b) -> a.rank() != b.rank() ? a.rank() - b.rank() : a.name.compareToIgnoreCase(b.name));
        StringBuilder out = new StringBuilder("[");
        for (Receiver r : list) {
            if (out.length() > 1) out.append(',');
            out.append(r.json());
        }
        return out.append(']').toString();
    }

    /** Address and name of the sink connected last, or null. */
    private static String[] lastSinkEntry() {
        try {
            String[] lines = new String(Files.readAllBytes(LAST_SINK.toPath()), StandardCharsets.UTF_8).split("\n");
            return lines.length >= 2 && !lines[0].trim().isEmpty() ? new String[] {lines[0].trim(), lines[1].trim()} : null;
        } catch (Exception e) {
            return null;
        }
    }

    /** Sinks seen by scans in the last ten minutes: address, name, epoch ms. */
    private static java.util.List<String[]> knownSinks() {
        java.util.List<String[]> out = new java.util.ArrayList<>();
        try {
            long now = System.currentTimeMillis();
            for (String line : new String(Files.readAllBytes(SEEN.toPath()), StandardCharsets.UTF_8).split("\n")) {
                String[] f = line.split("\t");
                if (f.length == 3 && now - Long.parseLong(f[2]) < SEEN_FOR) out.add(f);
            }
        } catch (Exception e) {
            // None seen yet.
        }
        return out;
    }

    /** Adds the sinks available now to the seen list. */
    private static void remember() throws Exception {
        java.util.Map<String, String> lines = new java.util.LinkedHashMap<>();
        for (String[] sink : knownSinks()) lines.put(sink[0].toLowerCase(Locale.ROOT), String.join("\t", sink));
        long now = System.currentTimeMillis();
        Object displays = call(wfdStatus(), "getDisplays");
        for (int i = 0; i < Array.getLength(displays); i++) {
            Object d = Array.get(displays, i);
            if (!(boolean) call(d, "isAvailable")) continue;
            String address = (String) call(d, "getDeviceAddress");
            String name = ((String) call(d, "getDeviceName")).replace('\t', ' ').replace('\n', ' ');
            lines.put(address.toLowerCase(Locale.ROOT), address + "\t" + name + "\t" + now);
        }
        SEEN.getParentFile().mkdirs();
        Files.write(SEEN.toPath(), (String.join("\n", lines.values()) + "\n").getBytes(StandardCharsets.UTF_8));
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
