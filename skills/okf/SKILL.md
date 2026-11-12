---
name: okf
description: >-
  Produce, extend, refresh, or validate an Open Knowledge Format (OKF) bundle —
  a directory of markdown files with YAML frontmatter (one "concept" per file)
  plus index files, cross-links, and citations — so coding agents and new
  engineers understand a project without pasting files each time. Works for any
  source: code, an API, a data platform, a product, or docs.
  Trigger whenever the user wants to build, enrich, refresh, or
  conformance-check an "okf bundle", "knowledge bundle" / «бандл знаний», or an
  agent-readable knowledge base — even if they never say "OKF" — e.g. "document
  this repo so agents understand it", «задокументируй проект для агентов»,
  "turn this project into a knowledge graph of concepts", or (existing bundle)
  "the okf-bundle/ is missing a module" / "check ./kb is valid OKF". Wiring a
  repo so the bundle stays in sync (hooks, CI, knowledge-mcp) is okf-repo-setup.
  NOT for single-file summaries, a README, an OpenAPI spec, a Confluence page,
  an MkDocs site, or an Obsidian vault.
---

# Producing OKF bundles

## What OKF is (and why the shape matters)

The Open Knowledge Format is deliberately boring: **a directory of markdown
files, each with a YAML frontmatter block.** No schema registry, no SDK, no
serving infrastructure. That boringness is the point — a bundle is
`cat`-readable by a human, ingestible verbatim by an LLM, diffable in git, and
portable across every tool that speaks markdown. Your job with this skill is to
turn a project into such a bundle: not a data dump, but a curated set of
**concepts** a newcomer (human or agent) could use to actually *understand* the
project.

The mental model, which every rule below serves:

- **Concept = one markdown file.** One thing worth understanding on its own — a
  service, a table, an API endpoint, a metric, a playbook. Not one file per
  source file; one file per *idea*.
- **Bundle = a tree of concepts.** Subdirectories group concepts by kind.
- **`index.md` = progressive disclosure.** Lets a reader see what's available at
  each level before opening documents — so an agent can navigate the hierarchy
  one level at a time instead of loading everything into context.
- **Links = a graph.** Concepts link to each other with normal markdown links,
  expressing relationships richer than the directory tree.
- **Citations = grounding.** Every non-obvious claim traces to a source.

The full working rules are in `references/spec.md` (a condensed, authoring-focused
version of the OKF v0.2 spec). Read it before authoring your first bundle; it is
the source of truth for frontmatter, provenance, trust, links, index, log, and
conformance.

## Workflow

Treat this as a produce-then-verify loop. Steps 1–2 are where the quality is
won or lost; don't rush them.

### 1. Scope the bundle with the user

Establish, briefly:

- **The source.** A repo path? A data platform? An API/OpenAPI spec? A docs
  folder? A live system you'll inspect? Get the concrete location.
- **The audience & purpose.** "Context for coding agents", "onboarding for new
  engineers", "a catalog of our data" — this sets the altitude. A bundle for
  agents favors dense, structured, cross-linked concepts; a bundle for humans
  can carry more narrative.
- **Where the bundle goes.** Default to `./okf-bundle/` or a name the user gives.
- **Product sources beyond the code.** When the bundle should carry a real
  product layer (step 2), ask what non-code sources exist — a PRD, a features
  wiki, tickets, decision docs. Code grounds *what* the system does; the *why
  and for whom* usually lives outside it, and without those sources the product
  layer can only be functional description.

If the user already pointed you at a source and stated intent, don't
interrogate — proceed and confirm your concept inventory in step 2.

### 2. Explore the source and draft a concept inventory

**Ground everything in the real source.** Read the README, manifests, directory
tree, entrypoints, schemas, existing docs — whatever the source offers. For a
large source, fan out with parallel subagents (one per subsystem) to map it
without blowing context; each returns a list of candidate concepts.

