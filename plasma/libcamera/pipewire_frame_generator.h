/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once
#include "frame_generator.h"
#include <gst/gst.h>
#include <string>
namespace libcamera {
struct PipeWireFrames { std::string target; };
class PipeWireFrameGenerator final : public FrameGenerator {
public:
 explicit PipeWireFrameGenerator(const std::string &target):target_(target){}
 ~PipeWireFrameGenerator() override { stop(); }
 void configure(const Size &size) override;
 int generateFrame(const Size &size,const FrameBuffer *buffer) override;
 void stop() override;
private:
 std::string target_;
 GstElement *pipeline_ = nullptr;
 GstElement *sink_ = nullptr;
};
}
