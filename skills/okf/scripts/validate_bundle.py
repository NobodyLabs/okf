#!/usr/bin/env python3
"""Validate an OKF bundle against the Open Knowledge Format v0.2 conformance rules.

Conformance (SPEC §11) is deliberately small, so ERRORS are few and the rest
are advisory WARN/INFO notes. A bundle is *conformant* when:

  1. Every non-reserved `.md` file has a parseable YAML frontmatter block.
  2. Every such frontmatter block has a non-empty `type` field.
  3. Reserved files (`index.md`, `log.md`) follow their formats when present.

Everything else (missing optional fields, unknown types, broken cross-links,
missing index files, malformed optional v0.2 families) is SOFT guidance —
reported as WARN/INFO, never fatal — because OKF is meant to stay useful as
bundles grow and are partially agent generated.

v0.1 documents (`timestamp`, a body `# Citations` list) stay readable under the
v0.2 fallbacks (§13.1). They are recognized and summarized in one INFO line, not
flagged per file: a legacy bundle is not a broken bundle.

Exit code: 0 if conformant (no ERRORs), 1 otherwise.

Usage:
    python validate_bundle.py <bundle_dir>
    python validate_bundle.py <bundle_dir> --strict   # WARNs also fail (exit 1)
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

RESERVED = {"index.md", "log.md"}
RECOMMENDED = ("title", "description")
STATUS_VALUES = {"draft", "stable", "deprecated"}
OKF_VERSION = "0.2"

try:
    import yaml  # optional; required for the nested v0.2 family checks
except Exception:  # pragma: no cover
    yaml = None

MD_LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)]+)\)")
FOOTNOTE = re.compile(r"\[\^([^\]\s]+)\]")
CITATIONS_HEADING = re.compile(r"^#+\s+Citations\s*$", re.MULTILINE)
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# §7 actors: `<producer>/<version>`, `human:<id>`, `process:<id>`. Accept any
# `<prefix>:<id>` (bundles in the wild also use `team:`), reject bare words.
ACTOR = re.compile(r"^[^\s:/]+[:/][^\s]+$")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warns: list[str] = []
        self.infos: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warns.append(msg)

    def info(self, msg: str) -> None:
        self.infos.append(msg)


def split_frontmatter(text: str):
    """Return (frontmatter_text_or_None, ok). ok=False => malformed block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, True  # no frontmatter block at all
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), True
    return None, False  # unterminated


# A `key: value` line whose value is a bare scalar (not quoted, not a flow
# collection, not a block scalar / anchor / alias).
BARE_SCALAR = re.compile(r"^(\s*(?:-\s+)?[A-Za-z_][\w.-]*):[ \t]+(?![\"'\[{&*|>#])(.*\S)[ \t]*$")


def ambiguous_scalars(fm_text: str) -> list[str]:
    """Find unquoted frontmatter values that contain `: `.

    A real YAML parser rejects these ("nested mappings are not allowed in
    compact mappings"), but the lenient `_mini_yaml` fallback below happily
    splits on the first colon and moves on — so without this check a bundle can
    be reported CONFORMANT while every YAML-based consumer fails to load it.
    Titles and descriptions in Russian use colons often, which is exactly how
    this slips in.
    """
    bad = []
    for line in fm_text.splitlines():
        m = BARE_SCALAR.match(line)
        if not m:
            continue
        value = m.group(2)
        if ": " in value or value.endswith(":"):
            bad.append(f"`{m.group(1).strip()}` → {value[:70]}")
    return bad


