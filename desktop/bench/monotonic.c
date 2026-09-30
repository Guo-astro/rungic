// SPDX-License-Identifier: MIT
// Android shell clock marker; timestamps use the same clock as SurfaceFlinger.
#include <stdio.h>
#include <time.h>
int main(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC,&ts)) return 1;
    printf("%lld\n",(long long)ts.tv_sec*1000000000LL+ts.tv_nsec);
    return 0;
}
