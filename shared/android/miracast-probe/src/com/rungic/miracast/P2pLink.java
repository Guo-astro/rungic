// SPDX-License-Identifier: MIT
package com.rungic.miracast;

import android.content.Context;
import android.net.wifi.p2p.WifiP2pConfig;
import android.net.wifi.p2p.WifiP2pDevice;
import android.net.wifi.p2p.WifiP2pInfo;
import android.net.wifi.p2p.WifiP2pManager;
import android.net.wifi.WpsInfo;
import android.os.Handler;
import android.os.Looper;
import java.net.InetAddress;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Wi-Fi Direct through Android's public WifiP2pManager (docs/84). Android's own
 * WifiDisplayController already sets the source WFD IE while "wifi display" is
 * on, so peers see us as a Miracast source. Discovery stays on the social
 * channels (or the sink's known listen frequency) because TVs listen only
 * briefly after showing their waiting screen.
 */
final class P2pLink {
    private final WifiP2pManager manager;
    private final WifiP2pManager.Channel channel;
    private final Handler handler;

    P2pLink(Context context, Looper looper) {
        manager = context.getSystemService(WifiP2pManager.class);
        channel = manager.initialize(context, looper, null);
        handler = new Handler(looper);
    }

    /** Search until a sink matching {@code target} (address, name or name prefix) is seen. */
    WifiP2pDevice find(String target, int listenMhz, long timeoutMs) throws InterruptedException {
        // Stopping a search drops peers not seen in it, so what follows is fresh:
        // a peer cached from an earlier search may no longer be listening.
        call(l -> manager.cancelConnect(channel, l), "cancelConnect");
        call(l -> manager.stopPeerDiscovery(channel, l), "stopDiscovery");
        Thread.sleep(300);
        long deadline = System.currentTimeMillis() + timeoutMs;
        long restart = 0;
        while (System.currentTimeMillis() < deadline) {
            if (System.currentTimeMillis() >= restart) {
                call(l -> {
                    if (listenMhz > 0) manager.discoverPeersOnSpecificFrequency(channel, listenMhz, l);
                    else manager.discoverPeersOnSocialChannels(channel, l);
                }, "discover");
                restart = System.currentTimeMillis() + 10_000;
            }
            WifiP2pDevice found = peer(target);
            if (found != null) return found;
            Thread.sleep(300);
        }
        return null;
    }

    private WifiP2pDevice peer(String target) throws InterruptedException {
        AtomicReference<WifiP2pDevice> out = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);
        handler.post(() -> manager.requestPeers(channel, peers -> {
            for (WifiP2pDevice d : peers.getDeviceList()) {
                if (d.getWfdInfo() == null || !d.getWfdInfo().isEnabled()) continue;
                if (d.deviceAddress.equalsIgnoreCase(target) || d.deviceName.equals(target) || d.deviceName.startsWith(target)) {
                    out.set(d);
                }
            }
            done.countDown();
        }));
        done.await(2, TimeUnit.SECONDS);
        return out.get();
    }

    /** Connect (reinvoking a saved group when there is one) and wait for the group. */
    WifiP2pInfo connect(WifiP2pDevice sink, int groupOwnerIntent, long timeoutMs) throws InterruptedException {
        // Keep searching: stopping now would mark the sink lost before connecting.
        WifiP2pConfig config = new WifiP2pConfig();
        config.deviceAddress = sink.deviceAddress;
        config.wps.setup = WpsInfo.PBC;
        config.groupOwnerIntent = groupOwnerIntent;
        call(l -> manager.connect(channel, config, l), "connect");
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            WifiP2pInfo info = connectionInfo();
            if (info != null && info.groupFormed) return info;
            Thread.sleep(300);
        }
        return null;
    }

    WifiP2pInfo connectionInfo() throws InterruptedException {
        AtomicReference<WifiP2pInfo> out = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);
        handler.post(() -> manager.requestConnectionInfo(channel, info -> { out.set(info); done.countDown(); }));
        done.await(2, TimeUnit.SECONDS);
        return out.get();
    }

    /** Our address on the group's interface (p2p*), for the RTSP listener. */
    static InetAddress groupAddress() throws java.net.SocketException {
        for (java.net.NetworkInterface nif : java.util.Collections.list(java.net.NetworkInterface.getNetworkInterfaces())) {
            if (!nif.getName().startsWith("p2p") || !nif.isUp()) continue;
            for (InetAddress a : java.util.Collections.list(nif.getInetAddresses())) {
                if (a instanceof java.net.Inet4Address) return a;
            }
        }
        return null;
    }

    void cancel() {
        call(l -> manager.cancelConnect(channel, l), "cancelConnect");
    }

    void disconnect() {
        call(l -> manager.removeGroup(channel, l), "removeGroup");
    }

    void close() {
        manager.stopPeerDiscovery(channel, null);
        channel.close();
    }

    private interface Action { void run(WifiP2pManager.ActionListener l); }

    private void call(Action action, String name) {
        CountDownLatch done = new CountDownLatch(1);
        handler.post(() -> action.run(new WifiP2pManager.ActionListener() {
            @Override public void onSuccess() { done.countDown(); }
            @Override public void onFailure(int reason) { Log.i(name + " failed: " + reason); done.countDown(); }
        }));
        try { done.await(3, TimeUnit.SECONDS); } catch (InterruptedException ignored) { }
    }
}