def strip_frontmatter(text: str) -> str:
    """Return the body with any leading frontmatter block removed."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:])
    return text


def _split_top(s: str, sep: str = ",") -> list[str]:
    """Split on `sep` at brace/bracket/quote depth zero."""
    out, buf, depth, quote = [], [], 0, ""
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "{[":
            depth += 1
            buf.append(ch)
        elif ch in "}]":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [x for x in out]


def _scalar(s: str):
    """Parse a YAML scalar, flow mapping, or flow sequence."""
    s = s.strip()
    if not s:
        return None
    if s.startswith("{") and s.endswith("}"):
        out: dict = {}
        for part in _split_top(s[1:-1]):
            if not part.strip():
                continue
            k, _, v = part.partition(":")
            out[k.strip()] = _scalar(v)
        return out
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(p) for p in _split_top(inner)] if inner else []
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s in ("null", "~"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    return s


def _strip_comment(s: str) -> str:
    """Drop a trailing ` #comment` outside quotes/braces."""
    quote, depth = "", 0
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        elif ch == "#" and depth == 0 and (i == 0 or s[i - 1] in " \t"):
            return s[:i]
    return s


def _mini_yaml(fm_text: str) -> dict:
    """Parse the YAML subset OKF frontmatter actually uses, with no dependency.

    Covers scalars, flow mappings/sequences (`{ by: x, at: y }`, `[a, b]`), block
    mappings, and block sequences of either — which is every shape the real
    bundles write. Anything more exotic than that is out of scope; install
    PyYAML if a bundle needs it.
    """
    rows: list[tuple[int, str]] = []
    for raw in fm_text.splitlines():
        body = _strip_comment(raw).rstrip()
        if not body.strip():
            continue
        rows.append((len(body) - len(body.lstrip(" ")), body.strip()))

    def parse_map(i: int, indent: int) -> tuple[dict, int]:
        out: dict = {}
        while i < len(rows) and rows[i][0] >= indent and not rows[i][1].startswith("- "):
            cur_indent, line = rows[i]
            if cur_indent > indent:  # unexpected deeper line; skip defensively
                i += 1
                continue
            k, sep, v = line.partition(":")
            if not sep:
                i += 1
                continue
            key, v = k.strip(), v.strip()
            i += 1
            if v:
                out[key] = _scalar(v)
            elif i < len(rows) and rows[i][0] == cur_indent and rows[i][1].startswith("- "):
                # PyYAML's default dump style puts sequence dashes at the
                # parent key's own indent, not deeper.
                out[key], i = parse_seq(i, cur_indent)
            elif i < len(rows) and rows[i][0] > cur_indent:
                child, i = parse_block(i, rows[i][0])
                out[key] = child
            else:
                out[key] = None
        return out, i

    def parse_seq(i: int, indent: int) -> tuple[list, int]:
        items: list = []
        while i < len(rows) and rows[i][0] == indent and rows[i][1].startswith("- "):
            content = rows[i][1][2:].strip()
            i += 1
            if content.startswith("{") or ":" not in content:
                items.append(_scalar(content))
                continue
            # a block mapping whose first key sits on the dash line
            k, _, v = content.partition(":")
            entry: dict = {}
            if v.strip():
                entry[k.strip()] = _scalar(v)
            elif i < len(rows) and rows[i][0] > indent:
                child, i = parse_block(i, rows[i][0])
                entry[k.strip()] = child
            if i < len(rows) and rows[i][0] > indent and not rows[i][1].startswith("- "):
                rest, i = parse_map(i, rows[i][0])
                entry.update(rest)
            items.append(entry)
        return items, i

    def parse_block(i: int, indent: int):
        if i < len(rows) and rows[i][1].startswith("- "):
            return parse_seq(i, indent)
        return parse_map(i, indent)

    data, _ = parse_map(0, 0)
    return data


TOP_LEVEL_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:", re.MULTILINE)


def duplicate_top_level_keys(fm_text: str) -> list[str]:
    """Top-level keys that appear more than once. PyYAML (and `_mini_yaml`)
    silently keep the last one, but the `yaml` package that knowledge-mcp
    loads the bundle with rejects the document ("Map keys must be unique") and
    the service crash-loops on start. Typical source: a merge of two branches
    that both refreshed the same concept and each kept its own `generated:`."""
    seen: set[str] = set()
    dups: list[str] = []
    for key in TOP_LEVEL_KEY.findall(fm_text):
        if key in seen and key not in dups:
            dups.append(key)
        seen.add(key)
    return dups


if yaml is not None:
    class _UniqueKeyLoader(yaml.SafeLoader):
        """SafeLoader that rejects duplicate keys at any nesting level."""

        def construct_mapping(self, node, deep=False):
            seen = set()
            for key_node, _ in node.value:
                key = self.construct_object(key_node, deep=deep)
                if key in seen:
                    raise ValueError(f"duplicate key `{key}` (line {key_node.start_mark.line + 1})")
                seen.add(key)
            return super().construct_mapping(node, deep=deep)


def parse_frontmatter(fm_text: str):
    """Parse frontmatter into a dict. Uses PyYAML when available, else the
    dependency-free subset parser above."""
    if yaml is not None:
        data = yaml.load(fm_text, Loader=_UniqueKeyLoader) or {}
        if not isinstance(data, dict):
            raise ValueError("frontmatter is not a YAML mapping")
        return data
    return _mini_yaml(fm_text)


def resolve_link(src: Path, target: str, root: Path) -> Path | None:
    """Resolve an internal markdown link target to a filesystem path, or None
    if it is external / an anchor. Supports bundle-absolute (`/x.md`) and
    relative (`../x.md`) forms."""
    t = target.split("#", 1)[0].strip()
    if not t or "://" in t or t.startswith(("mailto:", "tel:")):
        return None
    if t.startswith("/"):
        return (root / t.lstrip("/")).resolve()
    return (src.parent / t).resolve()


def as_date(value):
    """Coerce a YAML scalar to a date, or None if it isn't one. PyYAML turns an
    unquoted `2026-12-31` into a date object and a quoted one into a string."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and DATE_ONLY.match(value.strip()):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def normalize_verified(fm: dict) -> list:
    """§5.2/§11: a bare `{by, at}` mapping MUST be read as a one-element list."""
    v = fm.get("verified")
    if v is None:
        return []
    if isinstance(v, dict):
        return [v]
    if isinstance(v, list):
        return [e for e in v if isinstance(e, dict)]
    return []


