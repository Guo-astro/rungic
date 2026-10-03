"""The team's board in the leading conversation (agent/assistant/team_feed.py, docs/research/91 §14)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'agent/assistant'))
import team_feed  # noqa: E402

LEAD = 'conversation-thread'


def board(posts, phase='working', updated=1000.0):
    return {'lead': LEAD, 'phase': phase, 'title': 'Pixel Flappy', 'started': 900.0, 'updated': updated,
            'members': [{'role': 'lead', 'lead': True, 'kind': 'decision'}, {'role': 'art', 'kind': 'progress'}],
            'reviews': [], 'decision': '', 'result': '', 'posts': posts}


def write(path, data):
    path.write_text(json.dumps(data))
    # A new mtime each write, as a real update would have.
    import os
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 1 + data['updated'] / 1e6))


# covers: agent.team-board/E2
def test_each_change_once_with_only_new_posts(tmp_path):
    path = tmp_path / 'team-board.json'
    feed = team_feed.Feed(path, clock=lambda: 1010.0)
    assert feed.poll() == (None, [])
    write(path, board([{'role': 'lead', 'kind': 'brief', 'text': 'Go', 'time': 950.0}]))
    b, new = feed.poll()
    assert b['title'] == 'Pixel Flappy' and [p['kind'] for p in new] == ['brief']
    assert feed.poll() == (None, []), 'an unchanged file is nothing new'
    write(path, board([{'role': 'lead', 'kind': 'brief', 'text': 'Go', 'time': 950.0},
                       {'role': 'art', 'kind': 'done', 'text': '4 PNGs', 'time': 990.0}], updated=1001.0))
    assert [p['kind'] for p in feed.poll()[1]] == ['done']


# covers: agent.team-board/E5
def test_an_old_board_is_not_announced_again(tmp_path):
    path = tmp_path / 'team-board.json'
    write(path, board([{'role': 'art', 'kind': 'done', 'text': 'x', 'time': 990.0}], updated=1000.0))
    b, new = team_feed.Feed(path, clock=lambda: 5000.0).poll()
    assert b is not None and new == []


# covers: agent.team-board/E3
def test_only_what_matters_is_said_or_notified():
    b = board([])
    m = team_feed.milestone
    assert m({'role': 'art', 'kind': 'review', 'text': '2 points'}, b) is None
    assert m({'role': 'art', 'kind': 'progress', 'text': 'Layers'}, b) is None
    assert m({'role': 'lead', 'kind': 'brief', 'text': 'Go'}, b) is None
    started = m({'role': 'lead', 'kind': 'decision', 'text': 'All accepted'}, b)
    assert started['say'] and not started['notify']
    finished = m({'role': 'art', 'kind': 'done', 'text': '4 PNGs'}, b)
    assert 'art' in finished['say'] and not finished['notify']
    asked = m({'role': 'art', 'kind': 'question', 'text': 'Which palette?'}, b)
    assert asked['notify'] and asked['urgent'] and 'Which palette?' in asked['say']
    over = m({'role': 'lead', 'kind': 'done', 'text': 'Ready'}, b)
    assert over['notify'] and not over['say'], "the lead's answer is spoken with its turn"


# covers: agent.team-board/E2
def test_the_card_leaves_the_posts_out():
    assert 'posts' not in team_feed.card(board([{'kind': 'brief'}])) and team_feed.card(board([]))['title']
