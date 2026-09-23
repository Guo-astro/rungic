/* SPDX-License-Identifier: MIT
 * IPC transport shared by the GStreamer and FFmpeg adapters. The optional
 * preload constructor grants Firefox only a connection to the codec broker,
 * before its normal sandbox is installed. It does not change sandbox policy.
 */
#define _GNU_SOURCE
#include "codec-client.h"
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <poll.h>
#include <pthread.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <arpa/inet.h>
#define MAGIC 0x4d434231u
#define OPEN 0x4f50454eu
#define CHANNEL 0x4d434631u
static pthread_mutex_t broker_lock=PTHREAD_MUTEX_INITIALIZER;
static int broker=-1;static pid_t broker_pid;
static int io(int fd,void *data,size_t length,int sending) {
 uint8_t *p=data;
 while(length) {
  struct pollfd f={.fd=fd,.events=sending?POLLOUT:POLLIN};
  int r;do {r=poll(&f,1,12000);}while(r<0 && errno==EINTR);
  if(r<=0){if(!r)errno=ETIMEDOUT;return -1;}
  ssize_t n=sending?send(fd,p,length,MSG_NOSIGNAL):recv(fd,p,length,0);
  if(n<0 && errno==EINTR)continue;
  if(n<=0){if(!n)errno=EPIPE;return -1;}p+=n;length-=n;
 }
 return 0;
}
static int put32(int fd,uint32_t v){v=htonl(v);return io(fd,&v,4,1);}
static int get32(int fd,uint32_t *v){int r=io(fd,v,4,0);if(!r)*v=ntohl(*v);return r;}
static int connect_broker(void) {
 if(broker>=0 && broker_pid==getpid())return 0;
 if(broker>=0)close(broker);broker=-1;broker_pid=getpid();
 int fd=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0);if(fd<0)return -1;
 struct sockaddr_un addr={.sun_family=AF_UNIX};
 strcpy(addr.sun_path,"/mnt/android-wayland/codec.sock");
 if(connect(fd,(struct sockaddr *)&addr,sizeof(addr)) || put32(fd,MAGIC)) {int e=errno;close(fd);errno=e;return -1;}
 broker=fd;return 0;
}
static void before_fork(void){pthread_mutex_lock(&broker_lock);}
static void after_fork_parent(void){pthread_mutex_unlock(&broker_lock);}
static void after_fork_child(void) {
 /* Firefox's fork server does not exec its children. Establish a distinct
  * broker in the child before it installs the content/RDD sandbox. */
 int saved=errno;
 if(broker>=0)close(broker);
 broker=-1;broker_pid=0;
 pthread_mutex_unlock(&broker_lock);
 connect_broker();errno=saved;
}
__attribute__((constructor)) static void preload_broker(void) {
 if(getenv("MOTO_CODEC_PRECONNECT")) {
  int saved=errno;connect_broker();
  pthread_atfork(before_fork,after_fork_parent,after_fork_child);
  errno=saved;
 }
}
void moto_codec_init(MotoCodec *c){memset(c,0,sizeof(*c));c->fd=-1;}
static int fail(MotoCodec *c,const char *what) {
 snprintf(c->error,sizeof(c->error),"%s: %s",what,strerror(errno));return -1;
}
static int remote_error(MotoCodec *c) {
 uint32_t n;if(get32(c->fd,&n) || n>=sizeof(c->error)) {errno=EPROTO;return fail(c,"Backend error");}
 if(io(c->fd,c->error,n,0))return fail(c,"Read error");c->error[n]=0;return -1;
}
int moto_codec_open(MotoCodec *c,const MotoCodecConfig *config) {
 moto_codec_close(c);c->ended=0;c->input_count=c->output_count=0;c->error[0]=0;
 const char *disabled=getenv("MOTO_CODEC_DISABLE");
 if(disabled && !strcmp(disabled,"1")){errno=ENODEV;return fail(c,"Hardware disabled by environment");}
 int fdlist[4]={-1,-1,-1,-1},count=0,result=-1;
 pthread_mutex_lock(&broker_lock);
 if(connect_broker() || put32(broker,OPEN))goto broker_error;
 uint32_t word=0;
 char control[CMSG_SPACE(sizeof(fdlist))]={0};
 struct iovec vec={.iov_base=&word,.iov_len=4};
 struct msghdr msg={.msg_iov=&vec,.msg_iovlen=1,.msg_control=control,.msg_controllen=sizeof(control)};
 struct pollfd pollfd={.fd=broker,.events=POLLIN};
 int ready;do{ready=poll(&pollfd,1,12000);}while(ready<0 && errno==EINTR);
 if(ready<=0){if(!ready)errno=ETIMEDOUT;goto broker_error;}
 ssize_t n;do {n=recvmsg(broker,&msg,MSG_CMSG_CLOEXEC);}while(n<0 && errno==EINTR);
 if(n<=0)goto broker_error;
 for(struct cmsghdr *h=CMSG_FIRSTHDR(&msg);h;h=CMSG_NXTHDR(&msg,h)) {
  if(h->cmsg_level==SOL_SOCKET && h->cmsg_type==SCM_RIGHTS) {
   size_t bytes=h->cmsg_len-CMSG_LEN(0);
   for(size_t i=0;i<bytes/sizeof(int);i++) {int fd;memcpy(&fd,(char *)CMSG_DATA(h)+i*sizeof(int),sizeof(int));if(count<4)fdlist[count++]=fd;else close(fd);}
  }
 }
 if(n<4 && io(broker,(char *)&word+n,4-n,0))goto broker_error;
 if(ntohl(word)!=CHANNEL || count!=2 || (msg.msg_flags&MSG_CTRUNC)){errno=EBUSY;goto out;}
 c->fd=fdlist[0];fdlist[0]=-1;
 struct stat statbuf;
 /* Android SharedMemory can be an ashmem character device (st_size=0),
  * or a regular memfd. The trusted broker creates exactly two 16 MiB halves. */
 if(fstat(fdlist[1],&statbuf) ||
    !(statbuf.st_size==MOTO_CODEC_HALF*2 || (S_ISCHR(statbuf.st_mode) && statbuf.st_size==0))){errno=EPROTO;goto out;}
 c->memory=mmap(NULL,MOTO_CODEC_HALF*2,PROT_READ|PROT_WRITE,MAP_SHARED,fdlist[1],0);
 if(c->memory==MAP_FAILED){c->memory=NULL;goto out;}
 result=0;goto out;
broker_error:
 if(broker>=0)close(broker);broker=-1;
out:
 {int error=errno;for(int i=0;i<count;i++)if(fdlist[i]>=0)close(fdlist[i]);pthread_mutex_unlock(&broker_lock);errno=error;}
 if(result<0){fail(c,"Open codec channel");moto_codec_close(c);return -1;}
 const int values[]={MAGIC,config->encoder,config->kind,config->width,config->height,config->fps_num,config->fps_den,config->bitrate,config->key_interval,config->color_standard,config->color_range,config->color_transfer};
 for(size_t i=0;i<sizeof(values)/sizeof(values[0]);i++)if(put32(c->fd,values[i]))goto config_error;
 if(get32(c->fd,&word))goto config_error;
 if(word==(uint32_t)-1){remote_error(c);moto_codec_close(c);return -1;}
 if(word!=MOTO_DONE || get32(c->fd,&word) || word>=sizeof(c->name)){errno=EPROTO;goto config_error;}
 if(io(c->fd,c->name,word,0))goto config_error;c->name[word]=0;
 return 0;
config_error:fail(c,"Configure codec");moto_codec_close(c);return -1;
}
int moto_codec_exchange(MotoCodec *c,int cmd,int id,int64_t pts,int flags,int length,MotoCodecOutput callback,void *user) {
 int consumer_failed=0;
 if(c->fd<0){errno=ENOTCONN;return fail(c,"Codec closed");}
 if(put32(c->fd,cmd))goto error;
 if(cmd==MOTO_FRAME) {
  if(length<=0 || (unsigned)length>MOTO_CODEC_HALF){errno=EINVAL;goto error;}
  const uint32_t data[]={id,(uint64_t)pts>>32,(uint32_t)pts,flags,length};
  for(size_t i=0;i<5;i++)if(put32(c->fd,data[i]))goto error;
  c->input_count++;
 }
 for(;;) {
  uint32_t type;if(get32(c->fd,&type))goto error;
  if(type==MOTO_DONE){if(cmd==MOTO_FLUSH)c->ended=0;return consumer_failed?-1:0;}
  if(type==(uint32_t)-1)return remote_error(c);
  if(type==MOTO_EOS){c->ended=1;continue;}
  if(type<MOTO_ENCODED || type>MOTO_CONFIG){errno=EPROTO;goto error;}
  uint32_t h[18];for(int i=0;i<18;i++)if(get32(c->fd,&h[i]))goto error;
  MotoCodecFrame frame={.type=type,.id=h[0],.flags=h[1],.size=h[2],.pts=(int64_t)(((uint64_t)h[3]<<32)|h[4]),.width=h[5],.height=h[6],.crop_x=h[7],.crop_y=h[8],.data=c->memory+MOTO_CODEC_HALF};
  if(frame.size<0 || (unsigned)frame.size>MOTO_CODEC_HALF){errno=EPROTO;goto error;}
  for(int p=0;p<3;p++){frame.plane[p].stride=h[9+p*3];frame.plane[p].step=h[10+p*3];frame.plane[p].length=h[11+p*3];}
  int r=callback && !consumer_failed?callback(user,&frame):0;
  if(put32(c->fd,0xac))goto error;
  if(type!=MOTO_CONFIG)c->output_count++;
  /* A downstream FLUSHING result must not leave response records unread.
   * Consume/ack the rest of this exchange before the next FLUSH command. */
  if(r){snprintf(c->error,sizeof(c->error),"Output consumer stopped");consumer_failed=1;}
 }
error:return fail(c,"Codec exchange");
}
void moto_codec_close(MotoCodec *c) {
 if(c->fd>=0){shutdown(c->fd,SHUT_RDWR);close(c->fd);c->fd=-1;}
 if(c->memory){munmap(c->memory,MOTO_CODEC_HALF*2);c->memory=NULL;}
}
int moto_codec_copy_i420(const MotoCodecFrame *f,uint8_t *const dst[3],const int stride[3]) {
 if(f->type!=MOTO_DECODED || f->width<1 || f->height<1 || f->width>2560 || f->height>2560 || f->crop_x<0 || f->crop_y<0)return -1;
 size_t offset=0;
 for(int p=0;p<3;p++) {
  int w=p?(f->width+1)/2:f->width,h=p?(f->height+1)/2:f->height;
  int x=p?f->crop_x/2:f->crop_x,y=p?f->crop_y/2:f->crop_y;
  int step=f->plane[p].step,row=f->plane[p].stride,len=f->plane[p].length;
  if(step<1 || step>2 || row<1 || len<1 || stride[p]<w || offset+(size_t)len>(unsigned)f->size)return -1;
  size_t base=(size_t)y*row+(size_t)x*step,last=base+(size_t)(h-1)*row+(size_t)(w-1)*step;
  if(last>=(unsigned)len)return -1;
  for(int r=0;r<h;r++) {
   const uint8_t *s=f->data+offset+base+(size_t)r*row;uint8_t *d=dst[p]+r*stride[p];
   if(step==1)memcpy(d,s,w);else for(int col=0;col<w;col++)d[col]=s[col*step];
  }
  offset+=len;
 }
 return 0;
}
