#!/usr/bin/env python3
"""Git merge driver for OKF concepts: the date of a refresh no longer conflicts.

Two branches that refreshed the same concept each set its date (`generated.at`, or
v0.1's `timestamp`), so merging them conflicts on that frontmatter entry even when
the texts merge cleanly — in one project that was half of all concept conflicts.
When both sides changed the entry differently and each holds one date, the driver
gives both sides the later one, then runs git's own three-way merge
(`git merge-file`). Settling the date before the merge, not in its result, matters:
merge-file joins conflicts separated only by `---` and a blank line, so a date and
a disputed first paragraph would come out as one hunk. Every other conflict keeps
its markers and the driver exits 1, as git expects. `union` is no option for
concepts: keeping both sides duplicates `generated:`, and knowledge-mcp refuses to
load such a concept.

Wiring (okf-repo-setup's install.py does both):
  .gitattributes   okf-bundle/**/*.md merge=okf; log.md and .okf-anchor merge=union
  git config       merge.okf.driver — per clone, so the SessionStart hook runs --install

A clone without the config merges concepts the ordinary way: nothing breaks, the
date just conflicts again. A checked-out tree without this script falls back to
`git merge-file` (see DRIVER), so a conflict is never silently resolved as «ours».

Usage:
  python3 scripts/okf/merge_driver.py %O %A %B %L            # called by git
  python3 scripts/okf/merge_driver.py --install [--quiet]   # set merge.okf.driver in this clone
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SCRIPT = "scripts/okf/merge_driver.py"
# Git runs the driver through the shell from the top of the work tree. Only the driver is
# configured: a `merge.okf.name` without it makes every merge of these files fatal.
DRIVER = (f"if [ -f {SCRIPT} ]; then python3 {SCRIPT} %O %A %B %L; "
          "else git merge-file -L ours -L base -L theirs --marker-size=%L %A %O %B; fi")
DATE_KEYS = ("generated", "timestamp")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+)?(?:Z|[+-]\d{2}:?\d{2})?")


def entry(lines: list[str], key: str) -> tuple[int, int] | None:
    """Span of the top-level frontmatter entry `key` (its line plus indented ones), or None."""
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":
            return None
        if lines[i].startswith(key + ":"):
            j = i + 1
            while j < len(lines) and lines[j][:1] in (" ", "\t") and lines[j].strip():
                j += 1
            return i, j
    return None


def settle_dates(base: list[str], ours: list[str], theirs: list[str]) -> bool:
    """Give ours and theirs the later of their date entries where both changed them differently."""
    changed = False
    for key in DATE_KEYS:
        spans = [entry(text, key) for text in (base, ours, theirs)]
        if spans[1] is None or spans[2] is None:
            continue
        b, o, t = ("".join(text[s[0]:s[1]]) if s else None for text, s in zip((base, ours, theirs), spans))
        if o == t or o == b or t == b:  # one side kept it or both agree: an ordinary merge settles it
            continue
        dates = [DATE.findall(o), DATE.findall(t)]
        if len(dates[0]) != 1 or len(dates[1]) != 1:
            continue
        later = t if dates[1][0] > dates[0][0] else o
        for text, (i, j) in ((ours, spans[1]), (theirs, spans[2])):
            text[i:j] = later.splitlines(keepends=True)
        changed = True
    return changed


def merge(base: str, ours: str, theirs: str, size: int) -> int:
    paths = [Path(p) for p in (base, ours, theirs)]
    texts = [p.read_text(encoding="utf-8").splitlines(keepends=True) for p in paths]
    if settle_dates(*texts):
        for p, text in zip(paths[1:], texts[1:]):
            p.write_text("".join(text), encoding="utf-8")
    r = subprocess.run(["git", "merge-file", "-L", "ours", "-L", "base", "-L", "theirs",
                        f"--marker-size={size}", ours, base, theirs])
    if r.returncode == 0:
        return 0
    return 1 if 0 < r.returncode < 128 else 2  # a conflict count, or merge-file itself failed


def configure(repo: Path, dry: bool = False) -> str | None:
    """Set merge.okf.driver in `repo`'s local config: "set", "same", or None outside a git repository."""
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)

    if git("rev-parse", "--git-dir").returncode != 0:
        return None
    if git("config", "--local", "--get", "merge.okf.driver").stdout.rstrip("\n") == DRIVER:
        return "same"
    if not dry and git("config", "--local", "merge.okf.driver", DRIVER).returncode != 0:
        return None
    return "set"


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--install":
        quiet = "--quiet" in argv[1:]
        status = configure(Path(__file__).resolve().parents[2])
        if not quiet:
            print(f"{status or 'skipped':<9} git config merge.okf.driver"
                  + ("" if status else " — not a git repository"))
        return 0 if status or quiet else 2
    if len(argv) not in (3, 4):
        print(__doc__, file=sys.stderr)
        return 2
    size = int(argv[3]) if len(argv) == 4 and argv[3].isdigit() else 7
    return merge(argv[0], argv[1], argv[2], size)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
