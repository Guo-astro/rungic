# SPDX-License-Identifier: MIT
"""The feature inventory's checker (tools/feature_inventory.py, quality/README.md), on small made-up
repositories, and the real inventory: no broken reference, every file owned, every document
classified, the generated overview current."""
import datetime
from pathlib import Path
import textwrap

import feature_inventory as fi

ROOT = Path(__file__).resolve().parents[1]
TODAY = datetime.date(2026, 10, 3)


def repo(tmp_path, files, features='', docs='', interfaces='', acceptance=None):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (tmp_path / 'quality/features').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'quality/features/area.yaml').write_text(textwrap.dedent(features))
    (tmp_path / 'quality/docs.yaml').write_text(textwrap.dedent(docs))
    (tmp_path / 'quality/interfaces.yaml').write_text(textwrap.dedent(interfaces))
    if acceptance is not None:
        (tmp_path / 'release').mkdir(exist_ok=True)
        (tmp_path / 'release/acceptance.json').write_text(acceptance)
    names = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*') if p.is_file()]
    inventory = fi.Inventory(tmp_path, files=names, today=TODAY)
    (tmp_path / fi.RENDERED).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / fi.RENDERED).write_text(inventory.render())
    names.append(fi.RENDERED)
    return fi.Inventory(tmp_path, files=names, today=TODAY).check()


AREA = '''
area: a
title: An area
scenarios:
  - {id: a.use, title: Using it}
features:
  - id: a.thing
    title: The thing
    scenario: a.use
    status: live
    platform: linux
    summary: It does a thing.
    experience:
      - {id: E1, text: It works.}
      - {id: E2, text: It recovers., evidence: [{doc: docs/a.md, date: 2026-09-01}]}
    code: [src/]
    docs: [docs/a.md]
'''
DOCS = '''
- {path: docs/a.md, kind: reference}
- {path: docs/feature-inventory.md, kind: index}
'''


def kinds(inventory):
    return {k for k, _, _ in inventory.warnings}


# covers: delivery.feature-inventory/E1
def test_a_test_saying_what_it_covers_checks_that_experience(tmp_path):
    inventory = repo(tmp_path, {'src/thing.py': 'x = 1\n', 'tests/test_thing.py': '# covers: a.thing/E1\ndef test(): pass\n',
                                'docs/a.md': '# A\n'}, AREA + "    code: [src/, tests/]\n".replace('    code: [src/, tests/]\n', ''), DOCS)
    assert not inventory.errors, inventory.errors
    assert ('untested', 'a.thing/E1', 'It works.') not in inventory.warnings
    assert [k for k, _ in inventory.coverage('a.thing', {'id': 'E2', 'evidence': [{'doc': 'docs/a.md', 'date': '2026-09-01'}]})] == ['manual']
    assert ('unowned', 'tests/test_thing.py', 'no feature owns it') in inventory.warnings


# covers: delivery.feature-inventory/E1
def test_a_test_covering_what_does_not_exist_is_an_error(tmp_path):
    inventory = repo(tmp_path, {'src/thing.py': '', 'docs/a.md': '', 'src/test_x.py': '// covers: a.thing/E9 a.gone\n'}, AREA, DOCS)
    assert any("covers unknown 'a.thing/E9'" in e for e in inventory.errors)
    assert any("covers unknown 'a.gone'" in e for e in inventory.errors)


# covers: delivery.feature-inventory/E1
def test_paths_that_match_nothing_are_errors(tmp_path):
    inventory = repo(tmp_path, {'docs/a.md': ''}, AREA, DOCS)
    assert any("code 'src/' matches no tracked file" in e for e in inventory.errors)


# covers: delivery.feature-inventory/E1
def test_unowned_files_unclassified_and_superseded_documents_are_reported(tmp_path):
    inventory = repo(tmp_path, {'src/thing.py': '', 'docs/a.md': '', 'docs/old.md': '', 'docs/loose.md': '', 'stray.sh': ''},
                     AREA, DOCS + '- {path: docs/old.md, kind: superseded, superseded_by: docs/a.md}\n')
    assert not inventory.errors, inventory.errors
    assert ('unowned', 'stray.sh', 'no feature owns it') in inventory.warnings
    assert ('unclassified-doc', 'docs/loose.md', 'not in quality/docs.yaml') in inventory.warnings
    assert ('superseded-doc', 'docs/old.md', 'superseded by docs/a.md') in inventory.warnings


# covers: delivery.feature-inventory/E1
def test_a_retired_feature_with_code_left_is_a_cleanup(tmp_path):
    area = AREA.replace('status: live', 'status: retired')
    inventory = repo(tmp_path, {'src/thing.py': '', 'docs/a.md': ''}, area, DOCS)
    assert 'retired' in kinds(inventory)
    assert 'untested' not in kinds(inventory)


def test_old_evidence_by_hand_is_stale(tmp_path):
    area = AREA.replace('date: 2026-09-01', 'date: 2026-01-01')
    inventory = repo(tmp_path, {'src/thing.py': '', 'docs/a.md': ''}, area, DOCS)
    assert 'stale-evidence' in kinds(inventory)


