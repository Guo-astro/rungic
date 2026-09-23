#!/usr/bin/env python3
"""Offline Linux installer for the verified XT2537-4 clean/Magisk v3 images."""
import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

FINGERPRINT = 'motorola/mumba_cn/mumba:16/W1WAA36.48-23-10/1c41a-29619:user/release-keys'
BOOTLOADER = 'MBM-3.0-mumba_cn-134d447f1e26-260413-WWAA36V.48-23-ST12.4-1c41a'
BOOT_PARTS = ['boot', 'init_boot', 'vendor_boot', 'dtbo', 'recovery', 'pvmfw']
SUPER_CHUNKS = ['super.img_sparsechunk.' + str(i) for i in range(34)]
EXPECTED_PRODUCT_BYTES = 7613104128
PRODUCT_FILE_BYTES = 5045618204
PRODUCT_SHA256 = 'b5d417cb6cb30ff362e2f49b3a8923d410b96764da3428938977900899f24885'


class FlashError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise FlashError(message)


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(16 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify_payload(root):
    manifest = json.loads((root / 'payload-sha256.json').read_text())
    required = {'stock/' + n + '.img' for n in BOOT_PARTS}
    required.update('stock/' + n for n in SUPER_CHUNKS)
    required.update('images/' + n for n in ['product.img', 'init_boot.img', 'vbmeta.img', 'vbmeta_system.img'])
    required.update('tools/linux-x86_64/' + n for n in ['adb', 'fastboot', 'NOTICE.txt', 'source.properties'])
    if (root / 'delta').is_dir():
        required.remove('images/product.img')
        required.update(['delta/product.recipe.json.gz', 'delta/product.literals.gz', 'product_delta.py'])
    require(set(manifest) == required, '安装包清单缺失或包含意外文件；请重新解压完整包。')
    for i, name in enumerate(sorted(manifest), 1):
        require(sha256(root / name) == manifest[name], '文件校验失败：' + name)
        print('校验 {}/{}：{}'.format(i, len(manifest), name), flush=True)
    return manifest


def prepare_product(root):
    if (root / 'delta').is_dir():
        from product_delta import restore_product
        return restore_product(root, PRODUCT_SHA256, PRODUCT_FILE_BYTES)
    return root / 'images/product.img'


class Flasher:
    def __init__(self, root, serial=None):
        self.root = root
        self.serial = serial
        self.tools = root / 'tools/linux-x86_64'
        logs = root / 'logs'
        logs.mkdir(exist_ok=True)
        self.log_path = logs / ('flash-' + time.strftime('%Y%m%d-%H%M%S') + '.log')
        self.log = self.log_path.open('w', buffering=1)

    def run(self, tool, *args, host=False, timeout=240):
        cmd = [str(self.tools / tool)]
        if not host:
            require(bool(self.serial), '尚未选择设备。')
            cmd += ['-s', self.serial]
        cmd += [str(x) for x in args]
        line = '\n' + time.strftime('%Y-%m-%dT%H:%M:%S%z') + ' $ ' + ' '.join(cmd)
        print(line, flush=True)
        self.log.write(line + '\n')
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        timer = threading.Timer(timeout, p.kill)
        timer.start()
        output = []
        try:
            for line in p.stdout:
                print(line, end='', flush=True)
                self.log.write(line)
                output.append(line)
            code = p.wait()
        except BaseException:
            p.kill()
            p.wait()
            raise
        finally:
            timer.cancel()
        require(code == 0, '命令失败或超时，已停止后续刷写和清数据操作；日志：' + str(self.log_path))
        return ''.join(output)

    def fb(self, *args, **kwargs):
        return self.run('fastboot', *args, **kwargs)

    def var(self, name):
        output = self.fb('getvar', name)
        pieces = re.findall(re.escape(name) + r'\[(\d+)\]:\s*([^\r\n]+)', output)
        if pieces:
            return ''.join(v.strip() for _, v in sorted(pieces, key=lambda x: int(x[0])))
        found = re.search(r'(?:^|\n)(?:\(bootloader\)\s*)?' + re.escape(name) + r':\s*([^\r\n]+)', output)
        require(found is not None, '无法读取设备属性：' + name)
        return found.group(1).strip()

    def detect(self):
        adb = self.run('adb', 'devices', host=True)
        fb = self.run('fastboot', 'devices', host=True)
        states = {}
        for line in adb.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] in ['device', 'offline', 'unauthorized', 'authorizing']:
                states[parts[0]] = parts[1]
        for line in fb.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] in ['fastboot', 'fastbootd']:
                states[parts[0]] = 'fastboot'
        if self.serial:
            require(self.serial in states, '找不到指定设备：' + self.serial)
        else:
            require(len(states) == 1, '请只连接一台设备，并进入 Fastboot 或授权 USB 调试。')
            self.serial = next(iter(states))
        state = states[self.serial]
        require(state in ['device', 'fastboot'], '设备未授权或离线，请重新连接 USB 并允许调试，或手动进入 Fastboot。')
        return state

    def prepare(self, mode):
        state = self.detect()
        if state == 'device':
            def prop(name):
                return self.run('adb', 'shell', 'getprop ' + name).strip()
            require(prop('ro.boot.hardware.sku') == 'XT2537-4', '机型不匹配，只支持 XT2537-4。')
            require(prop('ro.bootloader') == BOOTLOADER, 'bootloader 版本不同，不能用本包自动恢复。')
            if mode == 'update':
                require(prop('ro.build.fingerprint') == FINGERPRINT, '保留数据更新要求相同原厂底包。')
                require(prop('ro.boot.slot_suffix') == '_a', '保留数据更新仅支持当前槽 a。')
            battery = self.run('adb', 'shell', 'dumpsys battery')
            level = re.search(r'^\s*level:\s*(\d+)', battery, re.M)
            require(level is not None and int(level.group(1)) >= 30, '请先充电至 30% 以上。')
            self.run('adb', 'reboot', 'bootloader')
        else:
            require(mode == 'full', '保留数据更新需要从已启动并授权调试的 Android 开始。')
        if self.var('is-userspace') == 'yes':
            self.fb('reboot', 'bootloader')
        self.check_bootloader()
        voltage = self.var('battery-voltage')
        require(voltage.isdigit() and int(voltage) >= 3700, '电池电压过低或无法确认，请充电后重试。')

    def check_bootloader(self):
        require(self.var('is-userspace') == 'no', '当前不是 bootloader fastboot。')
        require(self.var('product') == 'mumba', '产品型号不匹配。')
        require(self.var('sku') == 'XT2537-4', 'SKU 不匹配。')
        require(self.var('securestate') == 'flashing_unlocked', 'bootloader 尚未解锁。')
        require(self.var('version-bootloader') == BOOTLOADER, 'bootloader 版本不匹配；已停止，不降级底层固件。')

    def flash(self, mode):
        self.fb('oem', 'fb_mode_clear')
        if mode == 'full':
            self.fb('set_active', 'a')
        require(self.var('current-slot') == 'a', '目标槽不是 a。')
        for name in ['vbmeta', 'vbmeta_system']:
            self.fb('flash', name + '_a', self.root / 'images' / (name + '.img'))
        if mode == 'full':
            # Keep the matching GPT, bootloader, radio and calibration partitions.
            # Restore the complete Android system using Motorola's original chunks.
            for name in BOOT_PARTS:
                self.fb('flash', name, self.root / 'stock' / (name + '.img'))
            for name in SUPER_CHUNKS:
                self.fb('flash', 'super', self.root / 'stock' / name, timeout=900)
        self.fb('reboot', 'fastboot')
        require(self.var('is-userspace') == 'yes', '未能进入 fastbootd。')
        require(self.var('unlocked') == 'yes', 'fastbootd 报告设备未解锁。')
        require(self.var('current-slot') == 'a', 'fastbootd 当前槽不是 a。')
        require(int(self.var('partition-size:product_a'), 16) == EXPECTED_PRODUCT_BYTES, 'product_a 大小不匹配。')
        self.fb('-S', '256M', 'flash', 'product_a', self.root / 'images/product.img', timeout=900)
        require(int(self.var('partition-size:product_a'), 16) == EXPECTED_PRODUCT_BYTES, '刷写后 product_a 大小异常。')
        self.fb('reboot', 'bootloader')
        self.check_bootloader()
        require(self.var('current-slot') == 'a', '最终写入前目标槽变化。')
        self.fb('flash', 'init_boot_a', self.root / 'images/init_boot.img')
        if mode == 'full':
            self.fb('erase', 'userdata')
            self.fb('erase', 'metadata')
        self.fb('oem', 'fb_mode_clear')
        self.fb('reboot')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['full', 'update'], default='full')
    parser.add_argument('--serial')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--prepare-only', action='store_true', help='校验并还原完整镜像，不连接手机')
    parser.add_argument('--yes-wipe', action='store_true', help='明确接受完整重装清空所有用户数据，用于无人值守执行')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    require(sys.platform == 'linux' and platform.machine() in ['x86_64', 'amd64'], '本包自带工具仅支持 Linux x86_64。')
    print('XT2537-4 / W1WAA36.48-23-10 / clean Magisk v3', flush=True)
    verify_payload(root)
    if args.verify_only:
        print('全部文件校验通过；未连接或修改设备。')
        return
    prepare_product(root)
    if args.prepare_only:
        print('镜像准备完成；未连接或修改设备。')
        return
    require(not args.yes_wipe or args.mode == 'full', '--yes-wipe 仅适用于完整重装。')
    flasher = Flasher(root, args.serial)
    flasher.prepare(args.mode)
    if args.mode == 'full' and not args.yes_wipe:
        print('\n目标设备：' + flasher.serial)
        print('完整重装会清空这台手机的所有用户数据。镜像已校验，机型与底层版本匹配。')
        require(input('输入 WIPE 开始，其他输入取消：').strip() == 'WIPE', '已取消，尚未写入或清除任何分区。')
    flasher.flash(args.mode)
    result = dict(serial=flasher.serial, mode=args.mode, flash_complete=True,
                  factory_reset=args.mode == 'full', reboot_sent=True,
                  boot_verification='请等待 Android 启动并确认 Magisk 31.0', log=str(flasher.log_path))
    (root / 'last-install.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('\n刷写成功，已重启。首启会离线安装完整 Magisk；正常开机不会重复安装。')


if __name__ == '__main__':
    try:
        main()
    except (FlashError, OSError, ValueError, EOFError) as e:
        print('\n停止：' + str(e), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\n已中断；不要直接启动未完成的系统，请保留日志并重新执行完整刷写。', file=sys.stderr)
        sys.exit(130)
