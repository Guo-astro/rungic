// SPDX-License-Identifier: MIT
package com.rungic.miracast;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.net.wifi.p2p.WifiP2pDevice;
import android.net.wifi.p2p.WifiP2pInfo;
import android.os.Looper;
import android.view.Surface;
import java.net.InetAddress;
import java.net.InetSocketAddress;

/**
 * Protocol prototype run as root through app_process (docs/84 step 1): finds a
 * sink over Wi-Fi Direct, runs the WFD source and streams a test pattern (clock,
 * frame counter, moving block) with silent LPCM. No vendor cast component is used.
 *
 *   app_process / com.rungic.miracast.MiracastProbe <sink name|address> [seconds] [listen MHz] [GO intent]
 */
public final class MiracastProbe {
    private static volatile Streamer streamer;
    private static volatile boolean ended;

    public static void main(String[] args) throws Exception {
        Log.echo = true;
        String target = args.length > 0 ? args[0] : "TCL";
        int seconds = args.length > 1 ? Integer.parseInt(args[1]) : 60;
        int listenMhz = args.length > 2 ? Integer.parseInt(args[2]) : 2437;
        int goIntent = args.length > 3 ? Integer.parseInt(args[3]) : 15;
        Looper.prepareMainLooper();
        Class<?> at = Class.forName("android.app.ActivityThread");
        Context context = (Context) at.getMethod("getSystemContext").invoke(at.getMethod("systemMain").invoke(null));
        Thread worker = new Thread(() -> {
            int code = 0;
            try {
                run(context, target, seconds, listenMhz, goIntent);
            } catch (Throwable e) {
                Log.w("probe failed", e);
                code = 1;
            }
            System.exit(code);
        }, "probe");
        worker.start();
        Looper.loop();
    }

    private static void run(Context context, String target, int seconds, int listenMhz, int goIntent) throws Exception {
        P2pLink p2p = new P2pLink(context, Looper.getMainLooper());
        RtspSource rtsp = new RtspSource(new RtspSource.Listener() {
            @Override public void onPlay(InetSocketAddress rtp, WfdFormat video, String audio) throws java.io.IOException {
                Streamer s = new Streamer(video, audio, rtp, 8_000_000);
                streamer = s;
                Thread pattern = new Thread(() -> drawPattern(s, video), "pattern");
                pattern.start();
            }
            @Override public void onIdrRequest() {
                Log.i("sink asked for an IDR frame");
                Streamer s = streamer;
                if (s != null) s.requestKeyFrame();
            }
            @Override public void onEnd(String reason) {
                ended = true;
            }
        }, InetAddress.getByName("0.0.0.0"));
        long t0 = System.currentTimeMillis();
        WifiP2pInfo info = p2p.connectionInfo();
        if (info == null || !info.groupFormed) {
            Log.i("searching for " + target + (listenMhz > 0 ? " on " + listenMhz + " MHz" : " on social channels"));
            WifiP2pDevice sink = p2p.find(target, listenMhz, 90_000);
            if (sink == null) {
                Log.i("sink not found");
                rtsp.close();
                return;
            }
            Log.i("found " + sink.deviceName + " " + sink.deviceAddress + " wfd " + sink.getWfdInfo().getDeviceType()
                + " after " + (System.currentTimeMillis() - t0) + " ms");
            info = p2p.connect(sink, goIntent, 40_000);
            if (info == null) {
                Log.i("group not formed");
                p2p.cancel();
                rtsp.close();
                return;
            }
        }
        Log.i("group formed: owner=" + info.isGroupOwner + " ownerAddress=" + info.groupOwnerAddress
            + " local=" + P2pLink.groupAddress() + " after " + (System.currentTimeMillis() - t0) + " ms");
        long end = System.currentTimeMillis() + seconds * 1000L;
        long lastBytes = 0;
        while (!ended && System.currentTimeMillis() < end) {
            Thread.sleep(5000);
            Streamer s = streamer;
            if (s != null) {
                long bytes = s.bytesSent();
                Log.i(String.format(java.util.Locale.ROOT, "streaming: %d frames (%d key), %.1f Mbit/s",
                    s.frames, s.keyFrames, (bytes - lastBytes) * 8 / 5e6));
                lastBytes = bytes;
            }
        }
        Log.i(ended ? "session ended by the sink" : "time up, tearing down");
        rtsp.teardown();
        Streamer s = streamer;
        if (s != null) s.close();
        p2p.disconnect();
        Thread.sleep(500);
        p2p.close();
    }

