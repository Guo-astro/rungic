// SPDX-License-Identifier: MIT
package com.rungic.bluetooth;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothClass;
import android.bluetooth.BluetoothDevice;
import android.content.AttributionSource;
import android.os.Looper;
import android.os.ParcelUuid;
import java.lang.reflect.Method;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Bluetooth for the BlueZ service of the Linux side (docs/73), with the privileges Android keeps from
 * apps: the adapter as root (uid 0 holds BLUETOOTH_PRIVILEGED), made without an app context.
 *   state                        adapter and bonded devices as one JSON line
 *   unpair|connect|disconnect ADDRESS
 *   pair ADDRESS                 start bonding; Android asks the user to confirm
 *   name NAME                    the adapter's name
 * Not part of the app's own process: AndroidBluetoothBridge runs it as root with app_process from the
 * APK's own file. Prints a JSON line, {"error": ...} on failure.
 */
public final class RootBluetooth {
    public static void main(String[] args) {
        Looper.prepareMainLooper();
        try {
            System.out.println(run(args));
            System.exit(0);
        } catch (Throwable e) {
            Throwable cause = e instanceof java.lang.reflect.InvocationTargetException ? e.getCause() : e;
            System.out.println("{\"error\":" + JSONObject.quote(cause.getClass().getSimpleName() + ": " + cause.getMessage()) + "}");
            System.exit(1);
        }
    }

    private static BluetoothAdapter adapter() throws Exception {
        // app_process has no framework initialised: give Bluetooth its service manager, then make the
        // adapter for the shell identity (root).
        Class<?> manager = Class.forName("android.os.BluetoothServiceManager");
        Method set = Class.forName("android.bluetooth.BluetoothFrameworkInitializer")
                .getDeclaredMethod("setBluetoothServiceManager", manager);
        set.setAccessible(true);
        set.invoke(null, manager.getConstructor().newInstance());
        AttributionSource source = new AttributionSource.Builder(0).setPackageName("com.android.shell").build();
        Method create = BluetoothAdapter.class.getDeclaredMethod("createAdapter", AttributionSource.class);
        create.setAccessible(true);
        BluetoothAdapter adapter = (BluetoothAdapter) create.invoke(null, source);
        if (adapter == null) throw new IllegalStateException("no Bluetooth adapter");
        return adapter;
    }

    private static boolean call(Object target, String name, Object... values) throws Exception {
        for (Method m : target.getClass().getMethods()) {
            if (m.getName().equals(name) && m.getParameterCount() == values.length) {
                Object result = m.invoke(target, values);
                return !(result instanceof Boolean) || (Boolean) result;
            }
        }
        for (Method m : target.getClass().getDeclaredMethods()) {
            if (m.getName().equals(name) && m.getParameterCount() == values.length) {
                m.setAccessible(true);
                Object result = m.invoke(target, values);
                return !(result instanceof Boolean) || (Boolean) result;
            }
        }
        throw new NoSuchMethodException(name);
    }

    private static String run(String[] args) throws Exception {
        String command = args.length > 0 ? args[0] : "state";
        BluetoothAdapter adapter = adapter();
        if (command.equals("state")) return state(adapter).toString();
        if (command.equals("name") && args.length == 2) {
            return new JSONObject().put("ok", adapter.setName(args[1])).toString();
        }
        if (args.length != 2 || !BluetoothAdapter.checkBluetoothAddress(args[1])) {
            throw new IllegalArgumentException("usage: state | name NAME | pair|unpair|connect|disconnect ADDRESS");
        }
        BluetoothDevice device = adapter.getRemoteDevice(args[1]);
        boolean ok;
        switch (command) {
            case "pair": ok = device.createBond(); break;
            case "unpair": ok = call(device, "removeBond"); break;
            case "connect": ok = call(adapter, "connectAllEnabledProfiles", device); break;
            case "disconnect": ok = call(adapter, "disconnectAllEnabledProfiles", device); break;
            default: throw new IllegalArgumentException("unknown command " + command);
        }
        return new JSONObject().put("ok", ok).toString();
    }

    private static JSONObject state(BluetoothAdapter adapter) throws Exception {
        int state = adapter.getState();
        JSONObject result = new JSONObject().put("state", state).put("enabled", state == BluetoothAdapter.STATE_ON)
                .put("name", adapter.getName()).put("address", adapter.getAddress())
                .put("discovering", state == BluetoothAdapter.STATE_ON && adapter.isDiscovering());
        JSONArray devices = new JSONArray();
        if (state == BluetoothAdapter.STATE_ON) {
            for (BluetoothDevice d : adapter.getBondedDevices()) devices.put(device(d));
        }
        return result.put("devices", devices);
    }

    public static JSONObject device(BluetoothDevice d) throws Exception {
        BluetoothClass type = d.getBluetoothClass();
        JSONArray uuids = new JSONArray();
        ParcelUuid[] list = d.getUuids();
        if (list != null) for (ParcelUuid u : list) uuids.put(u.toString());
        Object connected;
        try { connected = BluetoothDevice.class.getMethod("isConnected").invoke(d); } catch (Exception e) { connected = false; }
        return new JSONObject().put("address", d.getAddress()).put("name", d.getName() == null ? "" : d.getName())
                .put("alias", d.getAlias() == null ? "" : d.getAlias()).put("class", type == null ? 0 : type.hashCode())
                .put("bond", d.getBondState()).put("connected", connected).put("type", d.getType()).put("uuids", uuids);
    }
}
