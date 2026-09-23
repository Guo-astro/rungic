/* Exercise KGSL -> GBM -> EGL -> GLES and verify actual rendered pixels. */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <gbm.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
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
    GLuint tex, fbo;
    glGenTextures(1,&tex); glBindTexture(GL_TEXTURE_2D,tex);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,64,64,0,GL_RGBA,GL_UNSIGNED_BYTE,NULL);
    glGenFramebuffers(1,&fbo); glBindFramebuffer(GL_FRAMEBUFFER,fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,tex,0);
    CHECK(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE);
    glViewport(0,0,64,64); glClearColor(0.25f,0.5f,0.75f,1); glClear(GL_COLOR_BUFFER_BIT); glFinish();
    unsigned char pixel[4];glReadPixels(32,32,1,1,GL_RGBA,GL_UNSIGNED_BYTE,pixel);
    CHECK(glGetError()==GL_NO_ERROR);
    printf("Rendered pixel: %u %u %u %u\n",pixel[0],pixel[1],pixel[2],pixel[3]);
    CHECK(abs(pixel[0]-64)<=1 && abs(pixel[1]-128)<=1 && abs(pixel[2]-191)<=1 && pixel[3]==255);
    struct gbm_bo *bo=gbm_bo_create(gbm,64,64,GBM_FORMAT_XRGB8888,GBM_BO_USE_RENDERING|GBM_BO_USE_LINEAR|GBM_BO_USE_SCANOUT);
    CHECK(bo);int prime=gbm_bo_get_fd(bo);CHECK(prime>=0);
    printf("GBM DMA-BUF export: PASS (stride %u)\n",gbm_bo_get_stride(bo));close(prime);gbm_bo_destroy(bo);
    glDeleteFramebuffers(1,&fbo);glDeleteTextures(1,&tex);eglMakeCurrent(d,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);eglDestroyContext(d,ctx);eglTerminate(d);gbm_device_destroy(gbm);close(fd);
    puts("Hardware render + readback: PASS");return 0;
}
