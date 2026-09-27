#!/system/bin/sh
# The rootfs snapshot rollback (plasma/rootfs-image) on a small test image, never the system's: dataset A,
# a snapshot, rounds that replace A (reusing its blocks) and leave without unmounting, a rollback;
# then fsck and A's checksums. Android side, Magisk root (docs/70, the 2026-09-27 incident).
#   rollback-test.sh SCRIPT ROUNDS [MERGE_ROUNDS]
# MERGE_ROUNDS (default 0): after the rollback, rounds that mount the merging device at once, write
# dataset C and detach before the merge has finished, as a container started on it does.
# SCRIPT: a copy of plasma/rootfs-image. The copy is rewritten to use a test directory and test
# device-mapper names, with the "container running" check disabled.
set -eu
SRC=$1; ROUNDS=${2:-3}; MERGE_ROUNDS=${3:-0}
T=/data/local/tmp/rungic-rootfs-test
rm -rf "$T"; mkdir -p "$T/lxc/images"
# Every path of the copy must point into $T: on 2026-09-27 a copy that still had the system's
# IMAGES= ran against the live system image and corrupted it.
sed -e "s#^LXC=.*#LXC=$T/lxc#" -e "s#^IMAGES=.*#IMAGES=$T/lxc/images#" -e 's#^ROOT_DM=.*#ROOT_DM=rungic-test-root#' \
    -e 's#^SNAP_DM=.*#SNAP_DM=rungic-test-before#' -e 's#^need_stopped() .*#need_stopped() { true; }#' \
    -e 's#^COW_SIZE=.*#COW_SIZE=1G#' "$SRC" > "$T/rootfs-image"
R="sh $T/rootfs-image"
grep -q "^IMAGES=$T/lxc/images\$" "$T/rootfs-image" || { echo "test copy does not use the test images" >&2; exit 1; }
! grep -n '/data/adb/rungic-lxc' "$T/rootfs-image" | grep -v '^[0-9]*:#' | grep -v -e rungic-plasma-enter -e /rootfs.sepolicy.rule || {
    echo "test copy still names the system's paths" >&2; exit 1; }
IMG=$T/lxc/images/rootfs.img
truncate -s 768M "$IMG"; mke2fs -q -t ext4 -L test-root "$IMG"
echo none > "$T/lxc/images/state"
M=$T/mnt; mkdir -p "$M"

# Dataset A: many small files in many directories; its checksums are the reference.
dev=$($R attach)
unshare -m sh -c "/data/adb/magisk/busybox mount --make-rprivate / && mount -t ext4 $dev $M
for d in \$(seq 1 60); do mkdir -p $M/a/\$d; for f in \$(seq 1 40); do head -c \$((\$f*37+500)) /dev/urandom > $M/a/\$d/\$f; done; done
(cd $M && find a -type f | sort | xargs md5sum) > $T/a.md5
umount $M"
$R detach
$R snapshot >/dev/null

# The deploy: remove A, write B (reusing A's blocks), then leave without unmounting: the mount
# namespace goes with the process, and the next step detaches at once, as moto-plasma stop does.
for round in $(seq 1 "$ROUNDS"); do
    dev=$($R attach)
    unshare -m sh -c "/data/adb/magisk/busybox mount --make-rprivate / && mount -t ext4 $dev $M
    rm -rf $M/a $M/b$round
    for d in \$(seq 1 60); do mkdir -p $M/b$round/\$d; for f in \$(seq 1 40); do head -c \$((\$f*41+300)) /dev/urandom > $M/b$round/\$d/\$f; done; done
    sync -f $M 2>/dev/null || true
    exit 0"
    $R detach || echo "round $round: detach failed"
done

# Roll back: the snapshot merges back; then check the filesystem and dataset A.
$R rollback >/dev/null
# The container starts on the merging device right away and writes while the merge runs; the next
# stop detaches it whether or not the merge has finished (the merge resumes from the COW).
for round in $(seq 1 "$MERGE_ROUNDS"); do
    dev=$($R attach)
    unshare -m sh -c "/data/adb/magisk/busybox mount --make-rprivate / && mount -t ext4 $dev $M
    for d in \$(seq 1 30); do mkdir -p $M/c$round/\$d; for f in \$(seq 1 40); do head -c \$((\$f*43+200)) /dev/urandom > $M/c$round/\$d/\$f; done; done
    rm -rf $M/c\$(($round-1))
    sync -f $M 2>/dev/null || true
    exit 0"
    echo "merge round $round: $(dmctl status rungic-test-root | tail -n1)"
    $R detach || echo "merge round $round: detach failed"
    echo "  state $(cat $T/lxc/images/state)"
done
dev=$($R attach)
for i in $(seq 1 300); do
    set -- $(dmctl status rungic-test-root | tail -n1 | tr '/' ' ' | awk '{print $(NF-2), $NF}')
    [ "$1" = "$2" ] && break; sleep 0.2
done
$R detach
echo "state after merge: $(cat $T/lxc/images/state)"
if e2fsck -fn "$IMG" > "$T/fsck.txt" 2>&1; then echo "fsck: clean"; else echo "fsck: ERRORS ($(grep -c '' $T/fsck.txt) lines)"; fi
dev=$($R attach)
unshare -m sh -c "/data/adb/magisk/busybox mount --make-rprivate / && mount -t ext4 -o ro $dev $M && (cd $M && md5sum -c $T/a.md5 2>/dev/null | grep -vc ': OK\$'); umount $M" > "$T/bad.txt" || true
echo "dataset A files not intact: $(cat $T/bad.txt) of $(grep -c '' $T/a.md5)"
$R detach
