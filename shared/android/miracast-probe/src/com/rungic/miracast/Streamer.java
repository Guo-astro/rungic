// SPDX-License-Identifier: MIT
package com.rungic.miracast;

import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.os.Bundle;
import android.view.Surface;
import java.io.IOException;
import java.net.InetSocketAddress;

/**
 * The media side of a session: the hardware H.264 encoder (fed through its input
 * Surface) and, when negotiated, LPCM audio, multiplexed into MPEG-TS and sent as
 * RTP to the sink. Timestamps use the monotonic clock of the encoder's Surface
 * input; the PCR runs {@link #PCR_DELAY_US} behind it so frames arrive ahead of
 * their presentation time.
 */
final class Streamer implements AutoCloseable {
    static final long PCR_DELAY_US = 100_000;
    private final MediaCodec encoder;
    private final Surface input;
    private final TsMuxer muxer;
    private final RtpSender rtp;
    private final boolean audio;
    private volatile boolean running = true;
    private final Thread videoThread, audioThread;
    private byte[] config = new byte[0];
    long frames, keyFrames;

    Streamer(WfdFormat format, String audioCodec, InetSocketAddress sink, int bitrate) throws IOException {
        audio = audioCodec != null;
        muxer = new TsMuxer(audio);
        rtp = new RtpSender(sink);
        String dump = System.getenv("RUNGIC_MIRACAST_DUMP");
        if (dump != null) rtp.dumpTo(dump);
        MediaFormat f = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, format.width, format.height);
        f.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface);
        f.setInteger(MediaFormat.KEY_BIT_RATE, bitrate);
        f.setInteger(MediaFormat.KEY_BITRATE_MODE, MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR);
        f.setInteger(MediaFormat.KEY_FRAME_RATE, format.fps);
        f.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1);
        f.setInteger(MediaFormat.KEY_PROFILE, format.androidProfile());
        f.setInteger(MediaFormat.KEY_LEVEL, format.androidLevel());
        f.setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0);
        f.setInteger(MediaFormat.KEY_PRIORITY, 0);
        f.setInteger(MediaFormat.KEY_LATENCY, 1);
        f.setInteger(MediaFormat.KEY_PREPEND_HEADER_TO_SYNC_FRAMES, 1);
        // A still desktop produces no frames; keep the stream going for the sink.
        f.setLong(MediaFormat.KEY_REPEAT_PREVIOUS_FRAME_AFTER, 1_000_000L / format.fps * 2);
        encoder = MediaCodec.createByCodecName(format.encoderName);
        encoder.configure(f, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
        input = encoder.createInputSurface();
        encoder.start();
        Log.i("encoder " + format.encoderName + " " + encoder.getOutputFormat());
        videoThread = new Thread(this::drainVideo, "wfd-video");
        videoThread.setPriority(Thread.MAX_PRIORITY);
        videoThread.start();
        audioThread = audio ? new Thread(this::sendSilence, "wfd-audio") : null;
        if (audioThread != null) audioThread.start();
    }

    Surface inputSurface() {
        return input;
    }

    void requestKeyFrame() {
        Bundle b = new Bundle();
        b.putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0);
        try { encoder.setParameters(b); } catch (IllegalStateException ignored) { }
    }

    long bytesSent() {
        return rtp.bytesSent;
    }

    private static long nowUs() {
        return System.nanoTime() / 1000;
    }

    private void drainVideo() {
        MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        byte[] au = new byte[1 << 20];
        try {
            while (running) {
                int index = encoder.dequeueOutputBuffer(info, 100_000);
                if (index < 0) continue;
                java.nio.ByteBuffer buffer = encoder.getOutputBuffer(index);
                int length = info.size;
                if (length > 0 && buffer != null) {
                    if (au.length < config.length + length) au = new byte[config.length + length];
                    buffer.position(info.offset);
                    if ((info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) != 0) {
                        config = new byte[length];
                        buffer.get(config);
                        muxer.setSps(config, spsOffset(config));
                    } else {
                        boolean key = (info.flags & MediaCodec.BUFFER_FLAG_KEY_FRAME) != 0;
                        int offset = 0;
                        buffer.get(au, 0, length);
                        byte[] data = au;
                        int total = length;
                        if (key && !startsWithSps(au, length) && config.length > 0) {
                            data = new byte[config.length + length];
                            System.arraycopy(config, 0, data, 0, config.length);
                            System.arraycopy(au, 0, data, config.length, length);
                            total = data.length;
                        }
                        long now = nowUs();
                        rtp.send(muxer.packetize(TsMuxer.VIDEO, data, offset, total, info.presentationTimeUs,
                            now - PCR_DELAY_US), now);
                        frames++;
                        if (key) keyFrames++;
                    }
                }
                encoder.releaseOutputBuffer(index, false);
            }
        } catch (Exception e) {
            if (running) Log.w("video stream stopped", e);
        }
    }

    /** Silence as LPCM access units: 6 × 80 stereo frames (10 ms) behind a 4-byte header. */
    private void sendSilence() {
        byte[] au = new byte[4 + 6 * 80 * 4];
        au[0] = (byte) 0xa0;
        au[1] = 6;
        au[2] = 0;
        au[3] = (byte) ((0 << 6) | (2 << 3) | 1); // 16 bit, 48 kHz, stereo
        long next = nowUs();
        try {
            while (running) {
                long now = nowUs();
                if (now < next) {
                    Thread.sleep(Math.max(1, (next - now) / 1000));
                    continue;
                }
                rtp.send(muxer.packetize(TsMuxer.AUDIO, au, 0, au.length, next, now - PCR_DELAY_US), now);
                next += 10_000;
            }
        } catch (Exception e) {
            if (running) Log.w("audio stream stopped", e);
        }
    }

    private static int spsOffset(byte[] config) {
        for (int i = 0; i + 4 < config.length; i++) {
            if (config[i] == 0 && config[i + 1] == 0 && config[i + 2] == 1 && (config[i + 3] & 0x1f) == 7) return i + 3;
        }
        return 0;
    }

    private static boolean startsWithSps(byte[] au, int length) {
        for (int i = 0; i + 4 < Math.min(length, 64); i++) {
            if (au[i] == 0 && au[i + 1] == 0 && au[i + 2] == 1) return (au[i + 3] & 0x1f) == 7;
        }
        return false;
    }

    @Override
    public void close() {
        running = false;
        try { videoThread.join(500); } catch (InterruptedException ignored) { }
        if (audioThread != null) try { audioThread.join(500); } catch (InterruptedException ignored) { }
        try { encoder.stop(); } catch (Exception ignored) { }
        encoder.release();
        input.release();
        rtp.close();
    }
}
