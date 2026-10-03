# SPDX-License-Identifier: MIT
"""The contracts themselves (quality/contracts/*.json) and the provider check that reads them on the
phone (tools/rungic_acceptance.py interface_contract), offline: every contract is well formed and keeps
its own examples, every one with read-only queries has its acceptance scenario, and the check, run here
against tools/contracts.py's stand-ins instead of the phone, passes a provider that keeps the contract,
names what a broken one breaks, never sends a query that changes something, and checks who serves an
abstract socket. Nothing here reaches the phone."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import contracts  # noqa: E402
import rungic_acceptance  # noqa: E402

ASK = "python3 - <<'ASK'"
SCENARIOS = json.loads((ROOT / 'release/acceptance.json').read_text())['scenarios']
INTERFACES = {i['id'] for i in yaml.safe_load((ROOT / 'quality/interfaces.yaml').read_text())}


def queries(name):
    return contracts.load(name)['queries']


# covers: delivery.system-tests/E2
@pytest.mark.parametrize('name', contracts.names())
def test_a_contract_is_well_formed_and_keeps_its_own_examples(name):
    contract = contracts.load(name)
    assert contract['interface'] == name and name in INTERFACES
    names = [q['name'] for q in contract['queries']]
    assert len(names) == len(set(names)), 'query names are unique'
    sockets = contracts.sockets(contract)
    for q in contract['queries']:
        where = f'{name}/{q["name"]}'
        assert isinstance(q.get('read_only'), bool), f'{where}: says whether the provider check may send it'
        for example in contracts.replies(q) if ('reply' in q or 'replies' in q) else []:
            assert contracts.check_reply(q, example) == [], where
        if 'command' in q:
            assert q.get('as', 'root') in ('root', 'container', 'user'), where
            assert q.get('format', 'json') in ('json', 'properties', 'exit', 'text'), where
            assert q.get('format') != 'text' or q.get('expect'), f'{where}: text needs expect'
            continue
        assert 'request' in q and isinstance(q['request'], dict), where
        assert contracts.matches(q, q['request']), f'{where}: its own request matches it'
        assert q.get('socket', next(iter(sockets))) in sockets, where
        assert not q.get('payload') or isinstance(q['request'].get(q['payload']), int), where
    if contract.get('framing') == 'binary':
        assert all(int(v, 0) >= 0 for v in contract['constants'].values())
    for q in contract['queries']:
        others = [o for o in contract['queries'] if o is not q and 'request' in o and 'request' in q
                  and contracts.socket_of(contract, o)[0] == contracts.socket_of(contract, q)[0]]
        assert not any(contracts.matches(o, q['request']) for o in others
                       if contract['queries'].index(o) < contract['queries'].index(q)), \
            f'{name}/{q["name"]}: an earlier query answers its request'


# covers: delivery.system-tests/E2
@pytest.mark.parametrize('name', contracts.names())
def test_a_contract_with_read_only_queries_is_checked_on_the_phone(name):
    if not any(q['read_only'] for q in queries(name)):
        return
    scenario = [s for s in SCENARIOS if s['check'] == 'interface_contract' and s.get('params', {}).get('interface') == name]
    assert len(scenario) == 1, f'one acceptance scenario runs interface_contract for {name}'
    assert f'iface:{name}' in scenario[0]['covers']


class Phone:
    """rungic_acceptance's run(), here: the container script runs on this computer against stand-ins
    (the platform bridge's path through its variable, abstract sockets routed), commands get canned
    outputs. Records every command it was asked to run."""

    def __init__(self, standins=(), outputs=None):
        self.platform = next((s for s in standins if s.spec.get('env')), None)
        self.routed = {s.address: [s.path, s.spec.get('peer_uid')] for s in standins if not s.spec.get('env')}
        self.outputs, self.commands = outputs or {}, []

    def __call__(self, script, level='root', timeout=60, check=True):
        if script.startswith(ASK):
            local = script.replace(ASK, f"{sys.executable} {contracts.__file__} run '{json.dumps(self.routed)}' - <<'ASK'", 1)
            env = {'PATH': '/usr/bin:/bin'}
            if self.platform:
                env[self.platform.spec['env']] = self.platform.path
            return subprocess.run(['sh'], input=local, capture_output=True, text=True, timeout=timeout, env=env)
        self.commands.append((script, level))
        code, out = self.outputs.get(script, (127, ''))
        return subprocess.CompletedProcess(script, code, out, '')


def check(monkeypatch, name, phone):
    monkeypatch.setattr(rungic_acceptance, 'run', phone)
    return rungic_acceptance.interface_contract({}, name)


# covers: delivery.system-tests/E2
@pytest.mark.parametrize('names', [['platform-bridge'], ['network', 'telephony'], ['bluetooth'], ['camera'],
                                   ['audio'], ['ocr'], ['wifi-display', 'platform-bridge']])
def test_the_provider_check_passes_a_provider_that_keeps_the_contract(monkeypatch, names):
    with contracts.StandIn(names) as android:
        result = check(monkeypatch, names[0], Phone([android]))
    assert result['passed'], result['details']
    read_only = [q['request'] for q in queries(names[0]) if q['read_only']]
    assert sorted(map(json.dumps, android.requests)) == sorted(map(json.dumps, read_only)), \
        'exactly the read-only queries were sent, nothing that changes the phone'
    assert all(len(p) == q['request'].get(q.get('payload'), 0)
               for p, q in zip(android.payloads, [q for q in queries(names[0]) if q.get('payload')]))


# covers: delivery.system-tests/E2
def test_the_provider_check_names_what_a_broken_provider_breaks(monkeypatch):
    snapshot = next(q for q in queries('network') if q['name'] == 'network-get')['reply']
    broken = {**snapshot, 'networks': [{k: v for k, v in snapshot['networks'][0].items() if k != 'interface'}]}
    with contracts.StandIn(['network', 'telephony'], {'network-get': broken}, keep_contract=False) as android:
        result = check(monkeypatch, 'network', Phone([android]))
    assert not result['passed']
    assert result['details']['problems'] == {'network-get': ['reply.networks[0].interface: missing']}
    with contracts.StandIn('network', handler=lambda name, request: {'error': 'Wi-Fi request failed'}) as android:
        result = check(monkeypatch, 'network', Phone([android]))
    assert result['details']['problems']['wifi-saved'] == ['error reply: Wi-Fi request failed']


# covers: delivery.system-tests/E2
def test_an_abstract_socket_must_be_served_by_the_trusted_uid(monkeypatch):
    with contracts.StandIn('telephony') as platform, contracts.StandIn('telephony', socket_name='calls') as calls:
        result = check(monkeypatch, 'telephony', Phone([platform, calls]))
        assert result['passed'], result['details']
        calls.spec = {**calls.spec, 'peer_uid': 10123}       # someone else listening on the name
        result = check(monkeypatch, 'telephony', Phone([platform, calls]))
    assert result['details']['problems'] == {'call-status': ['served by uid 10123, not 0']}
    with contracts.StandIn('clipboard', {'clipboard-get': {'available': True, 'text': 'a secret'}}) as daemon:
        phone = Phone([daemon])
        monkeypatch.setattr(rungic_acceptance, 'run', phone)
        script = rungic_acceptance.CONTRACT_ASK % repr(json.dumps([{
            'name': 'clipboard-get', 'request': {'op': 'clipboard-get'}, 'address': daemon.address, 'env': None,
            'peer_uid': 2000, 'timeout': 5, 'payload': 0, 'private': ['text']}]))
        out = phone(script, 'user').stdout
        assert 'a secret' not in out, 'private fields are blanked before they leave the phone'
        assert json.loads(out)['reply'] == {'available': True, 'text': ''}
        assert check(monkeypatch, 'clipboard', phone)['passed']


# covers: delivery.system-tests/E2
def test_command_queries_are_read_only_and_parsed_as_the_contract_says(monkeypatch):
    host = {q['name']: q['command'] for q in queries('host-controller')}
    phone = Phone(outputs={
        host['account-status']: (0, 'some warning\n{"configured": true, "username": "kevin"}\n'),
        host['memory-status']: (0, json.dumps(next(q for q in queries('host-controller') if q['name'] == 'memory-status')['reply'])),
        host['install-state']: (0, 'RELEASE_ID=20261003.1\nschema=2\nrelease=20261003.1\nstate=ready\nphase=complete\n'
                                   'updated=1790000000\nerror=none\n'),
    })
    result = check(monkeypatch, 'host-controller', phone)
    assert result['passed'], result['details']
    assert {c for c, _ in phone.commands} == {host['account-status'], host['memory-status'], host['install-state']}
    assert all(level == 'root' for _, level in phone.commands)
    phone.outputs[host['install-state']] = (0, 'RELEASE_ID=20261003.1\nstate=ready\n')
    phone.outputs[host['account-status']] = (1, 'Rungic 正在完成首次安装')
    problems = check(monkeypatch, 'host-controller', phone)['details']['problems']
    assert set(problems) == {'install-state', 'account-status'}
    gpu = {q['name']: q['command'] for q in queries('gpu-device')}
    phone = Phone(outputs={gpu['kgsl']: (0, ''), gpu['dma-heap']: (1, ''), gpu['render']: (0, 'GL_RENDERER: FD710')})
    assert check(monkeypatch, 'gpu-device', phone)['details']['problems'] == {'dma-heap': ['exit 1, not 0: ']}
    storage = {q['name']: q['command'] for q in queries('shared-storage')}
    phone = Phone(outputs={storage['android-storage']: (0, 'fuseblk\n'), storage['shared-home']: (0, ''),
                           storage['user-dirs']: (0, '')})
    assert check(monkeypatch, 'shared-storage', phone)['passed']
    assert {level for _, level in phone.commands} == {'container', 'user'}
