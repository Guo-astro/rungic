"""Reject stale casting builds and incompatible scan responses before false empty UI."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import cast_payload
loader = importlib.machinery.SourceFileLoader('cast_command', str(ROOT / 'desktop/cast/rungic-cast'))
spec = importlib.util.spec_from_loader(loader.name, loader)
command = importlib.util.module_from_spec(spec)
loader.exec_module(command)


# covers: desktop-mode.cast-install/E3
class CastBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.jar = self.folder / 'rungic-cast.jar'
        self.jar.write_bytes(b'fixture-dex')
        self.snapshot = self.folder / 'inputs.json'
        self.snapshot.write_text(json.dumps(cast_payload.build_inputs()))

    def test_missing_provenance_refuses_staging(self):
        with self.assertRaisesRegex(ValueError, 'no build provenance'):
            cast_payload.stage(self.folder / 'payload', self.jar)
        self.assertFalse((self.folder / 'payload').exists())

    def test_matching_sources_and_jar_stage(self):
        cast_payload.attest_build(self.jar, self.snapshot)
        cast_payload.stage(self.folder / 'payload', self.jar)
        self.assertEqual((self.folder / 'payload/rungic-cast.jar').read_bytes(), self.jar.read_bytes())

    def test_old_sources_rejected(self):
        cast_payload.attest_build(self.jar, self.snapshot)
        with patch.object(cast_payload, 'build_inputs', return_value={'new-source': 'new-hash'}):
            with self.assertRaisesRegex(ValueError, 'current sources'):
                cast_payload.validate_build(self.jar)

    def test_tampered_jar_rejected(self):
        cast_payload.attest_build(self.jar, self.snapshot)
        self.jar.write_bytes(b'old-dex')
        with self.assertRaisesRegex(ValueError, 'digest'):
            cast_payload.validate_build(self.jar)

    def test_source_change_during_build_rejected(self):
        self.snapshot.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'during compilation'):
            cast_payload.attest_build(self.jar, self.snapshot)
        self.assertFalse(self.jar.with_suffix('.build.json').exists())


# covers: desktop-mode.cast-connect/E5
class CastContractTests(unittest.TestCase):
    def test_old_scan_with_real_display_is_not_an_empty_success(self):
        old = {'active_state': 0, 'displays': [{'name': 'TV', 'available': True}]}
        for action in ('status', 'capabilities', 'scan'):
            with self.subTest(action=action):
                result = command.validate_result(action, old)
                self.assertEqual(result['code'], 'backend-incompatible')
                self.assertIn('error', result)

    def test_empty_and_nonempty_compatible_results(self):
        for receivers in ([], [{'name': 'TV', 'available': True}]):
            value = {'protocol_version': 1, 'receivers': receivers}
            self.assertEqual(command.validate_result('scan', value), value)

    def test_backend_errors_are_preserved(self):
        error = {'code': 'wifi-unavailable', 'error': 'Wi-Fi unavailable'}
        self.assertEqual(command.validate_result('scan', error), error)

    def test_future_protocol_or_missing_receivers_fail_explicitly(self):
        for value in ({'protocol_version': 2, 'receivers': []}, {'protocol_version': 1}, []):
            self.assertEqual(command.validate_result('scan', value)['code'], 'backend-incompatible')


if __name__ == '__main__':
    unittest.main()
