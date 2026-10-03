#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The feature inventory (docs/feature-inventory.md, quality/): what Rungic does for its user, what
each feature must feel like, and which code, documents and tests stand behind it.

quality/features/<area>.yaml lists an area's user scenarios and its features (one thing the user
can tell happens), each with the experience it must give (numbered E1, E2...: one requirement each),
the problems to keep in mind, and the code and documents it owns. quality/docs.yaml says what each
document is (a reference of how things are now, a journal of how they came to be, research, history,
an index, or superseded by another). Tests say what they cover, so a renamed or deleted test is
noticed: a comment `covers: FEATURE/E2 ...` in any language (a patch's tests too), or "covers" in a
release/acceptance.json scenario. Checks made by hand are evidence in the inventory, with the
document and the date.

Layers (quality/README.md): most features are the Linux system's and do not care whether Android or
a PC is under it (platform: linux); they are checked without Android, by unit tests (`covers:`) and
system tests on a headless KWin (`covers[system]:`). What they need of Android goes through the
interfaces of quality/interfaces.yaml, each tested from both ends against one contract: its Linux
consumers against a stand-in (`covers[consumer]: iface:ID`), Android's provider on the phone
(`covers[provider]: iface:ID`). Acceptance on the phone (release/acceptance.json) checks they meet.

  feature_inventory.py check [--strict] [--update-baseline]
                                          broken references (errors); unowned files, unclassified
                                          documents, experiences nobody checks, retired features
                                          and superseded documents still present (warnings).
                                          --strict fails on every structural warning, and on test
                                          backlog not in quality/baseline.json (it may only shrink:
                                          --update-baseline after it did)
  feature_inventory.py report             the warnings in full: what to test, clean up or decide
  feature_inventory.py render [--write]   docs/feature-inventory.md from the inventory (--write
                                          updates it; check fails while it is out of date)
  feature_inventory.py feature ID         one feature: its experience, tests, code and documents
  feature_inventory.py owner PATH...      which features own these files
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

import yaml

ROOT = Path(__file__).resolve().parents[1]
QUALITY = 'quality'
RENDERED = 'docs/feature-inventory.md'
STATUSES = ('live', 'experimental', 'retired')
PLATFORMS = ('linux', 'android')
TEST_LAYERS = ('unit', 'system')          # an experience's tests
INTERFACE_LAYERS = ('consumer', 'provider')  # an interface's contract tests
DOC_KINDS = ('reference', 'journal', 'research', 'history', 'index', 'superseded')
# A check by hand older than this is stale: do it again (or automate it).
STALE_DAYS = 90
# What may be left, and only what was there before (quality/baseline.json, `check --update-baseline`):
# the test backlog. Anything else a warning names is fixed at once (`check --strict`).
BACKLOG = ('untested', 'device-only', 'one-sided-contract', 'stale-evidence')
BASELINE = 'quality/baseline.json'
TAG = re.compile(r'^[+\s]*(?:#|//|\*|--|<!--)\s*covers(?:\[([a-z]+)\])?:\s*(.+?)\s*(?:-->)?$')
EXPERIENCE_ID = re.compile(r'^E\d+$')
# Files whose `covers:` lines are not tests (the inventory and its documentation describe them).
TAGLESS = ('quality/', 'docs/', 'tools/feature_inventory.py', 'tools/test_feature_inventory.py')


class Inventory:
    def __init__(self, root=ROOT, files=None, today=None):
        self.root = Path(root)
        self.files = sorted(files if files is not None else tracked(self.root))
        self.today = today or datetime.date.today()
        self.errors, self.warnings = [], []
        self.areas, self.features, self.scenarios = [], {}, {}
        self.docs = {}
        self.interfaces = {}
        self.covers = {}      # "feature/E1" or "iface:ID" -> [(layer, where)]
        self.load()

    # ---- loading --------------------------------------------------------------------------------
    def load(self):
        for path in sorted((self.root / QUALITY / 'features').glob('*.yaml')):
            data = yaml.safe_load(path.read_text()) or {}
            where = path.relative_to(self.root).as_posix()
            area = {'id': data.get('area'), 'title': data.get('title', ''), 'summary': data.get('summary', ''),
                    'file': where, 'scenarios': [], 'features': []}
            if not area['id']:
                self.errors.append(f'{where}: no area id')
                continue
            self.areas.append(area)
            for scenario in data.get('scenarios') or []:
                sid = scenario.get('id')
                if not sid or sid in self.scenarios:
                    self.errors.append(f'{where}: scenario id missing or repeated: {sid!r}')
                    continue
                self.scenarios[sid] = {**scenario, 'area': area['id']}
                area['scenarios'].append(sid)
            for feature in data.get('features') or []:
                self.add_feature(feature, area, where)
        interfaces = self.root / QUALITY / 'interfaces.yaml'
        for entry in (yaml.safe_load(interfaces.read_text()) if interfaces.exists() else None) or []:
            iid = entry.get('id')
            if not iid or iid in self.interfaces:
                self.errors.append(f'quality/interfaces.yaml: interface id missing or repeated: {iid!r}')
                continue
            entry.setdefault('provider', [])
            entry.setdefault('docs', [])
            self.interfaces[iid] = entry
        docs = self.root / QUALITY / 'docs.yaml'
        for entry in (yaml.safe_load(docs.read_text()) if docs.exists() else None) or []:
            path = entry.get('path')
            if not path or path in self.docs:
                self.errors.append(f'quality/docs.yaml: document path missing or repeated: {path!r}')
                continue
            self.docs[path] = entry
        self.scan_tests()

    def add_feature(self, feature, area, where):
        fid = feature.get('id')
        if not fid or fid in self.features:
            self.errors.append(f'{where}: feature id missing or repeated: {fid!r}')
            return
        feature = {**feature, 'area': area['id'], 'file': where}
        feature.setdefault('code', [])
        feature.setdefault('docs', [])
        feature.setdefault('experience', [])
        feature.setdefault('pitfalls', [])
        self.features[fid] = feature
        area['features'].append(fid)

    def scan_tests(self):
        for name in self.files:
            if name.startswith(TAGLESS) or not self.textual(name):
                continue
            try:
                text = (self.root / name).read_text(errors='replace')
            except (OSError, UnicodeDecodeError):
                continue
            if 'covers' not in text:     # covers: and covers[layer]:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                match = TAG.match(line)
                if match:
                    layer = match[1] or ('consumer' if 'iface:' in match[2] else 'unit')
                    for ref in re.split(r'[\s,]+', match[2]):
                        if ref:
                            self.covers.setdefault(ref, []).append((layer, f'{name}:{number}'))
        acceptance = self.root / 'release/acceptance.json'
        if acceptance.exists():
            for scenario in json.loads(acceptance.read_text()).get('scenarios', []):
                for ref in scenario.get('covers', []):
                    layer = 'provider' if ref.startswith('iface:') else 'device'
                    self.covers.setdefault(ref, []).append((layer, f'acceptance {scenario["id"]} ({scenario.get("level", "")})'))

    def textual(self, name):
        return PurePosixPath(name).suffix in {'.py', '.cpp', '.h', '.c', '.qml', '.java', '.kt', '.rs', '.sh', '.patch',
                                               '.js', '.ts', '.json', ''} and (self.root / name).is_file()

    # ---- matching -------------------------------------------------------------------------------
    def matches(self, pattern):
        if pattern.endswith('/'):
            pattern += '**'
        if any(c in pattern for c in '*?['):
            return [f for f in self.files if PurePosixPath(f).full_match(pattern)]
        return [pattern] if pattern in self.files else []

    def matches_all(self, patterns):
        return {found for pattern in patterns for found in self.matches(pattern)}

    def consumers(self, iid):
        return [fid for fid, f in self.features.items() if iid in f.get('interfaces', [])]

    def owners(self, name):
        return [fid for fid, f in self.features.items()
                if any(name in self.matches(p) for p in f['code'] + [d.split('#')[0] for d in f['docs']])]

    # ---- checks ---------------------------------------------------------------------------------
    def check(self):
        owned = set()
        for fid, f in self.features.items():
            where = f'{f["file"]}: {fid}'
            for key in ('title', 'summary', 'scenario', 'status'):
                if not f.get(key):
                    self.errors.append(f'{where}: no {key}')
            if f.get('scenario') and f['scenario'] not in self.scenarios:
                self.errors.append(f'{where}: unknown scenario {f["scenario"]!r}')
            if f.get('status') and f['status'] not in STATUSES:
                self.errors.append(f'{where}: status {f["status"]!r} is not one of {", ".join(STATUSES)}')
            if f.get('platform') not in PLATFORMS:
                self.errors.append(f'{where}: platform {f.get("platform")!r} is not one of {", ".join(PLATFORMS)}')
            for iid in f.get('interfaces', []):
                if iid not in self.interfaces:
                    self.errors.append(f'{where}: unknown interface {iid!r}')
            for pattern in f['code']:
                found = self.matches(pattern)
                if not found:
                    self.errors.append(f'{where}: code {pattern!r} matches no tracked file')
                owned.update(found)
            for doc in f['docs']:
                path = doc.split('#')[0]
                if path not in self.files:
                    self.errors.append(f'{where}: document {doc!r} is not a tracked file')
                owned.add(path)
            for pitfall in f['pitfalls']:
                if not pitfall.get('text'):
                    self.errors.append(f'{where}: a pitfall without text')
                for doc in pitfall.get('docs', []):
                    if doc.split('#')[0] not in self.files:
                        self.errors.append(f'{where}: pitfall document {doc!r} is not a tracked file')
            seen = set()
            for item in f['experience']:
                eid = item.get('id', '')
                if not EXPERIENCE_ID.match(eid) or eid in seen:
                    self.errors.append(f'{where}: experience id {eid!r} missing, malformed or repeated')
                    continue
                seen.add(eid)
                if not item.get('text'):
                    self.errors.append(f'{where}/{eid}: no text')
                for evidence in item.get('evidence', []):
                    self.check_evidence(f'{where}/{eid}', evidence)
                checks = self.coverage(fid, item)
                if f.get('status') != 'retired' and not checks and not item.get('gap'):
                    self.warnings.append(('untested', f'{fid}/{eid}', item.get('text', '')))
                # A Linux system feature checked only on the phone: a system test can do it without Android,
                # unless what the experience is about is the phone itself (`device: why`, quality/README.md).
                if 'device' in item and not str(item['device'] or '').strip():
                    self.errors.append(f'{where}/{eid}: device needs the reason only the phone can show it')
                if f.get('platform') == 'linux' and checks and not {k for k, _ in checks} & {'unit', 'system'} \
                        and not item.get('device'):
                    self.warnings.append(('device-only', f'{fid}/{eid}', 'a Linux feature checked only on the phone or by hand'))
            if f.get('status') == 'live' and not f['experience']:
                self.warnings.append(('no-experience', fid, 'a live feature with no experience to check'))
            if f.get('status') == 'retired' and not f.get('keep'):
                # Its history documents stay as evidence (quality/docs.yaml kind history); the rest goes.
                docs = {d.split('#')[0] for d in f['docs']} - {d for d, e in self.docs.items() if e.get('kind') == 'history'}
                left = sorted({x for p in f['code'] for x in self.matches(p)} | docs)
                if left:
                    self.warnings.append(('retired', fid, ', '.join(left[:6]) + (' ...' if len(left) > 6 else '')))
        for iid, entry in self.interfaces.items():
            where = f'quality/interfaces.yaml: {iid}'
            for key in ('title', 'summary'):
                if not entry.get(key):
                    self.errors.append(f'{where}: no {key}')
            for pattern in entry['provider']:
                found = self.matches(pattern)
                if not found:
                    self.errors.append(f'{where}: provider {pattern!r} matches no tracked file')
            if not self.consumers(iid):
                self.warnings.append(('unused-interface', iid, 'no feature names it in its interfaces'))
            for doc in entry['docs']:
                if doc.split('#')[0] not in self.files:
                    self.errors.append(f'{where}: document {doc!r} is not a tracked file')
                owned.add(doc.split('#')[0])
            layers = {k for k, _ in self.covers.get(f'iface:{iid}', [])}
            for found in self.matches_all(entry['provider']):
                owned.add(found)
            gaps = entry.get('gaps') or {}
            for side in gaps:
                if side not in INTERFACE_LAYERS or not str(gaps[side] or '').strip():
                    self.errors.append(f'{where}: gaps.{side} must be consumer or provider, with the reason')
            for side in INTERFACE_LAYERS:
                # A side that cannot be tested yet says why (gaps: {provider: why}), as an experience's gap.
                if side not in layers and not gaps.get(side):
                    self.warnings.append(('one-sided-contract', iid, f'no {side} test of its contract'))
        for ref, places in self.covers.items():
            if ref.startswith('iface:'):
                if ref[6:] not in self.interfaces:
                    for _, place in places:
                        self.errors.append(f'{place}: covers unknown interface {ref!r}')
                for layer, place in places:
                    if layer not in INTERFACE_LAYERS:
                        self.errors.append(f'{place}: an interface is covered as consumer or provider, not {layer!r}')
                continue
            for layer, place in places:
                if layer not in TEST_LAYERS + ('device',):
                    self.errors.append(f'{place}: layer {layer!r} is not one of {", ".join(TEST_LAYERS)}')
            fid, _, eid = ref.partition('/')
            feature = self.features.get(fid)
            if not feature or (eid and eid not in {e.get('id') for e in feature['experience']}):
                for _, place in places:
                    self.errors.append(f'{place}: covers unknown {ref!r}')
        for name in self.files:
            if name.startswith('docs/') and name.endswith('.md') and name not in self.docs:
                self.warnings.append(('unclassified-doc', name, 'not in quality/docs.yaml'))
        for path, entry in self.docs.items():
            if path not in self.files:
                self.errors.append(f'quality/docs.yaml: {path} is not a tracked file')
            if entry.get('kind') not in DOC_KINDS:
                self.errors.append(f'quality/docs.yaml: {path}: kind {entry.get("kind")!r} is not one of {", ".join(DOC_KINDS)}')
            if entry.get('kind') == 'superseded':
                by = entry.get('superseded_by')
                if not by or by.split('#')[0] not in self.files:
                    self.errors.append(f'quality/docs.yaml: {path}: superseded by a missing document {by!r}')
                self.warnings.append(('superseded-doc', path, f'superseded by {by}'))
            elif entry.get('kind') in ('reference', 'journal', 'research') and path not in owned:
                self.warnings.append(('orphan-doc', path, f'a {entry["kind"]} no feature refers to'))
            owned.add(path)
        for name in self.files:
            if name not in owned:
                self.warnings.append(('unowned', name, 'no feature owns it'))
        rendered = self.root / RENDERED
        if self.features and (not rendered.exists() or rendered.read_text() != self.render()):
            self.errors.append(f'{RENDERED} is out of date: tools/feature_inventory.py render --write')
        return self

    def check_evidence(self, where, evidence):
        doc, date = evidence.get('doc', ''), evidence.get('date')
        if doc.split('#')[0] not in self.files:
            self.errors.append(f'{where}: evidence document {doc!r} is not a tracked file')
        try:
            day = datetime.date.fromisoformat(str(date))
        except ValueError:
            self.errors.append(f'{where}: evidence date {date!r} is not YYYY-MM-DD')
            return
        if (self.today - day).days > STALE_DAYS:
            self.warnings.append(('stale-evidence', where.split(': ')[-1], f'checked by hand on {day}, over {STALE_DAYS} days ago'))

    def backlog(self):
        return {f'{kind} {what}' for kind, what, _ in self.warnings if kind in BACKLOG}

    def over_baseline(self):
        """The warnings --strict refuses: every structural one (an unowned file, an unclassified,
        orphaned or superseded document, a retired feature's leftovers, an unused interface), and test
        backlog that the baseline does not have yet."""
        path = self.root / BASELINE
        allowed = set(json.loads(path.read_text())) if path.exists() else set()
        return [(k, w, n) for k, w, n in self.warnings if k not in BACKLOG or f'{k} {w}' not in allowed]

    def coverage(self, fid, item):
        """[(kind, where)] of what checks an experience: tests and acceptance that say so, the
        feature-wide ones (`covers: FEATURE`), and evidence by hand."""
        found = list(self.covers.get(f'{fid}/{item.get("id")}', []))
        found += [('manual', f'{e.get("doc")} ({e.get("date")})') for e in item.get('evidence', [])]
        return found

    # ---- output ---------------------------------------------------------------------------------
    def render(self):
        lines = ['# Rungic 功能清单', '',
                 '<!-- Generated by tools/feature_inventory.py render --write from quality/; edit those, not this. -->', '',
                 '以产品功能和用户场景为骨架：每条功能是用户能感知的一件事；“体验”是它必须做到的，'
                 '每条都标明由什么检查（自动测试、实机验收、人工验证或已登记的缺口）。'
                 '数据在 `quality/`，规则见 [quality/README.md](../quality/README.md)。', '']
        total = covered = 0
        for area in self.areas:
            for fid in area['features']:
                for item in self.features[fid]['experience']:
                    if self.features[fid].get('status') != 'retired':
                        total += 1
                        covered += bool(self.coverage(fid, item))
        lines += [f'共 {len(self.features)} 条功能、{total} 条体验，其中 {covered} 条有检查。', '']
        for area in self.areas:
            lines += [f'## {area["title"]}', '']
            if area['summary']:
                lines += [area['summary'].strip(), '']
            for sid in area['scenarios']:
                scenario = self.scenarios[sid]
                lines += [f'### {scenario["title"]}', '']
                if scenario.get('summary'):
                    lines += [scenario['summary'].strip(), '']
                for fid in [f for f in area['features'] if self.features[f].get('scenario') == sid]:
                    lines += self.render_feature(fid)
        if self.interfaces:
            lines += ['## 安卓接口', '',
                      '系统功能经由这些接口用到安卓；每个接口的契约两头都测：Linux 一侧对着替身测（使用方），'
                      '安卓一侧在手机上测（提供方）。', '',
                      '| 接口 | 说明 | 使用它的功能 | 使用方测试 | 提供方测试 |', '|---|---|---|---|---|']
            for iid, entry in self.interfaces.items():
                layers = [k for k, _ in self.covers.get(f'iface:{iid}', [])]
                lines.append(f'| `{iid}` {entry.get("title", "")} | {str(entry.get("summary", "")).strip()} | '
                             f'{"、".join(f"`{c}`" for c in self.consumers(iid))} | {layers.count("consumer") or "—"} | '
                             f'{layers.count("provider") or "—"} |')
            lines.append('')
        return '\n'.join(lines).rstrip() + '\n'

    def render_feature(self, fid):
        f = self.features[fid]
        status = {'live': '', 'experimental': '（实验）', 'retired': '（已退役）'}.get(f.get('status'), '')
        platform = {'linux': 'Linux 系统功能', 'android': '依赖安卓'}.get(f.get('platform'), '')
        lines = [f'#### {f.get("title", fid)}{status}', '', f'`{fid}` · {platform} — {str(f.get("summary", "")).strip()}', '']
        if f.get('interfaces'):
            lines += ['经由接口：' + '、'.join(f'`{i}`' for i in f['interfaces']), '']
        for item in f['experience']:
            checks = self.coverage(fid, item)
            kinds = [k for k in ('unit', 'system', 'device', 'manual') if k in {c for c, _ in checks}]
            label = '、'.join({'unit': '单元测试', 'system': '系统测试', 'device': '实机验收', 'manual': '人工'}[k] for k in kinds) if kinds \
                else ('缺口：' + str(item['gap']).strip() if item.get('gap') else '**未检查**')
            if item.get('device'):
                label += '；只能在手机上看：' + str(item['device']).strip()
            lines.append(f'- **{item.get("id")}** {str(item.get("text", "")).strip()}（{label}）')
        if f['pitfalls']:
            lines += ['', '注意：']
            for pitfall in f['pitfalls']:
                refs = ''.join(f' [{d}](../{d})' for d in pitfall.get('docs', []))
                lines.append(f'- {str(pitfall["text"]).strip()}{refs}')
        if f['docs']:
            lines += ['', '文档：' + '、'.join(f'[{d}](../{d})' for d in f['docs'])]
        return lines + ['']

    def describe(self, fid):
        f = self.features[fid]
        out = [f'{fid}: {f.get("title")} ({f.get("status")}, {f["file"]})', f'  {f.get("summary", "")}']
        for item in f['experience']:
            out.append(f'  {item.get("id")} {item.get("text")}')
            for kind, where in self.coverage(fid, item):
                out.append(f'      {kind}: {where}')
            if item.get('gap'):
                out.append(f'      gap: {item["gap"]}')
            if item.get('device'):
                out.append(f'      device: {item["device"]}')
        for pitfall in f['pitfalls']:
            out.append(f'  ! {pitfall.get("text")} {" ".join(pitfall.get("docs", []))}')
        out += [f'  code: {p} ({len(self.matches(p))} files)' for p in f['code']]
        out += [f'  doc: {d}' for d in f['docs']]
        return '\n'.join(out)


def tracked(root):
    try:
        # Tracked, and new files not ignored yet: a feature added in the working tree is checked as it is written.
        out = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                             capture_output=True, check=True).stdout
        return sorted({n for n in out.decode().split('\0') if n and (root / n).exists()})
    except (OSError, subprocess.CalledProcessError):
        return [p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts]


