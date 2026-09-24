/* Screen capture through KWin's ScreenShot2 D-Bus interface (docs/64).
 *
 *   moto-screenshot screen <output-name>     one output, e.g. WL-0 or the TV
 *   moto-screenshot active-window            KWin's active window
 *
 * Writes one JSON line (width, height, stride, format, scale, screen) and then
 * the raw pixels to stdout. KWin allows ScreenShot2 only to executables whose
 * desktop file lists the interface (X-KDE-DBUS-Restricted-Interfaces); this
 * small program carries that permission instead of an interpreter such as
 * python3, which would extend it to every script. Captures are at native
 * resolution and without the cursor.
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <gio/gio.h>
#include <gio/gunixfdlist.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

typedef struct {
    int fd;
    GByteArray *data;
} Reader;

static gpointer read_all(gpointer user)
{
    Reader *reader = user;
    guint8 chunk[1 << 16];
    for (;;) {
        ssize_t n = read(reader->fd, chunk, sizeof chunk);
        if (n > 0)
            g_byte_array_append(reader->data, chunk, (guint)n);
        else if (n == 0 || errno != EINTR)
            break;
    }
    return NULL;
}

static void put_uint(GString *json, GVariant *results, const char *key)
{
    guint32 value = 0;
    if (g_variant_lookup(results, key, "u", &value))
        g_string_append_printf(json, "\"%s\":%u,", key, value);
}

int main(int argc, char **argv)
{
    const char *method;
    GVariantBuilder options;
    GVariant *parameters;
    g_variant_builder_init(&options, G_VARIANT_TYPE("a{sv}"));
    g_variant_builder_add(&options, "{sv}", "native-resolution", g_variant_new_boolean(TRUE));
    g_variant_builder_add(&options, "{sv}", "include-cursor", g_variant_new_boolean(FALSE));
    if (argc == 3 && strcmp(argv[1], "screen") == 0) {
        method = "CaptureScreen";
    } else if (argc == 2 && strcmp(argv[1], "active-window") == 0) {
        method = "CaptureActiveWindow";
        g_variant_builder_add(&options, "{sv}", "include-decoration", g_variant_new_boolean(FALSE));
    } else {
        fprintf(stderr, "usage: moto-screenshot screen <output-name> | active-window\n");
        return 2;
    }

    GError *error = NULL;
    GDBusConnection *bus = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, &error);
    if (!bus) {
        fprintf(stderr, "moto-screenshot: %s\n", error->message);
        return 1;
    }
    int fds[2];
    if (pipe2(fds, O_CLOEXEC) != 0) {
        perror("moto-screenshot: pipe");
        return 1;
    }
    GUnixFDList *fd_list = g_unix_fd_list_new();
    if (g_unix_fd_list_append(fd_list, fds[1], &error) < 0) {
        fprintf(stderr, "moto-screenshot: %s\n", error->message);
        return 1;
    }
    close(fds[1]);  /* the list holds its own copy; KWin gets another */

    /* KWin writes the image from its own thread, possibly before replying: drain
     * the pipe concurrently so a full pipe never blocks either side. */
    Reader reader = {fds[0], g_byte_array_new()};
    GThread *thread = g_thread_new("read", read_all, &reader);

    if (strcmp(method, "CaptureScreen") == 0)
        parameters = g_variant_new("(sa{sv}h)", argv[2], &options, 0);
    else
        parameters = g_variant_new("(a{sv}h)", &options, 0);
    GVariant *reply = g_dbus_connection_call_with_unix_fd_list_sync(
        bus, "org.kde.KWin", "/org/kde/KWin/ScreenShot2", "org.kde.KWin.ScreenShot2", method, parameters,
        G_VARIANT_TYPE("(a{sv})"), G_DBUS_CALL_FLAGS_NONE, 10000, fd_list, NULL, NULL, &error);
    g_object_unref(fd_list);  /* closes our write end, so the reader sees EOF once KWin is done */
    if (!reply) {
        fprintf(stderr, "moto-screenshot: %s\n", error->message);
        return 1;
    }
    g_thread_join(thread);
    close(fds[0]);

    GVariant *results = g_variant_get_child_value(reply, 0);
    GString *json = g_string_new("{");
    put_uint(json, results, "width");
    put_uint(json, results, "height");
    put_uint(json, results, "stride");
    put_uint(json, results, "format");
    gdouble scale = 1.0;
    if (g_variant_lookup(results, "scale", "d", &scale))
        g_string_append_printf(json, "\"scale\":%g,", scale);
    const gchar *screen = NULL;
    if (g_variant_lookup(results, "screen", "&s", &screen))
        g_string_append_printf(json, "\"screen\":\"%s\",", screen);
    g_string_append_printf(json, "\"bytes\":%u}\n", reader.data->len);
    fwrite(json->str, 1, json->len, stdout);
    fwrite(reader.data->data, 1, reader.data->len, stdout);
    return fflush(stdout) == 0 ? 0 : 1;
}
