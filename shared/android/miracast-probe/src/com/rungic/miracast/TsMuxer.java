// SPDX-License-Identifier: Apache-2.0
// Byte layouts follow AOSP 8.1 frameworks/av media/libstagefright/wifi-display/
// source/TSPacketizer.cpp (Apache-2.0), rewritten in Java (docs/84).
package com.rungic.miracast;

import java.io.ByteArrayOutputStream;

/**
 * MPEG-TS for Wi-Fi Display: one program with an H.264 video track (PID 0x1011)
 * and an LPCM audio track (PID 0x1100), PCR on PID 0x1000, PAT/PMT and PCR at
 * least every 100 ms. Access units are passed whole; the result is a multiple of
 * 188 bytes.
 */
final class TsMuxer {
    static final int VIDEO = 0, AUDIO = 1;
    private static final int PID_PMT = 0x100, PID_PCR = 0x1000;
    private static final int[] PID = {0x1011, 0x1100};
    private static final int[] STREAM_TYPE = {0x1b, 0x83};
    private static final int[] STREAM_ID = {0xe0, 0xbd};
    private static final int[] CRC_TABLE = new int[256];

    static {
        for (int i = 0; i < 256; i++) {
            int crc = i << 24;
            for (int j = 0; j < 8; j++) crc = (crc << 1) ^ ((crc & 0x80000000) != 0 ? 0x04C11DB7 : 0);
            CRC_TABLE[i] = crc;
        }
    }

    private final int[] continuity = new int[2];
    private int patContinuity, pmtContinuity;
    private long lastTablesUs = Long.MIN_VALUE;
    /** H.264 profile_idc, constraint flags and level_idc for the AVC video descriptor. */
    private final byte[] avcProfile = {0x42, (byte) 0xc0, 0x1f};
    private final boolean audio;

    TsMuxer(boolean audio) {
        this.audio = audio;
    }

    /** From the SPS (after its start code): profile_idc, constraint flags, level_idc. */
    synchronized void setSps(byte[] sps, int offset) {
        avcProfile[0] = sps[offset + 1];
        avcProfile[1] = sps[offset + 2];
        avcProfile[2] = sps[offset + 3];
    }

    /**
     * One access unit as TS packets. {@code ptsUs} is on the same clock as
     * {@code nowUs}, which stamps the PCR.
     */
    synchronized byte[] packetize(int track, byte[] au, int offset, int length, long ptsUs, long nowUs) {
        ByteArrayOutputStream out = new ByteArrayOutputStream(length + length / 184 * 4 + 188 * 4);
        if (lastTablesUs == Long.MIN_VALUE || nowUs - lastTablesUs >= 100_000) {
            out.write(pat(), 0, 188);
            out.write(pmt(), 0, 188);
            out.write(pcr(nowUs), 0, 188);
            lastTablesUs = nowUs;
        }
        // LPCM PES headers carry two stuffing bytes (AOSP MediaSender).
        int stuffing = track == AUDIO ? 2 : 0;
        long pesLength = length + 8 + stuffing;
        if (pesLength >= 65536) pesLength = 0; // allowed for video
        long pts = ptsUs * 9 / 100;
        byte[] packet = new byte[188];
        int copied = 0;
        boolean first = true;
        while (copied < length || first) {
            int header = first ? 14 + stuffing : 0;
            int room = 184 - header;
            int copy = Math.min(room, length - copied);
            int padding = room - copy;
            int p = 0;
            packet[p++] = 0x47;
            packet[p++] = (byte) ((first ? 0x40 : 0x00) | (PID[track] >> 8));
            packet[p++] = (byte) PID[track];
            packet[p++] = (byte) ((padding > 0 ? 0x30 : 0x10) | nextContinuity(track));
            if (padding > 0) {
                packet[p++] = (byte) (padding - 1);
                if (padding >= 2) {
                    packet[p++] = 0x00;
                    for (int i = 0; i < padding - 2; i++) packet[p++] = (byte) 0xff;
                }
            }
            if (first) {
                packet[p++] = 0x00;
                packet[p++] = 0x00;
                packet[p++] = 0x01;
                packet[p++] = (byte) STREAM_ID[track];
                packet[p++] = (byte) (pesLength >> 8);
                packet[p++] = (byte) pesLength;
                packet[p++] = (byte) 0x84; // data_alignment_indicator
                packet[p++] = (byte) 0x80; // PTS only
                packet[p++] = (byte) (0x05 + stuffing);
                packet[p++] = (byte) (0x20 | (((pts >> 30) & 7) << 1) | 1);
                packet[p++] = (byte) (pts >> 22);
                packet[p++] = (byte) ((((pts >> 15) & 0x7f) << 1) | 1);
                packet[p++] = (byte) (pts >> 7);
                packet[p++] = (byte) (((pts & 0x7f) << 1) | 1);
                for (int i = 0; i < stuffing; i++) packet[p++] = (byte) 0xff;
            }
            System.arraycopy(au, offset + copied, packet, p, copy);
            copied += copy;
            out.write(packet, 0, 188);
            first = false;
        }
        return out.toByteArray();
    }