def summary(inventory):
    kinds = {}
    for kind, _, _ in inventory.warnings:
        kinds[kind] = kinds.get(kind, 0) + 1
    return ', '.join(f'{n} {k}' for k, n in sorted(kinds.items())) or 'none'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('check')
    check.add_argument('--strict', action='store_true')
    check.add_argument('--update-baseline', action='store_true',
                       help=f'write the test backlog as it is now to {BASELINE} (it may only shrink)')
    sub.add_parser('report')
    render = sub.add_parser('render')
    render.add_argument('--write', action='store_true')
    feature = sub.add_parser('feature')
    feature.add_argument('id')
    owner = sub.add_parser('owner')
    owner.add_argument('paths', nargs='+')
    args = parser.parse_args(argv)
    inventory = Inventory()
    if args.command == 'render':
        text = inventory.render()
        if args.write:
            (ROOT / RENDERED).write_text(text)
        else:
            sys.stdout.write(text)
        return 0
    if args.command == 'feature':
        if args.id not in inventory.features:
            print(f'no feature {args.id}', file=sys.stderr)
            return 1
        print(inventory.describe(args.id))
        return 0
    if args.command == 'owner':
        for path in args.paths:
            print(f'{path}: {", ".join(inventory.owners(path)) or "(nobody)"}')
        return 0
    inventory.check()
    if args.command == 'report':
        for kind in sorted({k for k, _, _ in inventory.warnings}):
            rows = [(what, note) for k, what, note in inventory.warnings if k == kind]
            print(f'== {kind} ({len(rows)})')
            for what, note in rows:
                print(f'  {what}: {note}')
    for error in inventory.errors:
        print(f'error: {error}')
    print(f'{len(inventory.features)} features, {len(inventory.errors)} errors; warnings: {summary(inventory)}')
    if getattr(args, 'update_baseline', False):
        (ROOT / BASELINE).write_text(json.dumps(sorted(inventory.backlog()), indent=1, ensure_ascii=False) + '\n')
        print(f'{BASELINE}: {len(inventory.backlog())} backlog items')
    over = inventory.over_baseline() if getattr(args, 'strict', False) else []
    for kind, what, note in over:
        print(f'not allowed: {kind} {what}: {note}')
    failed = inventory.errors or over
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
