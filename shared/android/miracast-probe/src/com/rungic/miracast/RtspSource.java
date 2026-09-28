// SPDX-License-Identifier: Apache-2.0
// The M1–M16 exchange follows AOSP 8.1 wifi-display source/WifiDisplaySource.cpp
// (Apache-2.0); sink quirks from GNOME Network Displays are noted where applied.
package com.rungic.miracast;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * Wi-Fi Display source RTSP (WFD R1): listens on TCP 7236 (the port our WFD IE
 * announces), and once a sink connects runs M1 → M7, answers the sink's requests
 * (M13 IDR, keep-alives, TEARDOWN) and sends an M16 keep-alive every 25 s.
 */
final class RtspSource implements AutoCloseable {
    static final int PORT = 7236;

    interface Listener {
        /** The sink sent PLAY: stream to {@code rtp} with these formats (audio may be null). */
        void onPlay(InetSocketAddress rtp, WfdFormat video, String audio) throws IOException;
        void onIdrRequest();
        /** The session ended (TEARDOWN, closed connection or an error). */
        void onEnd(String reason);
    }

    private final Listener listener;
    private final ServerSocket server;
    private volatile Socket client;
    private volatile boolean closed;
    private int nextCSeq = 1;
    private final Map<Integer, String> pending = new java.util.concurrent.ConcurrentHashMap<>();
    private WfdFormat video;
    private String audio;
    private String clientRtpPorts;
    private int rtpPort;
    private String sessionId;
    private Thread keepAlive;
    String sinkVideoFormats, sinkAudioCodecs;

    RtspSource(Listener listener, InetAddress bind) throws IOException {
        this.listener = listener;
        server = new ServerSocket();
        server.setReuseAddress(true);
        server.bind(new InetSocketAddress(bind, PORT));
        Thread accept = new Thread(this::acceptLoop, "rtsp-accept");
        accept.setDaemon(true);
        accept.start();
    }

