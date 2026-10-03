"""The crash chain without the phone, on real cores (docs/61): a small program aborts under gdb, which
saves its core where the kernel would; the phone's own collector (system/diagnostics/
rungic-coredump-collect) turns it into a report, the MCP's crash_groups script groups the reports, and
the build host's analysis (tools/rungic_crash_symbolize.py) symbolizes one from a sysroot.

What only the phone shows: that the kernel writes desktop cores into the container's /data/app_dump
while Android's core_pattern stays its own, that journald and coredumpctl read the entries, and that
gdb on a desktop process's symbols would exhaust the phone (acceptance crash.new, docs/61)."""
import compression.zstd as zstd
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rungic_agent  # noqa: E402
import rungic_crash_symbolize  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / 'system/diagnostics/rungic-coredump-collect'
SOURCE = r'''#include <stdlib.h>
#include <string.h>
__attribute__((noinline)) void inner_fault(int n) { if (n > 0) abort(); }
__attribute__((noinline)) void outer_call(int n) { inner_fault(n); }
__attribute__((noinline)) void other_fault(void) { volatile int *p = 0; *p = 1; }
int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "segv")) other_fault();
    outer_call(argc);
    return 0;
}
'''
NO_PID = 4999999          # above any pid_max: the crashed process is gone
pytestmark = pytest.mark.skipif(not (shutil.which('gdb') and shutil.which('gcc') and shutil.which('objcopy')),
                                reason='needs gdb, gcc and binutils')


def load_collector():
    loader = importlib.machinery.SourceFileLoader('rungic_coredump_collect', str(COLLECTOR))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A container in miniature: spool, store, release files; gdb never asks debuginfod."""
    monkeypatch.setenv('DEBUGINFOD_URLS', '')
    collect = load_collector()
    root = tmp_path / 'root'
    spool, store = root / 'data/app_dump', root / 'var/lib/rungic-cores'
    spool.mkdir(parents=True)
    release, installed = root / 'release.json', root / 'rungic-release.list'
    monkeypatch.setattr(collect, 'SPOOL', spool)
    monkeypatch.setattr(collect, 'STORE', store)
    monkeypatch.setattr(collect, 'RELEASE', release)
    monkeypatch.setattr(collect, 'RELEASE_INSTALLED', installed)
    monkeypatch.setattr(collect, 'time', types.SimpleNamespace(monotonic=time.monotonic, sleep=lambda s: None))
    journal = []
    monkeypatch.setattr(collect, 'journal_send', journal.append)
    build = tmp_path / 'build'
    build.mkdir()
    (build / 'crash.c').write_text(SOURCE)
    subprocess.run(['gcc', '-g', '-O0', '-o', build / 'crasher', build / 'crash.c'], check=True)
    return types.SimpleNamespace(collect=collect, spool=spool, store=store, release=release, installed=installed,
                                 journal=journal, build=build, root=root)


def make_core(env, when, *args, exe=None):
    """Run the program under gdb until it crashes and save the core into the spool, named as
    Android's core_pattern names it (%e_%p_%t.core.gz, an uncompressed core)."""
    exe = exe or env.build / 'crasher'
    core = env.spool / f'crasher_{NO_PID}_{int(when)}.core.gz'
    done = subprocess.run(['gdb', '-batch', '-nx', '-ex', 'run', '-ex', f'generate-core-file {core}',
                           '--args', str(exe), *args], capture_output=True, text=True, cwd=env.build)
    assert core.exists(), done.stdout[-2000:] + done.stderr[-2000:]
    return core


def install_release(env, version, installed_at):
    env.release.write_text(json.dumps({'version': version, 'commit': 'abc1234'}))
    env.installed.write_text('')
    os.utime(env.installed, (installed_at, installed_at))


def reports(env):
    return sorted(p for p in env.store.iterdir() if p.is_dir())


