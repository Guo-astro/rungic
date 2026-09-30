#!/usr/bin/env python3
"""rungic_dev without a device (docs/97): development versions sort between the release's build and
the next one, overlays stack on the release they started from, and the metapackage and pins name
the overrides."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import rungic_dev
import rungic_release

RELEASE = {'version': '20260930.9', 'commit': 'be86132', 'packages': {'rungic-design': '0.510', 'kwin-wayland': '6.6.5-0+rungic8'},
           'session_restart': ['kwin-*'], 'user_restart': {'rungic-design': ['plasma-plasmashell.service']}}


def newer(a, b):
    return subprocess.run(['dpkg', '--compare-versions', a, 'gt', b]).returncode == 0


class VersionTests(unittest.TestCase):
    def test_between_release_builds(self):
        dev = rungic_dev.dev_version('0.510', '20260930t221500', '32b158c', True)
        self.assertEqual(dev, '0.510+dev20260930t221500.32b158c.dirty')
        self.assertTrue(newer(dev, '0.510'))
        self.assertTrue(newer('0.511', dev))
        self.assertTrue(newer(dev, '0.510+dev20260930t221459.32b158c'))   # a later build wins

    def test_release_metapackage_between(self):
        self.assertTrue(newer('20260930.9+dev20260930t221500', '20260930.9'))
        self.assertTrue(newer('20260930.10', '20260930.9+dev20260930t221500'))


class OverlayTests(unittest.TestCase):
    def override(self, version):
        return {'version': version, 'commit': 'x', 'dirty': True, 'built': 'now', 'file': f'rungic-design_{version}_arm64.deb'}

    def test_overlay_on_release(self):
        info = rungic_dev.overlay_info(RELEASE, {'rungic-design': self.override('0.510+dev1.a')}, '20260930t221500')
        self.assertEqual(info['version'], '20260930.9+dev20260930t221500')
        self.assertEqual(info['packages'], {'rungic-design': '0.510+dev1.a', 'kwin-wayland': '6.6.5-0+rungic8'})
        self.assertEqual(info['dev']['base'], '20260930.9')
        self.assertEqual(info['dev']['base_packages'], RELEASE['packages'])
        self.assertEqual(info['user_restart'], RELEASE['user_restart'])

    def test_overlay_on_overlay_keeps_the_base(self):
        first = rungic_dev.overlay_info(RELEASE, {'rungic-design': self.override('0.510+dev1.a')}, '1')
        second = rungic_dev.overlay_info(first, {'rungic-design': self.override('0.510+dev2.a')}, '2')
        self.assertEqual(second['version'], '20260930.9+dev2')
        self.assertEqual(second['dev']['base_packages'], RELEASE['packages'])
        self.assertEqual(rungic_dev.base_of(second), ('20260930.9', RELEASE['packages']))

    def test_pins_above_the_release(self):
        info = rungic_dev.overlay_info(RELEASE, {'rungic-design': self.override('0.510+dev1.a')}, '1')
        script = rungic_dev.config_script(info)
        self.assertIn('Package: rungic-design\nPin: version 0.510+dev1.a\nPin-Priority: 1002', script)
        self.assertIn('Package: rungic-release\nPin: version 20260930.9+dev1\nPin-Priority: 1002', script)
        self.assertIn(f'URIs: file:{rungic_dev.DEVICE_REPO}', script)
        self.assertNotIn('kwin-wayland', script)          # the release's own pins stay in charge

    def test_metapackage(self):
        info = rungic_dev.overlay_info(RELEASE, {'rungic-design': self.override('0.510+dev1.a')}, '1')
        with tempfile.TemporaryDirectory(dir=rungic_release.WORKSPACE / '.work/cache') as temp:
            deb = rungic_release.build_meta(info['version'], info['packages'], info, dest=Path(temp))
            depends = rungic_release.deb_field(deb, 'Depends')
            self.assertIn('rungic-design (= 0.510+dev1.a)', depends)
            self.assertIn('kwin-wayland (= 6.6.5-0+rungic8)', depends)
            self.assertEqual(rungic_release.deb_field(deb, 'Protected'), 'yes')
            listing = subprocess.run(['dpkg-deb', '--fsys-tarfile', str(deb)], capture_output=True, check=True).stdout
            extracted = subprocess.run(['tar', '-xOf', '-', './usr/share/rungic/release.json'], input=listing,
                                       capture_output=True, check=True).stdout
            self.assertEqual(json.loads(extracted)['dev']['base'], '20260930.9')


if __name__ == '__main__':
    unittest.main()