    private void acceptLoop() {
        try {
            Socket socket = server.accept();
            server.close(); // one sink per session
            client = socket;
            socket.setTcpNoDelay(true);
            Log.i("sink connected from " + socket.getInetAddress().getHostAddress());
            // GND: some sinks are not ready for M1 right after connecting.
            Thread.sleep(500);
            sendRequest("OPTIONS * RTSP/1.0", "M1", "Require: org.wfa.wfd1.0\r\n", null);
            InputStream in = socket.getInputStream();
            while (!closed) {
                Message message = Message.read(in);
                if (message == null) break;
                Log.d("<< " + message.firstLine + (message.body.isEmpty() ? "" : " [" + message.body.trim().replace("\r\n", "; ") + "]"));
                if (message.isResponse()) onResponse(message);
                else onRequest(message);
            }
            end("connection closed");
        } catch (Exception e) {
            end(closed ? "closed" : e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    private void onResponse(Message m) throws IOException {
        String what = pending.remove(m.cseq());
        int status = m.status();
        if (what == null) return;
        if (status != 200) {
            end(what + " answered " + m.firstLine);
            return;
        }
        switch (what) {
            case "M3": {
                Map<String, String> params = parameters(m.body);
                sinkVideoFormats = params.get("wfd_video_formats");
                sinkAudioCodecs = params.get("wfd_audio_codecs");
                clientRtpPorts = params.get("wfd_client_rtp_ports");
                Log.i("sink video " + sinkVideoFormats + " | audio " + sinkAudioCodecs + " | rtp " + clientRtpPorts
                    + " | protection " + params.get("wfd_content_protection"));
                if (clientRtpPorts == null) {
                    end("sink gave no wfd_client_rtp_ports");
                    return;
                }
                String[] rtp = clientRtpPorts.trim().split("\\s+");
                rtpPort = rtp.length > 1 ? Integer.parseInt(rtp[1]) : 0;
                video = WfdFormat.choose(sinkVideoFormats);
                if (video == null) {
                    end("no video mode both sides support");
                    return;
                }
                audio = WfdFormat.chooseAudio(sinkAudioCodecs);
                Log.i("chose " + video + ", audio " + audio);
                String local = client.getLocalAddress().getHostAddress();
                StringBuilder body = new StringBuilder();
                body.append("wfd_video_formats: ").append(video.m4()).append("\r\n");
                if (audio != null) body.append("wfd_audio_codecs: ").append(audio).append("\r\n");
                body.append("wfd_presentation_URL: rtsp://").append(local).append("/wfd1.0/streamid=0 none\r\n");
                body.append("wfd_client_rtp_ports: ").append(clientRtpPorts).append("\r\n");
                sendRequest("SET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0", "M4", "", body.toString());
                break;
            }
            case "M4":
                sendRequest("SET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0", "M5", "",
                    "wfd_trigger_method: SETUP\r\n");
                break;
            default:
                break;
        }
    }

    private void onRequest(Message m) throws IOException {
        String method = m.firstLine.split(" ")[0];
        switch (method) {
            case "OPTIONS": // M2
                respond(m, "Public: org.wfa.wfd1.0, SETUP, TEARDOWN, PLAY, PAUSE, GET_PARAMETER, SET_PARAMETER\r\n");
                sendRequest("GET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0", "M3", "",
                    "wfd_video_formats\r\nwfd_audio_codecs\r\nwfd_client_rtp_ports\r\nwfd_content_protection\r\n");
                break;
            case "SETUP": { // M6
                String transport = m.header("transport");
                int clientRtp = rtpPort;
                if (transport != null) {
                    int at = transport.indexOf("client_port=");
                    if (at >= 0) {
                        String ports = transport.substring(at + 12).split("[;\\s]")[0];
                        clientRtp = Integer.parseInt(ports.split("-")[0]);
                    }
                }
                rtpPort = clientRtp;
                // GND: some sinks accept at most 15 characters.
                sessionId = String.valueOf(10000000 + (int) (Math.random() * 89999999));
                respond(m, "Session: " + sessionId + ";timeout=30\r\n"
                    + "Transport: RTP/AVP/UDP;unicast;client_port=" + clientRtp + ";server_port=" + (clientRtp + 2) + "\r\n");
                startKeepAlive();
                break;
            }
            case "PLAY": { // M7
                respond(m, "Session: " + sessionId + ";timeout=30\r\nRange: npt=now-\r\n");
                InetSocketAddress rtp = new InetSocketAddress(client.getInetAddress(), rtpPort);
                Log.i("PLAY: streaming to " + rtp);
                listener.onPlay(rtp, video, audio);
                break;
            }
            case "SET_PARAMETER":
                respond(m, "");
                if (m.body.contains("wfd_idr_request")) listener.onIdrRequest();
                break;
            case "TEARDOWN":
                respond(m, "");
                end("sink sent TEARDOWN");
                break;
            case "GET_PARAMETER":
            case "PAUSE":
            default:
                respond(m, "");
                break;
        }
    }

    private void startKeepAlive() {
        if (keepAlive != null) return;
        keepAlive = new Thread(() -> {
            try {
                while (!closed) {
                    Thread.sleep(25_000);
                    if (!closed) sendRequest("GET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0", "M16",
                        "Session: " + sessionId + "\r\n", null);
                }
            } catch (Exception ignored) {
            }
        }, "rtsp-keepalive");
        keepAlive.setDaemon(true);
        keepAlive.start();
    }

    private synchronized void sendRequest(String line, String what, String headers, String body) throws IOException {
        int cseq = nextCSeq++;
        pending.put(cseq, what);
        write(line + "\r\n" + common(cseq) + headers, body);
        Log.d(">> " + what + " " + line);
    }

    private synchronized void respond(Message m, String headers) throws IOException {
        write("RTSP/1.0 200 OK\r\n" + common(m.cseq()) + headers, null);
    }

    private static String common(int cseq) {
        return "Date: " + new java.text.SimpleDateFormat("EEE, dd MMM yyyy HH:mm:ss z", Locale.US).format(new java.util.Date())
            + "\r\nServer: Rungic/1.0\r\nCSeq: " + cseq + "\r\n";
    }

    private void write(String head, String body) throws IOException {
        StringBuilder s = new StringBuilder(head);
        if (body != null) {
            byte[] b = body.getBytes(StandardCharsets.US_ASCII);
            s.append("Content-Type: text/parameters\r\nContent-Length: ").append(b.length).append("\r\n\r\n").append(body);
        } else {
            s.append("\r\n");
        }
        OutputStream out = client.getOutputStream();
        out.write(s.toString().getBytes(StandardCharsets.US_ASCII));
        out.flush();
    }

    /** Ask the sink to tear the session down (M5 with TEARDOWN), then close. */
    void teardown() {
        try {
            if (client != null && sessionId != null) {
                sendRequest("SET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0", "M5", "",
                    "wfd_trigger_method: TEARDOWN\r\n");
                Thread.sleep(300);
            }
        } catch (Exception ignored) {
        }
        close();
    }

    private void end(String reason) {
        boolean first;
        synchronized (this) {
            first = !closed;
            closed = true;
        }
        close();
        if (first) {
            Log.i("session ended: " + reason);
            listener.onEnd(reason);
        }
    }

    @Override
    public void close() {
        closed = true;
        try { server.close(); } catch (IOException ignored) { }
        Socket c = client;
        if (c != null) try { c.close(); } catch (IOException ignored) { }
    }

    static Map<String, String> parameters(String body) {
        Map<String, String> out = new HashMap<>();
        for (String line : body.split("\r\n")) {
            int colon = line.indexOf(':');
            if (colon > 0) out.put(line.substring(0, colon).trim(), line.substring(colon + 1).trim());
        }
        return out;
    }

    static final class Message {
        String firstLine;
        final Map<String, String> headers = new HashMap<>();
        String body = "";

        boolean isResponse() { return firstLine.startsWith("RTSP/"); }
        int status() { return Integer.parseInt(firstLine.split(" ")[1]); }
        int cseq() { String v = header("cseq"); return v == null ? 0 : Integer.parseInt(v.trim()); }
        String header(String name) { return headers.get(name.toLowerCase(Locale.ROOT)); }

        static Message read(InputStream in) throws IOException {
            ByteArrayOutputStream head = new ByteArrayOutputStream();
            int matched = 0;
            while (matched < 4) {
                int b = in.read();
                if (b < 0) return null;
                head.write(b);
                matched = (b == (matched % 2 == 0 ? '\r' : '\n')) ? matched + 1 : (b == '\r' ? 1 : 0);
            }
            Message m = new Message();
            String[] lines = new String(head.toByteArray(), StandardCharsets.US_ASCII).split("\r\n");
            m.firstLine = lines[0];
            for (int i = 1; i < lines.length; i++) {
                int colon = lines[i].indexOf(':');
                if (colon > 0) m.headers.put(lines[i].substring(0, colon).trim().toLowerCase(Locale.ROOT), lines[i].substring(colon + 1).trim());
            }
            String length = m.header("content-length");
            if (length != null) {
                int n = Integer.parseInt(length.trim());
                byte[] body = new byte[n];
                int got = 0;
                while (got < n) {
                    int r = in.read(body, got, n - got);
                    if (r < 0) return null;
                    got += r;
                }
                m.body = new String(body, StandardCharsets.US_ASCII);
            }
            return m;
        }
    }
}