def trust_tier(fm: dict) -> str:
    """§5.3, derived — never stored."""
    events = normalize_verified(fm)
    if not events:
        return "unverified"
    for e in events:
        by = e.get("by")
        if isinstance(by, str) and by.strip().startswith("human:"):
            return "human-reviewed"
    return "machine-confirmed"


def check_v02_families(rel: Path, fm: dict, body: str, rep: Report, stats: dict) -> None:
    """Advisory checks on the optional v0.2 frontmatter families (§5, §7, §10).

    Nothing here is ever an error: §11 forbids rejecting a concept for a missing
    or imperfect optional family.
    """
    # --- lifecycle -------------------------------------------------------
    status = fm.get("status")
    if status is not None:
        if not (isinstance(status, str) and status.strip() in STATUS_VALUES):
            rep.warn(
                f"{rel}: `status: {status}` is outside the v0.2 enum "
                f"({' | '.join(sorted(STATUS_VALUES))})"
            )
        elif status.strip() == "deprecated":
            stats["deprecated"] += 1

    if "stale_after" in fm:
        raw = fm.get("stale_after")
        d = as_date(raw)
        if d is None:
            rep.warn(
                f"{rel}: `stale_after: {raw}` is not an absolute YYYY-MM-DD date "
                "(v0.2 uses an absolute date, not a relative TTL)"
            )
        elif dt.date.today() >= d:
            stats["expired"].append(f"{rel} (stale_after {d.isoformat()})")

    # --- trust -----------------------------------------------------------
    gen = fm.get("generated")
    if gen is not None:
        if not isinstance(gen, dict):
            rep.warn(f"{rel}: `generated` should be a mapping of {{ by, at }}")
        else:
            by = gen.get("by")
            if not (isinstance(by, str) and by.strip()):
                rep.warn(f"{rel}: `generated` is missing the required `by` actor")
            elif not ACTOR.match(by.strip()):
                rep.warn(
                    f"{rel}: `generated.by: {by}` does not follow the actor "
                    "convention (`producer/version`, `human:<id>`, `process:<id>`)"
                )

    for e in normalize_verified(fm):
        by = e.get("by")
        if not (isinstance(by, str) and by.strip()):
            rep.warn(f"{rel}: a `verified` entry is missing its `by` actor")
        elif not ACTOR.match(by.strip()):
            rep.warn(
                f"{rel}: `verified.by: {by}` does not follow the actor convention "
                "(`producer/version`, `human:<id>`, `process:<id>`)"
            )
    stats["tiers"][trust_tier(fm)] += 1

    # --- provenance ------------------------------------------------------
    sources = fm.get("sources")
    source_ids: set[str] = set()
    if sources is not None:
        entries = [sources] if isinstance(sources, dict) else sources
        if not isinstance(entries, list):
            rep.warn(f"{rel}: `sources` should be a list of entries")
            entries = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                rep.warn(f"{rel}: `sources[{i}]` should be a mapping")
                continue
            res = entry.get("resource")
            if not (isinstance(res, str) and res.strip()):
                rep.warn(
                    f"{rel}: `sources[{i}]` has no `resource` "
                    "(required within a sources entry, §5.1)"
                )
            sid = entry.get("id")
            if isinstance(sid, str) and sid.strip():
                source_ids.add(sid.strip())

    # footnote labels join to `sources[].id` (§5.1)
    for label in sorted({m.group(1) for m in FOOTNOTE.finditer(body)}):
        if label not in source_ids:
            rep.warn(
                f"{rel}: footnote `[^{label}]` has no matching `sources[].id` "
                "— per-claim attribution resolves through that key"
            )

    # --- attested computations (§10.2) -----------------------------------
    typ = fm.get("type")
    if isinstance(typ, str) and typ.strip() == "Attested Computation":
        runtime = fm.get("runtime")
        if not (isinstance(runtime, str) and runtime.strip()):
            rep.warn(
                f"{rel}: `type: Attested Computation` requires `runtime` "
                "(it defines how `parameters` bind, §10.2)"
            )


