// Holds a zwp_idle_inhibitor_v1 for N seconds (docs/72).
//   idle-probe [seconds]          a visible xdg_toplevel with an inhibitor: KWin honours
//                                 inhibitors of shown windows only (acceptance idle.inhibit)
//   idle-probe --bare [seconds]   an inhibitor on a bare wl_surface, for testing the Android host
//                                 directly (WAYLAND_DISPLAY=/mnt/android-wayland/wayland-0); the
//                                 host keeps FLAG_KEEP_SCREEN_ON while it exists
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <wayland-client.h>
#include "idle-inhibit-unstable-v1-client-protocol.h"
#include "xdg-shell-client-protocol.h"

static struct wl_compositor *compositor;
static struct wl_shm *shm;
static struct xdg_wm_base *wm_base;
static struct zwp_idle_inhibit_manager_v1 *manager;
static int configured, width = 240, height = 240;

static void ping(void *d, struct xdg_wm_base *b, uint32_t s) { xdg_wm_base_pong(b, s); }
static const struct xdg_wm_base_listener wm_listener = { ping };
static void global(void *d, struct wl_registry *r, uint32_t n, const char *i, uint32_t v) {
    if (!strcmp(i, "wl_compositor")) compositor = wl_registry_bind(r, n, &wl_compositor_interface, 4);
    else if (!strcmp(i, "wl_shm")) shm = wl_registry_bind(r, n, &wl_shm_interface, 1);
    else if (!strcmp(i, "xdg_wm_base")) { wm_base = wl_registry_bind(r, n, &xdg_wm_base_interface, 1); xdg_wm_base_add_listener(wm_base, &wm_listener, NULL); }
    else if (!strcmp(i, "zwp_idle_inhibit_manager_v1")) manager = wl_registry_bind(r, n, &zwp_idle_inhibit_manager_v1_interface, 1);
}
static void global_remove(void *d, struct wl_registry *r, uint32_t n) {}
static const struct wl_registry_listener reg_listener = { global, global_remove };
static void surface_configure(void *d, struct xdg_surface *s, uint32_t serial) { xdg_surface_ack_configure(s, serial); configured = 1; }
static const struct xdg_surface_listener surface_listener = { surface_configure };
static void top_configure(void *d, struct xdg_toplevel *t, int32_t w, int32_t h, struct wl_array *st) {
    if (w > 0) width = w;
    if (h > 0) height = h;
}
static void top_close(void *d, struct xdg_toplevel *t) {}
static const struct xdg_toplevel_listener top_listener = { top_configure, top_close };

static int show_window(struct wl_display *display, struct wl_surface *surface) {
    struct xdg_surface *xs = xdg_wm_base_get_xdg_surface(wm_base, surface);
    xdg_surface_add_listener(xs, &surface_listener, NULL);
    struct xdg_toplevel *top = xdg_surface_get_toplevel(xs);
    xdg_toplevel_add_listener(top, &top_listener, NULL);
    xdg_toplevel_set_title(top, "idle-probe");
    xdg_toplevel_set_app_id(top, "idle-probe");
    wl_surface_commit(surface);
    while (!configured && wl_display_dispatch(display) != -1) {}
    int stride = width * 4, size = stride * height;
    int fd = memfd_create("idle-probe", 0);
    if (fd < 0 || ftruncate(fd, size) < 0) return -1;
    void *data = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (data == MAP_FAILED) return -1;
    memset(data, 0x40, size);
    struct wl_shm_pool *pool = wl_shm_create_pool(shm, fd, size);
    struct wl_buffer *buffer = wl_shm_pool_create_buffer(pool, 0, width, height, stride, WL_SHM_FORMAT_XRGB8888);
    wl_surface_attach(surface, buffer, 0, 0);
    wl_surface_damage(surface, 0, 0, width, height);
    return 0;
}

int main(int argc, char **argv) {
    int bare = argc > 1 && !strcmp(argv[1], "--bare");
    int seconds = argc > 1 + bare ? atoi(argv[1 + bare]) : 5;
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) { fprintf(stderr, "no Wayland display\n"); return 2; }
    wl_registry_add_listener(wl_display_get_registry(display), &reg_listener, NULL);
    wl_display_roundtrip(display);
    if (!compositor || !manager) { fprintf(stderr, "compositor without zwp_idle_inhibit_manager_v1\n"); return 3; }
    if (!bare && (!wm_base || !shm)) { fprintf(stderr, "compositor without xdg_wm_base or wl_shm\n"); return 3; }
    struct wl_surface *surface = wl_compositor_create_surface(compositor);
    if (!bare && show_window(display, surface) < 0) { fprintf(stderr, "no shm buffer\n"); return 4; }
    struct zwp_idle_inhibitor_v1 *inhibitor = zwp_idle_inhibit_manager_v1_create_inhibitor(manager, surface);
    wl_surface_commit(surface);
    wl_display_roundtrip(display);
    printf("inhibiting for %d s (%s)\n", seconds, bare ? "bare surface" : "shown window");
    fflush(stdout);
    for (int i = 0; i < seconds * 10; i++) {
        if (wl_display_roundtrip(display) == -1) break;
        usleep(100000);
    }
    zwp_idle_inhibitor_v1_destroy(inhibitor);
    wl_display_roundtrip(display);
    printf("released\n");
    int error = wl_display_get_error(display);
    wl_display_disconnect(display);
    return error ? 1 : 0;
}