    private int nextContinuity(int track) {
        int value = continuity[track];
        continuity[track] = (value + 1) & 0x0f;
        return value;
    }

    private byte[] pat() {
        byte[] p = new byte[188];
        java.util.Arrays.fill(p, (byte) 0xff);
        patContinuity = (patContinuity + 1) & 0x0f;
        int i = 0;
        p[i++] = 0x47; p[i++] = 0x40; p[i++] = 0x00; p[i++] = (byte) (0x10 | patContinuity); p[i++] = 0x00;
        int start = i;
        p[i++] = 0x00; p[i++] = (byte) 0xb0; p[i++] = 0x0d; p[i++] = 0x00; p[i++] = 0x00; p[i++] = (byte) 0xc3;
        p[i++] = 0x00; p[i++] = 0x00; p[i++] = 0x00; p[i++] = 0x01;
        p[i++] = (byte) (0xe0 | (PID_PMT >> 8)); p[i++] = (byte) PID_PMT;
        putCrc(p, start, i);
        return p;
    }

    private byte[] pmt() {
        byte[] p = new byte[188];
        java.util.Arrays.fill(p, (byte) 0xff);
        pmtContinuity = (pmtContinuity + 1) & 0x0f;
        int i = 0;
        p[i++] = 0x47; p[i++] = (byte) (0x40 | (PID_PMT >> 8)); p[i++] = (byte) PID_PMT;
        p[i++] = (byte) (0x10 | pmtContinuity); p[i++] = 0x00;
        int start = i;
        p[i++] = 0x02; p[i++] = 0x00; p[i++] = 0x00; // section_length below
        p[i++] = 0x00; p[i++] = 0x01; p[i++] = (byte) 0xc3; p[i++] = 0x00; p[i++] = 0x00;
        p[i++] = (byte) (0xe0 | (PID_PCR >> 8)); p[i++] = (byte) PID_PCR;
        p[i++] = (byte) 0xf0; p[i++] = 0x00; // no program descriptors
        // Video: AVC video descriptor (40) and AVC timing and HRD descriptor (42).
        p[i++] = (byte) STREAM_TYPE[VIDEO];
        p[i++] = (byte) (0xe0 | (PID[VIDEO] >> 8)); p[i++] = (byte) PID[VIDEO];
        p[i++] = (byte) 0xf0; p[i++] = 10;
        p[i++] = 40; p[i++] = 4; p[i++] = avcProfile[0]; p[i++] = avcProfile[1]; p[i++] = avcProfile[2]; p[i++] = 0x3f;
        p[i++] = 42; p[i++] = 2; p[i++] = 0x7e; p[i++] = 0x1f;
        if (audio) {
            // LPCM: 48 kHz, stereo (descriptor 0x83).
            p[i++] = (byte) STREAM_TYPE[AUDIO];
            p[i++] = (byte) (0xe0 | (PID[AUDIO] >> 8)); p[i++] = (byte) PID[AUDIO];
            p[i++] = (byte) 0xf0; p[i++] = 4;
            p[i++] = (byte) 0x83; p[i++] = 2; p[i++] = (byte) ((2 << 5) | (3 << 1)); p[i++] = (byte) ((1 << 5) | 0x0f);
        }
        int sectionLength = i - (start + 3) + 4;
        p[start + 1] = (byte) (0xb0 | (sectionLength >> 8));
        p[start + 2] = (byte) sectionLength;
        putCrc(p, start, i);
        return p;
    }

    private static byte[] pcr(long nowUs) {
        byte[] p = new byte[188];
        java.util.Arrays.fill(p, (byte) 0xff);
        long pcr = nowUs * 27;
        long base = pcr / 300;
        int ext = (int) (pcr % 300);
        int i = 0;
        p[i++] = 0x47; p[i++] = (byte) (0x40 | (PID_PCR >> 8)); p[i++] = (byte) PID_PCR;
        p[i++] = 0x20; // adaptation field only
        p[i++] = (byte) 0xb7; p[i++] = 0x10;
        p[i++] = (byte) (base >> 25); p[i++] = (byte) (base >> 17); p[i++] = (byte) (base >> 9);
        p[i++] = (byte) (((base & 1) << 7) | 0x7e | ((ext >> 8) & 1));
        p[i++] = (byte) ext;
        return p;
    }

    private static void putCrc(byte[] p, int start, int end) {
        int crc = 0xffffffff;
        for (int i = start; i < end; i++) crc = (crc << 8) ^ CRC_TABLE[((crc >>> 24) ^ p[i]) & 0xff];
        p[end] = (byte) (crc >>> 24);
        p[end + 1] = (byte) (crc >>> 16);
        p[end + 2] = (byte) (crc >>> 8);
        p[end + 3] = (byte) crc;
    }
}
