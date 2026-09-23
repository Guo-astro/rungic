/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* libcamera standard camera API backed by an existing PipeWire Video/Source.
 * No Android API or camera socket access is duplicated here.
 */
#include "pipewire_frame_generator.h"
#include "libcamera/internal/mapped_framebuffer.h"
#include <libcamera/base/log.h>
#include <gst/app/gstappsink.h>
#include <gst/video/video.h>
#include <libyuv/planar_functions.h>
#include <mutex>
#include <cerrno>
namespace libcamera {
LOG_DECLARE_CATEGORY(Virtual)
void PipeWireFrameGenerator::configure(const Size &size) {
 stop();
 static std::once_flag once;
 std::call_once(once,[]{gst_init(nullptr,nullptr);});
 // Use a property setter for the node name; never interpolate YAML into a pipeline.
 const std::string graph="pipewiresrc name=source do-timestamp=true provide-clock=false "
  "! queue max-size-buffers=2 leaky=downstream ! videoconvert ! videoscale "
  "! video/x-raw,format=NV12,width="+std::to_string(size.width)+",height="+std::to_string(size.height)+
  " ! appsink name=capture sync=false max-buffers=1 drop=true";
 GError *error=nullptr;
 pipeline_=gst_parse_launch(graph.c_str(),&error);
 if(error){LOG(Virtual,Error)<<error->message;g_error_free(error);stop();return;}
 GstElement *source=gst_bin_get_by_name(GST_BIN(pipeline_),"source");
 g_object_set(source,"target-object",target_.c_str(),nullptr);
 gst_object_unref(source);
 sink_=gst_bin_get_by_name(GST_BIN(pipeline_),"capture");
 // Configuration must not activate a camera. Actual capture starts on demand.
}
int PipeWireFrameGenerator::generateFrame(const Size &size,const FrameBuffer *buffer) {
 if(!pipeline_) configure(size);
 if(!pipeline_)return -EIO;
 gst_element_set_state(pipeline_,GST_STATE_PLAYING);
 GstSample *sample=gst_app_sink_try_pull_sample(GST_APP_SINK(sink_),3*GST_SECOND);
 if(!sample){
  GstBus *bus=gst_element_get_bus(pipeline_);
  GstMessage *msg=gst_bus_pop_filtered(bus,GST_MESSAGE_ERROR);
  if(msg){GError *error=nullptr;gchar *detail=nullptr;gst_message_parse_error(msg,&error,&detail);
   LOG(Virtual,Error)<<"PipeWire camera: "<<error->message;g_error_free(error);g_free(detail);gst_message_unref(msg);}
  gst_object_unref(bus);return -ETIMEDOUT;
 }
 GstVideoInfo info;gst_video_info_init(&info);
 GstVideoFrame frame;
 int result=-EINVAL;
 if(gst_video_info_from_caps(&info,gst_sample_get_caps(sample)) &&
    GST_VIDEO_INFO_FORMAT(&info)==GST_VIDEO_FORMAT_NV12 &&
    GST_VIDEO_INFO_WIDTH(&info)==static_cast<int>(size.width) &&
    GST_VIDEO_INFO_HEIGHT(&info)==static_cast<int>(size.height) &&
    gst_video_frame_map(&frame,&info,gst_sample_get_buffer(sample),GST_MAP_READ)){
  MappedFrameBuffer mapped(buffer,MappedFrameBuffer::MapFlag::Write);
  const auto &planes=mapped.planes();
  if(mapped.isValid() && planes.size()==2 && planes[0].size()>=size.width*size.height && planes[1].size()>=size.width*size.height/2)
   result=libyuv::NV12Copy(static_cast<const uint8_t *>(GST_VIDEO_FRAME_PLANE_DATA(&frame,0)),GST_VIDEO_FRAME_PLANE_STRIDE(&frame,0),
    static_cast<const uint8_t *>(GST_VIDEO_FRAME_PLANE_DATA(&frame,1)),GST_VIDEO_FRAME_PLANE_STRIDE(&frame,1),
    planes[0].data(),size.width,planes[1].data(),size.width,size.width,size.height);
  gst_video_frame_unmap(&frame);
 }
 gst_sample_unref(sample);return result;
}
void PipeWireFrameGenerator::stop(){
 if(pipeline_)gst_element_set_state(pipeline_,GST_STATE_NULL);
 if(sink_)gst_object_unref(sink_);
 if(pipeline_)gst_object_unref(pipeline_);
 sink_=nullptr;pipeline_=nullptr;
}
}
