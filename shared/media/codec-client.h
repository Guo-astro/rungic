/* SPDX-License-Identifier: MIT */
#ifndef MOTO_CODEC_CLIENT_H
#define MOTO_CODEC_CLIENT_H
#include <stdint.h>
#include <stddef.h>
#define MOTO_CODEC_HALF (16u*1024u*1024u)
enum { MOTO_FRAME=1, MOTO_DRAIN=2, MOTO_FLUSH=3, MOTO_CLOSE=4 };
enum { MOTO_DONE=0, MOTO_ENCODED=1, MOTO_DECODED=2, MOTO_CONFIG=3, MOTO_EOS=4 };
typedef struct {
 int encoder,kind,width,height,fps_num,fps_den,bitrate,key_interval;
 int color_standard,color_range,color_transfer;
} MotoCodecConfig;
typedef struct {
 int type,id,flags,size;int64_t pts;
 int width,height,crop_x,crop_y;
 struct {int stride,step,length;} plane[3];
 const uint8_t *data;
} MotoCodecFrame;
typedef struct {
 int fd;uint8_t *memory;char name[128],error[256];
 unsigned input_count,output_count;int ended;
} MotoCodec;
typedef int (*MotoCodecOutput)(void *,const MotoCodecFrame *);
void moto_codec_init(MotoCodec *);
int moto_codec_open(MotoCodec *,const MotoCodecConfig *);
int moto_codec_exchange(MotoCodec *,int cmd,int id,int64_t pts,int flags,int length,MotoCodecOutput,void *);
void moto_codec_close(MotoCodec *);
int moto_codec_copy_i420(const MotoCodecFrame *,uint8_t *const dst[3],const int stride[3]);
#endif
