#!/usr/bin/env python3
"""Regenerate OKF `index.md` files for a bundle (progressive disclosure).

An `index.md` in a directory enumerates that directory's contents so a human
or agent can see what is available before opening individual documents. This
script rebuilds every `index.md` in the tree deterministically from the
frontmatter of the concept docs, so you never hand-maintain them.

Format produced (matches the OKF reference tooling):

    # <Type A>

    * [Title](file.md) - one-line description
    ...

    # Subdirectories

    * [subdir](subdir/index.md) - description of the subdirectory

Concepts are grouped by their frontmatter `type`; groups and entries are
sorted alphabetically so the output is stable across runs (clean git diffs).

No third-party dependencies: frontmatter is read with a tiny scalar parser
that only needs `type`, `title`, `description` — all simple strings.

Usage:
    python gen_index.py <bundle_dir>
    python gen_index.py <bundle_dir> --check   # exit 1 if any index is stale
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml  # optional; gives faithful parsing of folded/quoted scalars
except Exception:  # pragma: no cover
    yaml = None

INDEX_FILE = "index.md"
RESERVED = {INDEX_FILE, "log.md"}


def _frontmatter_text(text: str) -> str | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return None


def read_scalars(path: Path, keys=("type", "title", "description")) -> dict[str, str]:
    """Read a handful of top-level scalar frontmatter keys.

    Uses PyYAML when available; otherwise a tiny fallback that understands
    quoted values and YAML block-folded continuation lines (a long value wrapped
    onto more-indented following lines, joined with spaces).
    """
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return out
    fm_text = _frontmatter_text(text)
    if fm_text is None:
        return out

    if yaml is not None:
        try:
            data = yaml.safe_load(fm_text) or {}
            if isinstance(data, dict):
                for k in keys:
                    v = data.get(k)
                    if v is not None and not isinstance(v, (dict, list)):
                        out[k] = str(v).strip()
                return out
        except Exception:
            pass  # fall through to the line parser

    cur = None  # key currently accumulating a (possibly folded) scalar
    for line in fm_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indented = line[:1] in (" ", "\t")
        is_list_item = line.lstrip().startswith("-")
        if indented and not is_list_item and cur in keys:
            out[cur] = (out.get(cur, "") + " " + line.strip()).strip()
            continue
        if indented or is_list_item or ":" not in line:
            cur = None
            continue
        key, _, val = line.partition(":")
        cur = key.strip()
        if cur not in keys:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
            val = val[1:-1]
        out[cur] = val
    return out


def build_index_text(entries: list[tuple[str, str, str, str]]) -> str:
    # entries: (type, title, relative_link, description)
    grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for typ, title, link, desc in entries:
        grouped[typ or "Other"].append((title, link, desc))

    sections: list[str] = []
    for typ in sorted(grouped, key=str.lower):
        lines = [f"# {typ}", ""]
        for title, link, desc in sorted(grouped[typ], key=lambda e: e[0].lower()):
            suffix = f" - {desc}" if desc else ""
            lines.append(f"* [{title}]({link}){suffix}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections) + "\n"


def existing_frontmatter_block(path: Path) -> str:
    """Return an existing file's raw frontmatter block (delimiters included), or
    "" when it has none.

    Index files carry no frontmatter with one exception: the bundle-root
    `index.md` may declare `okf_version` (SPEC §8/§12). That declaration is the
    only place a bundle states which OKF version it targets, so regeneration has
    to round-trip the block instead of silently dropping it.
    """
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[: i + 1]) + "\n\n"
    return ""  # unterminated block — treat as body, don't propagate the damage


def directories_to_index(root: Path) -> list[Path]:
    dirs: set[Path] = set()
    for md in root.rglob("*.md"):
        cur = md.parent
        while True:
            dirs.add(cur)
            if cur == root:
                break
            cur = cur.parent
    return sorted(dirs)


def compute_indexes(root: Path) -> dict[Path, str]:
    """Return {index_path: content} for every directory that has concepts.

    Directories are processed deepest-first so a subdirectory's synthesized
    description is available when building its parent's entry.
    """
    directories = sorted(
        directories_to_index(root),
        key=lambda p: (-len(p.relative_to(root).parts), str(p)),
    )
    dir_desc: dict[Path, str] = {}
    result: dict[Path, str] = {}

    for directory in directories:
        entries: list[tuple[str, str, str, str]] = []
        for child in sorted(directory.iterdir()):
            if child.name in RESERVED:
                continue
            if child.is_file() and child.suffix == ".md":
                fm = read_scalars(child)
                title = fm.get("title") or child.stem
                entries.append((fm.get("type", ""), title, child.name, fm.get("description", "")))
            elif child.is_dir() and any(child.rglob("*.md")):
                entries.append(
                    ("Subdirectories", child.name, f"{child.name}/{INDEX_FILE}", dir_desc.get(child, ""))
                )
        if not entries:
            continue
        index_path = directory / INDEX_FILE
        content = build_index_text(entries)
        if directory == root:
            content = existing_frontmatter_block(index_path) + content
        result[index_path] = content

        if directory != root:
            # Give the parent a description for this directory: reuse the single
            # child's description, else leave blank for a human/agent to fill.
            concept_entries = [e for e in entries if e[0] != "Subdirectories"]
            if len(concept_entries) == 1 and concept_entries[0][3]:
                dir_desc[directory] = concept_entries[0][3]
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Regenerate OKF index.md files.")
    ap.add_argument("bundle", type=Path, help="Bundle root directory")
    ap.add_argument("--check", action="store_true", help="Do not write; exit 1 if any index is stale")
    args = ap.parse_args()

    root = args.bundle.resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    indexes = compute_indexes(root)
    if not indexes:
        print("No concept documents found; nothing to index.")
        return 0

    stale = 0
    for path, content in sorted(indexes.items()):
        current = path.read_text(encoding="utf-8") if path.exists() else None
        rel = path.relative_to(root)
        if current == content:
            continue
        stale += 1
        if args.check:
            print(f"STALE  {rel}")
        else:
            path.write_text(content, encoding="utf-8")
            print(f"wrote  {rel}")

    if args.check:
        print(f"\n{stale} stale index file(s)." if stale else "All index files up to date.")
        return 1 if stale else 0
    print(f"\nRegenerated {len(indexes)} index file(s) ({stale} changed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