Then produce a **concept inventory**: a flat list of `concept-id → type →
one-line description`, organized into the directory layout you'll use. Pick a
small, consistent set of `type` values (see `references/frontmatter.md`) and a
2–3-level directory structure. For per-domain starting inventories and the right
altitude, read **`references/domains.md`** — it covers codebases, data
platforms, APIs, products, and docs-to-OKF.

Show the inventory to the user before writing dozens of files. This is cheap to
correct now and expensive later. Getting the *set of concepts* and their
*altitude* right is 80% of a good bundle.

The altitude test for each candidate: **"would someone search for this by
name?"** Yes → it's a concept. No → it's a section inside another concept.
Resist one-doc-per-file; resist a single giant doc. Aim for concepts that are
individually loadable and mutually linked.

**Cover the full technical surface (technical-documentation completeness).**
When the goal is *technical documentation* of a codebase — the common case for
"document this project" — don't stop at the components you happened to open.
Walk this checklist and mint a concept for every layer the source actually
contains (apply the altitude test; skip a layer the project genuinely lacks,
don't invent a stub):

- [ ] **Orientation / architecture** — the root `architecture.md` (`Architecture`):
      components, boundaries, request/data flow. The semantic front door.
- [ ] **Components / services / modules** (`Service` / `Module` / `Library`) —
      one per deployable or cohesive unit: responsibility, entrypoint, deps.
- [ ] **Data models / schema** (`Data Model`) — entities, tables, core types,
      relationships. Include migrations/storage if present.
- [ ] **APIs / interfaces** (`API Endpoint` / `Interface` / `CLI Command`) —
      the contract surface others integrate against.
- [ ] **Configuration** (`Config`) — env vars, settings, feature flags — what
      the operator must set. Pull from `.env.example`, config schemas.
- [ ] **Build, deploy & infrastructure** (`Guide` / `Runbook` / `Reference`) —
      how it's built, packaged (Docker), and shipped (CI/CD, k8s, IaC). Pull
      from Dockerfile, CI workflows, `docker-compose`, deploy manifests.
- [ ] **Tech stack & dependencies** (`Reference`) — languages, frameworks,
      major third-party services the system leans on and why.
- [ ] **Testing** (`Guide`) — how tests are structured and run.
- [ ] **Observability** (`Reference`) — logs, metrics, traces, alerts.
- [ ] **Security & non-functional** (`Policy` / `Reference`) — authn/z model,
      secrets handling, rate limits, SLAs, compliance boundaries. **Known
      findings**: when the repo has a security audit or incident write-ups
      (`SECURITY_AUDIT*.md`, `docs/security/`, `docs/incidents/`, postmortems),
      one `Reference` concept listing each finding that must not come back —
      what, where (route, env, identifier), why — citing the audit line. Agents
      grep it against a diff before changing or testing code; a re-introduced
      finding is the failure this layer exists to prevent.
- [ ] **Decisions / rationale** (`ADR`) — the *why* behind non-obvious choices,
      only where docs/comments/history evidence it.

This checklist is the difference between "documented the code I read" and
*full technical documentation*. Report which layers you captured and which the
source didn't contain, so the coverage is legible rather than silently partial.
`references/domains.md` (codebase section) expands each layer.

**Cover the product layer, not just the technical structure.** A bundle that
only mirrors the code — services, models, endpoints — captures *what exists* but
not *what it's for*. Even for a codebase, deliberately inventory the
product/business dimension: the capabilities the system delivers to users
(`type: Feature`), the flows users take through it (`type: User Journey`), the
business rules and policies it enforces (`type: Business Process` / `Policy`),
and the domain terms other concepts lean on (`type: Glossary Term`). These
answer the *why* a purely structural bundle leaves out, and they're what a
product-minded reader (or an agent reasoning about intent, not just call graphs)
comes for. Ground them in the same source — features inferred from routes and
handlers, rules from validation code and comments — never invented. When the
source *is* product documentation (a PRD, a features wiki) with no code, this
layer is the whole bundle; see `references/domains.md`.

When the user wants the product and technical layers **separately
maintainable**, give the product layer its own top-level directory
(`product/` — features, journeys, business processes, policies) alongside the
technical directories — still one bundle, one graph. Separation is
directory-level; consistency is link-level: every `Feature` links to the
services/endpoints that implement it, and those link back. Never split the two
layers into separate bundles — cross-bundle relative links break, and nothing
detects drift between the bundles.

**Cover the operational, onboarding, and rationale layer too.** Structural +
product concepts serve an agent doing a lookup, but leave a human onboarding, an
operator on call, or an architect asking "why" underserved. Deliberately check
for these cross-cutting blocks and capture the ones the source actually
contains: onboarding/getting-started (`Guide`), testing (`Guide`), runbooks and
troubleshooting (`Runbook`), observability (`Reference`), decisions/rationale
(`ADR`), a glossary (`Glossary Term`), and conventions/contribution (`Guide`).
The rule is **capture when the material genuinely exists, don't invent stubs** —
a real setup guide is gold; an empty `getting-started` placeholder is the noise
OKF avoids. To let one bundle serve several audiences without a second tree or
duplicated content, tag concepts by audience with the existing `tags` field
(`tags: [onboarding]`, `[oncall]`, `[product]`) so a consumer can pull its
slice; reserve thin `guides/<audience>.md` reading-path docs for large,
genuinely multi-audience bundles. Full guidance and the type table:
`references/domains.md` (the cross-cutting layer section).

**Give the bundle an entry point.** Include, as a strong default, one
root-level orientation concept that answers "what is this project, **what does
it do for its users/the business**, who is it for, where do I start" and links
out to the major areas — e.g. `overview.md` (`type: Overview`) or, for a
codebase, `architecture.md` (`type: Architecture`). Lead it with the product
framing (the one-paragraph "what and why"), then the technical map — so a reader
gets intent before implementation.
This is *not* the same as `index.md`: `index.md` is a mechanical file listing,
while the orientation concept is the semantic front door. A reader (human or
agent) that lands in the bundle root should hit context, not just a directory
of folders. The validator emits an advisory when the bundle root has no
concept doc — that's the nudge to add this. (For a pure standalone data export
where a `Dataset` concept already sits at the root, that concept can serve as
the entry point.)

