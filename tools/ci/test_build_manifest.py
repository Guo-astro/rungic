import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import standalone as s


class BuildManifestTests(unittest.TestCase):
    def setUp(self):
        names = ['rootfs.img.gz', 'host-seed.tar.gz', 'rungic.apk', 'rungic-sparse-write']
        inputs = {'component': 'fixture', 'outputs': names, 'dependencies': {}}
        report = {'schema': 1, 'component': 'fixture', 'inputs': inputs,
                  'input_sha256': s.build_artifact.digest(inputs),
                  'outputs': {name: {'sha256': 'a' * 64, 'bytes': 1} for name in names}}
        self.files = copy.deepcopy(report['outputs'])
        self.manifest = {'schema': 1, 'components': {'fixture': report},
                         'bindings': {name: {'component': 'fixture', 'output': name} for name in names}}

    def test_matching_build_manifest(self):
        s.validate_build_manifest(self.manifest, self.files)

    def test_swapping_apk_rejected(self):
        self.files['rungic.apk']['sha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'does not match payload'):
            s.validate_build_manifest(self.manifest, self.files)

    def test_missing_build_binding_rejected(self):
        del self.manifest['bindings']['rootfs.img.gz']
        with self.assertRaisesRegex(ValueError, 'bindings'):
            s.validate_build_manifest(self.manifest, self.files)

    def test_altered_inputs_rejected(self):
        self.manifest['components']['fixture']['inputs']['outputs'] = []
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            s.validate_build_manifest(self.manifest, self.files)

    def test_unresolved_component_dependency_rejected(self):
        record = self.manifest['components']['fixture']
        record['inputs']['dependencies']['native'] = {'input_sha256': 'b' * 64, 'file_sha256': 'a' * 64}
        record['input_sha256'] = s.build_artifact.digest(record['inputs'])
        with self.assertRaisesRegex(ValueError, 'dependency build'):
            s.validate_build_manifest(self.manifest, self.files)


if __name__ == '__main__':
    unittest.main()
