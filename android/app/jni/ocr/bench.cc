// Stand-alone check of the OCR engine on the phone (docs/64):
//   ocr-bench MODEL_DIR LIB_DIR IMAGE.rgb WIDTH HEIGHT [DET_SCALE] [gpu|cpu|mixed] [fp32|fp16] [RUNS]
// IMAGE.rgb holds WIDTH*HEIGHT*3 bytes. mixed: detector on the GPU, recognizers on the CPU.
// Prints each model's time per run, the pipeline's timings and the lines read.
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <vector>

#include "ppocr.h"

int main(int argc, char** argv) {
  if (argc < 6) {
    std::fprintf(stderr, "usage: %s MODEL_DIR LIB_DIR IMAGE.rgb WIDTH HEIGHT [DET_SCALE] [gpu|cpu|mixed] [fp32|fp16] [RUNS]\n",
                 argv[0]);
    return 2;
  }
  const int width = std::atoi(argv[4]), height = std::atoi(argv[5]);
  const float det_scale = argc > 6 ? std::atof(argv[6]) : 0.5f;
  const char* mode = argc > 7 ? argv[7] : "gpu";
  ppocr::Options options;
  options.model_dir = argv[1];
  options.lib_dir = argv[2];
  options.cache_dir = std::string(argv[1]) + "/cache";
  options.det_gpu = std::strcmp(mode, "cpu") != 0;
  options.rec_gpu = std::strcmp(mode, "gpu") == 0;
  options.fp32 = !(argc > 8 && std::strcmp(argv[8], "fp16") == 0);
  const int runs = argc > 9 ? std::atoi(argv[9]) : 3;
  std::ifstream in(argv[3], std::ios::binary);
  std::vector<uint8_t> rgb((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
  if (rgb.size() != static_cast<size_t>(width) * height * 3) {
    std::fprintf(stderr, "image has %zu bytes, expected %d\n", rgb.size(), width * height * 3);
    return 2;
  }
  std::string error;
  const auto t0 = std::chrono::steady_clock::now();
  auto engine = ppocr::Engine::Create(options, &error);
  if (!engine) {
    std::fprintf(stderr, "create: %s\n", error.c_str());
    return 1;
  }
  std::printf("create %.0f ms: %s\n",
              std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count(),
              engine->Describe().c_str());
  std::vector<double> ms;
  if (engine->Probe(5, &ms, &error)) {
    std::printf("probe ms per run:");
    for (double v : ms) std::printf(" %.1f", v);
    std::printf("\n");
  } else {
    std::printf("probe: %s\n", error.c_str());
  }
  std::vector<ppocr::Line> lines;
  for (int run = 0; run < runs; ++run) {
    ppocr::Timing t;
    if (!engine->Recognize(rgb.data(), width, height, det_scale, &lines, &t, &error)) {
      std::fprintf(stderr, "recognize: %s\n", error.c_str());
      return 1;
    }
    std::printf("run %d: total %.1f ms (prepare %.1f, det %.1f in %d tiles, boxes %.1f, rec %.1f; %d boxes)\n", run,
                t.total_ms, t.prepare_ms, t.det_ms, t.tiles, t.boxes_ms, t.rec_ms, t.boxes);
  }
  for (const auto& l : lines) {
    std::printf("%.2f [%4.0f %4.0f %4.0f %4.0f] %s\n", l.score, l.x1, l.y1, l.x2, l.y2, l.text.c_str());
  }
  return 0;
}
