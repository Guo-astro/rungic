# SPDX-License-Identifier: MIT
"""The container's sound without the phone (docs/48, docs/62): the container's PulseAudio runs with
its own configuration (system/pulse.pa), tunnelled to a stand-in of Android's PulseAudio (the app's
system/android-audio.pa, its OpenSL ES sink replaced by a null sink that can be listened to), and the
media bridge (rungic-media-bridge) runs against stand-ins of the platform bridge (its contract's
capture-info) and of the app's capture socket (tools/system/android_media.py: a microphone that plays
a sine). Checked: the default devices, the Android output suspending and coming back, the microphone
opened only while something records, the virtual Linux speaker and microphone (created after the
Android output, never the default, lossless), rungic-audio-route moving one program's streams and
back, and the microphone and phone output still working when the virtual devices cannot be made."""
import json
import math
import os
import shutil
import signal
import struct
import subprocess
import time
from pathlib import Path

import android_media
import contracts
import harness

SRC = Path('/src')
WORK = Path('/tmp/audio-test')
STEPS = []


def check(condition, what, detail=''):
    STEPS.append(what)
    if not condition:
        raise harness.Failed(f'{what}: not so {detail}'.rstrip() + logs())


def logs():
    out = ''
    for name in ('bridge.log', 'container-pa.log', 'android-pa.log'):
        path = WORK / name
        if path.exists():
            out += f'\n--- {name} ---\n' + path.read_text(errors='replace')[-1500:]
    return out


def wait(condition, what, timeout=10):
    deadline = time.monotonic() + timeout
    while True:
        value = condition()
        if value:
            STEPS.append(what)
            return value
        if time.monotonic() > deadline:
            raise harness.Failed(f'timed out waiting for {what}' + logs())
        time.sleep(0.2)


def pactl(*args, server=None):
    env = {**os.environ, 'LC_ALL': 'C', **({'PULSE_SERVER': server} if server else {})}
    return subprocess.run(['pactl', *args], capture_output=True, text=True, env=env, timeout=10).stdout.strip()


def devices(kind):
    """name -> state of `pactl list short sinks|sources`."""
    out = {}
    for line in pactl('list', 'short', kind).splitlines():
        fields = line.split('\t')
        if len(fields) >= 5:
            out[fields[1]] = fields[4]
    return out


def streams(kind):
    """[(index, device index, binary)] of sink-inputs or source-outputs."""
    header = 'Sink Input #' if kind == 'sink-inputs' else 'Source Output #'
    key = 'Sink:' if kind == 'sink-inputs' else 'Source:'
    found, current = [], None
    for line in pactl('list', kind).splitlines():
        if line.startswith(header):
            current = [line[len(header):].strip(), None, None]
            found.append(current)
        elif current and line.strip().startswith(key):
            current[1] = line.split(':', 1)[1].strip()
        elif current and 'application.process.binary = ' in line:
            current[2] = line.split('=', 1)[1].strip().strip('"')
    return found


def index_of(kind, name):
    for line in pactl('list', 'short', kind).splitlines():
        fields = line.split('\t')
        if len(fields) >= 2 and fields[1] == name:
            return fields[0]
    return None


def on(binary, kind):
    """The devices (by name) the binary's streams of this kind are on."""
    devices_kind = 'sinks' if kind == 'sink-inputs' else 'sources'
    names = {index_of(devices_kind, n): n for n in devices(devices_kind)}
    return sorted(names.get(device, device) for _, device, b in streams(kind) if b == binary)


def sine(seconds, channels, amplitude=10000, frequency=1000):
    frames = int(48000 * seconds)
    return b''.join(struct.pack('<h', int(amplitude * math.sin(2 * math.pi * frequency * i / 48000))) * channels
                    for i in range(frames))