### 3. Author the concept documents

For each concept, write one markdown file: frontmatter + structured body. Start
from `assets/concept_template.md`. The rules that matter:

- **Frontmatter.** `type` is the only *required* field, but always add `title`
  and a tight one-sentence `description` (it's reused verbatim in every
  `index.md`). Add `resource` when a real underlying asset exists (a repo path,
  URL, table URI) and `tags` for search. For product concepts implemented by
  specific code (a `Feature` backed by particular routes/handlers), set
  `resource` to that repo path — it is what lets the staleness check reach the
  product layer on refresh.
  Then add the v0.2 families that carry real information: `generated: { by, at }`
  on everything you author (`by` is an actor — `claude-code/<model>` for your own
  output, `human:<id>` **only** for hand-written content); `sources` for
  provenance; `status: deprecated` when superseding a concept others link to;
  `stale_after` when currency depends on a review cycle rather than a code
  change. Leave `verified` alone unless something genuinely confirmed the
  content — it is the trust signal, not a formality. Full field guide, the actor
  convention, and a `type` vocabulary: `references/frontmatter.md`. For governed
  metrics on a data platform, see `references/attested-computation.md`.
- **Body: structure over prose.** Lead with 1–3 short paragraphs of what the
  concept is and how it's used, then switch to tables, lists, and fenced code.
  Structural markdown aids both human reading and agent retrieval. Use
  conventional headings where they fit (`# Schema`, `# Interface`, `# Examples`,
  and `# Computation` on an Attested Computation); `references/domains.md`
  suggests sections per domain. There is no `# Citations` heading in v0.2 —
  provenance lives in frontmatter.
- **Cross-link as you write.** When prose names another concept, link it with a
  **file-relative path** from the current doc's directory (`[users](users.md)`,
  `[dataset](../datasets/sales.md)`). One link per mention per section; never
  over-link; never link a doc to itself or from headings/code fences. These
  links are what make the bundle a graph.
