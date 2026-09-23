// SPDX-License-Identifier: MIT
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define MAX_BUFFERS 4
#define MAX_LAYERS 8

struct options {
    const char *api, *sync;
    int layers, taps, buffers, width, height;
    double seconds, warmup;
    bool unthrottled;
};
extern struct options opt;

// One leased AHardwareBuffer shared with the Android host as a linear dma-buf.
struct output_buffer {
    int fd, lease;
    uint32_t stride;
    struct wl_buffer *wl;
    bool busy;
    void *priv;  // renderer state (EGLImage/FBO or VkImage/memory)
};
extern struct output_buffer out_buf[MAX_BUFFERS];

// Push constants shared by both renderers (std430-compatible layout).
struct quad {
    float rect[4];  // NDC x, y, w, h
    float uv[4];    // u, v, du, dv
    float alpha;
    int32_t taps;
};

struct renderer {
    void (*init)(void);
    void (*render)(struct output_buffer *target, int frame);  // record and submit
    void (*wait)(struct output_buffer *target);               // CPU-side completion wait per --sync
    const char *(*device_name)(void);
    void (*destroy)(void);
};
extern const struct renderer gles_renderer, vulkan_renderer;

void layer_quad(int layer, int frame, struct quad *q);
uint8_t *layer_pixels(int layer, int w, int h);
void mark(char phase, const char *name);
void die(const char *what);
double now_s(void);
