"""Exercise private PID recovery with real processes, including PID reuse."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'system/android-audio'


class AudioPidRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / 'runtime').mkdir()
        (self.base / 'bin').mkdir()
        self.pidfile = self.base / 'runtime/pid'
        source = SOURCE.read_text()
        self.functions = source[source.index('private_pid() {'):source.index('ensure_audio() {')]
        self.processes = []
        self.addCleanup(self.stop_processes)

    def stop_processes(self):
        for proc in self.processes:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()

    def call(self, action):
        return subprocess.run(['bash', '-eu', '-c',
            'PREFIX=$1; STATE=$1; uid=$(id -u)\n' + self.functions + '\n' + action,
            'test-audio', str(self.base)], capture_output=True, text=True, timeout=10)

    def test_reused_pid_is_removed_without_signalling_other_process(self):
        proc = subprocess.Popen(['sleep', '30'], start_new_session=True)
        self.processes.append(proc)
        self.pidfile.write_text(str(proc.pid) + '\n')
        result = self.call('stop_private; clear_stale_pid')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(proc.poll())
        self.assertFalse(self.pidfile.exists())

    def test_live_private_daemon_is_not_unlinked_until_stopped(self):
        executable = self.base / 'bin/pulseaudio'
        shutil.copyfile(shutil.which('bash'), executable)
        executable.chmod(0o700)
        proc = subprocess.Popen([str(executable), '-c', 'sleep 30; :',
            '-nF', str(self.base / 'default.pa'), 'test'], start_new_session=True)
        self.processes.append(proc)
        self.pidfile.write_text(str(proc.pid) + '\n')
        result = self.call('clear_stale_pid')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.pidfile.exists())
        self.assertIsNone(proc.poll())
        result = self.call('stop_private; clear_stale_pid')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.pidfile.exists())
        proc.wait(timeout=2)

    def test_pid_reused_by_kernel_thread_is_removed(self):
        # Use case (docs/94): after a reboot the saved PID belongs to a kernel thread,
        # which has no /proc/PID/exe even for root. PID 2 is kthreadd on every Linux.
        self.assertIn('Kthread:\t1', Path('/proc/2/status').read_text())
        self.pidfile.write_text('2\n')
        result = self.call('stop_private; clear_stale_pid')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.pidfile.exists())

    def test_corrupt_pid_is_removed(self):
        self.pidfile.write_text('not-a-pid\n')
        result = self.call('clear_stale_pid')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.pidfile.exists())


if __name__ == '__main__':
    unittest.main()
