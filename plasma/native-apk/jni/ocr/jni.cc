// JNI for dev.moto.plasma.OcrBridge (docs/64): one ppocr::Engine per handle, used from one thread.
#include <jni.h>

#include <cstdint>
#include <cstdio>
#include <memory>
#include <string>
#include <vector>

#include "ppocr.h"

namespace {

std::string Str(JNIEnv* env, jstring s) {
  const char* chars = env->GetStringUTFChars(s, nullptr);
  std::string out(chars);
  env->ReleaseStringUTFChars(s, chars);
  return out;
}

void Throw(JNIEnv* env, const std::string& message) {
  env->ThrowNew(env->FindClass("java/io/IOException"), message.c_str());
}

// Java strings from NewStringUTF must be modified UTF-8; the JSON is plain ASCII escapes plus UTF-8
// text, so characters outside the BMP (emoji in the dictionary) are escaped as surrogate pairs.
std::string JsonText(const std::string& s) {
  std::string out = "\"";
  for (size_t i = 0; i < s.size();) {
    const unsigned char c = s[i];
    uint32_t cp;
    int len;
    if (c < 0x80) { cp = c; len = 1; }
    else if ((c >> 5) == 6) { cp = c & 0x1f; len = 2; }
    else if ((c >> 4) == 14) { cp = c & 0x0f; len = 3; }
    else { cp = c & 0x07; len = 4; }
    for (int k = 1; k < len && i + k < s.size(); ++k) cp = (cp << 6) | (s[i + k] & 0x3f);
    char buf[16];
    if (cp == '"' || cp == '\\') { out += '\\'; out += static_cast<char>(cp); }
    else if (cp < 0x20) { std::snprintf(buf, sizeof buf, "\\u%04x", cp); out += buf; }
    else if (cp >= 0x10000) {
      cp -= 0x10000;
      std::snprintf(buf, sizeof buf, "\\u%04x\\u%04x", 0xd800 + (cp >> 10), 0xdc00 + (cp & 0x3ff));
      out += buf;
    } else {
      out.append(s, i, len);
    }
    i += len;
  }
  return out + "\"";
}

}  // namespace

extern "C" {

JNIEXPORT jlong JNICALL Java_dev_moto_plasma_OcrBridge_nativeCreate(JNIEnv* env, jclass, jstring model_dir,
                                                                    jstring lib_dir, jstring cache_dir, jboolean fp32) {
  ppocr::Options options;
  options.model_dir = Str(env, model_dir);
  options.lib_dir = Str(env, lib_dir);
  options.cache_dir = Str(env, cache_dir);
  options.fp32 = fp32;
  std::string error;
  auto engine = ppocr::Engine::Create(options, &error);
  if (!engine) {
    Throw(env, "OCR engine: " + error);
    return 0;
  }
  return reinterpret_cast<jlong>(engine.release());
}

JNIEXPORT jstring JNICALL Java_dev_moto_plasma_OcrBridge_nativeDescribe(JNIEnv* env, jclass, jlong handle) {
  return env->NewStringUTF(reinterpret_cast<ppocr::Engine*>(handle)->Describe().c_str());
}

// `pixels` is a direct ByteBuffer of width*height*3 RGB bytes. Returns the reply's JSON object.
JNIEXPORT jstring JNICALL Java_dev_moto_plasma_OcrBridge_nativeRecognize(JNIEnv* env, jclass, jlong handle,
                                                                        jobject pixels, jint width, jint height,
                                                                        jfloat det_scale) {
  auto* engine = reinterpret_cast<ppocr::Engine*>(handle);
  const auto* rgb = static_cast<const uint8_t*>(env->GetDirectBufferAddress(pixels));
  if (rgb == nullptr || env->GetDirectBufferCapacity(pixels) < static_cast<jlong>(width) * height * 3) {
    Throw(env, "OCR: the pixel buffer is not a direct buffer of width*height*3 bytes");
    return nullptr;
  }
  std::vector<ppocr::Line> lines;
  ppocr::Timing t;
  std::string error;
  if (!engine->Recognize(rgb, width, height, det_scale, &lines, &t, &error)) {
    Throw(env, "OCR: " + error);
    return nullptr;
  }
  std::string json = "{\"lines\":[";
  char buf[160];
  for (size_t i = 0; i < lines.size(); ++i) {
    const auto& l = lines[i];
    json += i ? ",{\"text\":" : "{\"text\":";
    json += JsonText(l.text);
    std::snprintf(buf, sizeof buf, ",\"score\":%.3f,\"box\":[%.1f,%.1f,%.1f,%.1f]}", l.score, l.x1, l.y1, l.x2, l.y2);
    json += buf;
  }
  std::snprintf(buf, sizeof buf,
                "],\"ms\":{\"total\":%.1f,\"prepare\":%.1f,\"det\":%.1f,\"boxes\":%.1f,\"rec\":%.1f},\"tiles\":%d}",
                t.total_ms, t.prepare_ms, t.det_ms, t.boxes_ms, t.rec_ms, t.tiles);
  json += buf;
  return env->NewStringUTF(json.c_str());
}

JNIEXPORT void JNICALL Java_dev_moto_plasma_OcrBridge_nativeDestroy(JNIEnv*, jclass, jlong handle) {
  delete reinterpret_cast<ppocr::Engine*>(handle);
}

}  // extern "C"
