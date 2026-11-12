# Frontmatter field guide + `type` vocabulary

## Fields

### Core

| Field         | Required | Notes |
|---------------|----------|-------|
| `type`        | **yes**  | Short, descriptive kind of concept. Drives routing/filtering/presentation. Reuse the same spelling across the bundle. |
| `title`       | rec.     | Human display name. If omitted, consumers derive it from the filename — so a good filename matters. |
| `description` | rec.     | **Exactly one sentence.** Reused verbatim in `index.md`, search snippets, previews. Make it say what the concept *is*, not "This document describes…". |
| `resource`    | rec.*    | Canonical URI of the underlying asset (repo path, API URL, dashboard, table URI). *Omit for purely abstract concepts (a metric definition, a business process).* |
| `tags`        | opt.     | YAML list of short cross-cutting labels for search/filter. Infer from content. |

### Provenance

| Field | Required | Notes |
|-------|----------|-------|
| `sources` | opt. | List of materials the concept derives from. |
| `sources[].resource` | **yes, within an entry** | A concrete artifact (URL, bundle-relative path) **or** a scope descriptor a consumer cannot follow (`all queries in project X`). |
| `sources[].id` | rec. | Stable key. Body footnotes (`[^id]`) join to it — required in practice whenever a claim is attributed. |
| `sources[].title` | opt. | Human-readable label. |
| `sources[].author` | opt. | Who produced the source, in the actor convention below. An authority signal. |
| `sources[].usage_count` | opt. | How often the source was exercised over `usage_window`. Read as liveness/trend, **not** as a score. |
| `sources[].last_modified` | opt. | `YYYY-MM-DD`, when the *source* last changed — distinct from `generated.at`, when the *concept* was written. |
| `usage_window` | opt. | `{ from, to }` date range framing every `usage_count`. A **sibling of `sources`**, not nested inside it. |

### Trust

| Field | Required | Notes |
|-------|----------|-------|
| `generated` | rec. | `{ by, at }` — how the current content was produced. |
| `generated.by` | **yes, within `generated`** | An actor (see below). |
| `generated.at` | rec. | ISO 8601 datetime of the last meaningful content change. |
| `verified` | opt. | **List** of `{ by, at }` confirmation events. A single verifier may be written as one bare mapping; consumers must read it as a one-element list. |

Trust tiers are *derived* from `verified`, never stored: no `verified` ⇒
unverified; non-`human:` verifiers only ⇒ machine-confirmed; a `human:<id>`
verifier ⇒ human-reviewed.

### Lifecycle

| Field | Required | Notes |
|-------|----------|-------|
| `status` | opt. | Enum: `draft` \| `stable` \| `deprecated`. **Absent means `stable`** — don't write it just to say "stable". Prefer `deprecated` over deleting a concept others link to. |
| `stale_after` | opt. | Absolute `YYYY-MM-DD`; stale when `today >= stale_after`. Not a relative TTL. The only freshness signal that works for concepts with no `resource` to diff against. |

### Actor convention

Every identity field (`generated.by`, `verified[].by`, `sources[].author`) uses
one form:

| Form | Use for | Example |
|------|---------|---------|
| `<producer>/<version>` | agents and tools | `claude-code/opus-5` |
| `human:<id>` | a person | `human:kliu@acme` |
| `process:<id>` | an automated process | `process:finance-nightly` |

Consumers key trust off the `human:` prefix, so it **MUST** be used for
hand-authored or human-confirmed content — and **must not** be used for
anything else. Writing `human:` on content a person never reviewed forges the
one signal the format's trust model rests on.

### Everything else

Producers MAY add any extra keys (`owner`, `sensitivity`, `version`, …).
Consumers preserve unknown keys and **must not** reject on them — so extend
freely when a field is worth querying or filtering on. Note that `status` is no
longer such a key: v0.2 specifies it with the enum above.

`type: Attested Computation` additionally carries `runtime` (required),
`parameters`, `computation`, `executor`, and `attester` — see
`attested-computation.md`.

**Legacy:** v0.1's `timestamp` is superseded by `generated.at`, and its body
`# Citations` list by `sources`. Don't write either in new documents; leave them
alone where they already exist.

### Writing a good `description`

It lands in every index and preview, so it is the highest-leverage sentence in
the doc. Say the grain and the essence.

- Weak: `This is the users table.`
- Strong: `One row per registered user, keyed by user_id, updated nightly.`
- Weak: `Documentation for the auth service.`
- Strong: `Issues and validates JWT session tokens for all first-party clients.`

## Choosing `type` values

`type` is free-form but should be consistent and self-explanatory. Pick a small
controlled set per bundle and reuse it. Good general-purpose values by domain
(mix and match — a bundle can span several):

**Software / codebase**
`Service`, `Library`, `Module`, `API Endpoint`, `CLI Command`, `Data Model`,
`Interface`, `Config`, `Job`, `Workflow`, `Architecture`, `ADR` (decision record).

**Data / catalog**
`Dataset`, `Table`, `View`, `Column Reference`, `Pipeline`, `Metric`,
`Dimension`, `Schema`.

**Product / operations**
`Feature`, `User Journey`, `Business Process`, `Policy`, `Playbook`, `Runbook`,
`SLA`, `Glossary Term`, `Persona`.

**Operational / onboarding / rationale** (cross-cutting — capture when the
source has the material, don't invent stubs)
`Guide` (onboarding, testing, conventions, or a `guides/` reading-path),
`Runbook` (operational procedure / troubleshooting), `ADR` (a decision + its
rationale), `Glossary Term`, `Policy`. See `domains.md`.

**Cross-cutting**
`Attested Computation` — the one type with normative behavior attached: it
requires `runtime` and carries a sanctioned way to compute a value. Reach for it
on data platforms and metric definitions, not in an ordinary codebase bundle
(see `attested-computation.md`).
`Reference` — a standalone doc that other concepts cite by name (an enum, a
status-code table, a units/timezone convention, a metric definition). `Overview`
— reserve for a single bundle-level orientation concept if you want one; don't
sprinkle `Overview`/`Getting Started` docs everywhere (that's noise, not
knowledge).

Rule of thumb: if you're inventing a new `type` for a single document, check
whether an existing value fits first. Fewer, well-populated types make the graph
and index views legible.
