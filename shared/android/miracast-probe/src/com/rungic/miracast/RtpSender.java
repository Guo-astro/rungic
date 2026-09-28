// SPDX-License-Identifier: Apache-2.0
// Packetization follows AOSP 8.1 wifi-display rtp/RTPSender.cpp (Apache-2.0).
package com.rungic.miracast;

import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetSocketAddress;

/**
 * RTP over UDP carrying MPEG-TS (payload type 33): at most seven TS packets per
 * datagram (a 1328-byte payload; AOSP notes sinks break above 1472 bytes), a 90 kHz
 * timestamp taken when sent.
 */
final class RtpSender implements AutoCloseable {
    private static final int TS_PER_RTP = 7;
    private static final int SSRC = 0xdeadbeef;
    private final DatagramSocket socket;
    private final byte[] packet = new byte[12 + TS_PER_RTP * 188];
    private final DatagramPacket datagram;
    private int sequence;
    long bytesSent, packetsSent;

    RtpSender(InetSocketAddress sink) throws IOException {
        socket = new DatagramSocket();
        socket.setSendBufferSize(1 << 20);
        datagram = new DatagramPacket(packet, packet.length, sink);
    }

    int localPort() {
        return socket.getLocalPort();
    }

    /** Development aid: a copy of the TS sent (RUNGIC_MIRACAST_DUMP=<file>). */
    private java.io.OutputStream dump;

    void dumpTo(String path) throws IOException {
        dump = new java.io.BufferedOutputStream(new java.io.FileOutputStream(path));
    }

    synchronized void send(byte[] ts, long nowUs) throws IOException {
        if (dump != null) dump.write(ts);
        long rtpTime = nowUs * 9 / 100;
        for (int offset = 0; offset < ts.length; offset += TS_PER_RTP * 188) {
            int length = Math.min(TS_PER_RTP * 188, ts.length - offset);
            packet[0] = (byte) 0x80;
            packet[1] = 33;
            packet[2] = (byte) (sequence >> 8);
            packet[3] = (byte) sequence;
            sequence = (sequence + 1) & 0xffff;
            packet[4] = (byte) (rtpTime >> 24);
            packet[5] = (byte) (rtpTime >> 16);
            packet[6] = (byte) (rtpTime >> 8);
            packet[7] = (byte) rtpTime;
            packet[8] = (byte) (SSRC >> 24);
            packet[9] = (byte) (SSRC >> 16);
            packet[10] = (byte) (SSRC >> 8);
            packet[11] = (byte) SSRC;
            System.arraycopy(ts, offset, packet, 12, length);
            datagram.setLength(12 + length);
            socket.send(datagram);
            bytesSent += 12 + length;
            packetsSent++;
        }
    }

    @Override
    public void close() {
        if (dump != null) try { dump.close(); } catch (IOException ignored) { }
        socket.close();
    }
}
