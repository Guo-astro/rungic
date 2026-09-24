// PP-OCR text detection and recognition on LiteRT (docs/64).
//
// The detector (DB) and the recognizers (CTC head) run as LiteRT CompiledModels, on the Adreno GPU
// (OpenCL) when it is available. The models have static shapes, as the GPU delegate requires:
//
//   det.tflite         [1,3,S,S] -> [1,1,S,S]  text probability; a larger image is read in
//                      overlapping tiles whose maps are merged before any box is taken;
//   rec_<W>.tflite     [1,3,48,W] -> [1,W/8,C] class probabilities, one model per width;
//   classes.txt        the C CTC classes, one per line (line 0, the blank, is ignored).
//
// Pre- and post-processing follow PaddleOCR: BGR planes, ImageNet mean/std for the detector and
// (v-127.5)/127.5 for the recognizer; the probability map thresholded, connected components as
// axis-aligned boxes (screen text is horizontal) grown by the DB unclip ratio; each box cropped from
// the full-resolution image at height 48; greedy CTC decoding.
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace ppocr {

struct Line {
  std::string text;      // UTF-8
  float score;           // mean character probability
  float x1, y1, x2, y2;  // in the input image's pixels
};

struct Timing {
  double prepare_ms = 0, det_ms = 0, boxes_ms = 0, rec_ms = 0, total_ms = 0;
  int tiles = 0, boxes = 0;
};

struct Options {
  std::string model_dir;  // det.tflite, rec_<W>.tflite, classes.txt
  std::string lib_dir;    // libLiteRtClGlAccelerator.so
  std::string cache_dir;  // compiled GPU programs, kept between runs
  bool det_gpu = true, rec_gpu = true;
  bool fp32 = true;  // GPU arithmetic in fp32: PP-OCRv6 matches its reference only so
};

class Engine {
 public:
  static std::unique_ptr<Engine> Create(const Options& options, std::string* error);
  ~Engine();

  // `rgb` is width*height*3 bytes, rows packed. The detector reads the image scaled by `det_scale`
  // (a detector reads text 10-40 px high best: about 1.5 image pixels per screen point);
  // recognition crops come from the full-resolution image.
  bool Recognize(const uint8_t* rgb, int width, int height, float det_scale, std::vector<Line>* lines,
                 Timing* timing, std::string* error);

  // Milliseconds per run of each model (inputs zeroed), for diagnosis: det first, then each rec.
  bool Probe(int runs, std::vector<double>* ms, std::string* error);
  std::string Describe() const;

  struct Net;
  struct Impl;

 private:
  explicit Engine(std::unique_ptr<Impl> impl);
  std::unique_ptr<Impl> impl_;
};

}  // namespace ppocr
