// SPDX-License-Identifier: MIT
// OpenGL ES renderer: the same EGL setup as KWin's Wayland backend on this phone
// (GBM on /dev/kgsl-3d0, EGL_PLATFORM_GBM_KHR, dma-buf EGLImage render targets).
#define _GNU_SOURCE
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <GLES2/gl2ext.h>
#include <gbm.h>

#include "compbench.h"

static EGLDisplay dpy;
static EGLContext ctx;
static GLuint program, textures[MAX_LAYERS + 1], vao;
static GLint u_rect, u_uv, u_alpha, u_taps;
static PFNEGLCREATEIMAGEKHRPROC create_image;
static PFNGLEGLIMAGETARGETRENDERBUFFERSTORAGEOESPROC image_renderbuffer;
static PFNEGLCREATESYNCKHRPROC create_sync;
static PFNEGLDESTROYSYNCKHRPROC destroy_sync;
static PFNEGLDUPNATIVEFENCEFDANDROIDPROC dup_fence;
static int pending_fence = -1;
static char device[128];

struct gles_target { EGLImageKHR image; GLuint rbo, fbo; };

static const char *vs_src =
    "#version 300 es\n"
    "uniform vec4 rect; uniform vec4 uv;\n"
    "out vec2 v_uv;\n"
    "void main() {\n"
    "  vec2 p = vec2(float(gl_VertexID & 1), float((gl_VertexID >> 1) & 1));\n"
    "  v_uv = uv.xy + p * uv.zw;\n"
    "  gl_Position = vec4(rect.xy + p * rect.zw, 0.0, 1.0);\n"
    "}\n";
static const char *fs_src =
    "#version 300 es\n"
    "precision mediump float;\n"
    "uniform sampler2D tex; uniform float alpha; uniform int taps;\n"
    "in vec2 v_uv; out vec4 color;\n"
    "void main() {\n"
    "  vec4 c = texture(tex, v_uv);\n"
    "  for (int i = 1; i < taps; i++) c += texture(tex, v_uv + vec2(float(i) * 0.0007, 0.0));\n"
    "  c /= float(max(taps, 1));\n"
    "  color = vec4(c.rgb, c.a * alpha);\n"
    "}\n";

static GLuint shader(GLenum type, const char *src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[1024]; glGetShaderInfoLog(s, sizeof log, NULL, log); fprintf(stderr, "%s\n", log); die("GLSL compile failed"); }
    return s;
}

