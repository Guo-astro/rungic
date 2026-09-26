// Holds a zwp_idle_inhibitor_v1 on a surface for N seconds (docs/72). Connected to the Android
// host's socket it tests the host alone (the APK window must gain FLAG_KEEP_SCREEN_ON); as a
// client of KWin it tests KWin forwarding the inhibition to the host.
//   idle-probe [seconds]      (default 5; WAYLAND_DISPLAY selects the compositor)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wayland-client.h>
#include "idle-inhibit-unstable-v1-client-protocol.h"

static struct wl_compositor *compositor;
static struct zwp_idle_inhibit_manager_v1 *manager;

static void global(void *d, struct wl_registry *r, uint32_t n, const char *i, uint32_t v) {
    if (!strcmp(i, "wl_compositor")) compositor = wl_registry_bind(r, n, &wl_compositor_interface, 4);
    else if (!strcmp(i, "zwp_idle_inhibit_manager_v1")) manager = wl_registry_bind(r, n, &zwp_idle_inhibit_manager_v1_interface, 1);
}
static void global_remove(void *d, struct wl_registry *r, uint32_t n) {}
static const struct wl_registry_listener listener = { global, global_remove };

int main(int argc, char **argv) {
    int seconds = argc > 1 ? atoi(argv[1]) : 5;
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) { fprintf(stderr, "no Wayland display\n"); return 2; }
    wl_registry_add_listener(wl_display_get_registry(display), &listener, NULL);
    wl_display_roundtrip(display);
    if (!compositor || !manager) { fprintf(stderr, "compositor without zwp_idle_inhibit_manager_v1\n"); return 3; }
    struct wl_surface *surface = wl_compositor_create_surface(compositor);
    struct zwp_idle_inhibitor_v1 *inhibitor = zwp_idle_inhibit_manager_v1_create_inhibitor(manager, surface);
    wl_surface_commit(surface);
    wl_display_roundtrip(display);
    printf("inhibiting for %d s\n", seconds);
    fflush(stdout);
    sleep(seconds);
    zwp_idle_inhibitor_v1_destroy(inhibitor);
    wl_display_roundtrip(display);
    printf("released\n");
    int error = wl_display_get_error(display);
    wl_display_disconnect(display);
    return error ? 1 : 0;
}