- **Diagram where it earns its place.** Full technical documentation is clearer
  with diagrams, and OKF is plain markdown — embed them as fenced `mermaid`
  blocks (they render in GitHub, most viewers, and Claude/Cursor). Reach for a
  diagram when structure beats prose: a `flowchart`/`graph` or C4-style view in
  the root `architecture.md`, a `sequenceDiagram` for a key request or auth flow,
  an `erDiagram` for related `Data Model` concepts. Keep each diagram small and
  focused (one flow, not the whole system), and **derive it from the source you
  actually read** — the same no-fabrication rule applies to boxes and arrows as
  to prose. Add one only where it clarifies; don't decorate every doc.
- **Cite, don't invent.** Record what you actually read as `sources` entries in
  frontmatter (`{ id, resource, title }`), and attribute a specific non-obvious
  claim with a markdown footnote whose label is that entry's `id`:
  `…sharded daily.[^ga4-schema]`. The label is the join key, so it survives the
  list being reordered — which agents do constantly. **Never fabricate** fields,
  schemas, endpoints, URLs, or relationships that aren't in the source — an
  ungrounded bundle is worse than a small one. If you don't know, leave it out.
- **Merge-friendly.** Branches refresh concepts in parallel, and two edits that
  land on one line conflict. No counts that move with the code ("133 route
  files", "2922 lines" — real conflicts, and stale the day after); one item per
  line (a table row per endpoint, not one row listing a whole domain); add list
  items and table rows in sorted order, not at the end. A repo wired by
  `okf-repo-setup` merges the date in `generated`, `log.md` and the anchor
  itself; what this rule prevents is the conflict left in the text.

Write concepts in dependency order when practical (the thing others link *to*
first), but don't block on it — broken links are tolerated by the format.

### 4. Generate index files (don't hand-write them)

Index files are mechanical and must stay in sync with the tree, so generate
them with the bundled script rather than authoring by hand:

```bash
python3 <skill>/scripts/gen_index.py <bundle_dir>
```

It walks the tree, groups each directory's concepts by `type`, pulls each
`description` from frontmatter, adds a `# Subdirectories` section, and writes a
stable, alphabetically-sorted `index.md` at every level. Re-run it any time the
set of concepts changes. (`--check` reports drift without writing — useful in
CI.) A bundle-root `index.md` may declare `okf_version: "0.2"` in frontmatter —
that is the one place frontmatter is allowed in an index, and the script
preserves it across regeneration.

Use `python3` explicitly — on some machines bare `python` is Python 2 and these
scripts require Python 3.

### 5. Optionally add a log

If the user wants change history, add a bundle-root `log.md` with
date-grouped entries newest-first (`## YYYY-MM-DD`). See `references/spec.md`.

### 6. Validate and graph-check before declaring done

Run the conformance validator and fix anything it flags:

```bash
python3 <skill>/scripts/validate_bundle.py <bundle_dir>
```

It enforces the actual OKF v0.2 conformance floor (§11: every non-reserved `.md`
parses and has a non-empty `type`, and reserved files follow their formats) as
**errors** — including frontmatter a strict YAML parser rejects: an unquoted
value containing `: ` (common in Russian titles) and duplicate keys (a merge
leftover). Quote such values and keep one key. It also reports missing recommended fields, malformed v0.2 families (a
`status` outside the enum, a `sources` entry with no `resource`, a footnote with
no matching `sources[].id`, an `Attested Computation` with no `runtime`), broken
cross-links, and a missing root-level orientation concept as
**warnings/advisories** (the spec tolerates those — don't chase every warning,
but do skim them for genuine mistakes like a typo'd link path or a bundle with
no entry point). Legacy v0.1 shapes (`timestamp`, `# Citations`) are recognized
and reported once as an INFO line, not flagged per file. Exit code 0 =
conformant.

Then run the graph diagnostic — it checks the bundle from the *consumer's* side,
where a valid-but-useless bundle hides: a conformant bundle can still be a bag
of unconnected concepts.

```bash
python3 <skill>/scripts/graph_check.py <bundle_dir>
```

It reports node/edge counts, **orphan concepts** (nothing links to them),
**disconnected components** (islands the reader can't reach by following
links), and the least-linked concepts. Orphans and multiple components are the
signal to add the cross-links the prose implies but you forgot to write —
that's what turns a directory of files into a navigable graph. (Dependency-free;
runs on any bundle.)

