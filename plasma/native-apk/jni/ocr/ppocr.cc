// PP-OCR on LiteRT: see ppocr.h (docs/64).
#include "ppocr.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <dirent.h>
#include <fstream>
#include <sstream>

#include "litert/c/litert_common.h"
#include "litert/c/litert_compiled_model.h"
#include "litert/c/litert_environment.h"
#include "litert/c/litert_model.h"
#include "litert/c/litert_opaque_options.h"
#include "litert/c/litert_options.h"
#include "litert/c/litert_tensor_buffer.h"
#include "litert/c/litert_tensor_buffer_requirements.h"

namespace ppocr {
namespace {

using Clock = std::chrono::steady_clock;
double Ms(Clock::time_point since) { return std::chrono::duration<double, std::milli>(Clock::now() - since).count(); }

// PP-OCRv6 DB post-processing (its model card): probability 0.2, box score 0.45, unclip 1.4.
constexpr float kBinaryThreshold = 0.2f;
constexpr float kBoxThreshold = 0.45f;
constexpr float kUnclipRatio = 1.4f;
constexpr int kMinBoxSide = 3;  // detector pixels
constexpr size_t kMaxCandidates = 3000;
constexpr int kTileOverlapDivisor = 8;  // tiles overlap by 1/8 of their side, so a line at a seam is whole in one
constexpr int kRecHeight = 48;
constexpr float kSplitWindow = 0.15f;  // a line too wide for every recognizer is cut near a gap within this share
// Detector planes are B, G, R, each with the ImageNet mean/std in this order (PaddleOCR reads BGR).
constexpr float kDetMean[3] = {0.485f, 0.456f, 0.406f};
constexpr float kDetStd[3] = {0.229f, 0.224f, 0.225f};
constexpr float kRecMean[3] = {0.5f, 0.5f, 0.5f};  // (v - 127.5) / 127.5
constexpr float kRecStd[3] = {0.5f, 0.5f, 0.5f};

bool Ok(LiteRtStatus status, const char* what, std::string* error) {
  if (status == kLiteRtStatusOk) return true;
  if (error) *error = std::string(what) + " failed (status " + std::to_string(status) + ")";
  return false;
}

// Bilinear samples of the RGB image into BGR float planes of `plane_width` columns: output pixel (x, y)
// for x < w, y < h comes from source (x0 + x*fx, y0 + y*fy); others keep their value. Each plane p is
// (v/255 - mean[p]) / std[p].
void Sample(const uint8_t* rgb, int width, int height, float x0, float y0, float fx, float fy, int w, int h,
            const float mean[3], const float std_[3], float* out, int plane_width, int plane_height) {
  const size_t plane = static_cast<size_t>(plane_width) * plane_height;
  float scale[3], bias[3];
  for (int p = 0; p < 3; ++p) {
    scale[p] = 1.0f / (255.0f * std_[p]);
    bias[p] = -mean[p] / std_[p];
  }
  for (int y = 0; y < h; ++y) {
    const float sy = std::clamp(y0 + y * fy, 0.0f, static_cast<float>(height - 1));
    const int ya = static_cast<int>(sy), yb = std::min(ya + 1, height - 1);
    const float wy = sy - ya;
    const uint8_t* ra = rgb + static_cast<size_t>(ya) * width * 3;
    const uint8_t* rb = rgb + static_cast<size_t>(yb) * width * 3;
    float* row = out + static_cast<size_t>(y) * plane_width;
    for (int x = 0; x < w; ++x) {
      const float sx = std::clamp(x0 + x * fx, 0.0f, static_cast<float>(width - 1));
      const int xa = static_cast<int>(sx), xb = std::min(xa + 1, width - 1);
      const float wx = sx - xa;
      for (int p = 0; p < 3; ++p) {
        const int c = 2 - p;  // plane 0 is blue
        const float a = ra[xa * 3 + c] + (ra[xb * 3 + c] - ra[xa * 3 + c]) * wx;
        const float b = rb[xa * 3 + c] + (rb[xb * 3 + c] - rb[xa * 3 + c]) * wx;
        row[p * plane + x] = (a + (b - a) * wy) * scale[p] + bias[p];
      }
    }
  }
}

void StoreFloats(const std::vector<float>& src, void* dst, LiteRtElementType type) {
  if (type == kLiteRtElementTypeFloat16) {
    auto* out = static_cast<__fp16*>(dst);
    for (size_t i = 0; i < src.size(); ++i) out[i] = static_cast<__fp16>(src[i]);
  } else {
    std::memcpy(dst, src.data(), src.size() * sizeof(float));
  }
}

void LoadFloats(const void* src, size_t count, LiteRtElementType type, std::vector<float>* dst) {
  dst->resize(count);
  if (type == kLiteRtElementTypeFloat16) {
    const auto* in = static_cast<const __fp16*>(src);
    for (size_t i = 0; i < count; ++i) (*dst)[i] = static_cast<float>(in[i]);
  } else {
    std::memcpy(dst->data(), src, count * sizeof(float));
  }
}

size_t Elements(const LiteRtLayout& layout) {
  size_t n = 1;
  for (unsigned i = 0; i < layout.rank; ++i) n *= static_cast<size_t>(std::max(layout.dimensions[i], 1));
  return n;
}

// A class's value as a probability. PP-OCRv6 ends in softmax; other exports end in logits.
float Probability(const float* row, int classes, int index) {
  double sum = 0;
  for (int i = 0; i < classes; ++i) sum += row[i];
  if (std::fabs(sum - 1.0) < 0.02 && row[index] >= 0) return row[index];
  const float top = row[index];
  double denominator = 0;
  for (int i = 0; i < classes; ++i) denominator += std::exp(static_cast<double>(row[i] - top));
  return static_cast<float>(1.0 / denominator);
}

struct Box {
  int x1, y1, x2, y2;  // inclusive, detector pixels
  float score;
};

// Connected components (4-neighbour) of the thresholded map, as boxes with their mean probability.
std::vector<Box> Components(const std::vector<float>& prob, int w, int h) {
  std::vector<uint8_t> seen(prob.size(), 0);
  std::vector<int> stack;
  std::vector<Box> boxes;
  for (int start = 0; start < w * h && boxes.size() < kMaxCandidates; ++start) {
    if (seen[start] || prob[start] <= kBinaryThreshold) continue;
    Box box{start % w, start / w, start % w, start / w, 0};
    double sum = 0;
    int count = 0;
    stack.assign(1, start);
    seen[start] = 1;
    while (!stack.empty()) {
      const int p = stack.back();
      stack.pop_back();
      const int x = p % w, y = p / w;
      sum += prob[p];
      ++count;
      box.x1 = std::min(box.x1, x);
      box.x2 = std::max(box.x2, x);
      box.y1 = std::min(box.y1, y);
      box.y2 = std::max(box.y2, y);
      const int next[4] = {x > 0 ? p - 1 : -1, x + 1 < w ? p + 1 : -1, y > 0 ? p - w : -1, y + 1 < h ? p + w : -1};
      for (int q : next) {
        if (q >= 0 && !seen[q] && prob[q] > kBinaryThreshold) {
          seen[q] = 1;
          stack.push_back(q);
        }
      }
    }
    box.score = static_cast<float>(sum / count);
    if (box.x2 - box.x1 + 1 >= kMinBoxSide && box.y2 - box.y1 + 1 >= kMinBoxSide && box.score >= kBoxThreshold) {
      boxes.push_back(box);
    }
  }
  return boxes;
}

// Tile origins along one side: one tile if it fits, else evenly spaced tiles overlapping by side/8.
std::vector<int> TileOrigins(int length, int tile) {
  if (length <= tile) return {0};
  const int overlap = tile / kTileOverlapDivisor;
  const int n = (length - overlap + (tile - overlap) - 1) / (tile - overlap);
  std::vector<int> out;
  for (int i = 0; i < n; ++i) out.push_back(static_cast<int>(std::lround(static_cast<double>(i) * (length - tile) / (n - 1))));
  return out;
}

// Where to cut a line crop [x1, x2) near `target`: the column with the least ink (luminance away
// from the crop's edge colour), which is usually a gap between characters.
float Cut(const uint8_t* rgb, int width, float x1, float x2, float y1, float y2, float target) {
  const int ya = static_cast<int>(y1), yb = std::max(ya + 1, static_cast<int>(y2));
  const int left = std::max(static_cast<int>(x1), static_cast<int>(target - kSplitWindow * (x2 - x1)));
  const int right = std::min(static_cast<int>(x2) - 1, static_cast<int>(target + kSplitWindow * (x2 - x1)));
  auto luma = [&](int x, int y) {
    const uint8_t* p = rgb + (static_cast<size_t>(y) * width + x) * 3;
    return 0.299f * p[0] + 0.587f * p[1] + 0.114f * p[2];
  };
  float background = 0;
  for (int y = ya; y < yb; ++y) background += luma(static_cast<int>(x1), y);
  background /= (yb - ya);
  float best = target, least = 1e30f;
  for (int x = left; x <= right; ++x) {
    float ink = 0;
    for (int y = ya; y < yb; ++y) ink += std::fabs(luma(x, y) - background);
    if (ink < least) {
      least = ink;
      best = static_cast<float>(x);
    }
  }
  return best;
}

}  // namespace

// One compiled model with host-visible input and output buffers.
struct Engine::Net {
  LiteRtEnvironment env = nullptr;
  LiteRtModel model = nullptr;
  LiteRtCompiledModel compiled = nullptr;
  LiteRtRankedTensorType in_type{}, out_type{};
  LiteRtTensorBuffer in_buf = nullptr, out_buf = nullptr;
  bool accelerated = false;
  std::string name;

