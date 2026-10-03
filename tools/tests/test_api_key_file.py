#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The OpenAI API key is a plain file of mode 600 in a 700 directory (rungic_cua.keys, docs/87),
also when the directory was made before, with the umask's mode: the voice service copies its
prompts into ~/.config/rungic-voice-agent at start, long before a key is set."""
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'agent/computer-use'))
from rungic_cua import keys  # noqa: E402


class KeyFileTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.saved = keys.FILES
        keys.FILES = Path(self.home.name) / '.config/rungic-voice-agent'
        self.addCleanup(setattr, keys, 'FILES', self.saved)

    # covers: agent.sign-in/E5
    def test_directory_made_earlier_becomes_private(self):
        keys.FILES.mkdir(parents=True, mode=0o755)
        os.chmod(keys.FILES, 0o755)          # as the service's prompt copy leaves it
        keys.store('openai-api-key', 'sk-test-0123456789')
        self.assertEqual(oct(keys.FILES.stat().st_mode & 0o777), '0o700')
        path = keys.FILES / 'openai-api-key'
        self.assertEqual(oct(path.stat().st_mode & 0o777), '0o600')
        self.assertEqual(path.read_text(), 'sk-test-0123456789\n')
        self.assertEqual(keys.read('openai-api-key'), 'sk-test-0123456789')

    # covers: agent.sign-in/E5
    def test_new_directory_is_private(self):
        keys.store('openai-api-key', 'sk-test-0123456789')
        self.assertEqual(oct(keys.FILES.stat().st_mode & 0o777), '0o700')


if __name__ == '__main__':
    unittest.main()
