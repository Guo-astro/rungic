// SPDX-License-Identifier: Apache-2.0
// wfd_video_formats layout and the CEA table follow AOSP 8.1 wifi-display
// VideoFormats.cpp (Apache-2.0).
package com.rungic.miracast;

import android.media.MediaCodecInfo;
import android.media.MediaCodecInfo.CodecProfileLevel;
import android.media.MediaCodecList;
import java.util.Locale;

/**
 * The video mode offered in M4: the best CEA mode both the sink (its M3 answer)
 * and this phone's hardware H.264 encoder (MediaCodecList) can do, at the lowest
 * level covering it. Only CEA modes and H.264 are used (a WFD R1 source).
 */
final class WfdFormat {
    /** CEA index, width, height, frame rate, WFD level bit needed (0 = 3.1 ... 4 = 4.2). */
    private static final int[][] CEA = {
        {8, 1920, 1080, 60, 4},
        {7, 1920, 1080, 30, 2},
        {6, 1280, 720, 60, 1},
        {5, 1280, 720, 30, 0},
        {0, 640, 480, 60, 0},
    };
    private static final int[] AVC_LEVELS = {CodecProfileLevel.AVCLevel31, CodecProfileLevel.AVCLevel32,
        CodecProfileLevel.AVCLevel4, CodecProfileLevel.AVCLevel41, CodecProfileLevel.AVCLevel42};

    final int ceaIndex, width, height, fps, levelBit;
    /** WFD profile bit: 0 = constrained baseline, 1 = constrained high. */
    final int profileBit;
    final String encoderName;

    private WfdFormat(int[] mode, int profileBit, String encoderName) {
        ceaIndex = mode[0];
        width = mode[1];
        height = mode[2];
        fps = mode[3];
        levelBit = mode[4];
        this.profileBit = profileBit;
        this.encoderName = encoderName;
    }

    int androidProfile() {
        return profileBit == 1 ? CodecProfileLevel.AVCProfileConstrainedHigh : CodecProfileLevel.AVCProfileConstrainedBaseline;
    }

    int androidLevel() {
        return AVC_LEVELS[levelBit];
    }

    /** The M4 value: native 00, no preferred mode, one H.264 entry. */
    String m4() {
        return String.format(Locale.ROOT, "00 00 %02x %02x %08x 00000000 00000000 00 0000 0000 00 none none",
            1 << profileBit, 1 << levelBit, 1 << ceaIndex);
    }

    @Override
    public String toString() {
        return width + "x" + height + "p" + fps + " " + (profileBit == 1 ? "CHP" : "CBP") + " level "
            + new String[] {"3.1", "3.2", "4", "4.1", "4.2"}[levelBit] + " (" + encoderName + ")";
    }

    /** Choose from the sink's wfd_video_formats value; null when nothing fits. */
    static WfdFormat choose(String sink) {
        if (sink == null || sink.trim().equals("none")) return null;
        String[] fields = sink.trim().split("\\s+");
        MediaCodecInfo.CodecCapabilities caps = null;
        String encoder = null;
        for (MediaCodecInfo info : new MediaCodecList(MediaCodecList.REGULAR_CODECS).getCodecInfos()) {
            if (!info.isEncoder() || !info.isHardwareAccelerated() || info.isAlias()) continue;
            for (String type : info.getSupportedTypes()) {
                if (type.equalsIgnoreCase("video/avc")) {
                    caps = info.getCapabilitiesForType(type);
                    encoder = info.getName();
                }
            }
            if (caps != null) break;
        }
        if (caps == null) return null;
        boolean encoderChp = false;
        int encoderLevel = 0;
        for (CodecProfileLevel pl : caps.profileLevels) {
            if (pl.profile == CodecProfileLevel.AVCProfileConstrainedHigh) encoderChp = true;
            encoderLevel = Math.max(encoderLevel, pl.level);
        }
        WfdFormat best = null;
        // fields: native, preferred, then entries of 11 fields separated by commas.
        String rest = sink.trim().substring(sink.trim().indexOf(' ', sink.trim().indexOf(' ') + 1) + 1);
        for (String entry : rest.split(",")) {
            String[] f = entry.trim().split("\\s+");
            if (f.length < 5) continue;
            int profiles = Integer.parseInt(f[0], 16);
            int levels = Integer.parseInt(f[1], 16);
            long cea = Long.parseLong(f[2], 16);
            int maxLevelBit = 31 - Integer.numberOfLeadingZeros(levels);
            int profileBit = (profiles & 2) != 0 && encoderChp ? 1 : 0;
            if ((profiles & (1 << profileBit)) == 0) continue;
            for (int[] mode : CEA) {
                if ((cea & (1L << mode[0])) == 0 || mode[4] > maxLevelBit) continue;
                if (AVC_LEVELS[mode[4]] > encoderLevel) continue;
                if (!caps.getVideoCapabilities().areSizeAndRateSupported(mode[1], mode[2], mode[3])) continue;
                WfdFormat candidate = new WfdFormat(mode, profileBit, encoder);
                if (best == null || rank(candidate) > rank(best)) best = candidate;
                break;
            }
        }
        return best;
    }

    private static long rank(WfdFormat f) {
        return (long) f.width * f.height * f.fps * 4 + f.profileBit;
    }

    /** "LPCM 00000002 00" when the sink takes 48 kHz stereo LPCM, else null. */
    static String chooseAudio(String sink) {
        if (sink == null) return null;
        for (String entry : sink.split(",")) {
            String[] f = entry.trim().split("\\s+");
            if (f.length >= 2 && f[0].equals("LPCM") && (Long.parseLong(f[1], 16) & 2) != 0) return "LPCM 00000002 00";
        }
        return null;
    }
}