  ~Net() {
    if (in_buf) LiteRtDestroyTensorBuffer(in_buf);
    if (out_buf) LiteRtDestroyTensorBuffer(out_buf);
    if (compiled) LiteRtDestroyCompiledModel(compiled);
    if (model) LiteRtDestroyModel(model);
  }

  int in_dim(int i) const { return in_type.layout.dimensions[i]; }
  int out_dim(int i) const { return out_type.layout.dimensions[i]; }

  // Accelerator settings travel as TOML in opaque options (litert/c/options/litert_{gpu,cpu}_options.cc,
  // whose builders libLiteRt.so does not export).
  static bool AddOpaque(LiteRtOptions options, const char* identifier, const std::string& toml, std::string* error) {
    char* payload = new char[toml.size() + 1];
    std::memcpy(payload, toml.c_str(), toml.size() + 1);
    LiteRtOpaqueOptions opaque;
    if (!Ok(LiteRtCreateOpaqueOptions(identifier, payload, [](void* p) { delete[] static_cast<char*>(p); }, &opaque),
            identifier, error)) {
      return false;
    }
    return Ok(LiteRtAddOpaqueOptions(options, opaque), identifier, error);
  }

  bool Load(LiteRtEnvironment environment, const std::string& path, const std::string& key, bool gpu,
            const Options& o, std::string* error) {
    env = environment;
    name = key;
    if (!Ok(LiteRtCreateModelFromFile(env, path.c_str(), &model), path.c_str(), error)) return false;
    LiteRtSignature signature;
    LiteRtTensor input, output;
    if (!Ok(LiteRtGetModelSignature(model, 0, &signature), "signature", error) ||
        !Ok(LiteRtGetSignatureInputTensorByIndex(signature, 0, &input), "input tensor", error) ||
        !Ok(LiteRtGetSignatureOutputTensorByIndex(signature, 0, &output), "output tensor", error) ||
        !Ok(LiteRtGetRankedTensorType(input, &in_type), "input type", error) ||
        !Ok(LiteRtGetRankedTensorType(output, &out_type), "output type", error)) {
      return false;
    }
    LiteRtOptions options;
    if (!Ok(LiteRtCreateOptions(&options), "options", error)) return false;
    LiteRtSetOptionsHardwareAccelerators(options, gpu ? kLiteRtHwAcceleratorGpu : kLiteRtHwAcceleratorCpu);
    // GPU: arithmetic precision (1 fp16, 2 fp32), and compiled programs kept under `key`, which saves
    // seconds of shader compilation on every later start. CPU: XNNPACK on the four big cores.
    std::string toml = gpu ? "precision = " + std::string(o.fp32 ? "2" : "1") + "\n" : "num_threads = 4\n";
    if (gpu && !o.cache_dir.empty()) {
      toml += "serialization_dir = \"" + o.cache_dir + "\"\nmodel_cache_key = \"" + key +
              (o.fp32 ? "_fp32" : "_fp16") + "\"\nserialize_program_cache = true\n";
    }
    bool ok = AddOpaque(options, gpu ? "gpu_options" : "xnnpack", toml, error) &&
              Ok(LiteRtCreateCompiledModel(env, model, options, &compiled), "compile", error);
    LiteRtDestroyOptions(options);
    if (!ok) return false;
    LiteRtCompiledModelIsFullyAccelerated(compiled, &accelerated);
    LiteRtTensorBufferRequirements in_req, out_req;
    return Ok(LiteRtGetCompiledModelInputBufferRequirements(compiled, 0, 0, &in_req), "input requirements", error) &&
           Ok(LiteRtGetCompiledModelOutputBufferRequirements(compiled, 0, 0, &out_req), "output requirements", error) &&
           Ok(LiteRtCreateManagedTensorBufferFromRequirements(env, &in_type, in_req, &in_buf), "input buffer", error) &&
           Ok(LiteRtCreateManagedTensorBufferFromRequirements(env, &out_type, out_req, &out_buf), "output buffer", error);
  }

