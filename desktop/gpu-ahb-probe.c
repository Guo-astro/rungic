/* Exercise Android AHB lease -> KGSL EGL import -> actual rendered pixels. */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <gbm.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <GLES2/gl2ext.h>
#include <drm_fourcc.h>
#define CHECK(v) do { if (!(v)) { fprintf(stderr, "FAIL line %d EGL=%x GL=%x\n", __LINE__, eglGetError(), glGetError()); return 1; } } while (0)
int main(void) {
    int fd = open("/dev/kgsl-3d0", O_RDWR | O_CLOEXEC);
    CHECK(fd >= 0);
    struct gbm_device *gbm = gbm_create_device(fd);
    CHECK(gbm);
    PFNEGLGETPLATFORMDISPLAYEXTPROC platform = (void*)eglGetProcAddress("eglGetPlatformDisplayEXT");
    CHECK(platform);
    EGLDisplay d = platform(EGL_PLATFORM_GBM_KHR, gbm, NULL);
    EGLint major, minor;
    CHECK(eglInitialize(d, &major, &minor));
    CHECK(eglBindAPI(EGL_OPENGL_ES_API));
    EGLint ca[] = { EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT, EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_NONE };
    EGLConfig config; EGLint count;
    CHECK(eglChooseConfig(d, ca, &config, 1, &count) && count > 0);
    EGLint ctxa[] = { EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE };
    EGLContext ctx = eglCreateContext(d, config, EGL_NO_CONTEXT, ctxa);
    CHECK(ctx != EGL_NO_CONTEXT);
    CHECK(eglMakeCurrent(d, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx));
    const char *renderer = (const char*)glGetString(GL_RENDERER);
    printf("EGL: %d.%d %s\nGL_VENDOR: %s\nGL_RENDERER: %s\nGL_VERSION: %s\n", major, minor, eglQueryString(d,EGL_VENDOR), glGetString(GL_VENDOR), renderer, glGetString(GL_VERSION));
    CHECK(renderer && (strstr(renderer, "Adreno") || strstr(renderer, "FD710")) && !strstr(renderer,"llvmpipe"));
    int lease=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0); CHECK(lease>=0);
    struct sockaddr_un address={.sun_family=AF_UNIX};
    strcpy(address.sun_path,"/mnt/android-wayland/rungic-gpu-alloc");
    CHECK(connect(lease,(void*)&address,sizeof(address))==0);
    uint32_t request[]={0x4d475055,64,64,DRM_FORMAT_XRGB8888},reply[3]={0};
    CHECK(send(lease,request,sizeof(request),MSG_NOSIGNAL)==sizeof(request));
    char control[CMSG_SPACE(sizeof(int))];struct iovec iov={reply,sizeof(reply)};
    struct msghdr message={.msg_iov=&iov,.msg_iovlen=1,.msg_control=control,.msg_controllen=sizeof(control)};
    CHECK(recvmsg(lease,&message,MSG_WAITALL|MSG_CMSG_CLOEXEC)==sizeof(reply));
    struct cmsghdr *c=CMSG_FIRSTHDR(&message);CHECK(c&&c->cmsg_level==SOL_SOCKET&&c->cmsg_type==SCM_RIGHTS);
    int ahb;memcpy(&ahb,CMSG_DATA(c),sizeof(ahb));CHECK(reply[0]==request[0]&&reply[2]==request[3]);
    EGLint attrs[]={EGL_WIDTH,64,EGL_HEIGHT,64,EGL_LINUX_DRM_FOURCC_EXT,DRM_FORMAT_XRGB8888,
        EGL_DMA_BUF_PLANE0_FD_EXT,ahb,EGL_DMA_BUF_PLANE0_OFFSET_EXT,0,EGL_DMA_BUF_PLANE0_PITCH_EXT,reply[1],EGL_NONE};
    PFNEGLCREATEIMAGEKHRPROC createImage=(void*)eglGetProcAddress("eglCreateImageKHR");
    PFNGLEGLIMAGETARGETTEXTURE2DOESPROC imageTarget=(void*)eglGetProcAddress("glEGLImageTargetTexture2DOES");
    CHECK(createImage&&imageTarget);
    EGLImageKHR image=createImage(d,EGL_NO_CONTEXT,EGL_LINUX_DMA_BUF_EXT,NULL,attrs);CHECK(image!=EGL_NO_IMAGE_KHR);
    GLuint tex,fbo;glGenTextures(1,&tex);glBindTexture(GL_TEXTURE_2D,tex);imageTarget(GL_TEXTURE_2D,image);CHECK(glGetError()==GL_NO_ERROR);
    glGenFramebuffers(1,&fbo); glBindFramebuffer(GL_FRAMEBUFFER,fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,tex,0);
    CHECK(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE);
    glViewport(0,0,64,64); glClearColor(0.25f,0.5f,0.75f,1); glClear(GL_COLOR_BUFFER_BIT); glFinish();
    unsigned char pixel[4];glReadPixels(32,32,1,1,GL_RGBA,GL_UNSIGNED_BYTE,pixel);
    CHECK(glGetError()==GL_NO_ERROR);
    printf("Rendered pixel: %u %u %u %u\n",pixel[0],pixel[1],pixel[2],pixel[3]);
    CHECK(abs(pixel[0]-64)<=1 && abs(pixel[1]-128)<=1 && abs(pixel[2]-191)<=1 && pixel[3]==255);
    puts("Android AHB DMA-BUF import and GPU readback: PASS");
    ((PFNEGLDESTROYIMAGEKHRPROC)eglGetProcAddress("eglDestroyImageKHR"))(d,image);
    close(ahb);close(lease);
    glDeleteFramebuffers(1,&fbo);glDeleteTextures(1,&tex);eglMakeCurrent(d,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);eglDestroyContext(d,ctx);eglTerminate(d);gbm_device_destroy(gbm);close(fd);
    puts("Hardware render + readback: PASS");return 0;
}
