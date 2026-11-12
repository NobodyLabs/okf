# Domain adapters — how to enumerate concepts for common project kinds

OKF is domain-agnostic. The hard part of producing a good bundle is **deciding
what the concepts are** and **at what altitude**. This file gives a starting
inventory per project kind. Adapt, don't follow mechanically — the goal is a
bundle a newcomer (human or agent) could use to *understand the project*, not a
1:1 mirror of the filesystem.

Universal principle: **one concept = one thing worth understanding on its own.**
A doc per meaningful unit, not per file. Group related concepts into
subdirectories. When unsure whether something deserves its own doc, ask: "would
someone search for this by name?" If yes, it's a concept; if no, it's a section
inside another concept.

---

## Codebase / software repository

Discover the shape first: read the README, `package.json`/`pyproject.toml`/
`go.mod`, the directory tree, entrypoints, and CI config. Then enumerate:

- **Architecture** (`type: Architecture`) — one root concept: the components,
  how they fit, the request/data flow. Links to every major component.
- **Services / components** (`type: Service` / `Module`) — one per deployable or
  logically-cohesive unit. Body: responsibility, entrypoint, key dependencies
  (link them), configuration.
- **API endpoints** (`type: API Endpoint`) — one per route or a grouped doc per
  resource. Body: `# Interface` (method, path, params, auth), `# Examples`
  (request/response), links to the data models it returns.
- **Data models** (`type: Data Model`) — domain entities / DB tables / core
  types. Body: `# Schema` (fields + types + meaning), relationships as links.
- **Workflows / jobs** (`type: Workflow` / `Job`) — background jobs, pipelines,
  cron tasks. Body: trigger, steps, side effects.
- **Configuration** (`type: Config`) — env vars, settings, feature flags the
  operator must set. Body: a table of key → meaning → default → required?. Pull
  from `.env.example`, config schemas, settings modules — not guessed.
- **Build, deploy & infrastructure** (`type: Guide` / `Runbook` / `Reference`)
  — how the project is built, containerized, and shipped. One concept for the
  build/packaging path (Dockerfile, build scripts) and one for
  deploy/infrastructure (CI/CD workflow, k8s manifests, Terraform/IaC,
  `docker-compose`). Body: the pipeline stages, environments, and where each
  artifact lands. Ground it in the actual workflow/manifest files.
- **Tech stack & dependencies** (`type: Reference`) — the languages,
  frameworks, datastores, and major third-party services the system leans on,
  and what each is used for. Pull from manifests (`package.json`,
  `pyproject.toml`, `go.mod`, `composer.json`) and lockfiles; don't list every
  transitive dep — capture the load-bearing ones.
- **Key decisions** (`type: ADR`) — non-obvious architectural choices and *why*
  (only if evident from docs/comments/commit history — don't fabricate).

`resource` for code concepts = the repo path or permalink (e.g.
`src/payments/service.py`). Cite files and docs you actually read.

Sections that work well: `# Responsibility`, `# Interface`, `# Schema`,
`# Dependencies`, `# Configuration`, `# Examples`.

**Diagrams (where the source supports them).** Technical docs read better with a
few small, focused diagrams — embed them as fenced ` ```mermaid ` blocks (they
render in GitHub, most markdown viewers, and coding agents). The high-value
placements:

- `architecture.md` → a `flowchart`/`graph` (or C4-style) of components and how
  requests/data flow between them.
- A `Workflow` / auth / request-handling concept → a `sequenceDiagram` of the
  key interaction across services.
- A cluster of related `Data Model` concepts → an `erDiagram` of entities and
  their relationships.
- A deploy/infrastructure concept → a `flowchart` of the CI/CD pipeline or
  runtime topology.

Derive every box and arrow from source you actually read — the no-fabrication
rule covers diagrams. One small diagram per flow beats one sprawling
whole-system picture; add a diagram only where it clarifies more than a table
would.

**Technical-completeness checklist.** Before declaring a codebase bundle done,
confirm you deliberately considered each layer (and skipped only those the
project genuinely lacks): architecture · components/services · data models ·
APIs/interfaces · configuration · build/deploy/infrastructure · tech
stack/dependencies · testing · observability · security/non-functional ·
decisions (ADR). The cross-cutting layer table below covers testing,
observability, security, onboarding, and conventions in detail.

---

## Data platform / catalog

Closest to the reference agent's original use case, minus the BigQuery lock-in.

- **Datasets** (`type: Dataset`) — logical grouping of tables. Links to member
  tables.
- **Tables / views** (`type: Table` / `View`) — one per table. Body: prose
  stating the **grain** (one row per X), time range, caveats; `# Schema` (flatten
  nested records, indent sub-fields); `# Common query patterns` (1–3 fenced SQL
  snippets); links to joined tables.
- **Metrics** (`type: Metric`, under `references/metrics/`) — one per metric.
  Body: one-line definition + the **concrete SQL expression** (not a paraphrase).
  Tables that use it link to it from a `# Metrics` section.
- **Joins** (`type: Reference`, under `references/joins/`) — one per table pair
  (names sorted, joined by `__`). Body: the concrete `ON` clause + when to use.
- **Enums / conventions** (`type: Reference`) — status codes, type IDs, units,
  timezone conventions cited by multiple tables.

