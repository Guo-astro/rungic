// SPDX-License-Identifier: MIT
package com.rungic.cast;

import android.media.MediaCodecInfo;
import android.media.MediaCodecInfo.CodecProfileLevel;
import android.media.MediaCodecList;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Keeps Qualcomm's Wi-Fi Display offer within what this phone's encoder can do.
 *
 * /vendor/etc/wfdconfig.xml lists the video modes the source offers the sink, and
 * the WFD stack hands the negotiated level straight to the V4L2 encoder. The file
 * is shared across a platform: on SM6435 it offers H.264 level 5.2 at 4096x2160,
 * while the encoder stops at level 5.0 and 1080p60, so a sink taking 5.2 (the TCL
 * TV's R2 entry) ends every session with "Failed to set level" (docs/58).
 *
 * For every VideoCodecN entry this lowers the resolution to the largest standard
 * size the hardware encoder of that type reports at the entry's frame rate
 * (MediaCodecList), and the level to the lowest one covering that size, never
 * above the encoder's own maximum. Nothing is raised above the vendor's values.
 */
final class WfdConfig {
    private static final int[][] SIZES = {{4096, 2160}, {3840, 2160}, {2560, 1440}, {1920, 1080}, {1280, 720}};

    /** One codec family: wfdconfig level indexes (see the file's comment) with their limits. */
    private static final class Family {
        final String mime;
        final String[] names;
        final int[] levels;      // CodecProfileLevel constants, main tier for HEVC
        final long[] maxFrame;   // AVC: macroblocks per frame; HEVC: luma samples per picture
        final long[] maxRate;    // per second

        Family(String mime, String[] names, int[] levels, long[] maxFrame, long[] maxRate) {
            this.mime = mime;
            this.names = names;
            this.levels = levels;
            this.maxFrame = maxFrame;
            this.maxRate = maxRate;
        }

        long frame(int w, int h) {
            return mime.equals("video/avc") ? (long) ((w + 15) / 16) * ((h + 15) / 16) : (long) w * h;
        }
    }

    // H.264 Table A-1 and H.265 Table A.8, for the indexes wfdconfig.xml uses.
    private static final Family AVC = new Family("video/avc",
            new String[] {"3.1", "3.2", "4", "4.1", "4.2", "5", "5.1", "5.2"},
            new int[] {CodecProfileLevel.AVCLevel31, CodecProfileLevel.AVCLevel32, CodecProfileLevel.AVCLevel4,
                    CodecProfileLevel.AVCLevel41, CodecProfileLevel.AVCLevel42, CodecProfileLevel.AVCLevel5,
                    CodecProfileLevel.AVCLevel51, CodecProfileLevel.AVCLevel52},
            new long[] {3600, 5120, 8192, 8192, 8704, 22080, 36864, 36864},
            new long[] {108000, 216000, 245760, 245760, 522240, 589824, 983040, 2073600});
    private static final Family HEVC = new Family("video/hevc",
            new String[] {"3.1", "4", "4.1", "5", "5.1"},
            new int[] {CodecProfileLevel.HEVCMainTierLevel31, CodecProfileLevel.HEVCMainTierLevel4,
                    CodecProfileLevel.HEVCMainTierLevel41, CodecProfileLevel.HEVCMainTierLevel5,
                    CodecProfileLevel.HEVCMainTierLevel51},
            new long[] {983040, 2228224, 2228224, 8912896, 8912896},
            new long[] {33177600, 66846720, 133693440, 267386880, 534773760});

    private static final Pattern ENTRY = Pattern.compile("<(VideoCodec\\d+)>(.*?)</\\1>", Pattern.DOTALL);

    private static MediaCodecInfo[] encoderInfos;
    private static String stockXml;
    private static MediaCodecInfo[] codecs() {
        if(encoderInfos==null)encoderInfos=new MediaCodecList(MediaCodecList.ALL_CODECS).getCodecInfos();
        return encoderInfos;
    }
    private static final java.util.Map<String,MediaCodecInfo.CodecCapabilities> encoderCaps=new java.util.HashMap<>();
    private WfdConfig() {}

    /** Writes the adjusted copy of {@code vendor} to {@code out}; returns a JSON summary. */
    static String generate(File vendor, File out) throws Exception {
        return generate(vendor, out, (WfdFormats.Mode)null);
    }

    static String generate(File vendor, File out, WfdFormats.Mode mode) throws Exception {
        stockXml=null;
        String xml = new String(Files.readAllBytes(vendor.toPath()), StandardCharsets.UTF_8);
        MediaCodecInfo[] codecs = codecs();
        StringBuilder result = new StringBuilder();
        StringBuilder summary = new StringBuilder();
        boolean changed = false;
        Matcher m = ENTRY.matcher(xml);
        int last = 0;
        while (m.find()) {
            String body = m.group(2);
            String name = field(body, "CodecName");
            Family family = "H.264".equals(name) ? AVC : "H.265".equals(name) ? HEVC : null;
            String entry = family == null ? "\"unknown codec\"" : null;
            if (family == null && mode != null) throw new IllegalArgumentException("Unknown WFD codec family");
            String adjusted = body;
            if (family != null) {
                MediaCodecInfo.CodecCapabilities caps = hardwareEncoder(codecs, family.mime);
                if (caps == null) {
                    if (mode != null) throw new IllegalArgumentException("No hardware encoder for " + name);
                    entry = "\"no hardware encoder\"";
                } else {
                    int level = Integer.parseInt(field(body, "Level"));
                    int width = Integer.parseInt(field(body, "HorizontalResolution"));
                    int height = Integer.parseInt(field(body, "VerticalResolution"));
                    int fps = Integer.parseInt(field(body, "VideoFps"));
                    if (mode != null) { width = Math.min(width,mode.width); height = Math.min(height,mode.height); fps = Math.min(fps,mode.fps); }
                    int[] size = mode == null ? largestSize(caps.getVideoCapabilities(), width, height, fps)
                            : caps.getVideoCapabilities().areSizeAndRateSupported(width,height,fps) ? new int[]{width,height}
                            : largestSize(caps.getVideoCapabilities(),width,height,fps);
                    int required = size == null ? family.levels.length - 1
                            : requiredLevel(family, family.frame(size[0], size[1]), fps);
                    int newLevel = Math.min(level, Math.min(maxLevel(family, caps), required));
                    if (size == null && mode != null) throw new IllegalArgumentException("No encodable mode at requested ceiling");
                    if (size == null) size = new int[] {width, height};
                    adjusted = set(set(set(set(body, "Level", newLevel), "HorizontalResolution", size[0]),
                            "VerticalResolution", size[1]), "VideoFps", fps);
                    entry = "{\"level\":\"" + family.names[level] + "->" + family.names[newLevel] + "\",\"size\":\""
                            + width + "x" + height + "->" + size[0] + "x" + size[1] + "@" + fps + "\"}";
                }
            }
            changed |= !adjusted.equals(body);
            result.append(xml, last, m.start(2)).append(adjusted);
            last = m.end(2);
            if (summary.length() > 0) summary.append(',');
            summary.append('"').append(m.group(1)).append(' ').append(name).append("\":").append(entry);
        }
        if (last == 0) throw new IllegalArgumentException("Unsupported WFD configuration schema");
        result.append(xml.substring(last));
        Files.write(out.toPath(), result.toString().getBytes(StandardCharsets.UTF_8));
        return "{\"changed\":" + changed + ",\"entries\":{" + summary + "}}";
    }

    static int levelForMode(int codec, int profile, WfdFormats.Mode mode, int remoteLevels) throws Exception {
        File stock=new File("/data/adb/rungic-wfd/wfdconfig-stock.xml");
        if(!stock.exists())return -1;
        Family family=codec==1?AVC:HEVC;
        MediaCodecInfo.CodecCapabilities caps=hardwareEncoder(codecs(),family.mime);
        if(caps==null||!caps.getVideoCapabilities().areSizeAndRateSupported(mode.width,mode.height,mode.fps))return -1;
        if(stockXml==null)stockXml=new String(Files.readAllBytes(stock.toPath()),StandardCharsets.UTF_8);
        Matcher m=ENTRY.matcher(stockXml);
        while(m.find()) {
            String body=m.group(2);
            if(!(codec==1?"H.264":"H.265").equals(field(body,"CodecName"))||Integer.parseInt(field(body,"Profile"))!=profile)continue;
            if(mode.width>Integer.parseInt(field(body,"HorizontalResolution")) || mode.height>Integer.parseInt(field(body,"VerticalResolution"))
                    ||mode.fps>Integer.parseInt(field(body,"VideoFps")))continue;
            int max=Math.min(Integer.parseInt(field(body,"Level")),Math.min(maxLevel(family,caps),31-Integer.numberOfLeadingZeros(remoteLevels)));
            if(requiredLevel(family,family.frame(mode.width,mode.height),mode.fps)<=max)return max;
        }
        return -1;
    }

    /** The hardware (non-alias) encoder of a type with the largest supported frame. */
    private static MediaCodecInfo.CodecCapabilities hardwareEncoder(MediaCodecInfo[] codecs, String mime) {
        if(encoderCaps.containsKey(mime))return encoderCaps.get(mime);
        MediaCodecInfo.CodecCapabilities best = null;
        long bestArea = 0;
        for (MediaCodecInfo info : codecs) {
            if (!info.isEncoder() || !info.isHardwareAccelerated() || info.isAlias()) continue;
            for (String type : info.getSupportedTypes()) {
                if (!type.equalsIgnoreCase(mime)) continue;
                MediaCodecInfo.CodecCapabilities caps = info.getCapabilitiesForType(type);
                MediaCodecInfo.VideoCapabilities video = caps.getVideoCapabilities();
                long area = (long) video.getSupportedWidths().getUpper() * video.getSupportedHeights().getUpper();
                if (area > bestArea) {
                    best = caps;
                    bestArea = area;
                }
            }
        }
        encoderCaps.put(mime,best);
        return best;
    }

    /** Largest standard size not above the vendor's that the encoder does at this rate. */
    private static int[] largestSize(MediaCodecInfo.VideoCapabilities video, int width, int height, int fps) {
        for (int[] size : SIZES) {
            if (size[0] <= width && size[1] <= height && video.areSizeAndRateSupported(size[0], size[1], fps)) {
                return size;
            }
        }
        return null;
    }

    /** Highest wfdconfig index whose level the encoder reports for any profile. */
    private static int maxLevel(Family family, MediaCodecInfo.CodecCapabilities caps) {
        int reported = 0;
        for (CodecProfileLevel pl : caps.profileLevels) reported = Math.max(reported, pl.level);
        int index = 0;
        for (int i = 0; i < family.levels.length; i++) if (family.levels[i] <= reported) index = i;
        return index;
    }

    /** Lowest wfdconfig index whose limits cover this frame size and rate. */
    private static int requiredLevel(Family family, long frame, int fps) {
        for (int i = 0; i < family.levels.length; i++) {
            if (frame <= family.maxFrame[i] && frame * fps <= family.maxRate[i]) return i;
        }
        return family.levels.length;
    }

    private static String field(String body, String tag) {
        Matcher m = Pattern.compile("<" + tag + ">\\s*([^<]*?)\\s*</" + tag + ">").matcher(body);
        if (!m.find()) throw new IllegalArgumentException("wfdconfig entry without " + tag);
        return m.group(1);
    }

    private static String set(String body, String tag, int value) {
        return body.replaceFirst("<" + tag + ">[^<]*</" + tag + ">", "<" + tag + ">" + value + "</" + tag + ">");
    }
}
