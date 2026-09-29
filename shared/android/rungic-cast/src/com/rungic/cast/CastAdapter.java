// SPDX-License-Identifier: MIT
package com.rungic.cast;

import android.content.Context;
import android.content.pm.PackageManager;
import android.content.pm.ApplicationInfo;
import android.os.Build;
import android.util.AtomicFile;
import java.io.File;
import java.io.FileOutputStream;
import java.io.RandomAccessFile;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import org.json.JSONArray;
import org.json.JSONObject;

/** Firmware quirks and runtime UI conflicts have separate selection criteria. */
final class CastAdapter {
    private static final File DIR = new File("/data/adb/rungic-wfd");
    private static final File LEASE = new File(DIR, "ui-lease.json");
    private static PackageManager packageManager;

    private static JSONObject configuration() throws Exception {
        File file = new File(DIR, "adapters.json");
        if (!file.exists()) return new JSONObject().put("adapters", new JSONArray());
        JSONObject root = new JSONObject(new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8));
        if (root.getInt("schema") != 1) throw new IllegalArgumentException("Unknown casting adapter schema");
        return root;
    }

    static JSONObject selected() throws Exception {
        JSONArray adapters = configuration().getJSONArray("adapters");
        for (int i = 0; i < adapters.length(); i++) {
            JSONObject adapter = adapters.getJSONObject(i);
            if (Build.DEVICE.equals(adapter.getString("device")) && Build.ID.equals(adapter.getString("build_id"))
                    && Build.VERSION.SDK_INT == adapter.getInt("sdk")) return adapter;
        }
        return new JSONObject().put("id", "android-native");
    }

    static JSONObject uiStatus() throws Exception {
        JSONObject out = new JSONObject().put("mode", "runtime-window-conflicts").put("claimed", new JSONArray());
        if (LEASE.exists()) {
            JSONObject lease = new JSONObject(new String(new AtomicFile(LEASE).readFully(), StandardCharsets.UTF_8));
            out.put("claimed", lease.getJSONObject("states").names()).put("display", lease.optInt("display", -1))
                .put("evidence", lease.optJSONObject("evidence"));
        }
        return out;
    }

    private static PackageManager packages() throws Exception {
        if (packageManager != null) return packageManager;
        Class<?> thread = Class.forName("android.app.ActivityThread");
        Object current = thread.getMethod("systemMain").invoke(null);
        Context context = (Context) thread.getMethod("getSystemContext").invoke(current);
        packageManager = context.getPackageManager();
        return packageManager;
    }

    private static void save(JSONObject state) throws Exception {
        AtomicFile file = new AtomicFile(LEASE);
        FileOutputStream stream = file.startWrite();
        try {
            stream.write(state.toString().getBytes(StandardCharsets.UTF_8));
            file.finishWrite(stream);
        } catch (Exception e) { file.failWrite(stream); throw e; }
    }

    /** Only an actual known vendor UI window above our desktop can acquire a lease. */
    static void claim(int display) throws Exception {
        if (display <= 0) return;
        int user = (int) Class.forName("android.app.ActivityManager").getMethod("getCurrentUser").invoke(null);
        if (user != 0) return; // This root PackageManager context observes owner-user packages only.
        JSONArray rules = configuration().optJSONArray("ui_rules");
        if (rules == null || rules.length() == 0) return;
        DIR.mkdirs();
        try (RandomAccessFile lock = new RandomAccessFile(new File(DIR, "ui-lease.lock"), "rw");
                FileLock held = lock.getChannel().lock()) {
            JSONObject lease = LEASE.exists()
                    ? new JSONObject(new String(new AtomicFile(LEASE).readFully(), StandardCharsets.UTF_8)) : null;
            if (lease != null && (!bootId().equals(lease.optString("boot"))
                    || (lease.has("display") && lease.getInt("display") != display))) {
                restore(lease);
                lease = null;
            }
            if (lease != null && !lease.optBoolean("applied")) apply(lease);
            PackageManager pm = packages();
            ApplicationInfo host;
            try { host = pm.getApplicationInfo("com.rungic.plasma", 0); }
            catch (PackageManager.NameNotFoundException absent) { return; }
            java.util.List<CastWindows.Window> windows = CastWindows.parse(windowDump());
            CastWindows.Window desktop = CastWindows.desktop(windows, display, host.uid);
            if (desktop == null) return; // Ordinary Android casting is not ours to take over.
            if (lease == null) lease = new JSONObject().put("user", user).put("display", display)
                    .put("created", System.currentTimeMillis()).put("elapsed", android.os.SystemClock.elapsedRealtime())
                    .put("boot", bootId()).put("states", new JSONObject()).put("evidence", new JSONObject());
            JSONObject states = lease.getJSONObject("states");
            JSONObject evidence = lease.optJSONObject("evidence");
            if (evidence == null) { evidence = new JSONObject(); lease.put("evidence", evidence); }
            boolean changed = false;
            for (int i = 0; i < rules.length(); i++) {
                JSONObject rule = rules.getJSONObject(i);
                String name = rule.getString("package");
                if (states.has(name)) continue;
                ApplicationInfo app;
                try { app = pm.getApplicationInfo(name, 0); }
                catch (PackageManager.NameNotFoundException absent) { continue; }
                // Factory preinstalls can lack FLAG_SYSTEM. WindowManager ownership,
                // the rule's privileged window type, and its actual layer are the evidence.
                int state = pm.getApplicationEnabledSetting(name);
                if (state != PackageManager.COMPONENT_ENABLED_STATE_DEFAULT && state != PackageManager.COMPONENT_ENABLED_STATE_ENABLED) continue;
                for (CastWindows.Window window : windows) {
                    if (!CastWindows.matches(window, desktop, name, app.uid,
                            rule.getString("window_prefix"), rule.getString("window_type"))) continue;
                    // A disconnect/display replacement during observation must not acquire a stale lease.
                    if (Main.connectedDisplayId() != display) return;
                    states.put(name, state);
                    evidence.put(name, new JSONObject().put("rule", rule.getString("id"))
                            .put("window", window.title).put("type", window.type).put("layer", window.layer)
                            .put("desktopLayer", desktop.layer).put("uid", window.uid));
                    changed = true;
                    break;
                }
            }
            if (!changed) return;
            lease.put("applied", false);
            save(lease); // Originals and observation are durable before any package mutation.
            apply(lease);
        }
    }

    private static String windowDump() throws Exception {
        File file = File.createTempFile("windows-", ".txt", DIR);
        Process process = null;
        try {
            process = new ProcessBuilder("dumpsys", "-t", "3", "window", "windows")
                    .redirectErrorStream(true).redirectOutput(file).start();
            if (!process.waitFor(4, java.util.concurrent.TimeUnit.SECONDS)) throw new java.io.IOException("window-observation-timeout");
            if (process.exitValue() != 0 || file.length() > 4 * 1024 * 1024) throw new java.io.IOException("window-observation-failed");
            return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
        } finally {
            if (process != null) process.destroy();
            file.delete();
        }
    }

    private static String bootId() throws Exception {
        return new String(Files.readAllBytes(new File("/proc/sys/kernel/random/boot_id").toPath()), StandardCharsets.UTF_8).trim();
    }

    private static void apply(JSONObject lease) throws Exception {
        JSONObject states = lease.getJSONObject("states");
        for (java.util.Iterator<String> it = states.keys(); it.hasNext(); )
            Main.command("pm", "disable-user", "--user", Integer.toString(lease.getInt("user")), it.next());
        lease.put("applied", true);
        save(lease);
    }

    static void release(boolean force) throws Exception {
        DIR.mkdirs();
        try (RandomAccessFile lock = new RandomAccessFile(new File(DIR, "ui-lease.lock"), "rw");
                FileLock held = lock.getChannel().lock()) {
            if (!LEASE.exists()) return;
            JSONObject lease = new JSONObject(new String(new AtomicFile(LEASE).readFully(), StandardCharsets.UTF_8));
            // Compatibility: old firmware-selected leases could be acquired before P2P.
            if (!force && !lease.has("display") && bootId().equals(lease.optString("boot"))
                    && android.os.SystemClock.elapsedRealtime() - lease.optLong("elapsed") < 65000) return;
            restore(lease);
        }
    }

    private static void restore(JSONObject lease) throws Exception {
        JSONObject states = lease.getJSONObject("states");
        String user = Integer.toString(lease.getInt("user"));
        for (java.util.Iterator<String> it = states.keys(); it.hasNext(); ) {
            String name = it.next();
            int current = packages().getApplicationEnabledSetting(name);
            // Preserve a later user/administrator change rather than blindly enabling.
            if (current == PackageManager.COMPONENT_ENABLED_STATE_DISABLED_USER)
                Main.command("pm", states.getInt(name) == 0 ? "default-state" : "enable", "--user", user, name);
        }
        new AtomicFile(LEASE).delete();
    }
}