  bool Run(const std::vector<float>& input, std::vector<float>* output, std::string* error) {
    void* host;
    if (!Ok(LiteRtLockTensorBuffer(in_buf, &host, kLiteRtTensorBufferLockModeWrite), "lock input", error)) return false;
    StoreFloats(input, host, in_type.element_type);
    LiteRtUnlockTensorBuffer(in_buf);
    if (!Ok(LiteRtRunCompiledModel(compiled, 0, 1, &in_buf, 1, &out_buf), "run", error)) return false;
    if (!Ok(LiteRtLockTensorBuffer(out_buf, &host, kLiteRtTensorBufferLockModeRead), "lock output", error)) return false;
    LoadFloats(host, Elements(out_type.layout), out_type.element_type, output);
    LiteRtUnlockTensorBuffer(out_buf);
    return true;
  }

  std::string Describe() const {
    std::ostringstream s;
    s << name << " [";
    for (unsigned i = 0; i < in_type.layout.rank; ++i) s << (i ? "," : "") << in_dim(i);
    s << "]->[";
    for (unsigned i = 0; i < out_type.layout.rank; ++i) s << (i ? "," : "") << out_dim(i);
    s << "]" << (accelerated ? "" : " (partly on CPU)");
    return s.str();
  }
};

struct Engine::Impl {
  Options options;
  LiteRtEnvironment env = nullptr;
  std::unique_ptr<Net> det;
  std::vector<std::unique_ptr<Net>> rec;  // by input width, narrowest first
  std::vector<std::string> classes;
  std::vector<float> input, output, prob;

