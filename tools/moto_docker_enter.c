/* Launch the Docker Linux user-space environment in a private mount namespace.
 * Run as Magisk root. The container's own isolation is created by Docker/runc.
 * Nothing is mounted in Android's original mount namespace.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

#define ROOT "/data/adb/moto-docker/runtime"

static _Noreturn void fail(const char *what) {
    perror(what);
    exit(1);
}

/* Query the live policy, not just the intended mode in sepolicy.rule. */
static int print_selinux_mode(void) {
    unsigned cls, allowed, decided, auditallow, auditdeny, seqno, flags;
    FILE *index = fopen("/sys/fs/selinux/class/file/index", "r");
    if (!index || fscanf(index, "%u", &cls) != 1) fail("read SELinux file class");
    fclose(index);
    char request[160], response[256];
    int len = snprintf(request, sizeof(request),
        "u:r:moto_docker:s0 u:object_r:moto_docker_file:s0 %u 1", cls);
    int fd = open("/sys/fs/selinux/access", O_RDWR | O_CLOEXEC);
    if (fd < 0 || write(fd, request, len) != len) fail("query Docker SELinux mode");
    if (lseek(fd, 0, SEEK_SET) < 0) fail("seek SELinux response");
    ssize_t n = read(fd, response, sizeof(response) - 1);
    if (n <= 0) fail("read SELinux response");
    close(fd);
    response[n] = 0;
    if (sscanf(response, "%x %x %x %x %u %x", &allowed, &decided,
               &auditallow, &auditdeny, &seqno, &flags) != 6) {
        fprintf(stderr, "Invalid SELinux access response\n");
        return 1;
    }
    puts((flags & 1) ? "Permissive" : "Enforcing");
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 2 || geteuid() != 0) {
        fprintf(stderr, "Usage (root): moto-docker-enter /absolute/program [args...]\n");
        return 2;
    }
    if (argc == 2 && !strcmp(argv[1], "--selinux-mode"))
        return print_selinux_mode();
    if (argv[1][0] != '/') {
        fprintf(stderr, "Program must be an absolute path inside the runtime.\n");
        return 2;
    }
    if (unshare(CLONE_NEWNS) < 0) fail("unshare mount namespace");
    if (mount(NULL, "/", NULL, MS_PRIVATE | MS_REC, NULL) < 0)
        fail("make mounts private");
    if (mount(ROOT, ROOT, NULL, MS_BIND, NULL) < 0) fail("bind runtime");
    const char *names[] = {"proc", "sys", "dev"};
    for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); i++) {
        char source[32], target[256];
        snprintf(source, sizeof(source), "/%s", names[i]);
        snprintf(target, sizeof(target), ROOT "/%s", names[i]);
        if (mount(source, target, NULL, MS_BIND | MS_REC, NULL) < 0)
            fail(target);
    }
    /* Keep the familiar Android path for explicit user bind mounts. This
     * exposes shared storage to the daemon; containers only get their
     * explicitly selected subdirectories. Keep Android's FUSE semantics.
     */
    if (mount("/storage/emulated/0", ROOT "/storage/emulated/0", NULL,
              MS_BIND, NULL) < 0)
        fail("mount Android shared storage (unlock the phone first)");
    /* Stable source for the daemon's shared-storage UID adapter. */
    if (mount("/storage/emulated/0", ROOT "/mnt/android-shared", NULL,
              MS_BIND, NULL) < 0)
        fail("mount shared-storage adapter source");
    /* Keep image layers on ext4: Android's casefold-capable F2FS cannot
     * currently be used as an OverlayFS backing filesystem.
     */
    FILE *loop_file = fopen("/data/adb/moto-docker/data.loop", "r");
    char loop[128];
    if (!loop_file || !fgets(loop, sizeof(loop), loop_file)) fail("read data loop");
    fclose(loop_file);
    loop[strcspn(loop, "\r\n")] = 0;
    const char *prefix = "/dev/block/loop";
    if (strncmp(loop, prefix, strlen(prefix)) || !loop[strlen(prefix)] ||
        strspn(loop + strlen(prefix), "0123456789") != strlen(loop + strlen(prefix))) {
        fprintf(stderr, "Invalid Docker loop device\n");
        return 2;
    }
    if (mount(loop, ROOT "/var/lib/docker", "ext4", MS_NOATIME, NULL) < 0)
        fail("mount Docker ext4 data");
    /* Make the Linux userspace the namespace's actual root for runtimes
     * joining it through setns; remove the old Android root completely. */
    if (chdir(ROOT) < 0) fail("chdir runtime");
    if (mkdir(".oldroot", 0700) < 0 && errno != EEXIST) fail("mkdir oldroot");
    if (syscall(SYS_pivot_root, ".", ".oldroot") < 0) fail("pivot runtime");
    if (chdir("/") < 0) fail("chdir root");
    if (umount2("/.oldroot", MNT_DETACH) < 0) fail("detach old Android root");
    if (chdir("/root") < 0) fail("chdir home");
    /* Enter the dedicated Docker domain; its mode is managed by policy. */
    const char context[] = "u:r:moto_docker:s0";
    FILE *current = fopen("/proc/self/attr/current", "w");
    if (!current || fwrite(context, 1, sizeof(context) - 1, current) != sizeof(context) - 1 ||
        fclose(current) != 0)
        fail("enter Docker SELinux domain");
    if (clearenv() != 0 ||
        setenv("PATH", "/usr/sbin:/usr/bin:/sbin:/bin", 1) != 0 ||
        setenv("HOME", "/root", 1) != 0 ||
        setenv("TERM", "xterm-256color", 1) != 0)
        fail("environment");
    execv(argv[1], argv + 1);
    fail("exec runtime program");
}