def test_a_linux_feature_checked_only_on_the_phone_wants_a_system_test(tmp_path):
    inventory = repo(tmp_path, {'src/thing.py': '', 'docs/a.md': '',
                                'release/x': ''}, AREA, DOCS,
                     acceptance='{"scenarios": [{"id": "s", "level": "smoke", "covers": ["a.thing/E1"]}]}')
    assert ('device-only', 'a.thing/E1', 'a Linux feature checked only on the phone or by hand') in inventory.warnings
    inventory = repo(tmp_path, {'src/t.py': '# covers[system]: a.thing/E1\n'}, AREA, DOCS)
    assert ('device-only', 'a.thing/E1', 'a Linux feature checked only on the phone or by hand') not in inventory.warnings


def test_an_interface_wants_both_ends_of_its_contract(tmp_path):
    area = AREA.replace('    platform: linux\n', '    platform: linux\n    interfaces: [bridge]\n')
    interfaces = '''
    - {id: bridge, title: A bridge, summary: Android answers., provider: [android/]}
    '''
    files = {'src/thing.py': '', 'docs/a.md': '', 'android/Bridge.java': '',
             'src/test_bridge.py': '# covers[consumer]: iface:bridge\n'}
    inventory = repo(tmp_path, files, area, DOCS, interfaces)
    assert not inventory.errors, inventory.errors
    assert ('one-sided-contract', 'bridge', 'no provider test of its contract') in inventory.warnings
    assert ('one-sided-contract', 'bridge', 'no consumer test of its contract') not in inventory.warnings
    assert ('unowned', 'android/Bridge.java', 'no feature owns it') not in inventory.warnings, 'a provider is owned by its interface'
    inventory = repo(tmp_path, {**files, 'src/test_bridge.py': '# covers[system]: iface:bridge\n'}, area, DOCS, interfaces)
    assert any('an interface is covered as consumer or provider' in e for e in inventory.errors)


# covers: delivery.feature-inventory/E3
def test_the_generated_overview_must_be_current(tmp_path):
    inventory = repo(tmp_path, {'src/thing.py': '', 'docs/a.md': ''}, AREA, DOCS)
    assert not [e for e in inventory.errors if 'out of date' in e]
    (tmp_path / fi.RENDERED).write_text('stale\n')
    again = fi.Inventory(tmp_path, files=inventory.files, today=TODAY).check()
    assert any('out of date' in e for e in again.errors)


def test_the_real_inventory_has_no_broken_reference():
    inventory = fi.Inventory(ROOT).check()
    assert not inventory.errors, '\n'.join(inventory.errors)


# covers: delivery.feature-inventory/E1
def test_the_real_inventory_keeps_within_its_baseline():
    """quality/README.md: structural warnings are fixed at once; the test backlog may only shrink.
    Evidence by hand going stale is the calendar, not a change: report shows it, this does not fail on it."""
    over = [w for w in fi.Inventory(ROOT).check().over_baseline() if w[0] != 'stale-evidence']
    assert not over, '\n'.join(f'{k}: {w}: {n}' for k, w, n in over) + \
        '\n(fix these; for test backlog that is meant to grow, run check --update-baseline and say why)'


# covers: delivery.feature-inventory/E1
def test_an_experience_only_the_phone_can_show_says_why(tmp_path):
    files = {'src/thing.py': '', 'docs/a.md': ''}
    acceptance = '{"scenarios": [{"id": "s", "level": "smoke", "covers": ["a.thing/E1"]}]}'
    area = AREA.replace('{id: E1, text: It works.}', '{id: E1, text: It works., device: frame pacing is the phone GPU}')
    inventory = repo(tmp_path, files, area, DOCS, acceptance=acceptance)
    assert not [w for w in inventory.warnings if w[0] == 'device-only' and w[1] == 'a.thing/E1']
    inventory = repo(tmp_path, files, AREA.replace('{id: E1, text: It works.}', "{id: E1, text: It works., device: ''}"), DOCS,
                     acceptance=acceptance)
    assert any('device needs the reason' in e for e in inventory.errors)


# covers: delivery.feature-inventory/E1
def test_a_side_of_a_contract_that_cannot_be_tested_says_why(tmp_path):
    area = AREA.replace('    platform: linux\n', '    platform: linux\n    interfaces: [bridge]\n')
    files = {'src/thing.py': '', 'docs/a.md': '', 'android/Bridge.java': '', 'src/test_bridge.py': '# covers[consumer]: iface:bridge\n'}
    interfaces = '- {id: bridge, title: A bridge, summary: Android answers., provider: [android/], gaps: {provider: needs a TV}}\n'
    inventory = repo(tmp_path, files, area, DOCS, interfaces)
    assert not [w for w in inventory.warnings if w[0] == 'one-sided-contract'], inventory.warnings
    inventory = repo(tmp_path, files, area, DOCS, interfaces.replace('provider: needs a TV', 'sideways: x'))
    assert any('gaps.sideways must be consumer or provider' in e for e in inventory.errors)