  ~Impl() {
    det.reset();
    rec.clear();
    if (env) LiteRtDestroyEnvironment(env);
  }

  // Recognize one crop region with the narrowest recognizer it fits; returns text and summed probability.
  bool Read(const uint8_t* rgb, int width, int height, float x1, float y1, float x2, float y2, std::string* text,
            double* score, int* kept, std::string* error) {
    const float cw = x2 - x1, ch = y2 - y1;
    const int natural = std::max(1, static_cast<int>(std::ceil(kRecHeight * cw / ch)));
    Net* net = rec.back().get();
    for (auto& candidate : rec) {
      if (candidate->in_dim(3) >= natural) {
        net = candidate.get();
        break;
      }
    }
    const int rec_width = net->in_dim(3), rw = std::min(natural, rec_width);
    input.assign(static_cast<size_t>(3) * kRecHeight * rec_width, 0.0f);  // right padding: normalized zero
    Sample(rgb, width, height, x1 + 0.5f * cw / rw - 0.5f, y1 + 0.5f * ch / kRecHeight - 0.5f, cw / rw,
           ch / kRecHeight, rw, kRecHeight, kRecMean, kRecStd, input.data(), rec_width, kRecHeight);
    if (!net->Run(input, &output, error)) return false;
    const int steps = net->out_dim(1), count = net->out_dim(2);
    if (count != static_cast<int>(classes.size())) {
      if (error) *error = net->name + " has " + std::to_string(count) + " classes, classes.txt " + std::to_string(classes.size());
      return false;
    }
    int previous = 0;
    for (int s = 0; s < steps; ++s) {
      const float* row = output.data() + static_cast<size_t>(s) * count;
      const int best = static_cast<int>(std::max_element(row, row + count) - row);
      if (best != 0 && best != previous) {
        *text += classes[best];
        *score += Probability(row, count, best);
        ++*kept;
      }
      previous = best;
    }
    return true;
  }
};

Engine::Engine(std::unique_ptr<Impl> impl) : impl_(std::move(impl)) {}
Engine::~Engine() = default;

std::unique_ptr<Engine> Engine::Create(const Options& o, std::string* error) {
  auto impl = std::make_unique<Impl>();
  impl->options = o;
  std::vector<LiteRtEnvOption> env_options;
  LiteRtEnvOption option{};
  option.tag = kLiteRtEnvOptionTagRuntimeLibraryDir;
  option.value.type = kLiteRtAnyTypeString;
  option.value.str_value = impl->options.lib_dir.c_str();
  env_options.push_back(option);
  if (!Ok(LiteRtCreateEnvironment(static_cast<int>(env_options.size()), env_options.data(), &impl->env), "environment",
          error)) {
    return nullptr;
  }
  impl->det = std::make_unique<Net>();
  if (!impl->det->Load(impl->env, o.model_dir + "/det.tflite", "det", o.det_gpu, impl->options, error)) return nullptr;
  std::vector<int> widths;
  if (DIR* dir = opendir(o.model_dir.c_str())) {
    while (dirent* entry = readdir(dir)) {
      int w = 0;
      if (std::sscanf(entry->d_name, "rec_%d.tflite", &w) == 1 && w > 0) widths.push_back(w);
    }
    closedir(dir);
  }
  std::sort(widths.begin(), widths.end());
  for (int w : widths) {
    auto net = std::make_unique<Net>();
    const std::string key = "rec_" + std::to_string(w);
    if (!net->Load(impl->env, o.model_dir + "/" + key + ".tflite", key, o.rec_gpu, impl->options, error)) return nullptr;
    impl->rec.push_back(std::move(net));
  }
  if (impl->rec.empty()) {
    if (error) *error = "no rec_<width>.tflite in " + o.model_dir;
    return nullptr;
  }
  std::ifstream file(o.model_dir + "/classes.txt");
  for (std::string line; std::getline(file, line);) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    impl->classes.push_back(impl->classes.empty() ? std::string() : line);
  }
  if (impl->classes.size() < 3) {
    if (error) *error = "classes.txt is missing or empty";
    return nullptr;
  }
  return std::unique_ptr<Engine>(new Engine(std::move(impl)));
}

