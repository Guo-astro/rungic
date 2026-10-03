# SPDX-License-Identifier: MIT
"""release/acceptance.json against tools/rungic_acceptance.py, offline: every scenario names a check
that exists and takes its parameters, so a renamed or removed check fails here, not on the phone
(cast.agent_screen named agent_screen_output for days after it was gone)."""
import inspect
import json
from pathlib import Path

import rungic_acceptance

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = json.loads((ROOT / 'release/acceptance.json').read_text())['scenarios']


# covers: delivery.acceptance
def test_every_scenario_names_a_check_that_takes_its_parameters():
    for scenario in SCENARIOS:
        fn = rungic_acceptance.CHECKS.get(scenario['check'])
        assert fn, f"{scenario['id']}: no check {scenario['check']!r} in tools/rungic_acceptance.py"
        inspect.signature(fn).bind(None, **scenario.get('params', {}))


# covers: delivery.acceptance
def test_scenarios_are_unique_and_run_at_a_known_level():
    ids = [s['id'] for s in SCENARIOS]
    assert len(ids) == len(set(ids)), 'a scenario id is used twice'
    assert {s['level'] for s in SCENARIOS} <= {'smoke', 'full'}