`resource` = the table/dataset URI. Never invent columns, partitions, or join
paths — capture only what schema metadata or documentation actually states.

---

## API / service (external-facing)

- **Overview** (`type: Overview`) — one orientation concept: base URL, auth
  model, versioning, rate limits.
- **Endpoints** (`type: API Endpoint`) — one per operation. Body: `# Interface`
  (method, path, path/query/body params with types), `# Examples` (curl +
  sample response), errors, links to the resource schemas involved.
- **Resource schemas** (`type: Data Model`) — the objects the API exchanges.
- **Auth / errors / webhooks** (`type: Reference`) — cited by many endpoints.

`resource` = the endpoint URL or OpenAPI path.

---

## Product / operations / business knowledge

Often has no code at all — pure organizational knowledge.

- **Features** (`type: Feature`) — one per product capability. Body: what it
  does, who uses it, links to the journeys and services behind it.
- **User journeys** (`type: User Journey`) — end-to-end flows a user takes.
- **Business processes** (`type: Business Process`) — internal workflows, with
  steps and owners.
- **Playbooks / runbooks** (`type: Playbook` / `Runbook`) — operational
  procedures. Body: `# Trigger`, `# Steps`, links to the systems involved.
- **Policies / SLAs** (`type: Policy` / `SLA`).
- **Glossary** (`type: Glossary Term`, under `glossary/`) — one per term other
  docs reference by name.

Purely organizational concepts have no `resource` (they're abstract) — that's
expected and fine. But when a feature or process *is* implemented by specific
code (routes, handlers, jobs), set `resource` to that repo path: it's what lets
`drift.py` flag the concept when the implementation changes. Product
concepts without a `resource` are invisible to the staleness check — keep them
linked from the technical concepts that realize them, so a refresh reaches them
via backlinks.

---

## Existing body of documentation (docs → OKF)

When the input is already prose docs (a wiki, `/docs`, a Notion export):

1. Don't copy pages 1:1. Identify the **concepts** the docs describe and make
   one OKF doc per concept, pulling the relevant prose from possibly several
   pages.
2. Split multi-topic pages; merge fragmentary ones.
3. Turn "see also" references into markdown cross-links.
4. Record the source page URLs as `sources` entries in frontmatter, and footnote
   individual claims by `sources[].id`.
5. Skip pure navigation/marketing/changelog pages — they're not concepts.

---

## The operational / onboarding / rationale layer (cross-cutting)

The per-domain inventories above lean structural (what the system *is*) and,
for the product section, functional (what it *does*). A bundle that stops there
serves an agent doing a lookup, but leaves gaps for a human onboarding, an
operator on call, or an architect asking "why". These concept kinds cut across
every domain — **capture them when the source actually contains the material,
and skip them (don't invent stubs) when it doesn't.** An empty
`getting-started` doc is the noise OKF is trying to avoid; a real one that walks
a newcomer through setup is high-value.

| Kind | `type` | Capture when the source has… |
|------|--------|------------------------------|
| **Onboarding / getting started** | `Guide` | a real setup path — install, env, run locally, first task. Pull from README, `docker-compose`, `.env.example`, Makefile. |
| **Testing** | `Guide` / `Reference` | how tests are structured and run (test dirs, `pytest`/`phpunit`/CI config). |
| **Runbooks / troubleshooting** | `Runbook` | operational procedures, common failures and fixes, on-call steps. |
| **Observability** | `Reference` | where logs/metrics/traces/alerts live and what to watch (logging config, dashboards, alert rules). |
| **Decisions / rationale** | `ADR` | the *why* behind a non-obvious choice — but only when it's evident from docs, comments, or commit history. Never fabricate rationale. |
| **Glossary** | `Glossary Term` | domain terms other concepts lean on by name (one term per doc, under `reference/glossary/`). |
| **Conventions / contribution** | `Guide` / `Reference` | how to add code, style rules, PR/branch process (CONTRIBUTING, lint config, `.editorconfig`). |
| **Non-functional / constraints** | `Policy` / `Reference` | security posture, rate limits, SLAs, compliance boundaries. |
| **Known findings** | `Reference` | what an audit or an incident already found and must not come back: each finding with the route / env / identifier it touches and a citation to the audit or write-up line. Only when such a source exists in the repo — never invent findings. |

### Serving multiple audiences without a second tree

Different readers want different slices of the *same* concepts — an agent wants
references and schemas, a new engineer wants onboarding + architecture +
glossary, an operator wants runbooks + observability. Don't fork the directory
tree or duplicate content to serve them. Use the tools the format already gives:

- **Audience via `tags`.** Add cross-cutting labels to frontmatter —
  `tags: [onboarding]`, `tags: [oncall]`, `tags: [product]` — so any consumer
  (search, a filter, an agent) can pull one audience's slice. This reuses the
  existing `tags` field; it is not a new required key.
- **`guides/` reading paths — only when a bundle earns them.** For a large,
  genuinely multi-audience bundle, a thin `guides/<audience>.md` concept
  (`type: Guide`) can curate a *reading order* — links to existing concepts with
  a line of context each, e.g. "Onboarding: [overview](../overview.md) →
  [local setup](...) → [glossary](...) → [wallet-auth journey](...)". Keep it to
  links plus context; never copy concept content into it, or it drifts and
  becomes stale. For small bundles this is overkill — skip it.
