#!/usr/bin/env python3
"""The assistant's prompts and skills are the user's to edit (rungic_voice_agent.sync_user_instructions):
every skill of the package gets a copy, a changed copy stays the user's, and a default the package
dropped (team.md, moved to the rungic-agent-team skill on 2026-10-01) takes its untouched copy along."""
import ast
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / 'agent/assistant/rungic_voice_agent.py'
tree = ast.parse(source.read_text())
functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'sync_user_instructions', 'file_hash'}]


def load(base: Path) -> dict:
    namespace = {'json': json, 'shutil': shutil, 'hashlib': hashlib, 'log': lambda *a: None,
                 'PROMPTS': base / 'pkg/prompts', 'USER_PROMPTS': base / 'user/prompts',
                 'SKILLS': base / 'pkg/skills', 'USER_SKILLS': base / 'user/skills',
                 'USER_SKILL': base / 'user/skills/rungic-phone-desktop',
                 'DATA': base / 'data', 'SEEDED': base / 'data/seeded.json'}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base)
        for path, text in {'pkg/prompts/agent.md': 'a', 'pkg/skills/rungic-phone-desktop/SKILL.md': 'desktop',
                           'pkg/skills/rungic-phone-desktop/team.md': 'team v1',
                           'pkg/skills/rungic-agent-team/SKILL.md': 'team skill'}.items():
            (self.base / path).parent.mkdir(parents=True, exist_ok=True)
            (self.base / path).write_text(text)
        self.ns = load(self.base)

    def test_every_skill_gets_a_copy(self):
        self.ns['sync_user_instructions']()
        user = self.base / 'user/skills'
        self.assertEqual((user / 'rungic-agent-team/SKILL.md').read_text(), 'team skill')
        self.assertEqual((user / 'rungic-phone-desktop/SKILL.md').read_text(), 'desktop')

    def test_a_dropped_default_takes_its_untouched_copy_along(self):
        self.ns['sync_user_instructions']()
        (self.base / 'pkg/skills/rungic-phone-desktop/team.md').unlink()
        self.ns['sync_user_instructions']()
        self.assertFalse((self.base / 'user/skills/rungic-phone-desktop/team.md').exists())

    def test_a_dropped_default_leaves_a_changed_copy(self):
        self.ns['sync_user_instructions']()
        (self.base / 'user/skills/rungic-phone-desktop/team.md').write_text('mine')
        (self.base / 'pkg/skills/rungic-phone-desktop/team.md').unlink()
        self.ns['sync_user_instructions']()
        self.assertEqual((self.base / 'user/skills/rungic-phone-desktop/team.md').read_text(), 'mine')


if __name__ == '__main__':
    unittest.main()