std::string Engine::Describe() const {
  std::string s = impl_->det->Describe();
  for (const auto& net : impl_->rec) s += "; " + net->Describe();
  return s + "; " + std::to_string(impl_->classes.size()) + " classes, " + (impl_->options.fp32 ? "fp32" : "fp16");
}

bool Engine::Probe(int runs, std::vector<double>* ms, std::string* error) {
  Impl& m = *impl_;
  ms->clear();
  std::vector<Net*> nets{m.det.get()};
  for (auto& net : m.rec) nets.push_back(net.get());
  for (Net* net : nets) {
    m.input.assign(Elements(net->in_type.layout), 0.0f);
    if (!net->Run(m.input, &m.output, error)) return false;  // warm-up
    const auto started = Clock::now();
    for (int i = 0; i < runs; ++i) {
      if (!net->Run(m.input, &m.output, error)) return false;
    }
    ms->push_back(Ms(started) / runs);
  }
  return true;
}

bool Engine::Recognize(const uint8_t* rgb, int width, int height, float det_scale, std::vector<Line>* lines,
                       Timing* timing, std::string* error) {
  Impl& m = *impl_;
  Timing t;
  const auto started = Clock::now();
  lines->clear();
  if (det_scale <= 0) det_scale = std::min(1.0f, 1280.0f / std::max(width, height));

  // Detection: the scaled image in tiles of the detector's size, their maps merged by maximum.
  const int dw = std::max(1, static_cast<int>(std::lround(width * det_scale)));
  const int dh = std::max(1, static_cast<int>(std::lround(height * det_scale)));
  const int th = m.det->in_dim(2), tw = m.det->in_dim(3);
  m.prob.assign(static_cast<size_t>(dw) * dh, 0.0f);
  const float step = 1.0f / det_scale;
  for (int ty : TileOrigins(dh, th)) {
    for (int tx : TileOrigins(dw, tw)) {
      auto phase = Clock::now();
      const int vw = std::min(tw, dw - tx), vh = std::min(th, dh - ty);
      m.input.assign(static_cast<size_t>(3) * tw * th, 0.0f);
      Sample(rgb, width, height, (tx + 0.5f) * step - 0.5f, (ty + 0.5f) * step - 0.5f, step, step, vw, vh, kDetMean,
             kDetStd, m.input.data(), tw, th);
      t.prepare_ms += Ms(phase);
      phase = Clock::now();
      if (!m.det->Run(m.input, &m.output, error)) return false;
      t.det_ms += Ms(phase);
      for (int y = 0; y < vh; ++y) {
        const float* src = m.output.data() + static_cast<size_t>(y) * tw;
        float* dst = m.prob.data() + static_cast<size_t>(ty + y) * dw + tx;
        for (int x = 0; x < vw; ++x) dst[x] = std::max(dst[x], src[x]);
      }
      ++t.tiles;
    }
  }

  auto phase = Clock::now();
  const std::vector<Box> boxes = Components(m.prob, dw, dh);
  t.boxes = static_cast<int>(boxes.size());
  t.boxes_ms = Ms(phase);

  phase = Clock::now();
  const int widest = m.rec.back()->in_dim(3);
  for (const Box& b : boxes) {
    const float w = b.x2 - b.x1 + 1.0f, h = b.y2 - b.y1 + 1.0f;
    const float d = w * h * kUnclipRatio / (2.0f * (w + h));  // DB unclip of a rectangle
    const float x1 = std::max(0.0f, (b.x1 - d) * step), y1 = std::max(0.0f, (b.y1 - d) * step);
    const float x2 = std::min(static_cast<float>(width), (b.x2 + 1 + d) * step);
    const float y2 = std::min(static_cast<float>(height), (b.y2 + 1 + d) * step);
    if (x2 - x1 < 2 || y2 - y1 < 2) continue;
    // A line wider than the widest recognizer is read in pieces cut at gaps, never squeezed.
    const float natural = kRecHeight * (x2 - x1) / (y2 - y1);
    const int pieces = std::max(1, static_cast<int>(std::ceil(natural / widest)));
    std::string text;
    double score = 0;
    int kept = 0;
    float left = x1;
    for (int i = 1; i <= pieces; ++i) {
      const float right = i == pieces ? x2 : Cut(rgb, width, x1, x2, y1, y2, x1 + (x2 - x1) * i / pieces);
      if (right - left >= 2 && !m.Read(rgb, width, height, left, y1, right, y2, &text, &score, &kept, error)) return false;
      left = right;
    }
    if (kept > 0) lines->push_back({text, static_cast<float>(score / kept), x1, y1, x2, y2});
  }
  t.rec_ms = Ms(phase);
  t.total_ms = Ms(started);
  std::sort(lines->begin(), lines->end(), [](const Line& a, const Line& b) { return a.y1 != b.y1 ? a.y1 < b.y1 : a.x1 < b.x1; });
  if (timing) *timing = t;
  return true;
}

}  // namespace ppocr
