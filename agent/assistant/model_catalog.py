# SPDX-License-Identifier: GPL-2.0-or-later
"""The agent's models, whichever provider runs it (docs/98).

A provider's catalog is read into one shape, so the service, the D-Bus interface and the app
never depend on a provider's own fields:

  {"id": "gpt-6-astra", "name": "GPT-6-Astra", "description": "...", "default": true,
   "efforts": [{"id": "low", "description": "..."}, ...], "defaultEffort": "low",
   "upgrade": null | "<model id>", "retiresAt": null | epoch, "inputs": ["text", "image"]}

The user's choice is {"model": "" | id, "effort": "" | effort id}: "" follows the account's
default model and that model's default effort, so a new default of the provider applies by
itself. resolve() turns a choice into what the agent runs with, falling back to the default
when the account no longer offers the chosen model or effort.

A provider implements Catalog.fetch() (and name); Codex is CodexCatalog, reading the
app-server's model/list. Another agent adds its own subclass and an entry in PROVIDERS.
"""
import time

REFRESH_S = 600          # a catalog older than this is read again when it is asked for


def normalize_choice(values):
    """{"model", "effort"}: strings, '' for "the default"."""
    values = values if isinstance(values, dict) else {}
    return {k: values.get(k) if isinstance(values.get(k), str) else '' for k in ('model', 'effort')}


def resolve(models, choice):
    """What the agent runs with for `choice`, given the catalog `models` (None: not read yet).

    -> {"model": id | None, "effort": id | None, "following": bool, "fallback": bool,
        "effortFallback": bool, "name": display name}
    model None means "let the provider pick" (catalog unknown and following the default)."""
    choice = normalize_choice(choice)
    result = {'model': choice['model'] or None, 'effort': choice['effort'] or None,
              'following': not choice['model'], 'fallback': False, 'effortFallback': False,
              'name': choice['model']}
    if not models:
        return result
    by_id = {m['id']: m for m in models}
    default = next((m for m in models if m.get('default')), models[0])
    chosen = by_id.get(choice['model']) if choice['model'] else default
    if chosen is None:
        chosen, result['fallback'] = default, True
    efforts = [e['id'] for e in chosen.get('efforts', [])]
    effort = choice['effort'] if choice['effort'] in efforts else None
    if choice['effort'] and effort is None:
        result['effortFallback'] = True
    result.update(model=chosen['id'], name=chosen.get('name') or chosen['id'],
                  effort=effort or chosen.get('defaultEffort') or None)
    return result


def valid_choice(models, choice):
    """An error text for a choice the catalog doesn't allow, or '' (an unknown catalog allows it)."""
    choice = normalize_choice(choice)
    if not models:
        return ''
    by_id = {m['id']: m for m in models}
    if choice['model'] and choice['model'] not in by_id:
        return f"unknown model {choice['model']}"
    model = by_id.get(choice['model']) or next((m for m in models if m.get('default')), models[0])
    if choice['effort'] and choice['effort'] not in [e['id'] for e in model.get('efforts', [])]:
        return f"{model['id']} has no reasoning effort {choice['effort']}"
    return ''


class Catalog:
    """A provider's models, read on demand and kept for REFRESH_S."""
    provider = ''
    name = ''

    def __init__(self):
        self.models = None       # None: never read; []: read, none offered
        self.fetched = 0.0
        self.error = ''

    def fetch(self):
        """The provider's models in the common shape (raises on failure)."""
        raise NotImplementedError

    def read(self, refresh=False):
        if refresh or self.models is None or time.time() - self.fetched > REFRESH_S:
            try:
                self.models = self.fetch()
                self.fetched, self.error = time.time(), ''
            except Exception as error:   # noqa: BLE001  (offline, signed out: keep what we had)
                self.error = str(error) or type(error).__name__
        return self.models

    def forget(self):
        """The account changed: its models are read again on the next read()."""
        self.models, self.fetched = None, 0.0

    def describe(self, choice):
        """The D-Bus reply of Models(): the catalog, the choice and what it resolves to."""
        return {'provider': self.provider, 'name': self.name, 'models': self.models or [],
                'known': self.models is not None, 'error': self.error, 'fetched': self.fetched,
                'choice': normalize_choice(choice), 'effective': resolve(self.models, choice)}


def normalize_codex(entry):
    """One entry of Codex's model/list (app-server v2 Model) in the common shape."""
    upgrade = entry.get('upgradeInfo') or {}
    return {'id': entry['id'], 'name': entry.get('displayName') or entry['id'],
            'description': entry.get('description') or '', 'default': bool(entry.get('isDefault')),
            'efforts': [{'id': e['reasoningEffort'], 'description': e.get('description') or ''}
                        for e in entry.get('supportedReasoningEfforts') or [] if e.get('reasoningEffort')],
            'defaultEffort': entry.get('defaultReasoningEffort') or '',
            'upgrade': entry.get('upgrade') or upgrade.get('model') or None,
            'retiresAt': upgrade.get('retirementAt'), 'inputs': list(entry.get('inputModalities') or [])}


class CodexCatalog(Catalog):
    """Codex's models for the signed-in account (app-server model/list, hidden ones left out)."""
    provider = 'codex'
    name = 'Codex'

    def __init__(self, server):
        super().__init__()
        self.server = server         # callable returning the running AppServer, or None

    def fetch(self):
        server = self.server()
        if not server:
            raise RuntimeError('Codex is not running')
        models, cursor = [], None
        for _ in range(10):
            params = {'includeHidden': False, 'limit': 100, **({'cursor': cursor} if cursor else {})}
            reply = server.call('model/list', params, timeout=15)
            models += [normalize_codex(m) for m in reply.get('data') or [] if not m.get('hidden')]
            cursor = reply.get('nextCursor')
            if not cursor:
                break
        return models