    private static void drawPattern(Streamer s, WfdFormat f) {
        // No text: app_process has no system fonts loaded (hwui asserts on the
        // default typeface), so the clock is drawn as seven-segment digits.
        Surface surface = s.inputSurface();
        Paint block = new Paint();
        int[] bars = {Color.WHITE, Color.YELLOW, Color.CYAN, Color.GREEN, Color.MAGENTA, Color.RED, Color.BLUE};
        long frame = 0;
        long period = 1_000_000_000L / f.fps;
        long next = System.nanoTime();
        java.text.SimpleDateFormat clock = new java.text.SimpleDateFormat("HHmmssSSS", java.util.Locale.ROOT);
        while (!ended) {
            try {
                Canvas c = surface.lockHardwareCanvas();
                c.drawColor(Color.rgb(20, 24, 32));
                int w = f.width / bars.length;
                for (int i = 0; i < bars.length; i++) {
                    block.setColor(bars[i]);
                    c.drawRect(i * w, 0, (i + 1) * w, f.height / 6f, block);
                }
                block.setColor(Color.rgb(61, 174, 233));
                float x = (frame * 8) % (f.width - f.height / 5f);
                c.drawRect(x, f.height * 0.72f, x + f.height / 5f, f.height * 0.92f, block);
                block.setColor(Color.WHITE);
                String digits = clock.format(new java.util.Date());
                float size = f.height / 5f, left = f.width * 0.06f;
                for (int i = 0; i < digits.length(); i++) {
                    if (i == 2 || i == 4 || i == 6) left += size * 0.35f;
                    drawDigit(c, block, digits.charAt(i) - '0', left, f.height * 0.25f, size);
                    left += size * 0.7f;
                }
                surface.unlockCanvasAndPost(c);
            } catch (Exception e) {
                Log.w("pattern stopped", e);
                return;
            }
            frame++;
            next += period;
            long wait = next - System.nanoTime();
            if (wait > 0) {
                try { Thread.sleep(wait / 1_000_000, (int) (wait % 1_000_000)); } catch (InterruptedException e) { return; }
            } else {
                next = System.nanoTime();
            }
        }
    }

    /** Segments a–g of 0–9. */
    private static final int[] SEGMENTS = {0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f};

    private static void drawDigit(Canvas c, Paint p, int digit, float x, float y, float h) {
        float w = h * 0.5f, t = h * 0.1f;
        int s = SEGMENTS[digit];
        if ((s & 1) != 0) c.drawRect(x, y, x + w, y + t, p);                         // a
        if ((s & 2) != 0) c.drawRect(x + w - t, y, x + w, y + h / 2, p);             // b
        if ((s & 4) != 0) c.drawRect(x + w - t, y + h / 2, x + w, y + h, p);         // c
        if ((s & 8) != 0) c.drawRect(x, y + h - t, x + w, y + h, p);                 // d
        if ((s & 16) != 0) c.drawRect(x, y + h / 2, x + t, y + h, p);                // e
        if ((s & 32) != 0) c.drawRect(x, y, x + t, y + h / 2, p);                    // f
        if ((s & 64) != 0) c.drawRect(x, y + h / 2 - t / 2, x + w, y + h / 2 + t / 2, p); // g
    }
}
