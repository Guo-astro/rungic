// SPDX-License-Identifier: MIT
// Write a decompressed image from stdin, preserving zero regions as holes.
#define _FILE_OFFSET_BITS 64
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static void fail(const char *path, int fd) {
    perror(path);
    if (fd >= 0) close(fd);
    unlink(path);
    exit(1);
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: rungic-sparse-write OUTPUT EXPECTED_BYTES\n");
        return 2;
    }
    char *end = NULL;
    errno = 0;
    unsigned long long expected = strtoull(argv[2], &end, 10);
    if (errno || !end || *end || !expected || expected > INT64_MAX) {
        fprintf(stderr, "invalid expected image length\n");
        return 2;
    }
    int fd = open(argv[1], O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (fd < 0) {
        perror(argv[1]);
        return 1;
    }
    unsigned char buffer[1024 * 1024];
    unsigned long long count = 0;
    for (;;) {
        ssize_t got = read(STDIN_FILENO, buffer, sizeof(buffer));
        if (got < 0 && errno == EINTR) continue;
        if (got < 0) fail(argv[1], fd);
        if (!got) break;
        if ((unsigned long long) got > expected - count) {
            errno = EFBIG;
            fail(argv[1], fd);
        }
        count += (unsigned long long) got;
        size_t index = 0;
        while (index < (size_t) got && buffer[index] == 0) index++;
        if (index == (size_t) got) {
            if (lseek(fd, got, SEEK_CUR) < 0) fail(argv[1], fd);
            continue;
        }
        ssize_t written = 0;
        while (written < got) {
            ssize_t step = write(fd, buffer + written, (size_t) (got - written));
            if (step < 0 && errno == EINTR) continue;
            if (step <= 0) fail(argv[1], fd);
            written += step;
        }
    }
    if (count != expected) {
        errno = EIO;
        fail(argv[1], fd);
    }
    if (ftruncate(fd, (off_t) count) || fsync(fd) || close(fd)) fail(argv[1], -1);
    printf("%llu bytes written\n", count);
    return 0;
}
