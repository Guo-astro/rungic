// SPDX-License-Identifier: MIT
// compbench: a minimal compositor-style renderer on KWin's exact Android output path.
//
// Like KWin's Wayland backend it connects to the Android host's Wayland server,
// leases AHardwareBuffers from the host allocator (linear XRGB8888), renders a
// frame into them and commits them through linux-dmabuf. Only the renderer
// (OpenGL ES through EGL dma-buf import, or Vulkan through dma-buf/modifier
// import on Turnip) and the CPU-side completion wait differ between runs, so
// the difference isolates what a native Vulkan KWin renderer could change.
//
// Scene: an opaque wallpaper and N alpha-blended window layers that move every
// frame (full repaint, as KWin does during scrolling/animations). `--taps`
// scales per-pixel shader cost. Output: one JSON summary on stdout; atrace
// markers (B|pid|name) go to trace_marker when tracefs is mounted.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <math.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>

#include <wayland-client.h>
#include "linux-dmabuf-v1-client-protocol.h"
#include "presentation-time-client-protocol.h"
#include "xdg-shell-client-protocol.h"
#include "gpu-allocator-client.h"  // shared/graphics

#include "compbench.h"

#define FOURCC_XR24 0x34325258u
#define MAX_FRAMES 20000

struct options opt = {
    .api = "gles", .sync = "finish", .layers = 3, .taps = 1, .seconds = 12, .warmup = 3,
    .buffers = 3, .unthrottled = false,
};

static struct wl_display *display;
static struct wl_compositor *compositor;
static struct xdg_wm_base *wm_base;
static struct zwp_linux_dmabuf_v1 *dmabuf;
static struct wp_presentation *presentation;
static struct wl_output *output;
static struct wl_surface *surface;
static int out_width, out_height, cfg_width, cfg_height;
static bool configured, frame_pending;
static int trace_fd = -1;

struct output_buffer out_buf[MAX_BUFFERS];

struct sample {
    double start, cpu_ms, wait_ms, commit, presented;
};
static struct sample samples[MAX_FRAMES];
static int nsamples;