### 7. Offer to register the bundle where consumers will find it

A bundle only pays off if consumers discover it. When you've produced one **for
a codebase** (not a standalone data export), offer to add a short pointer to the
project's `AGENTS.md` — the file every coding agent reads (Codex, Cursor) — and
make sure `CLAUDE.md` loads it with an `@AGENTS.md` line, since Claude Code reads
only `CLAUDE.md`. If the repo already has an `<!-- okf:begin -->` block (installed
by `okf-repo-setup`), it is the pointer: don't add a second one. A root
`AGENTS.md` that starts with "Personal Knowledge Base Schema" is the memory
compiler's file, not project instructions — don't write into it; say so instead.
The pointer:

```markdown
## Knowledge bundle
An OKF knowledge bundle for this project lives in `./okf-bundle/`. Start at
`okf-bundle/index.md` and load individual concept docs on demand — don't read
the whole bundle at once; that's what the index and progressive disclosure are
for.
```

Keep it to a **pointer**, never inline the bundle contents into `AGENTS.md` or
`CLAUDE.md` — dumping it defeats the progressive-disclosure design. This step
edits repo-tracked files, so **ask first** rather than doing it silently, and
target the *project's* files, not global ones.

## Enriching or updating an existing bundle

When the input is already an OKF bundle:

1. Read the existing docs first (start from the root `index.md`). Treat on-disk
   content as the source of truth.
2. When augmenting a concept, **preserve its existing headings and structure** —
   extend sections and add new ones after the existing ones; don't rewrite a doc
   wholesale into a paraphrase of new material. Merge `tags` (union), keep
   `type`/`title`/`resource` unless genuinely wrong. Merge `sources` by `id`
   (union — never replace the list, or you drop provenance the prose still
   footnotes), refresh `generated.at`, and **drop `verified`** when you change
   the content: a verification attests to the text that was reviewed, so
   carrying it across a rewrite forges the trust signal. Leave a legacy
   `timestamp` or `# Citations` in place if the doc has one — converting it is
   not what this step is for.
3. Mint a new `references/<slug>.md` concept only when the new material is
   something other concepts would cite *by name* (an enum, a metric, a
   convention). When in doubt, fold it into an existing concept or skip — a
   bundle full of `references/overview` docs is noise.
4. Regenerate indexes (step 4), then validate and graph-check (step 6).

## Refreshing a bundle after the source changed (keeping it in sync)

A bundle is only trustworthy if it tracks the thing it describes. When a repo
has drifted since its bundle was written, **refresh only what changed** rather
than regenerating from scratch — a full rebuild throws away hand-curated prose
and churns the git history. The move is diff-driven:

1. **Find the drift** with the bundled script (it uses git + each concept's
   `resource:` to map changed source files to the concepts that describe them):

   ```bash
   python3 <skill>/scripts/drift.py <bundle_dir>          # or --repo <root> --since <ref>
   ```

   "Since" defaults to the commit in `<bundle_dir>/.okf-anchor` (record it with
   `--set-anchor` once the bundle matches the code), else the last commit that
   touched the bundle. It reports **STALE** (concept whose source changed →
   refresh its content; ◐ = already touched in the same unit of work, still
   check it), **UNMATCHED** (a change in a file whose concepts declare
   `resource_anchors`, but outside every anchor), **UNCOVERED** (a new/changed
   source file no concept points at → probably a new concept), and **ORPHANED**
   (concept whose `resource:` file is gone → deprecate or repoint). A
   `resource:` may be a file or a whole directory; several concepts sharing one
   file are told apart by `resource_anchors`. The git-diff mapping only reaches concepts whose
   `resource` is a repo path; for URL-resourced bundles (APIs, data) it lists the
   changed files as a manual coverage checklist. Independently of git, it also
   reports **EXPIRED** — any concept whose `stale_after` date has passed. That is
   the freshness signal for concepts no diff can reach, so set `stale_after` on
   anything whose currency depends on a review cycle. `--gate` narrows it to what
   the current branch owes (concepts it made STALE and has not updated) — the check
   a repo wired by `okf-repo-setup` runs in its Stop hook and CI; a commit line
   `okf: n/a — <reason>` waives that commit's files.