# covers: delivery.crash-reports/E1
def test_a_crash_leaves_a_report_a_core_and_a_coredump_entry(env, capsys):
    install_release(env, '20261001.1', time.time() - 3600)
    when = time.time() - 60
    core = make_core(env, when)
    original = core.read_bytes()
    env.collect.main()

    assert list(env.spool.iterdir()) == []            # nothing left to re-trigger the path unit
    [report] = reports(env)
    info = json.loads((report / 'info.json').read_text())
    assert info['comm'] == 'crasher' and info['signal'] == 'SIGABRT'
    assert info['exe'] == str(env.build / 'crasher')
    # The signature starts below abort's plumbing (raise, abort, pthread_kill), at the program's frames.
    assert [f.split(' (')[0] for f in info['signature_frames'][:3]] == ['inner_fault', 'outer_call', 'main']
    assert info['release'] == {'version': '20261001.1', 'commit': 'abc1234'}
    assert 'inner_fault' in (report / 'backtrace.txt').read_text()
    with zstd.open(report / 'core.zst', 'rb') as kept:
        assert kept.read() == original

    # One line at err priority for log queries ...
    log = capsys.readouterr().out
    assert f'<3>coredump: crasher[{NO_PID}] SIGABRT' in log and f'sig={info["signature"]}' in log
    # ... and an entry in systemd-coredump's format, which coredumpctl list/info/debug read.
    [entry] = env.journal
    assert entry['MESSAGE_ID'] == 'fc2e22bc6ee647b6b90729ab34a250b1'
    assert entry['COREDUMP_FILENAME'] == str(report / 'core.zst')
    assert entry['COREDUMP_SIGNAL'] == 6 and entry['COREDUMP_SIGNAL_NAME'] == 'SIGABRT'
    assert entry['COREDUMP_PID'] == NO_PID and entry['COREDUMP_EXE'] == info['exe']
    assert entry['RUNGIC_CRASH_SIGNATURE'] == info['signature'] and entry['RUNGIC_RELEASE'] == '20261001.1'


def crash_groups(env, monkeypatch, **kwargs):
    """rungic_agent.crash_groups with its container script run here, against the test's store."""
    def run(script, level='root', timeout=60, check=True):
        assert level == 'container'
        script = script.replace("'/var/lib/rungic-cores', '/var/lib/moto-cores'", f"'{env.store}', '/nonexistent'")
        return subprocess.run(['sh', '-c', script], capture_output=True, text=True)
    monkeypatch.setattr(rungic_agent, 'run', run)
    monkeypatch.setattr(rungic_agent, 'out', lambda script, *a, **k: str(int(time.time())))
    return rungic_agent.crash_groups(**kwargs)


# covers: delivery.crash-reports/E2, delivery.crash-reports/E6
def test_reports_group_by_signature_per_release(env, monkeypatch):
    now = time.time()
    # A crash from before release .2 was installed is collected only afterwards (docs/61: the deploy's
    # restart still ran .1): it must not count as .2's.
    install_release(env, '20261001.2', now - 600)
    make_core(env, now - 900)
    env.collect.main()
    [before] = reports(env)
    assert json.loads((before / 'info.json').read_text())['release'] == {
        'version': None, 'before': '20261001.2', 'note': 'crashed before 20261001.2 was installed'}
    # The same crash twice under .2, and a new one (a segfault elsewhere).
    make_core(env, now - 300)
    make_core(env, now - 200)
    make_core(env, now - 100, 'segv')
    env.collect.main()

    answer = crash_groups(env, monkeypatch, release='20261001.2')
    assert answer['reports'] == 4
    abort, segv = answer['groups']
    assert abort['count'] == 3 and abort['signal'] == 'SIGABRT' and abort['releases'] == [None, '20261001.2']
    assert abort['frames'][0].startswith('inner_fault')
    assert abort['first'] < abort['last']
    assert segv['count'] == 1 and segv['signal'] == 'SIGSEGV' and segv['frames'][0].startswith('other_fault')
    assert abort['signature'] != segv['signature']
    # New in .2: only the segfault; the abort was already seen (before .2 was installed).
    assert answer['new_in_release'] == [segv['signature']]


# covers: delivery.crash-reports/E4
def test_a_crash_loop_keeps_two_cores_and_leaves_the_others(env):
    install_release(env, '20261001.3', time.time() - 3600)
    start = time.time() - 1000
    for i in range(4):
        make_core(env, start + i)
    make_core(env, start + 10, 'segv')
    env.collect.main()
    found = reports(env)
    assert len(found) == 5                                   # every report stays
    with_core = [p for p in found if (p / 'core.zst').exists()]
    signatures = [json.loads((p / 'info.json').read_text())['signal'] for p in with_core]
    assert sorted(signatures) == ['SIGABRT', 'SIGABRT', 'SIGSEGV']
    newest_aborts = sorted(p for p in found if 'SIGABRT' in (p / 'backtrace.txt').read_text())[-2:]
    assert all((p / 'core.zst').exists() for p in newest_aborts)
    # The collector runs with a memory cap: gdb on a large core fails, not the phone.
    unit = (ROOT / 'system/diagnostics/rungic-coredump.service').read_text()
    assert 'MemoryMax=768M' in unit.splitlines() and 'MemorySwapMax=0' in unit.splitlines()


