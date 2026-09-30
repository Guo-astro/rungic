// Firefox 156 / Rungic Android MediaCodec adapter. The private FFmpeg hybrid
// codecs accept CPU frames and use the APK, with software fallback at open.
pref("media.webrtc.encoder_creation_strategy", 1);
// Prefer the private FFmpeg video codecs. Keep the RDD sandbox enabled.
pref("media.rdd-ffvpx.enabled", false);
pref("media.prefer-non-ffvpx", false);