def validate(root: Path, rep: Report) -> None:
    md_files = sorted(root.rglob("*.md"))
    concept_count = 0
    typed: set[str] = set()
    legacy = 0
    stats = {
        "expired": [],
        "deprecated": 0,
        "tiers": {"unverified": 0, "machine-confirmed": 0, "human-reviewed": 0},
    }

    for md in md_files:
        rel = md.relative_to(root)
        text = md.read_text(encoding="utf-8")
        name = md.name

        if name in RESERVED:
            validate_reserved(md, rel, text, root, rep)
            continue

        concept_count += 1

        fm_text, ok = split_frontmatter(text)
        if not ok:
            rep.error(f"{rel}: unterminated YAML frontmatter block")
            continue
        if fm_text is None:
            rep.error(f"{rel}: missing YAML frontmatter block (concept docs require one)")
            continue
        for offender in ambiguous_scalars(fm_text):
            rep.error(f"{rel}: unquoted value containing ': ' — invalid YAML, quote it: {offender}")
        for key in duplicate_top_level_keys(fm_text):
            rep.error(f"{rel}: duplicate frontmatter key `{key}` — invalid YAML (merge leftover?), keep one")

        try:
            fm = parse_frontmatter(fm_text)
        except Exception as e:
            rep.error(f"{rel}: invalid frontmatter YAML: {e}")
            continue

        typ = fm.get("type")
        if not (isinstance(typ, str) and typ.strip()):
            rep.error(f"{rel}: frontmatter is missing a non-empty `type`")
        else:
            typed.add(typ.strip())

        for field in RECOMMENDED:
            val = fm.get(field)
            if not (isinstance(val, str) and val.strip()):
                rep.warn(f"{rel}: missing recommended frontmatter `{field}`")

        # v0.1 shapes are readable under the v0.2 fallbacks — count, don't nag.
        body = strip_frontmatter(text)
        if "timestamp" in fm or CITATIONS_HEADING.search(body):
            legacy += 1

        check_v02_families(rel, fm, body, rep, stats)

    # second pass: cross-link resolution (advisory)
    broken = 0
    for md in md_files:
        if md.name in RESERVED:
            continue
        rel = md.relative_to(root)
        body = md.read_text(encoding="utf-8")
        for m in MD_LINK.finditer(body):
            tgt = resolve_link(md, m.group(1), root)
            if tgt is None:
                continue
            if tgt.suffix != ".md":
                continue
            if not tgt.exists():
                broken += 1
                rep.warn(f"{rel}: cross-link to missing concept `{m.group(1)}`")

    # Advisory: a bundle should have a semantic entry point at its root, not
    # just an index.md file listing. A root-level concept doc (an Overview, an
    # Architecture, a top Dataset) is the natural front door.
    root_concepts = [p for p in root.glob("*.md") if p.name not in RESERVED]
    if concept_count and not root_concepts:
        rep.warn("no root-level orientation concept — consider an overview.md/architecture.md at the bundle root as the entry point (see SKILL.md step 2)")

    rep.info(f"{concept_count} concept doc(s), {len(typed)} distinct type(s): {', '.join(sorted(typed)) or '—'}")
    if broken:
        rep.info(f"{broken} broken cross-link(s) (tolerated by spec — may be not-yet-written knowledge)")
    if legacy:
        rep.info(
            f"{legacy} concept(s) use legacy v0.1 `timestamp`/`# Citations` — "
            "readable under the v0.2 fallbacks (§13.1); no action required"
        )
    tiers = stats["tiers"]
    if tiers["machine-confirmed"] or tiers["human-reviewed"]:
        rep.info(
            f"trust: {tiers['human-reviewed']} human-reviewed, "
            f"{tiers['machine-confirmed']} machine-confirmed, "
            f"{tiers['unverified']} unverified"
        )
    if stats["deprecated"]:
        rep.info(f"{stats['deprecated']} concept(s) marked `status: deprecated`")
    for item in stats["expired"]:
        rep.info(f"expired: {item} — past its stale_after date, re-verify or extend")


