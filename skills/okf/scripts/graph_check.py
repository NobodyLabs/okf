#!/usr/bin/env python3
"""Diagnose an OKF bundle's cross-link graph — the consumer's-eye view.

A bundle can be perfectly conformant and still be useless: a bag of concepts
nobody can navigate between. This script builds the directed graph of internal
markdown links and surfaces the problems the conformance validator can't:

  - orphan concepts   — nothing links TO them (unreachable by following links)
  - disconnected components — islands the reader can't cross between
  - dangling concepts — link OUT to nothing (dead ends)
  - least-linked concepts — candidates that need more cross-linking

Orphans and multiple components are the signal that the prose implies
relationships you never wrote as links. Fixing them is what turns a directory
of files into a navigable knowledge graph.

Dependency-free; runs on any bundle. index.md/log.md are ignored as nodes.

Usage:
    python3 graph_check.py <bundle_dir>
    python3 graph_check.py <bundle_dir> --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RESERVED = {"index.md", "log.md"}
MD_LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)]+)\)")


def resolve(src: Path, target: str, root: Path) -> Path | None:
    t = target.split("#", 1)[0].strip()
    if not t or "://" in t or t.startswith(("mailto:", "tel:")) or not t.endswith(".md"):
        return None
    p = (root / t.lstrip("/")) if t.startswith("/") else (src.parent / t)
    return p.resolve()


FM_SOURCE_RESOURCE = re.compile(r"^\s+-?\s*resource:\s*(.+)$")


def frontmatter_source_paths(text: str) -> list[str]:
    """Return the `sources[].resource` values from a document's frontmatter.

    §5.1 expresses lineage through links: when a source points at another
    concept in the bundle, that derivation is a real edge and the graph should
    see it. Only *indented* `resource:` keys belong to sources entries — the
    top-level one names the concept's own asset, not a relationship.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    out: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = FM_SOURCE_RESOURCE.match(line)
        if m:
            out.append(m.group(1).strip().strip("'\""))
    return out


def resolve_fm_path(src: Path, target: str, root: Path) -> Path | None:
    """Resolve a path-valued frontmatter field (§6.2). Tries the document's own
    directory first, then the bundle root — real bundles write both forms."""
    t = target.split("#", 1)[0].strip()
    if not t or "://" in t or not t.endswith(".md"):
        return None
    if t.startswith("/"):
        return (root / t.lstrip("/")).resolve()
    cand = (src.parent / t).resolve()
    return cand if cand.exists() else (root / t).resolve()


def components(nodes: set, undirected: dict) -> list[set]:
    seen: set = set()
    comps: list[set] = []
    for n in nodes:
        if n in seen:
            continue
        stack = [n]
        comp: set = set()
        while stack:
            cur = stack.pop()
            if cur in comp:
                continue
            comp.add(cur)
            seen.add(cur)
            stack.extend(undirected.get(cur, set()) - comp)
        comps.append(comp)
    return comps


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnose an OKF bundle's link graph.")
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = ap.parse_args()

    root = args.bundle.resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    concepts = [p.resolve() for p in root.rglob("*.md") if p.name not in RESERVED]
    nodes = set(concepts)
    out_edges: dict[Path, set] = {c: set() for c in concepts}
    in_deg: dict[Path, int] = {c: 0 for c in concepts}
    undirected: dict[Path, set] = {c: set() for c in concepts}
    edge_count = 0

    for c in concepts:
        text = c.read_text(encoding="utf-8", errors="replace")
        targets = [resolve(c, m.group(1), root) for m in MD_LINK.finditer(text)]
        targets += [resolve_fm_path(c, s, root) for s in frontmatter_source_paths(text)]
        for tgt in targets:
            if tgt is None or tgt == c or tgt not in nodes:
                continue
            if tgt not in out_edges[c]:
                out_edges[c].add(tgt)
                in_deg[tgt] += 1
                undirected[c].add(tgt)
                undirected[tgt].add(c)
                edge_count += 1

    def rel(p: Path) -> str:
        return str(p.relative_to(root))

    # Root-level concepts are entry points reached via index.md, not via inbound
    # cross-links — a designated front door with in-degree 0 is expected, not an
    # orphan. Only flag deeper concepts nothing links to.
    def depth(c: Path) -> int:
        return len(c.relative_to(root).parts)

    entry_points = sorted(rel(c) for c in concepts if in_deg[c] == 0 and depth(c) == 1)
    orphans = sorted(rel(c) for c in concepts if in_deg[c] == 0 and depth(c) > 1)
    dead_ends = sorted(rel(c) for c in concepts if not out_edges[c])
    comps = components(nodes, undirected)
    comps_sorted = sorted((sorted(rel(x) for x in comp) for comp in comps), key=len, reverse=True)
    degrees = sorted(
        ((rel(c), in_deg[c] + len(out_edges[c]), in_deg[c], len(out_edges[c])) for c in concepts),
        key=lambda t: t[1],
    )

    data = {
        "concepts": len(concepts),
        "edges": edge_count,
        "components": len(comps),
        "orphans": orphans,
        "entry_points": entry_points,
        "dead_ends": dead_ends,
        "component_sizes": [len(c) for c in comps_sorted],
    }

    if args.json:
        data["least_linked"] = [{"concept": d[0], "in": d[2], "out": d[3]} for d in degrees[:5]]
        print(json.dumps(data, indent=2))
        return 0

    print(f"Concepts: {len(concepts)}   Edges: {edge_count}   Components: {len(comps)}")
    print()
    if len(comps) > 1:
        print(f"⚠ {len(comps)} disconnected components — the bundle is not one navigable graph:")
        for i, comp in enumerate(comps_sorted, 1):
            head = ", ".join(comp[:4]) + (" …" if len(comp) > 4 else "")
            print(f"    component {i} ({len(comp)}): {head}")
        print()
    else:
        print("✓ Single connected component — every concept is reachable by following links.")
        print()

    if orphans:
        print(f"⚠ {len(orphans)} orphan concept(s) — nothing links to them (add inbound links):")
        for o in orphans:
            print(f"    {o}")
        print()
    else:
        print("✓ No orphans — every non-root concept has at least one inbound link.")
        print()
    if entry_points:
        print(f"· {len(entry_points)} root entry point(s) (in-degree 0 is expected — reached via index.md): {', '.join(entry_points)}")
        print()

    if dead_ends:
        print(f"· {len(dead_ends)} dead-end concept(s) — they link out to nothing (often fine for leaf refs):")
        for d in dead_ends[:10]:
            print(f"    {d}")
        if len(dead_ends) > 10:
            print(f"    … and {len(dead_ends) - 10} more")
        print()

    print("Least-linked concepts (in/out degree):")
    for name, total, ind, outd in degrees[:5]:
        print(f"    {name}  (in={ind}, out={outd})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
