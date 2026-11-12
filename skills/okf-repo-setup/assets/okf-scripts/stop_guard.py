#!/usr/bin/env python3
"""Stop hook: don't let a session end with code changed and okf-bundle/ left behind.

Why a Stop hook and not the SessionStart signal we had before: SessionStart fires
*before* the diff exists, so by the time the work is done the reminder is long out
of attention. Two cycles (~200 commits) produced exactly zero in-flow bundle
updates that way. Stop fires when the work is finished and the diff is real.

What the branch owes is `drift.py --gate` — the same rule CI applies to the PR:
concepts the branch made STALE and did not update (per concept: one refreshed
concept must not wave through another; whitespace is not an update), plus files
changed past every anchor while okf-bundle/ was left alone. A commit carrying
`okf: n/a — <reason>` takes its own files out of it.

Blocks (exit 2, stderr goes back to the model) when the branch owes something and
this session has not been told about this same set yet. Stop fires at the end of
every turn, not of the session: blocking on each of them would also intercept a
question the agent asks the human mid-task. A new concept in the debt, or a new
session, is news and blocks again.

Escape hatches, in order of bluntness:
  - OKF_SKIP=1 in the environment — for exploratory sessions (CI still checks);
  - `okf: n/a — <reason>` in the commit message — the decision stays in git, and
    CI accepts it;
  - let it block once and stop again: the second Stop carries `stop_hook_active`.

Never blocks when it cannot tell (no git, no merge-base, drift.py failure): a hook
that fails closed would strand the session over its own bug.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = os.environ.get("OKF_BASE_REF", "__OKF_BASE_REF__")
MAX_LISTED = 8


def git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(REPO), *args],
                           capture_output=True, text=True, timeout=15)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def drift_json(*flags: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts/okf/drift.py"), "--branch", BASE, "--worktree", "--json", *flags],
        capture_output=True, text=True, timeout=60, cwd=str(REPO))
    return json.loads(proc.stdout or "{}")


def debt(base: str) -> tuple[list[str], list[str]]:
    """(owed concepts, files past every anchor) for this branch, worktree included."""
    data = drift_json("--gate")
    if "owed" in data:
        return sorted(data["owed"]), [u["path"] for u in data.get("owed_unmatched") or []]
    # drift.py older than this hook (kept by install.py as locally changed): the old rule.
    data = drift_json()
    touched = any(p.startswith("okf-bundle/") for p in (git("diff", "--name-only", base) or "").splitlines())
    touched = touched or bool(git("ls-files", "--others", "--exclude-standard", "okf-bundle"))
    done = set(data.get("refreshed") or [])
    owed = sorted(c for c in (data.get("stale") or {}) if c not in done)
    unmatched = [] if touched else [u["path"] for u in data.get("unmatched") or []]
    return owed, unmatched


def already_told(session: str, owed: list[str], unmatched: list[str]) -> bool:
    """Has this session been blocked over exactly this debt? Marks it if not."""
    if not session:
        return False
    key = hashlib.sha1("\0".join([str(REPO), session, *owed, "|", *unmatched]).encode()).hexdigest()[:20]
    mark = Path(tempfile.gettempdir()) / f"okf-stop-{key}"
    if mark.exists():
        return True
    try:
        mark.touch()
    except OSError:
        pass
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    # Loop guard: we already blocked once this turn, let the session end.
    if payload.get("stop_hook_active"):
        return 0
    if os.environ.get("OKF_SKIP"):
        return 0

    base = git("merge-base", BASE, "HEAD")
    if not base:
        return 0  # detached, no upstream, fresh clone — not our business

    try:
        owed, unmatched = debt(base)
    except Exception:
        return 0  # detector broke — never strand the session over that
    if not owed and not unmatched:
        return 0
    if already_told(str(payload.get("session_id") or ""), owed, unmatched):
        return 0

    shown = ", ".join(owed[:MAX_LISTED]) + (f" (+{len(owed) - MAX_LISTED})" if len(owed) > MAX_LISTED else "")
    lines = [
        "Правки кода в этой ветке задели концепты бандла знаний, которые не обновлены.",
        "",
        f"Устарело концептов: {len(owed)}" + (f" — {shown}" if owed else ""),
    ]
    if unmatched:
        lines.append("Мимо якорей (проверить вручную): " + ", ".join(unmatched[:MAX_LISTED]))
    lines += [
        "",
        "Обнови затронутые концепты по правилам скилла `okf` и закоммить их отдельным",
        "коммитом `docs(okf): ...`. Полный отчёт: `python3 scripts/okf/drift.py --gate`.",
        "Концепт считается обработанным, когда его текст изменён в этой ветке (пробелы не в счёт).",
        "Если поведение не менялось (рефакторинг, эксперимент) — добавь в сообщение коммита",
        "с этим кодом `okf: n/a — <причина>`: CI на PR проверяет то же самое и примет отказ.",
        "Об этом наборе концептов в этой сессии больше не напомню.",
    ]
    print("\n".join(lines), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