double now_s(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static double thread_cpu_s(void) {
    struct timespec ts; clock_gettime(CLOCK_THREAD_CPUTIME_ID, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

void mark(char phase, const char *name) {
    if (trace_fd < 0) return;
    char line[96];
    int n = phase == 'B' ? snprintf(line, sizeof line, "B|%d|compbench:%s", getpid(), name)
                         : snprintf(line, sizeof line, "E|%d", getpid());
    if (write(trace_fd, line, n) < 0) { close(trace_fd); trace_fd = -1; }
}

void die(const char *what) { fprintf(stderr, "compbench: %s\n", what); exit(1); }

// ---------------------------------------------------------------- Wayland

static void output_mode(void *d, struct wl_output *o, uint32_t flags, int32_t w, int32_t h, int32_t r) {
    (void)d; (void)o; (void)r;
    if (flags & WL_OUTPUT_MODE_CURRENT) { out_width = w; out_height = h; }
}
static void output_geometry(void *d, struct wl_output *o, int32_t x, int32_t y, int32_t pw, int32_t ph,
                            int32_t sp, const char *make, const char *model, int32_t t) {
    (void)d; (void)o; (void)x; (void)y; (void)pw; (void)ph; (void)sp; (void)make; (void)model; (void)t;
}
static void output_noop(void *d, struct wl_output *o) { (void)d; (void)o; }
static void output_scale(void *d, struct wl_output *o, int32_t s) { (void)d; (void)o; (void)s; }
static void output_str(void *d, struct wl_output *o, const char *s) { (void)d; (void)o; (void)s; }
static const struct wl_output_listener output_listener = {
    output_geometry, output_mode, output_noop, output_scale, output_str, output_str,
};

static void wm_ping(void *d, struct xdg_wm_base *b, uint32_t serial) { (void)d; xdg_wm_base_pong(b, serial); }
static const struct xdg_wm_base_listener wm_listener = { wm_ping };

static void registry_global(void *d, struct wl_registry *r, uint32_t name, const char *iface, uint32_t version) {
    (void)d;
    if (!strcmp(iface, wl_compositor_interface.name))
        compositor = wl_registry_bind(r, name, &wl_compositor_interface, 4);
    else if (!strcmp(iface, xdg_wm_base_interface.name)) {
        wm_base = wl_registry_bind(r, name, &xdg_wm_base_interface, 1);
        xdg_wm_base_add_listener(wm_base, &wm_listener, NULL);
    } else if (!strcmp(iface, zwp_linux_dmabuf_v1_interface.name) && version >= 2)
        dmabuf = wl_registry_bind(r, name, &zwp_linux_dmabuf_v1_interface, version < 3 ? version : 3);
    else if (!strcmp(iface, wp_presentation_interface.name))
        presentation = wl_registry_bind(r, name, &wp_presentation_interface, 1);
    else if (!strcmp(iface, wl_output_interface.name) && !output) {
        output = wl_registry_bind(r, name, &wl_output_interface, version < 4 ? version : 4);
        wl_output_add_listener(output, &output_listener, NULL);
    }
}
static void registry_remove(void *d, struct wl_registry *r, uint32_t n) { (void)d; (void)r; (void)n; }
static const struct wl_registry_listener registry_listener = { registry_global, registry_remove };

static void xdg_surface_configure(void *d, struct xdg_surface *s, uint32_t serial) {
    (void)d; xdg_surface_ack_configure(s, serial); configured = true;
}
static const struct xdg_surface_listener xdg_surface_listener = { xdg_surface_configure };
static void toplevel_configure(void *d, struct xdg_toplevel *t, int32_t w, int32_t h, struct wl_array *s) {
    (void)d; (void)t; (void)s;
    if (w > 0 && h > 0) { cfg_width = w; cfg_height = h; }
}
static void toplevel_close(void *d, struct xdg_toplevel *t) { (void)d; (void)t; }
static const struct xdg_toplevel_listener toplevel_listener = { toplevel_configure, toplevel_close };

static void buffer_release(void *d, struct wl_buffer *b) { (void)b; ((struct output_buffer *)d)->busy = false; }
static const struct wl_buffer_listener buffer_listener = { buffer_release };

static void frame_done(void *d, struct wl_callback *cb, uint32_t t) { (void)d; (void)t; wl_callback_destroy(cb); frame_pending = false; }
static const struct wl_callback_listener frame_listener = { frame_done };

static void fb_sync_output(void *d, struct wp_presentation_feedback *f, struct wl_output *o) { (void)d; (void)f; (void)o; }
static void fb_presented(void *d, struct wp_presentation_feedback *f, uint32_t hi, uint32_t lo, uint32_t nsec,
                         uint32_t refresh, uint32_t seq_hi, uint32_t seq_lo, uint32_t flags) {
    (void)refresh; (void)seq_hi; (void)seq_lo; (void)flags;
    struct sample *s = d;
    s->presented = ((double)(((uint64_t)hi << 32) | lo)) + nsec / 1e9;
    wp_presentation_feedback_destroy(f);
}
static void fb_discarded(void *d, struct wp_presentation_feedback *f) { (void)d; wp_presentation_feedback_destroy(f); }
static const struct wp_presentation_feedback_listener feedback_listener = { fb_sync_output, fb_presented, fb_discarded };

static void connect_host(void) {
    display = wl_display_connect(getenv("WAYLAND_DISPLAY") ? NULL : "/mnt/android-wayland/wayland-0");
    if (!display) die("cannot connect to the Android host Wayland server");
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, NULL);
    wl_display_roundtrip(display);
    wl_display_roundtrip(display);
    if (!compositor || !wm_base || !dmabuf) die("host lacks wl_compositor, xdg_wm_base or linux-dmabuf v2+");
    surface = wl_compositor_create_surface(compositor);
    struct xdg_surface *xs = xdg_wm_base_get_xdg_surface(wm_base, surface);
    xdg_surface_add_listener(xs, &xdg_surface_listener, NULL);
    struct xdg_toplevel *top = xdg_surface_get_toplevel(xs);
    xdg_toplevel_add_listener(top, &toplevel_listener, NULL);
    xdg_toplevel_set_title(top, "compbench");
    xdg_toplevel_set_fullscreen(top, output);
    wl_surface_commit(surface);
    while (!configured && wl_display_dispatch(display) >= 0) {}
    opt.width = opt.width ? opt.width : (cfg_width ? cfg_width : out_width);
    opt.height = opt.height ? opt.height : (cfg_height ? cfg_height : out_height);
    if (opt.width <= 0 || opt.height <= 0) die("no output size; pass --size WxH");
}

static void allocate_buffers(void) {
    const char *socket = getenv("MOTO_GPU_ALLOCATOR") ? getenv("MOTO_GPU_ALLOCATOR") : "/mnt/android-wayland/moto-gpu-alloc";
    for (int i = 0; i < opt.buffers; i++) {
        struct output_buffer *b = &out_buf[i];
        if (!moto_gpu_allocate(socket, opt.width, opt.height, FOURCC_XR24, &b->lease, &b->fd, &b->stride))
            die("host allocator refused an AHardwareBuffer lease");
        struct zwp_linux_buffer_params_v1 *params = zwp_linux_dmabuf_v1_create_params(dmabuf);
        zwp_linux_buffer_params_v1_add(params, b->fd, 0, 0, b->stride, 0, 0);  // DRM_FORMAT_MOD_LINEAR
        b->wl = zwp_linux_buffer_params_v1_create_immed(params, opt.width, opt.height, FOURCC_XR24, 0);
        zwp_linux_buffer_params_v1_destroy(params);
        wl_buffer_add_listener(b->wl, &buffer_listener, b);
    }
    wl_display_roundtrip(display);
}

static struct output_buffer *free_buffer(void) {
    for (;;) {
        for (int i = 0; i < opt.buffers; i++)
            if (!out_buf[i].busy) return &out_buf[i];
        if (wl_display_dispatch(display) < 0) die("Wayland connection lost");
    }
}

// ---------------------------------------------------------------- scene

void layer_quad(int layer, int frame, struct quad *q) {
    if (layer == 0) {  // opaque wallpaper
        *q = (struct quad){ {-1, -1, 2, 2}, {0, 0, 1, 1}, 1.0f, opt.taps };
        return;
    }
    // Window-like layers: nearly full-screen, sliding as during a scroll or open animation.
    float phase = frame * 0.045f + layer * 1.3f;
    float y = -0.95f + 0.08f * sinf(phase);
    float x = -1.0f + 0.04f * cosf(phase * 0.7f);
    *q = (struct quad){ {x, y, 2.0f, 1.8f}, {0, 0, 1, 1}, layer == opt.layers ? 0.92f : 0.85f, opt.taps };
}

uint8_t *layer_pixels(int layer, int w, int h) {
    uint8_t *p = malloc((size_t)w * h * 4);
    if (!p) die("out of memory");
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++) {
            uint8_t *px = p + ((size_t)y * w + x) * 4;
            bool stripe = ((x / 24) + (y / 40) + layer) % 7 == 0;  // text-like detail, defeats trivial caching
            px[0] = (uint8_t)(40 + layer * 50 + x * 120 / w);
            px[1] = (uint8_t)(60 + y * 150 / h);
            px[2] = (uint8_t)(stripe ? 230 : 90 + layer * 30);
            px[3] = layer == 0 ? 255 : (uint8_t)(200 + (x + y) % 55);
        }
    return p;
}

// ---------------------------------------------------------------- main loop

static int compare(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

static void print_stats(const char *name, double *v, int n, bool last) {
    if (n <= 0) { printf("  \"%s\": {\"n\": 0}%s\n", name, last ? "" : ","); return; }
    qsort(v, n, sizeof *v, compare);
    double sum = 0; for (int i = 0; i < n; i++) sum += v[i];
    #define Q(q) v[(int)((n - 1) * (q) + 0.5)]
    printf("  \"%s\": {\"n\": %d, \"mean\": %.3f, \"p50\": %.3f, \"p95\": %.3f, \"p99\": %.3f, \"max\": %.3f}%s\n",
           name, n, sum / n, Q(.5), Q(.95), Q(.99), v[n - 1], last ? "" : ",");
    #undef Q
}

static void usage(void) {
    fprintf(stderr, "usage: compbench [--api gles|vulkan] [--sync finish|fence|none] [--layers N] [--taps N]\n"
                    "                 [--seconds S] [--warmup S] [--buffers N] [--size WxH] [--unthrottled]\n");
    exit(2);
}

int main(int argc, char **argv) {
    static const struct option longopts[] = {
        {"api", 1, 0, 'a'}, {"sync", 1, 0, 's'}, {"layers", 1, 0, 'l'}, {"taps", 1, 0, 't'},
        {"seconds", 1, 0, 'd'}, {"warmup", 1, 0, 'w'}, {"buffers", 1, 0, 'b'}, {"size", 1, 0, 'z'},
        {"unthrottled", 0, 0, 'u'}, {0, 0, 0, 0}};
    for (int c; (c = getopt_long(argc, argv, "", longopts, NULL)) != -1;) {
        switch (c) {
        case 'a': opt.api = optarg; break;
        case 's': opt.sync = optarg; break;
        case 'l': opt.layers = atoi(optarg); break;
        case 't': opt.taps = atoi(optarg); break;
        case 'd': opt.seconds = atof(optarg); break;
        case 'w': opt.warmup = atof(optarg); break;
        case 'b': opt.buffers = atoi(optarg); break;
        case 'z': if (sscanf(optarg, "%dx%d", &opt.width, &opt.height) != 2) usage(); break;
        case 'u': opt.unthrottled = true; break;
        default: usage();
        }
    }
    if (opt.layers < 0 || opt.layers > MAX_LAYERS || opt.buffers < 2 || opt.buffers > MAX_BUFFERS || opt.taps < 1)
        usage();
    bool vulkan = !strcmp(opt.api, "vulkan");
    if (!vulkan && strcmp(opt.api, "gles")) usage();
    if (strcmp(opt.sync, "finish") && strcmp(opt.sync, "fence") && strcmp(opt.sync, "none")) usage();
    trace_fd = open("/sys/kernel/tracing/trace_marker", O_WRONLY | O_CLOEXEC);

    connect_host();
    allocate_buffers();
    const struct renderer *r = vulkan ? &vulkan_renderer : &gles_renderer;
    r->init();

    double begin = now_s(), measure_from = begin + opt.warmup, end = measure_from + opt.seconds;
    struct rusage ru0 = {0}, ru1;
    bool measuring = false;
    for (int frame = 0; now_s() < end; frame++) {
        if (!measuring && now_s() >= measure_from) { measuring = true; getrusage(RUSAGE_SELF, &ru0); }
        struct output_buffer *b = free_buffer();
        struct sample *s = measuring && nsamples < MAX_FRAMES ? &samples[nsamples++] : &(struct sample){0};
        s->start = now_s();
        double cpu0 = thread_cpu_s();
        mark('B', "render"); r->render(b, frame); mark('E', NULL);
        s->cpu_ms = (thread_cpu_s() - cpu0) * 1e3;
        double wait0 = now_s();
        mark('B', "wait"); r->wait(b); mark('E', NULL);
        s->wait_ms = (now_s() - wait0) * 1e3;
        b->busy = true;
        wl_surface_attach(surface, b->wl, 0, 0);
        wl_surface_damage_buffer(surface, 0, 0, opt.width, opt.height);
        if (!opt.unthrottled) {
            frame_pending = true;
            wl_callback_add_listener(wl_surface_frame(surface), &frame_listener, NULL);
        }
        if (presentation && measuring)
            wp_presentation_feedback_add_listener(wp_presentation_feedback(presentation, surface), &feedback_listener, s);
        wl_surface_commit(surface);
        s->commit = now_s();
        wl_display_flush(display);
        while (frame_pending && wl_display_dispatch(display) >= 0) {}
        wl_display_dispatch_pending(display);
    }
    getrusage(RUSAGE_SELF, &ru1);
    wl_display_roundtrip(display);  // collect the last presentation feedback

    static double cpu[MAX_FRAMES], wait[MAX_FRAMES], interval[MAX_FRAMES], present[MAX_FRAMES];
    int ni = 0, np = 0;
    double last_present = 0;
    for (int i = 0; i < nsamples; i++) {
        cpu[i] = samples[i].cpu_ms; wait[i] = samples[i].wait_ms;
        if (i) interval[ni++] = (samples[i].commit - samples[i - 1].commit) * 1e3;
        if (samples[i].presented > 0) {
            if (last_present > 0) present[np++] = (samples[i].presented - last_present) * 1e3;
            last_present = samples[i].presented;
        }
    }
    double proc_cpu = (ru1.ru_utime.tv_sec - ru0.ru_utime.tv_sec + ru1.ru_stime.tv_sec - ru0.ru_stime.tv_sec)
                    + (ru1.ru_utime.tv_usec - ru0.ru_utime.tv_usec + ru1.ru_stime.tv_usec - ru0.ru_stime.tv_usec) / 1e6;
    printf("{\n  \"api\": \"%s\", \"sync\": \"%s\", \"layers\": %d, \"taps\": %d, \"size\": [%d, %d],\n"
           "  \"device\": \"%s\", \"throttled\": %s, \"frames\": %d, \"seconds\": %.3f,\n"
           "  \"fps\": %.2f, \"process_cpu_core_pct\": %.2f, \"presented_frames\": %d,\n",
           opt.api, opt.sync, opt.layers, opt.taps, opt.width, opt.height, r->device_name(),
           opt.unthrottled ? "false" : "true", nsamples, opt.seconds, nsamples / opt.seconds,
           100 * proc_cpu / opt.seconds, np + (last_present > 0));
    print_stats("render_cpu_ms", cpu, nsamples, false);
    print_stats("wait_ms", wait, nsamples, false);
    print_stats("commit_interval_ms", interval, ni, false);
    print_stats("present_interval_ms", present, np, true);
    printf("}\n");
    r->destroy();
    return 0;
}
