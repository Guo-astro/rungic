/* SPDX-License-Identifier: MIT */
#ifndef RUNGIC_CODEC_CLIENT_H
#define RUNGIC_CODEC_CLIENT_H
#include <stdint.h>
#include <stddef.h>
#define RUNGIC_CODEC_HALF (16u*1024u*1024u)
enum { RUNGIC_FRAME=1, RUNGIC_DRAIN=2, RUNGIC_FLUSH=3, RUNGIC_CLOSE=4 };
enum { RUNGIC_DONE=0, RUNGIC_ENCODED=1, RUNGIC_DECODED=2, RUNGIC_CONFIG=3, RUNGIC_EOS=4 };
typedef struct {
 int encoder,kind,width,height,fps_num,fps_den,bitrate,key_interval;
 int color_standard,color_range,color_transfer;
} RungicCodecConfig;
typedef struct {
 int type,id,flags,size;int64_t pts;
 int width,height,crop_x,crop_y;
 struct {int stride,step,length;} plane[3];
 const uint8_t *data;
} RungicCodecFrame;
typedef struct {
 int fd;uint8_t *memory;char name[128],error[256];
 unsigned input_count,output_count;int ended;
} RungicCodec;
typedef int (*RungicCodecOutput)(void *,const RungicCodecFrame *);
void rungic_codec_init(RungicCodec *);
int rungic_codec_open(RungicCodec *,const RungicCodecConfig *);
int rungic_codec_exchange(RungicCodec *,int cmd,int id,int64_t pts,int flags,int length,RungicCodecOutput,void *);
void rungic_codec_close(RungicCodec *);
int rungic_codec_copy_i420(const RungicCodecFrame *,uint8_t *const dst[3],const int stride[3]);
#endif
