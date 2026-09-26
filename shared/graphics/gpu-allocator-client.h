#ifndef RUNGIC_GPU_ALLOCATOR_CLIENT_H
#define RUNGIC_GPU_ALLOCATOR_CLIENT_H
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/time.h>
#include <string.h>
/* Protocol v1: little-endian magic, width, height, fourcc. Reply: magic,
 * byte stride, fourcc plus one SCM_RIGHTS fd. Keeping the socket open leases
 * the AHardwareBuffer. Its contents remain on the GPU display path. */
static bool rungic_gpu_allocate(const char *path, int width, int height,
        uint32_t format, int *lease, int *buffer_fd, uint32_t *stride) {
    union { struct sockaddr generic; struct sockaddr_un local; } address = { .local.sun_family=AF_UNIX };
    if (strlen(path) >= sizeof(address.local.sun_path)) return false;
    strcpy(address.local.sun_path,path);
    int sock=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0);
    if(sock<0) return false;
    struct timeval timeout={.tv_sec=5};
    setsockopt(sock,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
    setsockopt(sock,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
    if(connect(sock,&address.generic,sizeof(address.local))<0) goto fail;
    uint32_t request[]={0x4d475055,(uint32_t)width,(uint32_t)height,format};
    if(send(sock,request,sizeof(request),MSG_NOSIGNAL)!=sizeof(request)) goto fail;
    uint32_t reply[3]={0};
    struct iovec iov={.iov_base=reply,.iov_len=sizeof(reply)};
    union {struct cmsghdr align;char data[CMSG_SPACE(sizeof(int))];} control={0};
    struct msghdr msg={.msg_iov=&iov,.msg_iovlen=1,.msg_control=control.data,.msg_controllen=sizeof(control)};
    ssize_t n=recvmsg(sock,&msg,MSG_WAITALL|MSG_CMSG_CLOEXEC);
    struct cmsghdr *c=CMSG_FIRSTHDR(&msg);
    if(!c || c->cmsg_level!=SOL_SOCKET || c->cmsg_type!=SCM_RIGHTS || c->cmsg_len!=CMSG_LEN(sizeof(int))) goto fail;
    int fd;memcpy(&fd,CMSG_DATA(c),sizeof(fd));
    if(n!=sizeof(reply) || msg.msg_flags&MSG_CTRUNC || reply[0]!=0x4d475055 || reply[2]!=format || reply[1]<(uint32_t)width*4 || reply[1]>65536) {close(fd);goto fail;}
    *buffer_fd=fd;*lease=sock;*stride=reply[1];return true;
fail:
    close(sock);return false;
}
#endif