def rms(data, channels):
    samples = struct.unpack(f'<{len(data) // 2}h', data[:len(data) // 2 * 2])[::channels]
    loud = [i for i, s in enumerate(samples) if abs(s) > 200]
    if len(loud) < 4800:
        return 0.0
    middle = samples[loud[0]:loud[-1]]
    middle = middle[len(middle) // 4:len(middle) * 3 // 4]
    return math.sqrt(sum(s * s for s in middle) / len(middle))


class Recording:
    def __init__(self, device, channels, server=None, binary='parec'):
        env = {**os.environ, **({'PULSE_SERVER': server} if server else {})}
        self.path = WORK / f'rec-{time.monotonic_ns()}.raw'
        self.channels = channels
        self.process = subprocess.Popen([binary, '--record', f'--device={device}', '--raw', '--format=s16le',
                                         '--rate=48000', f'--channels={channels}', '--latency-msec=20'],
                                        stdout=open(self.path, 'wb'), env=env)

    def stop(self):
        self.process.send_signal(signal.SIGINT)
        self.process.wait(5)
        return rms(self.path.read_bytes(), self.channels)


def play(device, data, channels):
    subprocess.run(['pacat', '--playback', f'--device={device}', '--raw', '--format=s16le', '--rate=48000',
                    f'--channels={channels}', '--latency-msec=20'], input=data, check=True, timeout=20)


def pulseaudio(config, log, env):
    return subprocess.Popen(['pulseaudio', '-n', '-F', str(config), '--daemonize=no', '--exit-idle-time=-1',
                             '--use-pid-file=no', '--realtime=no', '--high-priority=no', f'--log-target=file:{log}'],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def configs():
    """The container's and Android's PulseAudio configurations as shipped, at this test's paths."""
    cookie, android = WORK / 'cookie', WORK / 'android'
    container = (SRC / 'system/pulse.pa').read_text()
    for path in ('/var/lib/rungic-host/audio-cookie', '/mnt/android-audio/native'):
        assert path in container, f'system/pulse.pa no longer names {path}'
    container = container.replace('/var/lib/rungic-host/audio-cookie', str(cookie)) \
        .replace('/mnt/android-audio/native', str(android / 'native'))
    provider = (SRC / 'system/android-audio.pa').read_text()
    termux = '/data/data/com.termux/files/usr/tmp/rungic-plasma-audio'
    assert termux in provider and 'module-sles-sink' in provider
    provider = '\n'.join('load-module module-null-sink sink_name=android_output rate=48000 channels=2'
                         if 'module-sles-sink' in line else line for line in provider.splitlines())
    provider = provider.replace(f'{termux}/native', str(android / 'native')).replace(f'{termux}/cookie', str(cookie))
    (WORK / 'container.pa').write_text(container)
    (WORK / 'android.pa').write_text(provider)


# covers[system]: apps.phone-audio/E1 apps.phone-audio/E2 apps.phone-audio/E3
# covers[system]: apps.virtual-audio/E1 apps.virtual-audio/E2 apps.virtual-audio/E3 apps.virtual-audio/E4
# covers[system]: apps.wechat/E2
# covers[consumer]: iface:audio iface:platform-bridge
def test():
    shutil.rmtree(WORK, ignore_errors=True)
    (WORK / 'android').mkdir(parents=True)
    (WORK / 'cookie').write_bytes(os.urandom(256))
    runtime = Path(f'/tmp/rt-{os.getuid()}')
    runtime.mkdir(mode=0o700, exist_ok=True)
    os.environ.update(XDG_RUNTIME_DIR=str(runtime), PULSE_COOKIE=str(WORK / 'cookie'), LANG='C.UTF-8')
    configs()
    android_server = f'unix:{WORK / "android/native"}'
    capture_info = {**contracts.query(contracts.load('platform-bridge'), {'op': 'capture-info'})['reply'],
                    'cameras': []}
    children = []
    try:
        with contracts.StandIn('platform-bridge', {'capture-info': capture_info}) as bridge, \
                android_media.Capture() as capture:
            os.environ.update(RUNGIC_PLATFORM_SOCKET=bridge.path, RUNGIC_CAPTURE_SOCKET=capture.path)
            android_env = {**os.environ, 'XDG_RUNTIME_DIR': str(WORK / 'android'), 'HOME': str(WORK / 'android'),
                           'PULSE_STATE_PATH': str(WORK / 'android/state'),
                           # Not on this session's bus: the container's PulseAudio takes org.PulseAudio1 there.
                           'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/nonexistent'}
            children.append(pulseaudio(WORK / 'android.pa', WORK / 'android-pa.log', android_env))
            wait(lambda: pactl('info', server=android_server), 'Android\'s PulseAudio (the stand-in) runs')
            virtual_devices_wait_for_android()

            # The phone's boot: the container's PulseAudio with system/pulse.pa, then the bridge.
            os.environ['PULSE_STATE_PATH'] = str(WORK / 'state')
            children.append(pulseaudio(WORK / 'container.pa', WORK / 'container-pa.log', os.environ))
            wait(lambda: 'android' in devices('sinks'), 'the tunnel to Android (sink android) is there', 20)
            bridge_log = open(WORK / 'bridge.log', 'w')
            media = subprocess.Popen(['python3', '/usr/bin/rungic-media-bridge'], stdout=bridge_log, stderr=subprocess.STDOUT)
            children.append(media)
            wait(lambda: 'android_microphone' in devices('sources') and 'android_phone' in devices('sinks')
                 and {'linux_speaker', 'linux_microphone_input'} <= set(devices('sinks'))
                 and 'linux_microphone' in devices('sources'),
                 'the bridge adds the Android microphone, the phone output and the Linux speaker and microphone')
            check(pactl('get-default-sink') == 'android', 'the default output is android', f'({pactl("get-default-sink")})')
            check(pactl('get-default-source') == 'android_microphone', 'the default input is android_microphone',
                  f'({pactl("get-default-source")}; android.monitor is not a microphone)')
            described = pactl('list', 'sinks')
            check('Description: Linux Speaker' in described and 'Description: Linux Microphone Input' in described,
                  'the virtual devices carry their names with spaces')

            # The Android output: sound arrives on Android's side, then it suspends; again and again.
            for round_ in range(1, 4):
                listener = Recording('android_output.monitor', 2, server=android_server)
                time.sleep(0.3)
                play('@DEFAULT_SINK@', sine(1.0, 2), 2)
                time.sleep(1.0)
                level = listener.stop()
                check(level > 3000, f'round {round_}: what plays on the default output reaches Android', f'(rms {level:.0f})')
                wait(lambda: devices('sinks').get('android') == 'SUSPENDED', f'round {round_}: then the output suspends', 10)

            # The microphone: Android records only while something records from it.
            check('microphone' not in capture.ops(), 'no Android recording while nothing records')
            recording = Recording('android_microphone', 1)
            wait(lambda: capture.count('microphone') == 1, 'recording starts Android\'s microphone', 8)
            time.sleep(1.5)
            level = recording.stop()
            check(level > 1000, 'what Android records arrives', f'(rms {level:.0f})')
            wait(lambda: capture.count('microphone') == 0, 'when recording ends the Android microphone stops', 8)
            wait(lambda: devices('sources').get('android_microphone') == 'SUSPENDED', 'and the source suspends', 10)
            # The Linux desktop not in front (the app in the background): nothing opens the microphone.
            capture_info['visible'], capture.visible = False, False
            time.sleep(2.5)
            asked = capture.ops().count('microphone')
            recording = Recording('android_microphone', 1)
            time.sleep(4)
            recording.stop()
            check(capture.ops().count('microphone') == asked, 'in the background the microphone is not opened')
            capture_info['visible'], capture.visible = True, True
            time.sleep(2)

            # The virtual devices are lossless: gain 1 through the Linux microphone and the speaker's monitor.
            for target, source, channels in (('linux_microphone_input', 'linux_microphone', 1),
                                             ('linux_speaker', 'linux_speaker.monitor', 2)):
                listener = Recording(source, channels)
                time.sleep(0.3)
                play(target, sine(1.0, channels), channels)
                time.sleep(0.3)
                level = listener.stop()
                check(abs(level / 7071.07 - 1) < 0.01, f'{target} comes out of {source} unchanged', f'(rms {level:.1f})')

            route_one_program()
            virtual_devices_fail(media, bridge_log, capture)
    finally:
        for child in reversed(children):
            child.terminate()
            try:
                child.wait(5)
            except subprocess.TimeoutExpired:
                child.kill()
    return STEPS


def virtual_devices_wait_for_android():
    """The virtual devices are made only once the Android output is there: the container's PulseAudio
    without its tunnel first, the tunnel loaded later with the arguments system/pulse.pa gives it."""
    tunnel = next(line for line in (WORK / 'container.pa').read_text().splitlines()
                  if line.startswith('load-module module-tunnel-sink-new'))
    (WORK / 'no-tunnel.pa').write_text((WORK / 'container.pa').read_text().replace(tunnel, ''))
    env = {**os.environ, 'PULSE_STATE_PATH': str(WORK / 'state-before')}
    server = pulseaudio(WORK / 'no-tunnel.pa', WORK / 'container-pa.log', env)
    media = subprocess.Popen(['python3', '/usr/bin/rungic-media-bridge'], stdout=open(WORK / 'bridge.log', 'w'),
                             stderr=subprocess.STDOUT, env=env)
    try:
        wait(lambda: 'android_microphone' in devices('sources') and 'android_phone' in devices('sinks'),
             'the bridge adds the Android microphone and the phone output')
        time.sleep(3)
        check('linux_speaker' not in devices('sinks') and 'linux_microphone' not in devices('sources'),
              'no Linux speaker or microphone while there is no Android output')
        pactl('load-module', *tunnel.split()[1:])
        wait(lambda: 'android' in devices('sinks'), 'the Android output appears')
        wait(lambda: {'linux_speaker', 'linux_microphone_input'} <= set(devices('sinks'))
             and 'linux_microphone' in devices('sources'), 'then the Linux speaker and microphone are made')
        time.sleep(1)
        ours = ('linux_speaker', 'linux_microphone_input', 'linux_microphone')
        check(not pactl('get-default-sink').startswith(ours) and pactl('get-default-source') == 'android_microphone',
              'they are not the default devices', f'({pactl("get-default-sink")}, {pactl("get-default-source")})')
    finally:
        media.terminate()
        media.wait(10)
        server.terminate()
        server.wait(10)


def route_one_program():
    """rungic-audio-route moves WeChat's streams, call streams named "Chromium" like other apps'."""
    apps = WORK / 'apps'
    apps.mkdir()
    for name in ('wechat', 'otherapp'):
        shutil.copy('/usr/bin/pacat', apps / name)
    os.environ['PULSE_PROP'] = 'application.name=Chromium'
    other = Recording('@DEFAULT_SOURCE@', 1, binary=str(apps / 'otherapp'))
    talk = Recording('@DEFAULT_SOURCE@', 1, binary=str(apps / 'wechat'))
    listen = subprocess.Popen([str(apps / 'wechat'), '--playback', '--raw'], stdin=open('/dev/zero', 'rb'))
    wait(lambda: on('wechat', 'source-outputs') == ['android_microphone'] and on('wechat', 'sink-inputs') == ['android'],
         'a WeChat call records and plays on the Android devices')
    for ending in ('stdin', signal.SIGTERM, signal.SIGINT):
        router = subprocess.Popen(['python3', '/usr/bin/rungic-audio-route', '--binary', 'wechat', '--microphone', '--speaker'],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        label = ending if ending == 'stdin' else signal.Signals(ending).name
        check(router.stdout.readline().strip() == 'ready', f'rungic-audio-route says ready first (ended by {label})')
        wait(lambda: on('wechat', 'source-outputs') == ['linux_microphone'] and on('wechat', 'sink-inputs') == ['linux_speaker'],
             'the call\'s streams move to the Linux microphone and speaker')
        check(on('otherapp', 'source-outputs') == ['android_microphone'], 'another "Chromium" program stays where it is')
        later = Recording('@DEFAULT_SOURCE@', 1, binary=str(apps / 'wechat'))
        wait(lambda: on('wechat', 'source-outputs') == ['linux_microphone', 'linux_microphone'],
             'a stream WeChat opens later moves too')
        if ending == 'stdin':
            router.stdin.close()
        else:
            router.send_signal(ending)
        router.wait(10)
        wait(lambda: on('wechat', 'source-outputs') == ['android_microphone', 'android_microphone']
             and on('wechat', 'sink-inputs') == ['android'], f'routing ended by {label}: every stream is back')
        later.stop()
    for p in (other, talk):
        p.stop()
    listen.terminate()
    listen.wait(5)
    fresh = Recording('@DEFAULT_SOURCE@', 1, binary=str(apps / 'otherapp'))
    wait(lambda: on('otherapp', 'source-outputs') == ['android_microphone'],
         'a new "Chromium" stream afterwards opens on the default microphone (the move is not remembered)')
    fresh.stop()
    del os.environ['PULSE_PROP']


def virtual_devices_fail(media, bridge_log, capture):
    """The virtual devices cannot be made (their modules fail to load): the rest works as before."""
    media.terminate()
    media.wait(10)
    for module in ('module-null-sink', 'module-remap-source', 'module-pipe-source', 'module-pipe-sink'):
        pactl('unload-module', module)
    check(not {'linux_speaker', 'android_phone'} & set(devices('sinks')), 'the bridge\'s devices are gone')
    failing = WORK / 'failing-bin'
    failing.mkdir()
    (failing / 'pactl').write_text('#!/bin/sh\ncase "$*" in *module-null-sink*|*module-remap-source*) '
                                   'echo "Failure: Module initialization failed" >&2; exit 1;; esac\n'
                                   'exec /usr/bin/pactl "$@"\n')
    (failing / 'pactl').chmod(0o755)
    env = {**os.environ, 'PATH': f'{failing}:{os.environ["PATH"]}'}
    restarted = subprocess.Popen(['python3', '/usr/bin/rungic-media-bridge'], stdout=bridge_log, stderr=subprocess.STDOUT, env=env)
    try:
        wait(lambda: 'android_microphone' in devices('sources') and 'android_phone' in devices('sinks'),
             'without virtual devices the bridge still adds the microphone and the phone output')
        wait(lambda: 'Linux speaker/microphone not available' in (WORK / 'bridge.log').read_text(), 'and logs a warning')
        check('linux_speaker' not in devices('sinks'), 'no Linux speaker')
        check(pactl('get-default-sink') == 'android' and pactl('get-default-source') == 'android_microphone',
              'the defaults are the Android devices')
        recording = Recording('android_microphone', 1)
        wait(lambda: capture.count('microphone') == 1, 'recording still starts Android\'s microphone', 8)
        time.sleep(1.5)
        level = recording.stop()
        check(level > 1000, 'and its sound arrives', f'(rms {level:.0f})')
        before = capture.received.get('phone-output', 0)
        play('android_phone', sine(0.5, 2), 2)
        wait(lambda: capture.received.get('phone-output', 0) > before + 48000, '"This Phone" still plays on the phone')
        check(restarted.poll() is None, 'the bridge keeps running')
    finally:
        restarted.terminate()
        restarted.wait(10)


if __name__ == '__main__':
    harness.run('media_audio', test)
