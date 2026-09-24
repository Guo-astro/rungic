// Commits an xdg_toplevel whose minimum width exceeds its maximum (as WeChat 4.1
// did) and reports whether the compositor keeps the connection.
#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <wayland-client.h>
#include "xdg-shell-client-protocol.h"

static struct wl_compositor *compositor;
static struct wl_shm *shm;
static struct xdg_wm_base *wm_base;
static int configured, width = 700, height = 400;

static void ping(void *d, struct xdg_wm_base *b, uint32_t s) { xdg_wm_base_pong(b, s); }
static const struct xdg_wm_base_listener wm_listener = { ping };
static void global(void *d, struct wl_registry *r, uint32_t n, const char *i, uint32_t v) {
    if (!strcmp(i, "wl_compositor")) compositor = wl_registry_bind(r, n, &wl_compositor_interface, 4);
    else if (!strcmp(i, "wl_shm")) shm = wl_registry_bind(r, n, &wl_shm_interface, 1);
    else if (!strcmp(i, "xdg_wm_base")) { wm_base = wl_registry_bind(r, n, &xdg_wm_base_interface, 1); xdg_wm_base_add_listener(wm_base, &wm_listener, NULL); }
}
static void global_remove(void *d, struct wl_registry *r, uint32_t n) {}
static const struct wl_registry_listener reg_listener = { global, global_remove };
static void surface_configure(void *d, struct xdg_surface *s, uint32_t serial) { xdg_surface_ack_configure(s, serial); configured = 1; }
static const struct xdg_surface_listener surface_listener = { surface_configure };
static void top_configure(void *d, struct xdg_toplevel *t, int32_t w, int32_t h, struct wl_array *st) {
    printf("configure %dx%d\n", w, h);
    if (w > 0) width = w;
    if (h > 0) height = h;
}
static void top_close(void *d, struct xdg_toplevel *t) {}
static const struct xdg_toplevel_listener top_listener = { top_configure, top_close };

int main(void) {
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) { puts("no display"); return 2; }
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &reg_listener, NULL);
    wl_display_roundtrip(display);
    struct wl_surface *surface = wl_compositor_create_surface(compositor);
    struct xdg_surface *xs = xdg_wm_base_get_xdg_surface(wm_base, surface);
    xdg_surface_add_listener(xs, &surface_listener, NULL);
    struct xdg_toplevel *top = xdg_surface_get_toplevel(xs);
    xdg_toplevel_add_listener(top, &top_listener, NULL);
    xdg_toplevel_set_title(top, "minmax-probe");
    xdg_toplevel_set_app_id(top, "minmax-probe");
    xdg_toplevel_set_min_size(top, 700, 400);
    xdg_toplevel_set_max_size(top, 360, 800);
    wl_surface_commit(surface);
    while (!configured && wl_display_dispatch(display) != -1) {}
    int stride = width * 4, size = stride * height;
    int fd = memfd_create("probe", 0);
    if (ftruncate(fd, size) < 0) return 3;
    void *data = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    memset(data, 0x80, size);
    struct wl_shm_pool *pool = wl_shm_create_pool(shm, fd, size);
    struct wl_buffer *buffer = wl_shm_pool_create_buffer(pool, 0, width, height, stride, WL_SHM_FORMAT_XRGB8888);
    wl_surface_attach(surface, buffer, 0, 0);
    wl_surface_commit(surface);
    for (int i = 0; i < 20; i++) {
        if (wl_display_roundtrip(display) == -1) { printf("DISCONNECTED: error %d\n", wl_display_get_error(display)); return 1; }
        usleep(100000);
    }
    printf("still connected after 2 s (buffer %dx%d)\n", width, height);
    return 0;
}
