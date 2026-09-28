// SPDX-License-Identifier: MIT
package com.rungic.cast;

import android.content.Context;
import android.content.pm.PackageManager;
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

/** Firmware exceptions are data; the default never modifies vendor packages/configuration. */
final class CastAdapter {
    private static final File DIR = new File("/data/adb/rungic-wfd");
    private static final File LEASE = new File(DIR, "ui-lease.json");
    private static PackageManager packageManager;

    static JSONObject selected() throws Exception {
        File file = new File(DIR, "adapters.json");
        if (file.exists()) {
            JSONObject root = new JSONObject(new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8));
            if (root.getInt("schema") != 1) throw new IllegalArgumentException("Unknown casting adapter schema");
            JSONArray adapters = root.getJSONArray("adapters");
            for (int i = 0; i < adapters.length(); i++) {
                JSONObject adapter = adapters.getJSONObject(i);
                if (Build.DEVICE.equals(adapter.getString("device")) && Build.ID.equals(adapter.getString("build_id"))
                        && Build.VERSION.SDK_INT == adapter.getInt("sdk")) return adapter;
            }
        }
        return new JSONObject().put("id", "android-native").put("suspend_packages", new JSONArray());
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

    static void claim() throws Exception {
        DIR.mkdirs();
        try (RandomAccessFile lock = new RandomAccessFile(new File(DIR, "ui-lease.lock"), "rw");
                FileLock held = lock.getChannel().lock()) {
            if (LEASE.exists()) {
                JSONObject lease = new JSONObject(new String(new AtomicFile(LEASE).readFully(), StandardCharsets.UTF_8));
                if (!lease.optBoolean("applied")) apply(lease);
                return;
            }
            JSONObject adapter = selected();
            JSONArray names = adapter.getJSONArray("suspend_packages");
            if (names.length() == 0) return;
            int user = (int) Class.forName("android.app.ActivityManager").getMethod("getCurrentUser").invoke(null);
            // This app_process context queries user 0. Refuse an unverified cross-user modification.
            if (user != 0) throw new IllegalStateException("Casting adapter requires the owner user");
            PackageManager pm = packages();
            JSONObject states = new JSONObject();
            for (int i = 0; i < names.length(); i++) {
                String name = names.getString(i);
                try { pm.getApplicationInfo(name, 0); }
                catch (PackageManager.NameNotFoundException absent) { continue; }
                int state = pm.getApplicationEnabledSetting(name);
                if (state == PackageManager.COMPONENT_ENABLED_STATE_DEFAULT || state == PackageManager.COMPONENT_ENABLED_STATE_ENABLED)
                    states.put(name, state);
            }
            // Persist originals before any mutation, including if a later operation fails.
            JSONObject lease = new JSONObject().put("adapter", adapter.getString("id")).put("user", user)
                    .put("created", System.currentTimeMillis()).put("elapsed", android.os.SystemClock.elapsedRealtime())
                    .put("boot", bootId()).put("states", states);
            save(lease);
            apply(lease);
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
            // A connect request acquires before P2P starts; give it time to reach the framework.
            if (!force && bootId().equals(lease.optString("boot"))
                    && android.os.SystemClock.elapsedRealtime() - lease.optLong("elapsed") < 65000) return;
            JSONObject states = lease.getJSONObject("states");
            String user = Integer.toString(lease.getInt("user"));
            for (java.util.Iterator<String> it = states.keys(); it.hasNext(); ) {
                String name = it.next();
                int current = packages().getApplicationEnabledSetting(name);
                // Restore only values we set; preserve a later user/administrator change.
                if (current == PackageManager.COMPONENT_ENABLED_STATE_DISABLED_USER)
                    Main.command("pm", states.getInt(name) == 0 ? "default-state" : "enable", "--user", user, name);
            }
            new AtomicFile(LEASE).delete();
        }
    }
}
