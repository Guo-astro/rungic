// SPDX-License-Identifier: MIT
package com.rungic.wifi;

import android.os.Binder;
import android.os.Bundle;
import android.os.IBinder;
import android.os.Looper;
import android.os.Parcel;
import java.lang.reflect.Method;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * Wi-Fi operations `cmd wifi` lacks, for the NetworkManager service of the Linux side (docs/73):
 *   connect <networkId>   join a saved network (IWifiManager.connect by id)
 *   disconnect            leave the current network (Android may rejoin by itself)
 * Not part of the app's own process: AndroidNetworkBridge runs it as root with app_process from the
 * APK's own file (uid 0 holds NETWORK_SETTINGS). Prints "success" or "failure <reason>".
 */
public final class RootWifi {
    private static final CountDownLatch DONE = new CountDownLatch(1);
    private static volatile String result = "failure timeout";

    public static void main(String[] args) throws Exception {
        Looper.prepareMainLooper();
        Object binder = Class.forName("android.os.ServiceManager").getMethod("getService", String.class).invoke(null, "wifi");
        Object wifi = Class.forName("android.net.wifi.IWifiManager$Stub").getMethod("asInterface", IBinder.class).invoke(null, binder);
        String command = args.length > 0 ? args[0] : "";
        if (command.equals("disconnect") && args.length == 1) {
            boolean ok = (Boolean) wifi.getClass().getMethod("disconnect", String.class).invoke(wifi, "com.android.shell");
            System.out.println(ok ? "success" : "failure refused");
            System.exit(0);
        }
        if (!command.equals("connect") || args.length != 2 || !args[1].matches("\\d{1,9}")) {
            System.out.println("failure usage: connect <networkId> | disconnect");
            System.exit(2);
        }
        // IActionListener: onSuccess() is transaction 1, onFailure(int reason) transaction 2.
        Binder listener = new Binder() {
            @Override
            protected boolean onTransact(int code, Parcel data, Parcel reply, int flags) {
                if (code == 1) {
                    result = "success";
                } else if (code == 2) {
                    data.enforceInterface("android.net.wifi.IActionListener");
                    result = "failure " + data.readInt();
                } else {
                    return false;
                }
                DONE.countDown();
                return true;
            }
        };
        Class<?> listenerType = Class.forName("android.net.wifi.IActionListener");
        Object callback = Class.forName("android.net.wifi.IActionListener$Stub").getMethod("asInterface", IBinder.class)
                .invoke(null, listener);
        Method connect = wifi.getClass().getMethod("connect", Class.forName("android.net.wifi.WifiConfiguration"), int.class,
                listenerType, String.class, Bundle.class);
        connect.invoke(wifi, null, Integer.parseInt(args[1]), callback, "com.android.shell", new Bundle());
        DONE.await(15, TimeUnit.SECONDS);
        System.out.println(result);
        System.exit(result.equals("success") ? 0 : 1);
    }
}
