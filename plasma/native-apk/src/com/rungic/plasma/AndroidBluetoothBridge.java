package com.rungic.plasma;

import android.Manifest;
import android.app.Activity;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothClass;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.os.SystemClock;
import org.json.*;
import java.io.IOException;
import java.util.*;

/** Bluetooth for the Linux side's BlueZ service (docs/73). The adapter's state, bonded devices and the
 * privileged operations (unpair, connect, disconnect, name) come from com.rungic.bluetooth.RootBluetooth
 * run as root; the on/off switch is Android's cmd bluetooth_manager; discovery uses this app's own
 * adapter (BLUETOOTH_SCAN), as discovery results arrive as broadcasts to an app. Bonding is started
 * here and confirmed by the user in Android's pairing dialog. */
final class AndroidBluetoothBridge {
    private final Activity activity;
    private final AndroidNetworkBridge root;
    private final Map<String,JSONObject> found=new HashMap<>();
    private boolean receiving;
    AndroidBluetoothBridge(Activity activity,AndroidNetworkBridge root) { this.activity=activity;this.root=root; }

    private final BroadcastReceiver receiver=new BroadcastReceiver() {
        @Override public void onReceive(Context context,Intent intent) {
            BluetoothDevice device=intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE,BluetoothDevice.class);
            if(device==null)return;
            try {
                BluetoothClass type=intent.getParcelableExtra(BluetoothDevice.EXTRA_CLASS,BluetoothClass.class);
                String name=intent.getStringExtra(BluetoothDevice.EXTRA_NAME);
                synchronized(found) {
                    JSONObject row=found.containsKey(device.getAddress())?found.get(device.getAddress()):new JSONObject().put("address",device.getAddress());
                    if(name!=null)row.put("name",name);
                    if(type!=null)row.put("class",type.hashCode());
                    if(intent.hasExtra(BluetoothDevice.EXTRA_RSSI))row.put("rssi",intent.getShortExtra(BluetoothDevice.EXTRA_RSSI,(short)0));
                    row.put("seen",SystemClock.elapsedRealtime());
                    found.put(device.getAddress(),row);
                }
            } catch(JSONException ignored) {}
        }
    };

    private BluetoothAdapter adapter() {
        BluetoothManager manager=activity.getSystemService(BluetoothManager.class);
        return manager==null?null:manager.getAdapter();
    }

    private static final java.util.regex.Pattern ADDRESS=java.util.regex.Pattern.compile("[0-9A-F]{2}(:[0-9A-F]{2}){5}");

    private JSONObject helper(String arguments) throws Exception {
        String apk=activity.getApplicationInfo().sourceDir;
        String reply=root.rootShell("CLASSPATH='"+apk.replace("'","'\\''")+"' /system/bin/app_process /system/bin com.rungic.bluetooth.RootBluetooth "+arguments+" || true",15000);
        String[] lines=reply.trim().split("\n");
        JSONObject result=new JSONObject(lines[lines.length-1]);
        if(result.has("error"))throw new IOException(result.getString("error"));
        return result;
    }

    JSONObject handle(JSONObject request) throws Exception {
        String action=request.optString("action");
        String address=request.optString("address","").toUpperCase(Locale.ROOT);
        switch(action) {
            case "state": {
                JSONObject state=helper("state");
                JSONArray devices=new JSONArray();
                long now=SystemClock.elapsedRealtime();
                synchronized(found) {
                    for(Iterator<Map.Entry<String,JSONObject>> it=found.entrySet().iterator();it.hasNext();) {
                        JSONObject row=it.next().getValue();
                        if(now-row.optLong("seen")>120000)it.remove();else devices.put(row);
                    }
                }
                return state.put("found",devices);
            }
            case "power": {
                root.rootShell("/system/bin/cmd bluetooth_manager "+(request.getBoolean("on")?"enable":"disable"),10000);
                return new JSONObject().put("accepted",true);
            }
            case "discover": {
                BluetoothAdapter adapter=adapter();
                if(adapter==null)throw new IOException("No Bluetooth adapter");
                if(request.getBoolean("on")) {
                    // Discovery runs in this app; the permission comes from root like the helper's privileges.
                    for(String permission:new String[]{Manifest.permission.BLUETOOTH_SCAN,Manifest.permission.BLUETOOTH_CONNECT})
                        if(activity.checkSelfPermission(permission)!=PackageManager.PERMISSION_GRANTED)
                            root.rootShell("/system/bin/pm grant "+activity.getPackageName()+" "+permission,10000);
                    if(!receiving) {
                        IntentFilter filter=new IntentFilter(BluetoothDevice.ACTION_FOUND);
                        filter.addAction(BluetoothDevice.ACTION_NAME_CHANGED);
                        activity.getApplicationContext().registerReceiver(receiver,filter,Context.RECEIVER_EXPORTED);
                        receiving=true;
                    }
                    if(!adapter.isDiscovering() && !adapter.startDiscovery())throw new IOException("Discovery refused");
                } else if(adapter.isDiscovering()) adapter.cancelDiscovery();
                return new JSONObject().put("accepted",true);
            }
            case "pair": case "unpair": case "connect": case "disconnect":
                if(!ADDRESS.matcher(address).matches())throw new IllegalArgumentException("Invalid address");
                return helper(action+" "+address);
            case "name": {
                String name=request.getString("name");
                if(name.isEmpty() || name.length()>248 || !name.matches("[^\\p{Cntrl}]+"))throw new IllegalArgumentException("Invalid name");
                return helper("name '"+name.replace("'","'\\''")+"'");
            }
            default: throw new IllegalArgumentException("Unknown Bluetooth action");
        }
    }
}
