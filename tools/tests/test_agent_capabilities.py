# SPDX-License-Identifier: MIT
"""The capability sections of the assistant's prompts (tools/agent_capabilities.py, docs/59): one
source, agent/assistant/prompts/capabilities.yaml, rendered into agent.md, phone.md and realtime.md.
The real prompts must be current, and every skill a capability names must ship with the package."""
from pathlib import Path
import re

import pytest

import agent_capabilities as ac

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / 'agent/assistant/skills'

SOURCE = '''
capabilities:
  - name: SMS
    can: Send SMS.
    when: '"发短信"'
    how: skill `rungic-messages-calls`
    external: Sending
  - name: Files
    can: Find files
    when: a file to find
    how: the shell
'''


def prompts(tmp_path):
    (tmp_path / 'capabilities.yaml').write_text(SOURCE)
    for name in ac.INTRO:
        (tmp_path / name).write_text(f'Before.\n{ac.BEGIN}\nold\n{ac.END}\nAfter.\n')
    return tmp_path


# covers: agent.instructions/E5
def test_the_real_prompts_are_current():
    assert ac.stale() == {}, 'run: python3 tools/agent_capabilities.py render --write'


# covers: agent.instructions/E5
def test_a_stale_section_is_found_and_rendered_in_each_voice(tmp_path):
    base = prompts(tmp_path)
    changed = ac.stale(base, base / 'capabilities.yaml')
    assert set(changed) == set(ac.INTRO)
    agent = changed['agent.md']
    assert agent.startswith('Before.\n') and agent.endswith(f'{ac.END}\nAfter.\n')
    assert ('- **SMS**: Send SMS. Use when: "发短信". How: skill `rungic-messages-calls`. '
            'Sending has an external effect') in agent
    assert '- **Files**: Find files. Use when: a file to find. How: the shell.\n' in agent
    assert '- SMS: Send SMS. When: "发短信". Sending needs the user\'s go-ahead.\n' in changed['phone.md']
    assert '* Files: Find files. When: a file to find.\n' in changed['realtime.md']
    for name, text in changed.items():
        (base / name).write_text(text)
    assert ac.stale(base, base / 'capabilities.yaml') == {}


def test_a_prompt_without_the_markers_is_an_error(tmp_path):
    base = prompts(tmp_path)
    (base / 'phone.md').write_text('No section here.\n')
    with pytest.raises(ValueError, match='phone.md'):
        ac.stale(base, base / 'capabilities.yaml')


def test_every_named_skill_ships():
    named = {m for entry in ac.load() for m in re.findall(r'skill `([a-z0-9-]+)`', entry['how'])}
    assert named
    for name in sorted(named):
        skill = SKILLS / name / 'SKILL.md'
        assert skill.exists(), f'capabilities.yaml names skill {name}, which does not exist'
        assert f'\nname: {name}\n' in skill.read_text()


# covers: agent.instructions/E5
def test_both_voices_speak_as_the_assistant_that_operates_the_phone():
    # 2026-10-05: in a call the voice said "I am only a voice assistant, I cannot use Krita" while
    # the executor was drawing in it. Push-to-talk's voice already had the rule; the call's lacked it.
    prompts = Path(__file__).resolve().parents[2] / 'agent/assistant/prompts'
    phone = (prompts / 'phone.md').read_text()
    realtime = (prompts / 'realtime.md').read_text()
    assert 'Never say that you cannot use' in phone and 'only a\nvoice assistant' in phone
    assert 'Do not claim that you cannot perform some actions' in realtime
