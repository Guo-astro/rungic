"""A team's board in the conversation that leads it (docs/research/91 §14).

When the assistant's Codex leads a team (the rungic-agent-team skill), every team_post updates the
board <runtime>/rungic-agent-screen/team-board.json (rungic_cua.team): the brief, the phase, each
member's state and words, the reviews, the lead's decision and result, the last posts. The lead's
thread is the conversation's, so the board goes into that conversation as a card ({"type": "team"}),
and the posts that matter become milestones: some spoken (in the voice's own words), a few notified
while nobody looks at the conversation.

What is said follows the usual practice for agent teams (docs/research/91 §13): only what changes
the plan or needs the user interrupts. Reviews and progress stay on the card.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# A board last changed longer ago than this when first seen (the agent restarted) is history: its
# posts are not announced again.
STALE_S = 60


def board_path() -> Path:
    runtime = os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
    return Path(runtime) / 'rungic-agent-screen' / 'team-board.json'


class Feed:
    """Follows the board file: each change once, with the posts not seen before."""

    def __init__(self, path: Path | None = None, clock=time.time):
        self.path = path or board_path()
        self.clock = clock
        self.mtime = 0.0
        self.seen: dict[str, float] = {}

    def poll(self) -> tuple[dict | None, list[dict]]:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None, []
        if mtime == self.mtime:
            return None, []
        self.mtime = mtime
        try:
            board = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None, []
        lead = board.get('lead') or ''
        posts = board.get('posts') or []
        if lead not in self.seen:
            fresh = self.clock() - float(board.get('updated') or 0) < STALE_S
            self.seen[lead] = float(board.get('started') or 0) - 1 if fresh else float(board.get('updated') or 0)
        new = [p for p in posts if float(p.get('time') or 0) > self.seen[lead]]
        if posts:
            self.seen[lead] = max(self.seen[lead], max(float(p.get('time') or 0) for p in posts))
        return board, new


def card(board: dict) -> dict:
    """The conversation's card: the board without its post history."""
    return {k: v for k, v in board.items() if k != 'posts'}


def is_lead(post: dict, board: dict) -> bool:
    members = board.get('members') or []
    lead = next((m for m in members if m.get('lead')), None)
    return bool(lead) and post.get('role') == lead.get('role')


def milestone(post: dict, board: dict) -> dict | None:
    """What the user hears or sees of `post`: {'say': fact for the voice, 'notify': bool,
    'urgent': bool}, or None for a post that stays on the card."""
    kind, role, text = post.get('kind', ''), post.get('role', ''), post.get('text', '')
    lead = is_lead(post, board)
    if kind in ('question', 'blocked'):
        what = 'has a question' if kind == 'question' else 'is blocked'
        return {'say': f'The team member "{role}" {what}: {text}', 'notify': True, 'urgent': True}
    if lead and kind == 'decision':
        return {'say': f'The lead settled the reviews and the team is now at work: {text}', 'notify': False, 'urgent': False}
    if lead and kind == 'done':
        # The lead's own answer ends the turn and is spoken with it: only a notification here.
        return {'say': '', 'notify': True, 'urgent': False}
    if kind == 'failed':
        return {'say': f'The team member "{role}" failed: {text}', 'notify': True, 'urgent': True}
    if not lead and kind == 'done':
        return {'say': f'The team member "{role}" finished: {text}', 'notify': False, 'urgent': False}
    return None


def spoken(facts: list[str]) -> str:
    """Instructions for the voice (English, like its prompt; it speaks the user's language)."""
    listed = '\n'.join(f'- {fact}' for fact in facts)
    return ("Team update (from the system, not the user's words: say it to the user directly in one short "
            "sentence, in the language you speak with them; do not respond to this message itself)\n"
            f"{listed}\nSay only these facts, plainly; do not repeat what you said before.")
