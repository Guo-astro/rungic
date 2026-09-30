#!/usr/bin/env python3
"""The agent's model choice (docs/98): Codex's catalog in the common shape, the choice resolved
against it (the account's default when nothing is chosen or the choice is gone), and a catalog
that is read on demand."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'agent/assistant'))
import model_catalog  # noqa: E402

# As the phone's Codex 0.156.1 gave them (model/list, 2026-09-30), shortened.
ASTRA = {'id': 'gpt-6-astra', 'model': 'gpt-6-astra', 'displayName': 'GPT-6-Astra', 'description': 'Frontier',
         'isDefault': True, 'hidden': False, 'defaultReasoningEffort': 'low', 'inputModalities': ['text', 'image'],
         'supportedReasoningEfforts': [{'reasoningEffort': e, 'description': e} for e in
                                       ('low', 'medium', 'high', 'xhigh', 'max', 'ultra')], 'upgrade': None}
LUNA = {'id': 'gpt-6-luna', 'displayName': 'GPT-6-Luna', 'description': 'Fast', 'isDefault': False, 'hidden': False,
        'defaultReasoningEffort': 'medium', 'supportedReasoningEfforts': [{'reasoningEffort': e, 'description': ''}
                                                                         for e in ('low', 'medium', 'high', 'xhigh', 'max')]}
OLD = {'id': 'gpt-5.5', 'displayName': 'GPT-5.5', 'isDefault': False, 'hidden': False, 'defaultReasoningEffort': 'xhigh',
       'supportedReasoningEfforts': [{'reasoningEffort': 'high'}], 'upgrade': 'gpt-5.6-sol',
       'upgradeInfo': {'model': 'gpt-5.6-sol', 'retirementAt': 1800000000}}
HIDDEN = {'id': 'codex-auto-review', 'displayName': 'Codex Auto Review', 'isDefault': False, 'hidden': True,
          'defaultReasoningEffort': 'medium', 'supportedReasoningEfforts': []}
MODELS = [model_catalog.normalize_codex(m) for m in (ASTRA, LUNA, OLD)]


class NormalizeTests(unittest.TestCase):
    def test_common_shape(self):
        astra = MODELS[0]
        self.assertEqual(astra['id'], 'gpt-6-astra')
        self.assertEqual(astra['name'], 'GPT-6-Astra')
        self.assertTrue(astra['default'])
        self.assertEqual([e['id'] for e in astra['efforts']], ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'])
        self.assertEqual(astra['defaultEffort'], 'low')
        self.assertEqual(MODELS[2]['upgrade'], 'gpt-5.6-sol')
        self.assertEqual(MODELS[2]['retiresAt'], 1800000000)


class ResolveTests(unittest.TestCase):
    def test_default_follows_the_account(self):
        r = model_catalog.resolve(MODELS, {'model': '', 'effort': ''})
        self.assertEqual((r['model'], r['effort'], r['following'], r['fallback']), ('gpt-6-astra', 'low', True, False))

    def test_chosen_model_and_effort(self):
        r = model_catalog.resolve(MODELS, {'model': 'gpt-6-luna', 'effort': 'high'})
        self.assertEqual((r['model'], r['effort'], r['name']), ('gpt-6-luna', 'high', 'GPT-6-Luna'))

    def test_effort_default_is_the_models(self):
        self.assertEqual(model_catalog.resolve(MODELS, {'model': 'gpt-6-luna', 'effort': ''})['effort'], 'medium')

    def test_gone_model_falls_back_to_the_default(self):
        r = model_catalog.resolve(MODELS, {'model': 'gpt-4', 'effort': 'ultra'})
        self.assertEqual((r['model'], r['effort'], r['fallback'], r['effortFallback']), ('gpt-6-astra', 'ultra', True, False))

    def test_unsupported_effort_falls_back(self):
        r = model_catalog.resolve(MODELS, {'model': 'gpt-6-luna', 'effort': 'ultra'})
        self.assertEqual((r['effort'], r['effortFallback']), ('medium', True))

    def test_unknown_catalog_leaves_it_to_the_provider(self):
        r = model_catalog.resolve(None, {'model': '', 'effort': ''})
        self.assertEqual((r['model'], r['effort']), (None, None))
        self.assertEqual(model_catalog.resolve(None, {'model': 'gpt-6-luna', 'effort': 'low'})['model'], 'gpt-6-luna')

    def test_choice_values_are_strings(self):
        self.assertEqual(model_catalog.normalize_choice({'model': 3, 'effort': None, 'x': 'y'}), {'model': '', 'effort': ''})
        self.assertEqual(model_catalog.normalize_choice('nonsense'), {'model': '', 'effort': ''})


class ValidTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(model_catalog.valid_choice(MODELS, {'model': 'gpt-6-luna', 'effort': 'max'}), '')
        self.assertEqual(model_catalog.valid_choice(MODELS, {'model': '', 'effort': 'ultra'}), '')   # Astra has it
        self.assertEqual(model_catalog.valid_choice(None, {'model': 'anything'}), '')

    def test_invalid(self):
        self.assertIn('unknown model', model_catalog.valid_choice(MODELS, {'model': 'gpt-4'}))
        self.assertIn('no reasoning effort', model_catalog.valid_choice(MODELS, {'model': 'gpt-6-luna', 'effort': 'ultra'}))


class FakeServer:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def call(self, method, params, timeout=60):
        self.calls.append((method, params))
        return self.pages[len(self.calls) - 1]


class CodexCatalogTests(unittest.TestCase):
    def test_pages_and_hidden(self):
        server = FakeServer([{'data': [ASTRA, HIDDEN], 'nextCursor': 'c1'}, {'data': [LUNA], 'nextCursor': None}])
        catalog = model_catalog.CodexCatalog(lambda: server)
        self.assertEqual([m['id'] for m in catalog.read()], ['gpt-6-astra', 'gpt-6-luna'])
        self.assertEqual(server.calls[1][1]['cursor'], 'c1')
        self.assertFalse(server.calls[0][1]['includeHidden'])

    def test_cached_until_forgotten(self):
        server = FakeServer([{'data': [ASTRA]}, {'data': [LUNA]}])
        catalog = model_catalog.CodexCatalog(lambda: server)
        catalog.read()
        catalog.read()
        self.assertEqual(len(server.calls), 1)
        catalog.forget()
        self.assertEqual([m['id'] for m in catalog.read()], ['gpt-6-luna'])

    def test_failure_keeps_the_last_catalog(self):
        server = FakeServer([{'data': [ASTRA]}])
        catalog = model_catalog.CodexCatalog(lambda: server)
        catalog.read()
        catalog.server = lambda: None
        self.assertEqual([m['id'] for m in catalog.read(refresh=True)], ['gpt-6-astra'])
        self.assertEqual(catalog.error, 'Codex is not running')

    def test_describe(self):
        server = FakeServer([{'data': [ASTRA, LUNA]}])
        catalog = model_catalog.CodexCatalog(lambda: server)
        catalog.read()
        reply = catalog.describe({'model': 'gpt-6-luna'})
        self.assertEqual((reply['provider'], reply['known'], reply['effective']['model']), ('codex', True, 'gpt-6-luna'))


if __name__ == '__main__':
    unittest.main()