def validate_reserved(md: Path, rel: Path, text: str, root: Path, rep: Report) -> None:
    fm_text, ok = split_frontmatter(text)
    is_root_index = md.name == "index.md" and md.parent.resolve() == root.resolve()
    if md.name == "index.md":
        if fm_text is not None and not is_root_index:
            rep.warn(f"{rel}: non-root index.md should not carry frontmatter (only the root index may, for okf_version)")
        if fm_text is not None and is_root_index:
            try:
                fm = parse_frontmatter(fm_text)
            except Exception as e:
                rep.warn(f"{rel}: invalid frontmatter YAML: {e}")
                return
            declared = fm.get("okf_version")
            if declared is not None and str(declared).strip() != OKF_VERSION:
                rep.warn(
                    f"{rel}: declares `okf_version: {declared}` but this skill "
                    f"authors OKF v{OKF_VERSION}"
                )
    if md.name == "log.md":
        # log entries are date-grouped `## YYYY-MM-DD` headings — advisory check
        if not re.search(r"^##\s+\d{4}-\d{2}-\d{2}", text, re.MULTILINE):
            rep.warn(f"{rel}: log.md has no `## YYYY-MM-DD` date headings")


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate an OKF bundle (v0.2 conformance).")
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--strict", action="store_true", help="Treat WARNs as failures too")
    args = ap.parse_args()

    root = args.bundle.resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    rep = Report()
    validate(root, rep)

    for m in rep.infos:
        print(f"INFO  {m}")
    for m in rep.warns:
        print(f"WARN  {m}")
    for m in rep.errors:
        print(f"ERROR {m}")

    print()
    if rep.errors:
        print(f"NOT CONFORMANT — {len(rep.errors)} error(s), {len(rep.warns)} warning(s).")
        return 1
    if args.strict and rep.warns:
        print(f"CONFORMANT but {len(rep.warns)} warning(s) under --strict.")
        return 1
    print(f"CONFORMANT with OKF v{OKF_VERSION} — 0 errors, {len(rep.warns)} warning(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
