#!/usr/bin/env python3
"""Detect which parts of okf-bundle/ went stale relative to the code.

The okf skill runs it straight from the plugin; the `okf-repo-setup` skill
vendors it into `scripts/okf/` with the integration branch filled in. It
replaced the simpler `okf_staleness.py`; what it does differently, all of which
matters on real bundles:

  1. Many-to-one resources. A `dict[path] -> concept` index keeps only the last
     concept when several share one `resource:` (a schema file backing a dozen
     concepts reported 1 stale concept). Here a path maps to a *list* of
     concepts, narrowed by `resource_anchors`.
  2. Directory resources. Concepts that describe a whole app or package
     (`resource: apps/web`) are covered too, though the resource has no file
     extension. A changed file is attributed to the *most specific* concept that
     covers it: an exact file match wins, otherwise the longest directory prefix.
  3. Altitude filter. UNCOVERED only lists files that no concept covers at any
     level, minus noise (tests, fixtures, generated output) — new helpers and test
     files are not concepts.
  4. In-flow marks. A STALE concept updated in the same unit of work as every
     change of its sources is marked ◐ (JSON `refreshed`) but still reported: a PR
     that touched the concept often missed part of the change. A unit is a merged
     PR, the current unpushed branch, or — in linear history — the code commits
     closed by a `docs(okf)` commit right after them (see `change_units`). The Stop
     hook uses the mark to ask a branch for exactly the concepts it has not updated
     yet.
  5. Enclosing hunk headers only. `resource_anchors` are matched against the
     changed lines and against a hunk's `@@` header only when the change sits
     inside the declaration that header names (see `anchor_text`), so a new or
     removed top-level declaration doesn't flag the concept of its neighbour —
     neither as STALE nor in the per-commit check behind ◐.

"Since when" is the commit recorded in `okf-bundle/.okf-anchor` (set it with
`--set-anchor` after every refresh). An anchor that is no longer an ancestor of
HEAD (a rebase replayed the history) is not trusted as-is: the range falls back
to its merge-base with HEAD, which over-reports rather than hides drift.

The integration branch (`--branch` default) is the one okf-repo-setup filled in;
an unvendored copy takes $OKF_BASE_REF, else origin/develop, else origin/main.

Usage:
    python3 scripts/okf/drift.py                  # full report
    python3 scripts/okf/drift.py --quiet          # one-line summary (used by the SessionStart hook)
    python3 scripts/okf/drift.py --since HEAD~30  # explicit range
    python3 scripts/okf/drift.py --json
    python3 scripts/okf/drift.py --gate           # what the branch owes (CI and the Stop hook)

Exit code: 0 = no drift, 1 = drift found (with --gate: the branch owes the
bundle, see `report_gate`), 2 = usage/setup error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BUNDLE_DEFAULT = "okf-bundle"
RESERVED = {"index.md", "log.md"}
ANCHOR_FILE = ".okf-anchor"  # commit whose code state the bundle describes
BASE_REF = "__OKF_BASE_REF__"  # integration branch; substituted by okf-repo-setup
# Linear history: code written this long before a bundle-only commit counts as the
# same unit of work (see change_units). A rebase keeps author time, so stale work
# replayed onto the branch does not slip in.
RUN_WINDOW_S = 12 * 3600

# Extensions that can plausibly deserve a concept of their own.
CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".prisma", ".sql", ".yaml", ".yml", ".sh",
            ".php", ".go", ".rb", ".java", ".kt", ".rs", ".cs", ".swift", ".proto", ".graphql"}

# Files that change constantly but never warrant a concept (altitude test).
IGNORE_GLOBS = (
    "*.test.*", "*.spec.*", "*/tests/*", "*/__tests__/*", "*/test_*.py",
    "*/node_modules/*", "*/dist/*", "*/build/*", "*/.venv/*",
    "e2e/*", ".claude/*", "scripts/okf/*", "*/migrations/*",
    "*lock.yaml", "*lock.json", "*.lock",
)


def git(repo: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def read_meta(path: Path) -> dict:
    """Read the top-level frontmatter keys we need, without a YAML dependency.

    Only top-level keys are scanned, so an indented `sources[].resource` is
    correctly ignored (same rule as upstream).
    """
    out: dict = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return out
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    in_generated = False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        indented = line[:1] in (" ", "\t")
        if in_generated and indented:
            m = re.match(r"\s+at:\s*(.+)$", line)
            if m:
                out["generated_at"] = m.group(1).strip().strip("'\"")
            continue
        in_generated = False
        if indented:
            continue
        for key in ("resource", "status", "stale_after"):
            if line.startswith(key + ":"):
                v = line.split(":", 1)[1].strip().strip("'\"")
                if v:
                    out[key] = v
        if line.startswith("resource_anchors:"):
            v = line.split(":", 1)[1].strip()
            if v.startswith("[") and v.endswith("]"):
                out["resource_anchors"] = [a.strip().strip("'\"")
                                           for a in v[1:-1].split(",") if a.strip()]
        if line.startswith("generated:"):
            rest = line.split(":", 1)[1].strip()
            m = re.search(r"\bat:\s*([^,}]+)", rest)
            if m:
                out["generated_at"] = m.group(1).strip().strip("'\"")
            else:
                in_generated = True
    return out


def parse_date(value: str | None):
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def as_repo_path(resource: str) -> str | None:
    """Normalise a `resource:` value to a repo-relative path, or None for URLs."""
    if not resource or "://" in resource:
        return None
    r = resource.strip()
    while r.startswith("./"):
        r = r[2:]
    r = r.lstrip("/")
    return r or None


def read_anchor(bundle: Path, repo: Path) -> tuple[str | None, str]:
    """Return (commit, note) for the bundle's anchor — the code state it describes.

    Prefers the explicit `.okf-anchor` file over guessing from git history: the
    guess ("last commit touching the bundle") silently collapses to an empty range
    after a rebase, because rebasing replays the bundle commit on top of the very
    code changes it has not seen yet.
    """
    f = bundle / ANCHOR_FILE
    if f.is_file():
        shas = [s for s in (l.strip() for l in f.read_text(encoding="utf-8", errors="replace").splitlines())
                if s and not s.startswith("#")]
        # Two branches that each moved the anchor merge the file by union (.gitattributes):
        # both commits are ancestors of the merge, and a range from either one still holds
        # every change of the other branch — the first is taken.
        several = (f" — в нём несколько коммитов ({len(shas)}): ветки слились, диапазон от первого; "
                   f"`--set-anchor` после рефреша оставит один") if len(shas) > 1 else ""
        for line in shas:
            if git(repo, "cat-file", "-e", line + "^{commit}") is not None:
                if git(repo, "merge-base", "--is-ancestor", line, "HEAD") is not None:
                    return line, "файл .okf-anchor" + several
                # After `pull --rebase` the anchor can name a replaced twin of a
                # commit: still in the object store, but off HEAD's history. Diffing
                # from it drags already-refreshed work into the range and pushes
                # real changes behind it; the merge-base covers both sides.
                base = git(repo, "merge-base", line, "HEAD")
                if base:
                    return base, (f"⚠ якорь {line[:12]} не предок HEAD (ребейз?) — диапазон "
                                  f"от merge-base {base[:12]}, возможны лишние STALE; после "
                                  f"рефреша: `python3 scripts/okf/drift.py --set-anchor`")
            return None, (f"⚠ .okf-anchor указывает на несуществующий коммит {line[:12]} "
                          f"(перезаписан историей?) — задайте якорь заново: "
                          f"`python3 scripts/okf/drift.py --set-anchor <ref>`")
    return None, "последний коммит бандла (эвристика)"


def diff_text(repo: Path, since: str, path: str, worktree: bool = False) -> str:
    """The text of one file's diff that `resource_anchors` are matched against.

    `-U0` keeps context out of the way; git still puts a declaration on the `@@`
    line (`@@ … @@ model Client {`, `@@ … @@ export enum BugStatus {`), which is
    exactly the symbol an anchor names — when it encloses the change.
    """
    args = ["diff", "-U0", since] + ([] if worktree else ["HEAD"]) + ["--", path]
    return anchor_text(git(repo, *args) or "")


def anchor_text(diff: str) -> str:
    """Changed lines, plus each hunk header that encloses its hunk.

    git names the nearest declaration *above* a change on the `@@` line. For an
    edit inside a block (an indented field of `model Client {`, a line in a
    function body) that is the enclosing symbol. For a change at the top level
    (a new `model Runner` after `model ProjectMembership`, a removed function
    after `function inScope`) it is only the previous neighbour, which did not
    change. So a header counts when the hunk's first non-blank changed line is
    indented or closes a block; the changed lines always count, and they name
    a top-level declaration themselves.
    """
    out: list[str] = []
    header: str | None = None
    pending = False  # header seen, its hunk's first changed line not yet
    for line in diff.splitlines():
        if line.startswith("@@"):
            header, pending = line, True
            continue
        if header is None or not line or line[0] not in "+-":
            continue  # file headers (`diff --git`, `---`, `+++`) and `\ No newline`
        body = line[1:]
        if pending and body.strip():
            pending = False
            if body[:1].isspace() or body[:1] in ")]}":
                out.append(header)
        out.append(line)
    return "\n".join(out)


_cache: dict = {}


def _cached(key, fn):
    if key not in _cache:
        _cache[key] = fn()
    return _cache[key]


def _worktree_dirty(repo: Path) -> set[str]:
    """Paths with uncommitted changes, untracked files included."""
    def compute():
        dirty = set((git(repo, "diff", "--name-only", "HEAD") or "").splitlines())
        dirty |= set((git(repo, "ls-files", "--others", "--exclude-standard") or "").splitlines())
        return dirty
    return _cached(("dirty",), compute)


def change_units(repo: Path, since: str, base_ref: str | None, bundle_rel: str) -> dict[str, str]:
    """Map every commit in `since..HEAD` to the unit of work that brought it in.

    A unit is one first-parent step of the integration branch — a merged PR is one
    unit — and everything on the current branch past its merge-base with `base_ref`
    (plus uncommitted edits) is one more unit, "branch".

    Direct commits on the integration branch (linear history, no PR merges) follow
    the convention "code commit(s), then `docs(okf): ...` on top": a commit that
    touches the bundle closes a run, and the code commits written shortly before
    it (author time within RUN_WINDOW_S) join its unit. Older code in the run — a
    forgotten change, or week-old work rebased in — stays a unit of its own, so a
    refresh about bug X is still not credited for it. A bundle-only commit right
    after a closing one (a follow-up fix of the refresh) shares its unit.
    """
    mb = (git(repo, "merge-base", base_ref, "HEAD") if base_ref else None) or git(repo, "rev-parse", "HEAD")
    units: dict[str, str] = {}
    for c in (git(repo, "rev-list", f"{mb}..HEAD") or "").split():
        units[c] = "branch"
    # One call: "@<sha> <parents…> <author time>" per step, then its files (none for merges).
    log = git(repo, "log", "--first-parent", "--reverse", "--name-only",
              "--format=@%H %P %at", f"{since}..{mb}") or ""
    steps: list[tuple[str, list[str], int, list[str]]] = []
    for line in log.splitlines():
        if line.startswith("@"):
            sha, *rest = line[1:].split()
            steps.append((sha, rest[:-1], int(rest[-1]), []))
        elif line and steps:
            steps[-1][3].append(line)
    pending: list[tuple[str, int]] = []  # direct code commits not yet followed by a bundle update
    closer: str | None = None  # unit of the bundle-only commit right before, if any
    for sha, parents, at, files in steps:
        if len(parents) > 1:
            for c in (git(repo, "rev-list", f"{parents[0]}..{sha}") or "").split():
                units.setdefault(c, sha)
            pending, closer = [], None  # a merge ends the run; pending stay units of their own
            continue
        in_bundle = [f.startswith(bundle_rel + "/") for f in files]
        if any(in_bundle):
            # A bundle-only follow-up joins the bundle commit right before it; a commit
            # that also changes other files must not inherit a refresh made before it.
            unit = closer if closer and not pending and all(in_bundle) else sha
            for c, c_at in pending:
                if at - c_at <= RUN_WINDOW_S:
                    units.setdefault(c, unit)
            units.setdefault(sha, unit)
            pending, closer = [], unit
            continue
        pending.append((sha, at))
        closer = None
    for sha, *_ in steps:
        units.setdefault(sha, sha)  # everything not grouped above is its own unit
    return units


def concept_refreshed(repo: Path, since: str, concept_path: str, files: list[tuple[str, str]],
                      anchors: list[str], worktree: bool, units: dict[str, str]) -> bool:
    """Was the concept updated in the same unit of work as every change of its sources?

    Same unit, not merely "later": a concept touched in a PR about bug X says nothing
    about a tariff rework merged a week earlier. Crediting any later edit hid real
    drift on a real project — 42 of 53 concepts it waved through still needed fixing.
    For anchored concepts only commits whose own diff hits an anchor (see
    `anchor_text`) count, so an unrelated edit to a shared file (schema.prisma)
    does not re-open the concept.
    """
    dirty = _worktree_dirty(repo) if worktree else set()
    need: set[str] = set()
    for path, _status in files:
        if path in dirty:
            need.add("branch")
            continue
        commits = _cached(("revs", since, path), lambda: (
            git(repo, "rev-list", f"{since}..HEAD", "--", path) or "").split())
        if anchors:
            hits = [c for c in commits if any(a in _cached(("show", c, path), lambda c=c: anchor_text(git(
                repo, "show", "-U0", "--format=", c, "--", path) or "")) for a in anchors)]
            commits = hits or commits  # no per-commit hit: stay conservative, take them all
        need.update(units.get(c, "?") for c in commits)
    if not need:
        return False
    have = {units.get(c) for c in (git(repo, "rev-list", f"{since}..HEAD", "--", concept_path) or "").split()}
    if concept_path in dirty:
        have.add("branch")
    return need <= have and substantive(repo, since, concept_path, worktree)


def substantive(repo: Path, since: str, path: str, worktree: bool) -> bool:
    """Does `path` differ from `since` by more than whitespace and blank lines?

    A trailing space or an empty line must not count as updating a concept: it
    would clear the Stop hook and the gate without anyone rereading the text.
    Rewriting only `generated.at` does count — that is a deliberate "rechecked".
    `--name-only` lists whitespace-only changes even with `-w`, so look for hunks.
    """
    if worktree and path in (git(repo, "ls-files", "--others", "--exclude-standard", "--", path) or "").splitlines():
        return True  # a new, uncommitted file is all content
    args = ["diff", "--ignore-all-space", "--ignore-blank-lines", since] + ([] if worktree else ["HEAD"]) + ["--", path]
    return any(line.startswith("@@") for line in (git(repo, *args) or "").splitlines())


# `okf: n/a — <reason>` (em dash or hyphen) in a commit message: that commit's
# changes do not affect the bundle. Same shape as the kit's `docs: n/a — …`, but a
# token of its own, so one waiver never silently clears both checks in a repo
# that has both.
WAIVER = re.compile(r"okf:\s*n/a\s*(?:—|-)\s*(.+)", re.IGNORECASE)
WAIVER_MIN_CHARS = 8  # non-space characters: «рефакторинг» passes, «да» does not


def waiver_reason(message: str) -> str | None:
    for line in message.splitlines():
        m = WAIVER.search(line)
        if m and len("".join(m.group(1).split())) >= WAIVER_MIN_CHARS:
            return m.group(1).strip()
    return None


def commit_waivers(repo: Path, since: str, uncommitted: set[str]) -> dict[str, list[tuple[str, str]]]:
    """Files waived by `okf: n/a — …` commits in `since..HEAD` -> [(commit, reason)].

    A waiver covers the files of its own commit only: a refactor waived in commit A
    does not excuse a behaviour change to the same file in commit B, and edits not
    committed yet carry no message at all.
    """
    waived: dict[str, list[tuple[str, str]]] = {}
    plain: set[str] = set(uncommitted)
    for sha in (git(repo, "rev-list", "--no-merges", f"{since}..HEAD") or "").split():
        files = (git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "--no-renames", sha) or "").splitlines()
        reason = waiver_reason(git(repo, "log", "-1", "--format=%B", sha) or "")
        if reason:
            for f in files:
                waived.setdefault(f, []).append((sha, reason))
        else:
            plain.update(files)
    return {f: v for f, v in waived.items() if f not in plain}


def ignored(path: str) -> bool:
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch("/" + path, g)
               for g in IGNORE_GLOBS)


def base_ref(repo: Path) -> str | None:
    """The integration branch: vendored value, else $OKF_BASE_REF, else a guess."""
    if not (BASE_REF.startswith("__") and BASE_REF.endswith("__")):
        return BASE_REF
    if os.environ.get("OKF_BASE_REF"):
        return os.environ["OKF_BASE_REF"]
    return next((r for r in ("origin/develop", "origin/main", "origin/master")
                 if git(repo, "rev-parse", "--verify", "-q", r) is not None), None)


def report_gate(args, repo: Path, bundle: Path, since: str | None, changed: dict[str, str],
                stale: dict[str, list[tuple[str, str]]], refreshed: set[str],
                unmatched: list[tuple[str, str]], bundle_touched: bool,
                waived: dict[str, list[tuple[str, str]]], uncovered: list[tuple[str, str]],
                expired: list[tuple[str, str]]) -> int:
    """`--gate`: what the branch owes the bundle; exit 1 only for that debt.

    The debt is the Stop hook's rule, here so that the hook and CI agree: concepts the
    branch made STALE and did not update, plus files changed past every anchor while
    the branch left the bundle alone. UNCOVERED and EXPIRED are heuristic or not the
    branch's doing — reported, never blocking.
    """
    owed = {c: v for c, v in stale.items() if c not in refreshed}
    owed_unmatched = [] if bundle_touched else unmatched
    not_affected = os.environ.get("OKF_NOT_AFFECTED") == "1"
    failed = bool(owed or owed_unmatched) and not not_affected
    waivers = [(p, sha, reason) for p, v in sorted(waived.items()) for sha, reason in v]

    if args.json:
        print(json.dumps({
            "repo": str(repo), "bundle": str(bundle), "base": args.branch, "since": since,
            "changed_source_files": len(changed),
            "owed": {c: [{"path": p, "status": s} for p, s in v] for c, v in sorted(owed.items())},
            "owed_unmatched": [{"path": p, "status": s} for p, s in owed_unmatched],
            "refreshed": sorted(c for c in stale if c in refreshed),
            "waived": [{"path": p, "commit": sha, "reason": r} for p, sha, r in waivers],
            "not_affected": not_affected,
            "uncovered": [{"path": p, "status": s} for p, s in uncovered],
            "expired": [{"concept": c, "stale_after": d} for c, d in expired],
        }, ensure_ascii=False, indent=2))
        return 1 if failed else 0

    if args.quiet:
        if failed:
            bits = [f"{len(owed)} концепт(ов) не обновлено ({', '.join(sorted(owed)[:3])}…)"] if owed else []
            if owed_unmatched:
                bits.append(f"{len(owed_unmatched)} файл(ов) мимо якорей")
            print(f"okf-bundle: ветка должна бандлу — {'; '.join(bits)}. "
                  f"Подробно — `python3 scripts/okf/drift.py --gate`.")
        return 1 if failed else 0

    print(f"OKF gate: ветка от {args.branch} ({(since or '—')[:12]}), "
          f"{len(changed)} изменённых файл(ов) вне бандла")
    print()
    if owed:
        print(f"ДОЛГ — {len(owed)} концепт(ов): источник изменён в ветке, сам концепт нет:")
        for c, files in sorted(owed.items()):
            head = ", ".join(f"[{s}] {p}" for p, s in files[:3])
            more = f" (+{len(files) - 3})" if len(files) > 3 else ""
            print(f"    {c}   ← {head}{more}")
        print()
    if owed_unmatched:
        print(f"МИМО ЯКОРЕЙ — {len(owed_unmatched)} файл(ов), а бандл в ветке не тронут "
              f"(либо правка не про концепты, либо якорь узок):")
        for p, s in owed_unmatched:
            print(f"    [{s}] {p}")
        print()
    if waivers:
        print("Отказы в коммитах (okf: n/a) — файлы исключены из проверки:")
        for p, sha, reason in waivers:
            print(f"    {p}   {sha[:10]}: {reason}")
        print()
    info = [f"UNCOVERED {len(uncovered)}"] if uncovered else []
    if expired:
        info.append(f"EXPIRED {len(expired)}")
    if info:
        print(f"Для сведения, не блокирует: {', '.join(info)} — `python3 scripts/okf/drift.py --branch {args.branch}`.")
        print()
    if not_affected and (owed or owed_unmatched):
        print("Долг снят для всей ветки: OKF_NOT_AFFECTED=1 (метка PR okf-not-affected).")
    elif failed:
        print("Обнови концепты по правилам скилла okf отдельным коммитом `docs(okf): ...`. Если поведение "
              "не менялось, добавь в сообщение коммита с этим кодом `okf: n/a — <причина>`: отказ покрывает "
              "файлы только своего коммита.")
    else:
        print("✓ Долга по бандлу нет.")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect okf-bundle drift vs the code.")
    ap.add_argument("bundle", nargs="?", type=Path, default=Path(BUNDLE_DEFAULT))
    ap.add_argument("--repo", type=Path, default=None)
    ap.add_argument("--since", default=None,
                    help="Git ref/date to diff from (default: .okf-anchor, else last commit touching the bundle)")
    ap.add_argument("--branch", nargs="?", const="", default=None, metavar="BASE",
                    help="Drift of the current branch only: diff from merge-base with BASE "
                         "(default: the integration branch). Use in PR/pre-commit flows.")
    ap.add_argument("--set-anchor", nargs="?", const="HEAD", default=None, metavar="REF",
                    help="Record REF (default HEAD) as the code state the bundle describes, then exit")
    ap.add_argument("--worktree", action="store_true",
                    help="Compare against the working tree instead of HEAD (uncommitted edits count)")
    ap.add_argument("--gate", action="store_true",
                    help="What the branch owes the bundle (implies --branch): exit 1 when it made concepts "
                         "stale and did not update them, or changed files past every anchor with the bundle "
                         "untouched. `okf: n/a — <reason>` in a commit message waives that commit's files; "
                         "OKF_NOT_AFFECTED=1 waives the whole branch (CI sets it from a PR label).")
    ap.add_argument("--quiet", action="store_true", help="One-line summary only")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    bundle = args.bundle
    if not bundle.is_dir():
        # Hooks do not guarantee a cwd, so fall back to the bundle next to this script.
        fallback = Path(__file__).resolve().parents[2] / BUNDLE_DEFAULT
        if fallback.is_dir():
            bundle = fallback
    bundle = bundle.resolve()
    if not bundle.is_dir():
        if args.quiet:
            return 0  # SessionStart in a repo whose bundle is not generated yet: nothing to say
        print(f"error: not a directory: {bundle}", file=sys.stderr)
        return 2

    repo = (args.repo or Path(git(bundle, "rev-parse", "--show-toplevel") or bundle.parent)).resolve()
    if git(repo, "rev-parse", "--git-dir") is None:
        print(f"error: not a git repo: {repo} (pass --repo)", file=sys.stderr)
        return 2
    if args.gate:
        if args.since:
            print("error: --gate считает долг ветки от merge-base — с --since не сочетается", file=sys.stderr)
            return 2
        if args.branch is None:
            args.branch = ""
    integration = base_ref(repo)
    if args.branch == "":
        if integration is None:
            print("error: не знаю базовую ветку — передайте --branch <ref> или OKF_BASE_REF", file=sys.stderr)
            return 2
        args.branch = integration

    try:
        bundle_rel = str(bundle.relative_to(repo))
    except ValueError:
        bundle_rel = None

    if args.set_anchor is not None:
        sha = git(repo, "rev-parse", args.set_anchor)
        if not sha:
            print(f"error: неизвестный ref: {args.set_anchor}", file=sys.stderr)
            return 2
        (bundle / ANCHOR_FILE).write_text(
            "# Коммит, состоянию кода на котором соответствует бандл.\n"
            "# Обновлять при каждом рефреше: python3 scripts/okf/drift.py --set-anchor\n"
            f"{sha}\n", encoding="utf-8")
        print(f"Якорь бандла: {sha[:12]} ({git(repo, 'log', '-1', '--format=%s', sha) or '—'})")
        return 0

    concepts = [p for p in bundle.rglob("*.md") if p.name not in RESERVED]
    meta_by_concept = {c: read_meta(c) for c in concepts}

    # Index concepts by the code they describe: exact files and whole directories.
    by_file: dict[str, list[tuple[str, list[str]]]] = {}  # path -> [(concept, anchors)]
    by_dir: dict[str, list[str]] = {}
    deprecated: set[str] = set()
    for c in sorted(concepts):
        rel = str(c.relative_to(bundle))
        meta = meta_by_concept[c]
        if meta.get("status") == "deprecated":
            deprecated.add(rel)
            continue  # a deliberate retirement is not drift
        rp = as_repo_path(meta.get("resource", ""))
        if not rp:
            continue
        if (repo / rp).is_dir():
            by_dir.setdefault(rp, []).append(rel)
        else:
            by_file.setdefault(rp, []).append((rel, meta.get("resource_anchors") or []))
    anchors_of = {str(c.relative_to(bundle)): meta_by_concept[c].get("resource_anchors") or []
                  for c in concepts}

    # EXPIRED needs no git at all — it is the only signal that reaches concepts
    # no diff can touch (product/, decisions/, policy/).
    today = dt.date.today()
    expired = []
    for c in sorted(concepts):
        rel = str(c.relative_to(bundle))
        if rel in deprecated:
            continue
        d = parse_date(meta_by_concept[c].get("stale_after"))
        if d and today >= d:
            expired.append((rel, d.isoformat()))

    since, anchor_note, anchor_broken = args.since, "явно через --since", False
    if since is None and args.branch:
        base = git(repo, "merge-base", args.branch, "HEAD")
        if not base:
            print(f"error: не найдена база слияния с {args.branch}", file=sys.stderr)
            return 2
        since, anchor_note = base, f"ветка от {args.branch}"
    if since is None:
        since, anchor_note = read_anchor(bundle, repo)
        if since is not None and anchor_note.startswith("⚠") and not args.json:
            print(f"okf-bundle: {anchor_note}", file=sys.stderr)
        if since is None:
            anchor_broken = anchor_note.startswith("⚠")
            if bundle_rel is not None:
                since = git(repo, "log", "-1", "--format=%H", "--", bundle_rel)

    changed: dict[str, str] = {}
    if since:
        diff = (git(repo, "diff", "--name-status", since)
                if args.worktree else git(repo, "diff", "--name-status", since, "HEAD"))
        if diff is None:
            print(f"error: `git diff {since} HEAD` failed. Pass a valid --since ref.", file=sys.stderr)
            return 2
        for line in diff.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status, path = parts[0][:1], parts[-1]
            if bundle_rel and path.startswith(bundle_rel + "/"):
                continue  # changes inside the bundle are not drift
            changed[path] = status
        if args.worktree:
            # `git diff` does not list untracked files, and a brand-new file is
            # exactly the change a session is most likely to leave uncommitted.
            for path in (git(repo, "ls-files", "--others", "--exclude-standard") or "").splitlines():
                if not (bundle_rel and path.startswith(bundle_rel + "/")):
                    changed.setdefault(path, "A")

    # Gate only: drop files whose every change on the branch came with a waiver.
    waived: dict[str, list[tuple[str, str]]] = {}
    if args.gate and since:
        uncommitted = _worktree_dirty(repo) if args.worktree else set()
        waived = {p: v for p, v in commit_waivers(repo, since, uncommitted).items() if p in changed}
        for p in waived:
            del changed[p]

    # Attribute every changed file to the most specific concept covering it.
    stale: dict[str, list[tuple[str, str]]] = {}  # concept -> [(path, status)]
    uncovered: list[tuple[str, str]] = []
    unmatched: list[tuple[str, str]] = []  # anchored file changed, no anchor hit
    for path, status in sorted(changed.items()):
        if path in by_file:
            entries = by_file[path]
            anchored = [(c, a) for c, a in entries if a]
            plain = [c for c, a in entries if not a]
            for c in plain:
                stale.setdefault(c, []).append((path, status))
            if anchored:
                text = diff_text(repo, since, path, args.worktree) if status != "D" else ""
                hit = False
                for c, anchors in anchored:
                    if any(a in text for a in anchors):
                        stale.setdefault(c, []).append((path, status))
                        hit = True
                # Anchors must never hide drift: if nothing claimed the change and
                # no unanchored concept covers the file either, say so explicitly.
                if not hit and not plain:
                    unmatched.append((path, status))
            continue
        dirs = [d for d in by_dir if path.startswith(d.rstrip("/") + "/")]
        if dirs:
            best = max(dirs, key=len)  # most specific directory wins
            for c in by_dir[best]:
                stale.setdefault(c, []).append((path, status))
            continue
        if status in ("A", "M") and Path(path).suffix in CODE_EXT and not ignored(path):
            uncovered.append((path, status))

    # STALE concepts that were already updated in the same PR as every change of their
    # sources. They stay STALE — on a real project 13 of 22 such concepts still needed
    # fixing (the PR touched the concept but missed part of the change) — but a refresh
    # can start from the rest, and the Stop hook uses this to tell what a branch owes.
    refreshed: set[str] = set()
    if since and stale and bundle_rel is not None:
        units = change_units(repo, since, args.branch or integration, bundle_rel)
        refreshed = {c for c in stale
                     if concept_refreshed(repo, since, f"{bundle_rel}/{c}", stale[c],
                                          anchors_of.get(c, []), args.worktree, units)}

    orphaned = [(c, rp) for rp, cs in sorted(by_file.items())
                for c, _anchors in cs if not (repo / rp).exists()]
    orphaned += [(c, rp) for rp, cs in sorted(by_dir.items())
                 for c in cs if not (repo / rp).exists()]

    if args.gate:
        bundle_touched = bool(since and bundle_rel is not None and (
            substantive(repo, since, bundle_rel, args.worktree)
            or (args.worktree and git(repo, "ls-files", "--others", "--exclude-standard", "--", bundle_rel))))
        return report_gate(args, repo, bundle, since, changed, stale, refreshed, unmatched,
                           bundle_touched, waived, uncovered, expired)

    # A broken anchor counts as drift: staying silent would mean reporting "in sync"
    # on the strength of a range we know is wrong.
    has_drift = bool(stale or uncovered or orphaned or expired or unmatched or anchor_broken)

    if args.json:
        print(json.dumps({
            "repo": str(repo), "bundle": str(bundle), "since": since,
            "changed_source_files": len(changed),
            "stale": {c: [{"path": p, "status": s} for p, s in v] for c, v in sorted(stale.items())},
            "refreshed": sorted(refreshed),
            "uncovered": [{"path": p, "status": s} for p, s in uncovered],
            "unmatched": [{"path": p, "status": s} for p, s in unmatched],
            "orphaned": [{"concept": c, "resource": r} for c, r in orphaned],
            "expired": [{"concept": c, "stale_after": d} for c, d in expired],
        }, ensure_ascii=False, indent=2))
        return 1 if has_drift else 0

    if args.quiet:
        if not has_drift:
            return 0
        if anchor_broken:
            print(f"okf-bundle: {anchor_note}")
        bits = []
        if stale:
            top = sorted(stale.items(), key=lambda kv: (kv[0] in refreshed, -len(kv[1])))[:3]
            inflow = f", из них {len(refreshed)} правлены в потоке" if refreshed else ""
            bits.append(f"{len(stale)} концепт(ов) устарело{inflow} ({', '.join(c for c, _ in top)}…)")
        if uncovered:
            bits.append(f"{len(uncovered)} изменённых файл(ов) без концепта")
        if unmatched:
            bits.append(f"{len(unmatched)} файл(ов) мимо якорей")
        if orphaned:
            bits.append(f"{len(orphaned)} концепт(ов) с исчезнувшим источником")
        if expired:
            bits.append(f"{len(expired)} просрочено по stale_after")
        if bits:
            print(f"okf-bundle отстал от кода: {'; '.join(bits)}. "
                  f"Подробно — `python3 scripts/okf/drift.py`, обновление — скилл okf.")
        return 1

    print(f"Repo:   {repo}")
    print(f"Bundle: {bundle_rel or bundle}")
    print(f"Since:  {(since or '—')[:12]}  [{anchor_note}]  "
          f"({len(changed)} изменённых файл(ов) вне бандла)")
    print(f"Концептов: {len(concepts)}, из них привязано к коду: "
          f"{sum(len(v) for v in by_file.values()) + sum(len(v) for v in by_dir.values())}")
    print()

    if stale:
        print(f"STALE — {len(stale)} концепт(ов), чей источник изменился (обновить):")
        # Untouched ones first: those are certainly behind; the in-flow ones may be complete.
        for c, files in sorted(stale.items(), key=lambda kv: (kv[0] in refreshed, -len(kv[1]), kv[0])):
            head = ", ".join(f"[{s}] {p}" for p, s in files[:3])
            more = f" (+{len(files) - 3})" if len(files) > 3 else ""
            mark = "  ◐" if c in refreshed else ""
            print(f"    {c}{mark}   ← {head}{more}")
        if refreshed:
            print(f"  ◐ — {len(refreshed)} из них уже правлены в том же PR, что и код: проверить полноту")
        print()
    if orphaned:
        print(f"ORPHANED — {len(orphaned)} концепт(ов), чей источник исчез (deprecate/перепривязать):")
        for c, rp in orphaned:
            print(f"    {c}   ↮ {rp}")
        print()
    if expired:
        print(f"EXPIRED — {len(expired)} концепт(ов) просрочено по `stale_after` (перепроверить):")
        for c, d in expired:
            print(f"    {c}   ⏳ {d}")
        print()
    if unmatched:
        print(f"UNMATCHED — {len(unmatched)} файл(ов) изменились мимо всех якорей "
              f"(проверить вручную: либо правка не про концепты, либо якорь узок):")
        for p, s in unmatched:
            print(f"    [{s}] {p}")
        print()
    if uncovered:
        print(f"UNCOVERED — {len(uncovered)} изменённых файл(ов) не покрыто ни одним концептом "
              f"(возможно, нужен новый):")
        for p, s in uncovered:
            print(f"    [{s}] {p}")
        print()

    if not has_drift:
        print("✓ Дрейфа нет — бандл соответствует коду.")
    return 1 if has_drift else 0


if __name__ == "__main__":
    sys.exit(main())