def build_id(path):
    notes = subprocess.run(['readelf', '-n', str(path)], capture_output=True, text=True).stdout
    return next(line.split()[-1] for line in notes.splitlines() if 'Build ID' in line)


# covers: delivery.crash-reports/E3
def test_symbolized_on_the_build_host_from_the_phone_files(env, tmp_path):
    """The phone has a stripped program; its symbols exist only as a -dbgsym's debug file. The build
    host's analysis (ANALYSE, the phone's own collector against a sysroot of the phone's files) names
    the frames, recomputes the signature and keeps the phone's."""
    install_release(env, '20261001.4', time.time() - 3600)
    phone_exe = env.build / 'crasher-stripped'
    debug = env.build / 'crasher.debug'
    subprocess.run(['objcopy', '--only-keep-debug', env.build / 'crasher', debug], check=True)
    subprocess.run(['objcopy', '--strip-all', env.build / 'crasher', phone_exe], check=True)
    make_core(env, time.time() - 30, exe=phone_exe)
    env.collect.main()
    [report] = reports(env)
    phone_info = json.loads((report / 'info.json').read_text())
    assert not any(f.startswith('inner_fault') for f in phone_info['signature_frames'])   # no symbols there

    # What rungic_crash_symbolize copies from the phone: the report and the mapped files, as a sysroot.
    work = tmp_path / 'host/crash' / report.name
    sysroot = work / 'sysroot'
    stored = sysroot / f'var/lib/rungic-cores/{report.name}'
    stored.mkdir(parents=True)
    for name in ('info.json', 'core.zst'):
        shutil.copy(report / name, stored / name)
    for path in [str(phone_exe)] + [m['file'] for m in phone_info['modules'] if m['file']] + \
            [os.path.realpath(p) for p in ('/lib64/ld-linux-x86-64.so.2', '/lib/x86_64-linux-gnu/libc.so.6')
             if os.path.exists(p)]:
        target = sysroot / path.lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, target)
    for alias in ('/lib64/ld-linux-x86-64.so.2', '/lib/x86_64-linux-gnu/libc.so.6'):
        if os.path.islink(alias) and not (sysroot / alias.lstrip('/')).exists():
            (sysroot / alias.lstrip('/')).parent.mkdir(parents=True, exist_ok=True)
            os.symlink(os.path.realpath(alias), sysroot / alias.lstrip('/'))
    bid = build_id(phone_exe)
    (sysroot / f'usr/lib/debug/.build-id/{bid[:2]}').mkdir(parents=True)
    shutil.copy(debug, sysroot / f'usr/lib/debug/.build-id/{bid[:2]}/{bid[2:]}.debug')
    shutil.copy(COLLECTOR, work.parent / 'rungic-coredump-collect')
    (work.parent / 'analyse.py').write_text(rungic_crash_symbolize.ANALYSE)
    done = subprocess.run([sys.executable, str(work.parent / 'analyse.py'), str(work), report.name],
                          capture_output=True, text=True, env={**os.environ, 'DEBUGINFOD_URLS': ''})
    assert done.returncode == 0, done.stderr[-3000:]
    result = json.loads(done.stdout.splitlines()[-1])
    info = json.loads((work / 'info.json').read_text())
    assert info['symbolized'] is True and info['symbolized_on'] == 'build host'
    assert [f.split(' (')[0] for f in info['signature_frames'][:3]] == ['inner_fault', 'outer_call', 'main']
    assert info['signature'] == result['signature'] != phone_info['signature']
    assert info['signature_unsymbolized'] == phone_info['signature']
    backtrace = (work / 'backtrace.txt').read_text()
    assert 'inner_fault' in backtrace and str(sysroot) not in backtrace   # paths as the phone has them