static void init(void) {
    int fd = open(getenv("RUNGIC_KWIN_RENDER_DEVICE") ? getenv("RUNGIC_KWIN_RENDER_DEVICE") : "/dev/kgsl-3d0", O_RDWR | O_CLOEXEC);
    if (fd < 0) die("cannot open the render device");
    struct gbm_device *gbm = gbm_create_device(fd);
    if (!gbm) die("gbm_create_device failed");
    PFNEGLGETPLATFORMDISPLAYEXTPROC get_display = (void *)eglGetProcAddress("eglGetPlatformDisplayEXT");
    dpy = get_display(EGL_PLATFORM_GBM_KHR, gbm, NULL);
    if (!dpy || !eglInitialize(dpy, NULL, NULL)) die("eglInitialize failed");
    eglBindAPI(EGL_OPENGL_ES_API);
    const EGLint attrs[] = {EGL_CONTEXT_MAJOR_VERSION, 3, EGL_NONE};
    ctx = eglCreateContext(dpy, EGL_NO_CONFIG_KHR, EGL_NO_CONTEXT, attrs);
    if (!ctx || !eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx)) die("EGL context failed");
    snprintf(device, sizeof device, "%s", (const char *)glGetString(GL_RENDERER));
    create_image = (void *)eglGetProcAddress("eglCreateImageKHR");
    image_renderbuffer = (void *)eglGetProcAddress("glEGLImageTargetRenderbufferStorageOES");
    create_sync = (void *)eglGetProcAddress("eglCreateSyncKHR");
    destroy_sync = (void *)eglGetProcAddress("eglDestroySyncKHR");
    dup_fence = (void *)eglGetProcAddress("eglDupNativeFenceFDANDROID");
    if (!create_image || !image_renderbuffer) die("EGL dma-buf import entry points missing");
    if (!strcmp(opt.sync, "fence") && !dup_fence) die("EGL_ANDROID_native_fence_sync missing");

    for (int i = 0; i < opt.buffers; i++) {
        struct output_buffer *b = &out_buf[i];
        struct gles_target *t = calloc(1, sizeof *t);
        const EGLint image_attrs[] = {
            EGL_WIDTH, opt.width, EGL_HEIGHT, opt.height, EGL_LINUX_DRM_FOURCC_EXT, 0x34324258,  // XB24
            EGL_DMA_BUF_PLANE0_FD_EXT, b->fd, EGL_DMA_BUF_PLANE0_OFFSET_EXT, 0,
            EGL_DMA_BUF_PLANE0_PITCH_EXT, (EGLint)b->stride,
            EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT, 0, EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT, 0, EGL_NONE};
        t->image = create_image(dpy, EGL_NO_CONTEXT, EGL_LINUX_DMA_BUF_EXT, NULL, image_attrs);
        if (t->image == EGL_NO_IMAGE_KHR) die("dma-buf EGLImage import failed");
        glGenRenderbuffers(1, &t->rbo);
        glBindRenderbuffer(GL_RENDERBUFFER, t->rbo);
        image_renderbuffer(GL_RENDERBUFFER, t->image);
        glGenFramebuffers(1, &t->fbo);
        glBindFramebuffer(GL_FRAMEBUFFER, t->fbo);
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, t->rbo);
        if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) die("dma-buf framebuffer incomplete");
        b->priv = t;
    }
    program = glCreateProgram();
    glAttachShader(program, shader(GL_VERTEX_SHADER, vs_src));
    glAttachShader(program, shader(GL_FRAGMENT_SHADER, fs_src));
    glLinkProgram(program);
    u_rect = glGetUniformLocation(program, "rect"); u_uv = glGetUniformLocation(program, "uv");
    u_alpha = glGetUniformLocation(program, "alpha"); u_taps = glGetUniformLocation(program, "taps");
    glGenVertexArrays(1, &vao);
    glGenTextures(opt.layers + 1, textures);
    for (int l = 0; l <= opt.layers; l++) {
        uint8_t *pixels = layer_pixels(l, opt.width, opt.height);
        glBindTexture(GL_TEXTURE_2D, textures[l]);
        glTexStorage2D(GL_TEXTURE_2D, 1, GL_RGBA8, opt.width, opt.height);
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, opt.width, opt.height, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        free(pixels);
    }
    glFinish();
}

static void render(struct output_buffer *b, int frame) {
    struct gles_target *t = b->priv;
    glBindFramebuffer(GL_FRAMEBUFFER, t->fbo);
    glViewport(0, 0, opt.width, opt.height);
    glUseProgram(program);
    glBindVertexArray(vao);
    glActiveTexture(GL_TEXTURE0);
    for (int l = 0; l <= opt.layers; l++) {
        struct quad q;
        layer_quad(l, frame, &q);
        if (l == 0) glDisable(GL_BLEND);
        else { glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA); }
        glBindTexture(GL_TEXTURE_2D, textures[l]);
        glUniform4fv(u_rect, 1, q.rect); glUniform4fv(u_uv, 1, q.uv);
        glUniform1f(u_alpha, q.alpha); glUniform1i(u_taps, q.taps);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    }
    if (!strcmp(opt.sync, "fence")) {
        EGLSyncKHR sync = create_sync(dpy, EGL_SYNC_NATIVE_FENCE_ANDROID, NULL);
        glFlush();
        pending_fence = dup_fence(dpy, sync);
        destroy_sync(dpy, sync);
    } else if (!strcmp(opt.sync, "none")) {
        glFlush();
    }
}

static void wait(struct output_buffer *b) {
    (void)b;
    if (!strcmp(opt.sync, "finish")) {
        glFinish();  // what KWin does before handing the buffer to Android today
    } else if (pending_fence >= 0) {
        struct pollfd p = {pending_fence, POLLIN, 0};
        poll(&p, 1, 1000);  // sync_file signals when the GPU finished, without draining the GL pipeline
        close(pending_fence);
        pending_fence = -1;
    }
}

static const char *device_name(void) { return device; }
static void destroy(void) { eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT); eglTerminate(dpy); }

const struct renderer gles_renderer = {init, render, wait, device_name, destroy};