2. **Update the STALE concepts** in place, following the augmentation rules
   above — re-read the changed source, correct the prose/schema, refresh
   `generated.at`, drop a now-invalid `verified`. Don't rewrite untouched
   concepts.
3. **Propagate to the product layer.** `drift.py` only sees concepts
   with a repo-path `resource:`, so product concepts without one are never
   flagged. For each STALE technical concept, follow its backlinks into
   `product/` (or wherever `Feature` / `User Journey` / `Policy` concepts
   live) and check whether the linked product concept still describes
   reality — update it or note the review in `log.md`.
4. **Add concepts for UNCOVERED source** worth capturing (apply the altitude
   test — a new service or model, not every new helper file), and **deprecate
   ORPHANED ones** — prefer `status: deprecated` plus a note over deleting, so
   the links other concepts already carry keep resolving; record the change in
   `log.md` either way.
5. **Record the change** in the bundle-root `log.md` — a dated entry
   (`## YYYY-MM-DD`) naming what was added/updated/deprecated. This is the audit
   trail that makes the next refresh legible.
6. **Regenerate indexes** (workflow step 4) and **validate + graph-check**
   (workflow step 6).

The refresh path is the same skill, not a separate one — same authoring rules,
same scripts. Keeping create and refresh together is what stops the two from
drifting apart.

### Automating refresh across repos

For keeping many repos' bundles fresh, wrap this skill in automation rather than
running it by hand — the skill produces the bundle; a scheduler decides *when*.
Two common shapes:

- **On merge (CI):** a job that, after a merge to the main branch, runs
  `drift.py`; if it reports drift, invokes an agent with this skill to
  refresh the affected concepts and opens a PR with the updated `okf-bundle/`.
  Gate it on the staleness output so clean merges are no-ops.
- **Scheduled sweep:** a periodic (e.g. weekly) agent that loops the target
  repos, runs the staleness check in each, and refreshes where drift is found.

Both are orchestration *around* the skill, not part of it — keep the wiring
(cron, CI workflow, repo list) in your automation config, and let each run
invoke the skill per repo.

## Anti-patterns (what makes a bundle bad)

- **Mirroring the filesystem.** One doc per source file produces a directory
  listing, not knowledge. Concepts are ideas, not files.
- **A single mega-doc.** Defeats progressive disclosure and cross-linking. Split.
- **Fabricated content.** Invented columns, endpoints, or citations destroy
  trust in the whole bundle. Ground every claim or omit it.
- **Prose walls.** Long unstructured paragraphs are hard for agents to retrieve
  from. Prefer tables, lists, code.
- **Frontmatter without a `type`.** It's the one required field and the only one
  the validator errors on. Every concept needs a real, consistent `type`.
- **Hand-maintained indexes.** They drift. Always regenerate with the script.
- **A disconnected bag of concepts.** Conformant but unlinked is still useless —
  orphans and islands mean the reader can't navigate. Run the graph check and
  add the cross-links the prose implies.
- **No entry point.** A bundle whose root is only an `index.md` file listing
  makes readers guess where to start. Give it an orientation concept.
- **Two parallel bundles (product vs technical).** Splitting the layers into
  separate bundles breaks cross-links and leaves drift between them
  undetectable. Separate by directory inside one bundle; connect by links.
- **Forged trust.** Writing `verified` — especially with a `human:<id>` actor —
  for content no person actually reviewed, or carrying an old `verified` across
  a rewrite. Consumers derive their whole trust model from that one prefix, so a
  fabricated entry is worse than no entry. Same for `generated.by`: your own
  output is `claude-code/<model>`, never `human:`.
