"""moto-clicker: whole desktop goals, every step chosen by JEV (docs/64).

typesafe-computer-use (vendor/typesafe-computer-use) with the Linux platform adapter: each step
captures the display, reads it (OCR plus the accessibility tree), and asks JEV which action
comes next. The writer model only writes text: what to type, and the answer when JEV stops.

  moto-clicker run GOAL [--steps N] [--reply QUESTION=ANSWER ...]   one JSON result on stdout
  moto-clicker stop                                                 stop a running goal
  moto-clicker inspect [GOAL]                                       what JEV would see, no action

A question the writer wants to put to the user ends the run with outcome "question": whoever
started it asks the user and runs the goal again with --reply. The voice assistant owns the
conversation, so nothing here listens for an answer.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HOME = Path.home()
KEYS = {
    "TYPESAFE_API_KEY": (HOME / ".config/moto-cua/typesafe-api-key", HOME / ".config/moto-voice-agent/typesafe-api-key"),
    "CLICKER_WRITER_API_KEY": (HOME / ".config/moto-voice-agent/openai-api-key",),
}
DEFAULTS = {
    "CLICKER_PLATFORM": "linux",
    "CLICKER_WRITER_API": "openai",
    "CLICKER_WRITER_BASE_URL": "https://api.openai.com/v1",
    "CLICKER_WRITER_MODEL": "gpt-6-luna",
    "CLICKER_ANSWER_MODEL": "gpt-6-luna",
    "CLICKER_BROWSER": "firefox",
}
RUNS = HOME / ".local/state/moto-clicker/runs"
KEEP_RUNS = 20


def configure() -> None:
    """Keys from the device's own files, model and browser defaults; the environment wins."""
    for name, value in DEFAULTS.items():
        os.environ.setdefault(name, value)
    for name, paths in KEYS.items():
        if os.environ.get(name):
            continue
        for path in paths:
            if path.exists():
                os.environ[name] = path.read_text().strip()
                break
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise SystemExit("No JEV (TypeSafe) API key: put it in ~/.config/moto-cua/typesafe-api-key")


class NeedsAnswer(Exception):
    """The writer has a question only the user can answer."""


def ask(question: str) -> str:
    raise NeedsAnswer(question)


def with_replies(goal: str, replies: list[str]) -> str:
    """Earlier answers from the user travel with the goal, the one text every model reads."""
    if not replies:
        return goal
    lines = [f"- {q.strip()} → {a.strip()}" for q, _, a in (r.partition("=") for r in replies)]
    return goal + "\nThe user already answered:\n" + "\n".join(lines)


def prune_runs() -> None:
    runs = sorted(p for p in RUNS.iterdir() if p.is_dir()) if RUNS.exists() else []
    for old in runs[:-KEEP_RUNS]:
        for f in old.iterdir():
            f.unlink()
        old.rmdir()


def run_goal(goal: str, steps: int, replies: list[str], delay: float) -> dict:
    from typesafe_computer_use import linux
    from typesafe_computer_use.actions import Context
    from typesafe_computer_use.runner import RunConfig, run
    from typesafe_computer_use.writer import make_writer

    linux.ABORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    linux.ABORT_FILE.unlink(missing_ok=True)
    (linux.ABORT_FILE.parent / "pid").write_text(str(os.getpid()))
    prune_runs()
    out = RUNS / time.strftime("%Y%m%d-%H%M%S")
    full_goal = with_replies(goal, replies)
    writer = make_writer()
    cfg = RunConfig(goal=full_goal, out=out, act=True, steps=steps, delay=delay)
    question = None

    def ctx_factory(typesafe, history):
        return Context(goal=full_goal, browser=os.environ["CLICKER_BROWSER"], email=None, typesafe=typesafe,
                       writer=writer, history=history, ask=ask)

    started = time.time()
    # The runner's log goes to stdout; keep stdout for the one JSON result.
    real_stdout, sys.stdout = sys.stdout, sys.stderr
    try:
        state = run(cfg, ctx_factory)
        outcome = state.outcome
    except NeedsAnswer as e:
        question, outcome = str(e), "question"
        state = None
    finally:
        sys.stdout = real_stdout
    summary = json.loads((out / "run.json").read_text()) if (out / "run.json").exists() else {}
    result = {
        "outcome": outcome,
        "achieved": summary.get("goal_achieved"),
        "answer": summary.get("answer"),
        "steps": summary.get("history", state.history if state else []),
        "seconds": round(time.time() - started, 1),
        "run": str(out),
    }
    if question:
        result["question"] = question
    return result


def inspect(goal: str) -> dict:
    from typesafe_computer_use.config import MAX_OPTIONS
    from typesafe_computer_use.perception import capture, perceive

    timing: dict[str, float] = {}
    screen = capture(browser=os.environ["CLICKER_BROWSER"], timing=timing)
    items = perceive(screen, MAX_OPTIONS, goal, timing)
    return {
        "app": screen.app,
        "window": screen.window,
        "field": screen.field.summary() if screen.field else None,
        "items": [{"i": it.index, "text": it.text, "role": it.role, "source": it.source} for it in items],
        "offscreen": [n.label for n in screen.offscreen],
        "timing": timing,
    }


def stop() -> dict:
    from typesafe_computer_use import linux

    linux.ABORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    linux.ABORT_FILE.touch()
    return {"stopping": True}


def main() -> None:
    parser = argparse.ArgumentParser(prog="moto-clicker", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("goal")
    p_run.add_argument("--steps", type=int, default=30)
    p_run.add_argument("--delay", type=float, default=1.0, help="seconds to let the screen settle after each action")
    p_run.add_argument("--reply", action="append", default=[], help="QUESTION=ANSWER from an earlier run")
    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("goal", nargs="?", default="(no goal given)")
    sub.add_parser("stop")
    args = parser.parse_args()
    configure()
    if args.command == "run":
        data = run_goal(args.goal, args.steps, args.reply, args.delay)
    elif args.command == "inspect":
        data = inspect(args.goal)
    else:
        data = stop()
    print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
