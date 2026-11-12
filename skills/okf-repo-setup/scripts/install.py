#!/usr/bin/env python3
"""Install the OKF upkeep machinery into a repository. Idempotent.

What it writes (all relative to --repo):
  scripts/okf/{drift,stop_guard,validate_bundle,gen_index,graph_check,merge_driver}.py
  .claude/settings.json            — SessionStart drift line and merge driver setup + Stop guard (merged, not replaced)
  .claude/skills/okf-guardian/     — periodic safety-net skill
  AGENTS.md                        — short bundle block between <!-- okf:begin --> / <!-- okf:end -->
  CLAUDE.md                        — `@AGENTS.md` import; an okf block left there by an older install moves out
  .claude/rules/okf.md             — upkeep rules, loaded by path (paths: from the concepts' resource:)
  .gitattributes                   — block between # okf:begin / # okf:end: how the bundle merges
  .git/config                      — merge.okf.driver (per clone, hence also the SessionStart hook)
  .github/workflows/okf-gate.yml   — drift.py --gate on every PR and push to the integration branch,
                                     unless a workflow already runs it
  <mcp-dir>/                       — only with --with-mcp: knowledge-mcp service

AGENTS.md is the canon every agent reads (Codex, Cursor); Claude Code reads
CLAUDE.md, hence the import. What the upkeep takes (layers, commands, drift
signals) is needed only when code or the bundle changes, so it goes to a
path-scoped rule instead of the always-loaded instructions. A root AGENTS.md
that is the claude-memory-compiler schema (the memory once installed into the
repo root) is left alone with CLAUDE.md and the rule: a block in it would mix
two documents. Move the memory into its own directory first.

Every branch that refreshes the bundle writes the top of log.md, the anchor and
the date of the concepts it touched, so parallel branches used to conflict there
even when the texts merged cleanly. log.md and .okf-anchor merge by union (both
sides kept); a concept goes through scripts/okf/merge_driver.py, which settles a
conflict in the date alone and leaves any other one to the person merging.

File policy: missing -> written; identical -> skipped; differs -> kept and
reported, unless --force (engine files only). `src/project.ts` of the MCP is
the project's own config and is never overwritten; neither is `src/org.ts`
(redaction shared by a team's projects), unless --org-file names the team's copy. The okf blocks (AGENTS.md,
.gitattributes) and .claude/rules/okf.md are managed: rewritten on every run.

It does NOT generate the bundle (that is the `okf` skill), set the anchor
(only true after the bundle matches the code), or touch the rest of CI and
the deployment (those need judgement — see the skill's references/). The gate is the
exception: the AGENTS.md block says CI checks the rule, and nothing else makes
that true.

Usage:
  python3 install.py --repo . [--base-ref origin/develop] [--with-mcp]
                     [--mcp-dir apps/knowledge-mcp] [--product-name "..."]
                     [--app-slug my-app] [--org-file team-org.ts] [--force] [--dry-run]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
ASSETS = SKILL / "assets"
# One copy of each tool: bundle tools live in the okf skill, the Stop guard here.
OKF_SCRIPTS = SKILL.parent / "okf" / "scripts"
TOOLS = {
    "drift.py": OKF_SCRIPTS,
    "validate_bundle.py": OKF_SCRIPTS,
    "gen_index.py": OKF_SCRIPTS,
    "graph_check.py": OKF_SCRIPTS,
    "merge_driver.py": OKF_SCRIPTS,
    "stop_guard.py": ASSETS / "okf-scripts",
}
BEGIN, END = "<!-- okf:begin", "<!-- okf:end -->"
ATTR_BEGIN, ATTR_END = "# okf:begin", "# okf:end"
HOOK_MARK = "scripts/okf/"
RULE = ".claude/rules/okf.md"
IMPORT = re.compile(r"^@AGENTS\.md[ \t]*$", re.M)
AGENTS_HEAD = (
    "# AGENTS.md\n\n"
    "Инструкции для агентов в этом репозитории (Claude Code, Codex, Cursor). `CLAUDE.md` подключает "
    "этот файл строкой `@AGENTS.md`: общее для всех агентов пиши сюда, в `CLAUDE.md` — только то, "
    "что касается Claude Code.\n\n"
)
# First line of claude-memory-compiler's own AGENTS.md: the old install copied it into the repo root.
MEMORY_SCHEMA = "Personal Knowledge Base Schema"
# A bundle section written by hand before the markers existed.
HANDWRITTEN = re.compile(r"^#{1,4}\s+Knowledge bundle\b", re.M)


class Report:
    def __init__(self, dry: bool):
        self.dry = dry
        self.lines: list[str] = []
        self.warnings: list[str] = []

    def add(self, status: str, path: str, note: str = "") -> None:
        self.lines.append(f"  {status:<9} {path}{('  — ' + note) if note else ''}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def git(repo: Path, *args: str) -> str | None:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def render(text: str, subs: dict[str, str]) -> str:
    for k, v in subs.items():
        text = text.replace(k, v)
    return text


def put(rep: Report, repo: Path, rel: str, content: str, *, force: bool, never_overwrite: bool = False,
        mode: int | None = None) -> None:
    target = repo / rel
    if target.exists():
        current = target.read_text(encoding="utf-8")
        if current == content:
            rep.add("same", rel)
            return
        if never_overwrite or not force:
            rep.add("kept", rel, "differs from template" + ("" if never_overwrite else "; --force to replace"))
            return
        status = "replaced"
    else:
        status = "created"
    if not rep.dry:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if mode:
            target.chmod(mode)
    rep.add(status, rel)


GATE = ".github/workflows/okf-gate.yml"


def install_gate(rep: Report, repo: Path, base_ref: str, force: bool) -> None:
    """The CI half of the rule the AGENTS.md block states: drift.py --gate for every commit."""
    workflows = repo / ".github" / "workflows"
    for wf in sorted(workflows.glob("*.y*ml")) if workflows.is_dir() else []:
        rel = wf.relative_to(repo).as_posix()
        if rel != GATE and re.search(r"drift\.py\b[^\n]*--gate", read(wf)):
            rep.add("same", rel, "already runs drift.py --gate")
            return
    branch = base_ref.split("/", 1)[1] if base_ref.startswith("origin/") else base_ref
    put(rep, repo, GATE, render(read(ASSETS / "ci" / "okf-gate.yml"), {"__OKF_BRANCH__": branch}), force=force)


def detect_base_ref(repo: Path) -> str:
    for ref in ("origin/develop", "origin/main", "origin/master"):
        if git(repo, "rev-parse", "--verify", "--quiet", ref) is not None:
            return ref
    return "origin/main"


def merge_hooks(rep: Report, repo: Path) -> None:
    rel = ".claude/settings.json"
    path = repo / rel
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except json.JSONDecodeError as e:
        rep.warn(f"{rel} is not valid JSON ({e}) — hooks NOT installed; fix it and re-run")
        return
    hooks = settings.setdefault("hooks", {})
    # (event, script, group): a hook is present when some command of its event names the script.
    wanted = [
        ("SessionStart", "drift.py", {"matcher": "", "hooks": [{
            "type": "command",
            "command": 'python3 "$CLAUDE_PROJECT_DIR"/scripts/okf/drift.py --quiet || true',
            "timeout": 10}]}),
        # The merge driver lives in .git/config, which a clone does not carry: set it up in every one.
        ("SessionStart", "merge_driver.py", {"matcher": "", "hooks": [{
            "type": "command",
            "command": 'python3 "$CLAUDE_PROJECT_DIR"/scripts/okf/merge_driver.py --install --quiet || true',
            "timeout": 10}]}),
        ("Stop", "stop_guard.py", {"hooks": [{
            "type": "command",
            "command": 'python3 "$CLAUDE_PROJECT_DIR"/scripts/okf/stop_guard.py',
            "timeout": 90}]}),
    ]
    changed = []
    for event, script, group in wanted:
        groups = hooks.setdefault(event, [])
        present = any(HOOK_MARK + script in h.get("command", "") for g in groups for h in g.get("hooks", []))
        if not present:
            groups.append(group)
            changed.append(f"{event} {script}")
    if not changed:
        rep.add("same", rel, "okf hooks already present")
        return
    if not rep.dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rep.add("merged", rel, "added " + ", ".join(changed))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write(rep: Report, repo: Path, rel: str, old: str, new: str, note: str) -> None:
    if new == old:
        rep.add("same", rel, note)
        return
    if not rep.dry:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(new, encoding="utf-8")
    rep.add("updated" if old else "created", rel, note)


def without_block(text: str) -> str:
    """`text` with the okf block cut out and the blank lines around it collapsed."""
    if BEGIN not in text or END not in text:
        return text
    head = text[:text.index(BEGIN)].rstrip("\n")
    tail = text[text.index(END) + len(END):].lstrip("\n")
    if head and tail:
        return head + "\n\n" + tail
    return head + "\n" if head else tail


def memory_schema(text: str) -> bool:
    first = next((line for line in text.splitlines() if line.strip()), "")
    return MEMORY_SCHEMA in first


def upsert_agents_md(rep: Report, repo: Path, section: str) -> None:
    rel = "AGENTS.md"
    text = read(repo / rel)
    if BEGIN in text and END in text:
        new = text[:text.index(BEGIN)] + section.strip() + text[text.index(END) + len(END):]
    else:
        new = (text.rstrip() + "\n\n" if text.strip() else AGENTS_HEAD) + section.strip() + "\n"
    write(rep, repo, rel, text, new, "okf block")


def import_agents_md(rep: Report, repo: Path, agents_before: str) -> None:
    """Claude Code reads CLAUDE.md, not AGENTS.md: make it import the canon."""
    rel = "CLAUDE.md"
    text = read(repo / rel)
    new = without_block(text)
    if not IMPORT.search(new):
        if without_block(agents_before).strip() and new.strip():
            rep.warn("AGENTS.md was there and CLAUDE.md did not import it — Claude Code now loads both: "
                     "check that they do not repeat each other")
        new = "@AGENTS.md\n" + ("\n" + new.lstrip("\n") if new.strip() else "")
    write(rep, repo, rel, text, new, "@AGENTS.md" + (", okf block moved out" if BEGIN in text else ""))
    if HANDWRITTEN.search(new):
        rep.warn("CLAUDE.md has a «Knowledge bundle» section outside the okf markers — the bundle is now "
                 "described in AGENTS.md and .claude/rules/okf.md: remove that section by hand")


def okf_module(name: str):
    """A bundle tool of the okf skill, imported from its one copy."""
    spec = importlib.util.spec_from_file_location(f"okf_{name}", OKF_SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upsert_gitattributes(rep: Report, repo: Path) -> None:
    rel = ".gitattributes"
    text = read(repo / rel)
    block = read(ASSETS / "gitattributes-okf").strip() + "\n"
    if ATTR_BEGIN in text and ATTR_END in text[text.index(ATTR_BEGIN):]:
        start = text.index(ATTR_BEGIN)
        stop = text.find("\n", text.index(ATTR_END, start))
        new = text[:start] + block + (text[stop + 1:] if stop != -1 else "")
    else:
        new = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    write(rep, repo, rel, text, new, "okf block: how the bundle merges")


def configure_merge(rep: Report, repo: Path) -> None:
    """The driver .gitattributes names lives in .git/config: set it for this clone."""
    status = okf_module("merge_driver").configure(repo, dry=rep.dry)
    if status is None:
        rep.warn("git config merge.okf.driver is not set — concepts merge without the driver; "
                 "run python3 scripts/okf/merge_driver.py --install")
    else:
        rep.add(status, "git config merge.okf.driver", "the bundle's merge driver in this clone")


def rule_paths(repo: Path, mcp_dir: str | None) -> list[str]:
    """Where the upkeep rule loads: the bundle, the MCP serving it and the top-level dirs and root files
    its concepts describe."""
    drift = okf_module("drift")
    bundle = repo / drift.BUNDLE_DEFAULT
    paths = {f"{drift.BUNDLE_DEFAULT}/**"} | ({f"{mcp_dir}/**"} if mcp_dir else set())
    for concept in sorted(bundle.rglob("*.md")) if bundle.is_dir() else []:
        meta = drift.read_meta(concept)
        res = drift.as_repo_path(meta.get("resource", ""))
        if concept.name in drift.RESERVED or not res or meta.get("status") == "deprecated":
            continue
        top, _, rest = res.rstrip("/").partition("/")
        paths.add(f"{top}/**" if rest or res.endswith("/") or (repo / top).is_dir() else top)
    return sorted(paths)


def isolate_from_host(rep: Report, repo: Path, mcp_dir: str) -> None:
    """Keep the host app's toolchain from swallowing the MCP package.

    A root tsconfig with `**/*.ts` typechecks the MCP sources, and in the host's
    Docker build (no MCP node_modules there) `next build` fails on missing
    `express` / `@modelcontextprotocol/sdk`. Minimal text edits only: configs
    are often JSONC and hand-formatted.
    """
    tsconfig = repo / "tsconfig.json"
    if tsconfig.exists():
        text = tsconfig.read_text(encoding="utf-8")
        m = re.search(r'"exclude"\s*:\s*\[', text)
        if re.search(r'"exclude"\s*:\s*\[[^\]]*"' + re.escape(mcp_dir) + r'"', text):
            rep.add("same", "tsconfig.json", f"{mcp_dir} already excluded")
        elif m:
            new = text[:m.end()] + f'"{mcp_dir}", ' + text[m.end():]
            if not rep.dry:
                tsconfig.write_text(new, encoding="utf-8")
            rep.add("patched", "tsconfig.json", f"exclude += {mcp_dir}")
        else:
            rep.warn(f'tsconfig.json has no "exclude" — add "{mcp_dir}" to it by hand if its include covers the MCP dir')

    ignore = repo / ".dockerignore"
    if ignore.exists():
        lines = ignore.read_text(encoding="utf-8").splitlines()
        if mcp_dir in (l.strip().strip("/") for l in lines):
            rep.add("same", ".dockerignore", f"{mcp_dir} already ignored")
        else:
            if not rep.dry:
                ignore.write_text("\n".join(lines + [mcp_dir]) + "\n", encoding="utf-8")
            rep.add("patched", ".dockerignore", f"+ {mcp_dir} (the MCP image has its own Dockerfile.dockerignore)")

    gitignore = repo / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    added = []
    # Build output and `npm install` — without the latter thousands of files land in a commit.
    for path in (f"{mcp_dir}/dist", f"{mcp_dir}/node_modules"):
        # A path inside the dir, so directory-only rules (`node_modules/`) match too.
        if git(repo, "check-ignore", "-q", f"{path}/x") is not None:
            rep.add("same", ".gitignore", f"{path} already ignored")
        else:
            added.append(path)
            rep.add("patched", ".gitignore", f"+ {path}")
    if added and not rep.dry:
        gitignore.write_text("\n".join(lines + added) + "\n", encoding="utf-8")

    for name in ("vitest.config.ts", "vitest.config.mts", "vitest.config.js", "jest.config.js", "jest.config.ts"):
        cfg = repo / name
        if cfg.exists() and "include" not in cfg.read_text(encoding="utf-8"):
            rep.warn(f"{name} has no explicit include — make sure it does not pick up {mcp_dir}/**/*.test.ts")
    for name in (".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs", "eslint.config.js", "eslint.config.mjs"):
        if (repo / name).exists():
            rep.warn(f"{name}: add {mcp_dir} to ignores so host lint does not lint the MCP package")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--base-ref", default=None, help="integration branch for --branch drift (auto: origin/develop|main)")
    ap.add_argument("--with-mcp", action="store_true", help="also install the knowledge-mcp service")
    ap.add_argument("--mcp-dir", default=None, help="where to put knowledge-mcp (default: apps/knowledge-mcp if apps/ exists, else knowledge-mcp)")
    ap.add_argument("--product-name", default=None)
    ap.add_argument("--app-slug", default=None, help="image/app name prefix (default: repo dir name)")
    ap.add_argument("--org-file", type=Path, default=None,
                    help="with --with-mcp: a team's src/org.ts (redaction shared by its projects); replaces the installed one")
    ap.add_argument("--force", action="store_true", help="replace engine files that differ from the template")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo = args.repo.resolve()
    top = git(repo, "rev-parse", "--show-toplevel")
    if not top:
        print(f"error: {repo} is not a git repository", file=sys.stderr)
        return 2
    repo = Path(top)
    rep = Report(args.dry_run)

    base_ref = args.base_ref or detect_base_ref(repo)
    if git(repo, "rev-parse", "--verify", "--quiet", base_ref) is None:
        rep.warn(f"base ref {base_ref} does not resolve — the Stop guard stays silent until it does "
                 f"(git fetch, or re-run with --base-ref)")
    if args.org_file and not args.org_file.is_file():
        print(f"error: --org-file {args.org_file} does not exist", file=sys.stderr)
        return 2
    slug = args.app_slug or repo.name
    product = args.product_name or slug

    subs = {"__OKF_BASE_REF__": base_ref, "__APP_SLUG__": slug, "__PRODUCT_NAME__": product}

    for name, src_dir in TOOLS.items():
        src = (src_dir / name).read_text(encoding="utf-8")
        put(rep, repo, f"scripts/okf/{name}", render(src, subs), force=args.force, mode=0o755)

    merge_hooks(rep, repo)
    upsert_gitattributes(rep, repo)
    configure_merge(rep, repo)
    install_gate(rep, repo, base_ref, args.force)
    put(rep, repo, ".claude/skills/okf-guardian/SKILL.md",
        render((ASSETS / "guardian" / "SKILL.md").read_text(encoding="utf-8"), subs), force=args.force)

    mcp_dir = None
    mcp_line = mcp_section = ""
    if args.with_mcp:
        mcp_dir = args.mcp_dir or ("apps/knowledge-mcp" if (repo / "apps").is_dir() else "knowledge-mcp")
        mcp_dir = mcp_dir.strip("/")
        subs["__MCP_DIR__"] = mcp_dir
        src_root = ASSETS / "knowledge-mcp"
        for f in sorted(p for p in src_root.rglob("*") if p.is_file()):
            rel = f.relative_to(src_root).as_posix()
            if rel == "src/org.ts" and args.org_file:
                # The team's copy is managed by whoever passes it: always the current one.
                put(rep, repo, f"{mcp_dir}/{rel}", args.org_file.read_text(encoding="utf-8"), force=True)
                continue
            put(rep, repo, f"{mcp_dir}/{rel}", render(f.read_text(encoding="utf-8"), subs),
                force=args.force, never_overwrite=rel in ("src/project.ts", "src/org.ts"))
        mcp_line = render(read(ASSETS / "agents-md-mcp.md"), subs)
        mcp_section = render(read(ASSETS / "rules-okf-mcp.md"), subs)
        isolate_from_host(rep, repo, mcp_dir)

    agents_before = read(repo / "AGENTS.md")
    if memory_schema(agents_before):
        rep.warn(f"AGENTS.md at the root is the claude-memory-compiler schema ({MEMORY_SCHEMA}), the memory "
                 "installed into the repo root the old way — AGENTS.md, CLAUDE.md and .claude/rules/okf.md are "
                 "left as they are. Move the memory into its own directory (tools/memory-compiler), so that "
                 "the root AGENTS.md holds project instructions (memory.md of your setup standard, if you have one), "
                 "then re-run")
    else:
        block = render(read(ASSETS / "agents-md-section.md"), subs).replace("__MCP_LINE__", mcp_line)
        upsert_agents_md(rep, repo, block)
        import_agents_md(rep, repo, agents_before)
        globs = "\n".join(f"  - {json.dumps(p, ensure_ascii=False)}" for p in rule_paths(repo, mcp_dir))
        rule = render(read(ASSETS / "rules-okf.md"), subs).replace("__MCP_SECTION__", mcp_section)
        put(rep, repo, RULE, rule.replace("__OKF_RULE_PATHS__", globs), force=True)

    bundle = repo / "okf-bundle"
    if not bundle.is_dir():
        rep.warn("okf-bundle/ does not exist yet — generate it with the `okf` skill, set the anchor and re-run "
                 f"this script: {RULE} loads by the concepts' paths")
    elif not (bundle / ".okf-anchor").exists():
        rep.warn("okf-bundle/.okf-anchor is missing — once the bundle matches the code: "
                 "python3 scripts/okf/drift.py --set-anchor")

    print(f"okf-repo-setup → {repo}{'  (dry run)' if args.dry_run else ''}")
    print(f"  base ref: {base_ref}   app slug: {slug}   product: {product}")
    print("\n".join(rep.lines))
    for w in rep.warnings:
        print(f"  ⚠ {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