class FakeHost:
    def __init__(self):
        self.commands, self.files = [], {}

    def run(self, command, timeout=None):
        self.commands.append(command)

    def put(self, local, remote, mode):
        self.files[remote] = Path(local).read_bytes()

    def out(self, command, timeout=None):
        self.commands.append(command)
        return json.dumps({'report': 'r', 'signature': 'new', 'frames': [], 'missing_symbols': 0})


# covers: delivery.crash-reports/E3
def test_the_phone_only_lists_and_packs_files(tmp_path, monkeypatch):
    """symbolize(): gdb runs on the build host; the phone answers a dpkg-query manifest, tars the exact
    files straight to the build host and receives backtrace.txt and info.json back. The analysis script
    goes to the workspace's .work, which a fresh checkout does not have yet."""
    report = '20261001-120000-kalk-4242'
    phone = []

    def on_phone(script, timeout=300):
        phone.append(script)
        if len(phone) == 1:
            return json.dumps({'info': {}, 'files': ['/usr/bin/kalk', '/usr/lib/libQt6Core.so.6'],
                               'owners': {'kalk': {'version': '1:24.12-1', 'arch': 'arm64'}}})
        return ''
    monkeypatch.setattr(rungic_crash_symbolize, 'phone', on_phone)
    monkeypatch.setattr(rungic_crash_symbolize, 'WORKSPACE', tmp_path)     # a checkout without .work
    (tmp_path / 'system/diagnostics').mkdir(parents=True)
    shutil.copy(COLLECTOR, tmp_path / 'system/diagnostics')
    monkeypatch.setattr(rungic_crash_symbolize.rungic_release, 'POOL', tmp_path / 'pool')
    host = FakeHost()
    rungic_crash_symbolize.symbolize(host, report)

    assert not any('gdb' in script or 'rungic-crash-symbols' in script for script in phone)
    assert 'dpkg-query' in phone[0] and 'tar -chf - -C / usr/bin/kalk usr/lib/libQt6Core.so.6' in phone[1]
    assert any('kalk-dbgsym=1:24.12-1' in c for c in host.commands)          # symbols at the phone's version
    assert any(f'analyse.py /root/rungic-build/crash/{report}' in c for c in host.commands)
    written = [s for s in phone if 'get crash/' in s]
    assert [s.split(' get ')[1].split()[0] for s in written] == [f'crash/{report}/backtrace.txt',
                                                                f'crash/{report}/info.json']
    assert all(f'/var/lib/rungic-cores/{report}/' in s for s in written)


CREDENTIAL_UNITS = ('agent/assistant/rungic-voice-agent.service',      # and its codex app-server, call proxy
                    'agent/suggestions/rungic-suggestions.service', 'agent/suggestions/rungic-suggestions-collect.service')


# covers: delivery.crash-reports/E5
def test_services_holding_credentials_dump_no_core(tmp_path, monkeypatch):
    """The units of the services that hold API keys and the Codex login set LimitCORE=0 (their children
    inherit it); rungic-integrity's crash-chain check reports a voice-agent unit that lost it."""
    for unit in CREDENTIAL_UNITS:
        lines = [line.strip() for line in (ROOT / unit).read_text().splitlines()]
        assert 'LimitCORE=0' in lines[lines.index('[Service]'):], unit

    loader = importlib.machinery.SourceFileLoader('rungic_integrity', str(ROOT / 'system/diagnostics/rungic-integrity'))
    integrity = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(integrity)
    units = tmp_path / 'usr/lib/systemd/user'
    units.mkdir(parents=True)
    real_run = integrity.run

    def run(*argv, check=False):     # the container's files under tmp_path; no drkonqi installed
        if argv[0] == 'dpkg-query':
            return ''
        return real_run(*[a.replace('/usr/lib/systemd/user/', f'{units}/').replace('/etc/systemd/user/', f'{tmp_path}/etc/')
                          for a in argv])
    monkeypatch.setattr(integrity, 'run', run)
    shutil.copy(ROOT / CREDENTIAL_UNITS[0], units)
    core_limit = lambda: [p for p in integrity.check_crash() if 'LimitCORE' in p]   # (this computer's sysctl.d aside)
    assert core_limit() == []
    (units / 'rungic-voice-agent.service').write_text((ROOT / CREDENTIAL_UNITS[0]).read_text().replace('LimitCORE=0', ''))
    assert core_limit() == ['rungic-voice-agent.service holds API keys but has no LimitCORE=0']
