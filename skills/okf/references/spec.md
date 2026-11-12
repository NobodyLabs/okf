# OKF v0.2 — condensed spec (authoring cheatsheet)

The Open Knowledge Format is a directory of markdown files with YAML
frontmatter. No schema registry, no required tooling: if you can `cat` a file
you can read it; if you can `git clone` a repo you can ship it. This file is
the working subset needed to *author* a conformant bundle, and the source of
truth for this skill: the full normative spec does not ship with the plugin.
Where this file is silent, follow the validator (`scripts/validate_bundle.py`).

## Vocabulary

- **Bundle** — the directory tree; the unit of distribution.
- **Concept** — one unit of knowledge = one markdown document. May describe a
  tangible asset (a table, an API, a service) or an abstract idea (a metric, a
  business process).
- **Concept ID** — the file path within the bundle minus `.md`. `tables/users.md`
  → `tables/users`.
- **Link** — a normal markdown link from one concept to another (a relationship).
- **Source** — material a concept derives from, recorded in `sources`.
- **Provenance** — where the content came from (`sources`, §5.1 below).
- **Actor** — an identity string for who produced or confirmed content (§7).
- **Trust tier** — unverified / machine-confirmed / human-reviewed, *derived*
  from `verified`, never stored.
- **Attested Computation** — a concept that carries a sanctioned way to compute
  a value. See `attested-computation.md`.

## Bundle layout

```
bundle/
├── index.md            # optional; directory listing (progressive disclosure)
├── log.md              # optional; chronological update history
├── <concept>.md        # a root-level concept
└── <group>/            # subdirectories organize concepts by kind
    ├── index.md
    ├── <concept>.md
    └── <subgroup>/ …
```

The directory structure is **producer's choice** — organize by whatever makes
the knowledge navigable. Depth of 2–3 levels is typical.

### Reserved filenames (never use for concepts)

| File       | Purpose                        |
|------------|--------------------------------|
| `index.md` | Directory listing (§ Index)    |
| `log.md`   | Update history (§ Log)         |

Every other `.md` is a concept document.

## Concept document = frontmatter + body

```markdown
---
type: BigQuery Table            # REQUIRED — the only mandatory field
title: Customer Orders          # recommended
description: One row per completed order across all channels.   # recommended, ONE sentence
resource: https://…/orders      # recommended when a real asset exists
tags: [sales, orders, revenue]  # optional
generated: { by: claude-code/opus-5, at: 2026-08-07T14:30:00Z }  # who wrote this content
verified:                       # optional; who confirmed it
  - { by: human:kliu, at: 2026-08-08T16:00:00Z }
status: stable                  # optional; draft | stable | deprecated
stale_after: 2026-12-31         # optional; stale on/after this date
sources:                        # optional; provenance
  - id: warehouse-schema
    resource: https://wiki.internal/data/schemas/sales
    title: Warehouse schema — sales dataset
# … any producer-defined keys are allowed
---

Prose intro (1–3 short paragraphs).

# Schema
| Column | Type | Description |
| … |

Orders settle on a 30-day window.[^warehouse-schema]

[^warehouse-schema]: Warehouse schema — sales dataset
```

- `type` is the **only** required field. It routes/filters/presents the concept
  (`Service`, `API Endpoint`, `Metric`, `Playbook`, `Reference`, …). Not
  registered centrally; pick descriptive, self-explanatory values and reuse
  them consistently within a bundle.
- Favor **structural** markdown (headings, tables, lists, fenced code) over
  freeform prose — structure aids both human reading and agent retrieval.
- Conventional body headings (use when applicable): `# Schema`, `# Examples`,
  `# Computation`. Anything else is fine too.
- Producers MAY add any extra keys. Consumers **MUST NOT** reject a document
  for unrecognized fields, and should preserve them when round-tripping.

## Provenance: `sources` and per-claim attribution

Provenance lives in frontmatter, not in a body list. Each `sources` entry:

| Key | Required | Notes |
|-----|----------|-------|
| `resource` | **yes, within the entry** | A concrete artifact (URL, bundle-relative path) **or** a scope descriptor a consumer cannot follow (`all queries in project X`). |
| `id` | recommended | Stable key. Required in practice whenever the body attributes a claim to this source. |
| `title` | optional | Human-readable label. |
| `author` | optional | Who produced the source, in the actor convention (§ Actors). |
| `usage_count` | optional | How often the source was exercised over `usage_window`. A liveness signal, not a score. |
| `last_modified` | optional | `YYYY-MM-DD` — when the *source* last changed (distinct from `generated.at`, when the *concept* was written). |

`usage_window: { from: <date>, to: <date> }` is written **once as a sibling of
`sources`**, framing every `usage_count`. A single entry may override it.

**Per-claim attribution** uses a markdown footnote whose label is a
`sources[].id`:

```markdown
The `events_` table is sharded daily as `events_YYYYMMDD`.[^ga4-schema]

[^ga4-schema]: GA4 BigQuery Export schema
```

The label is the join key — consumers resolve attribution through the matching
`sources` entry, not by parsing the footnote prose. Labels are keyed rather
than positional because agents constantly rewrite these documents: a positional
index misattributes silently the moment the list is reordered.

**Cite only sources you actually consulted — never invent URLs.** This rule did
not change; only where the citation is stored did.

## Trust: `generated` and `verified`

`generated` records how the current content was produced; `verified` records
who confirmed it. They are separate because whoever *wrote* a concept need not
be whoever *checked* it.

- `generated.by` — REQUIRED within `generated`. An actor.
- `generated.at` — ISO 8601 datetime of the content's last meaningful change.
- `verified` — a **list** of `{ by, at }` verification events. A single
  verifier MAY be written as one bare mapping; consumers MUST read a bare
  mapping as a one-element list.

Content can change without re-confirmation, and facts can be re-confirmed
without regeneration — so never assume the two move together.

### Actors

Any field recording an identity (`generated.by`, `verified[].by`,
`sources[].author`) uses one convention:

| Form | Use for | Example |
|------|---------|---------|
| `<producer>/<version>` | agents and tools | `claude-code/opus-5` |
| `human:<id>` | a person | `human:kliu@acme` |
| `process:<id>` | an automated process | `process:finance-nightly` |

Consumers classify trust off the `human:` prefix, so producers **MUST** use it
for hand-authored or human-confirmed content — and must not use it for anything
else.

### Trust tiers (derived, never stored)

- No `verified` key ⇒ **unverified**
- `verified` by non-`human:` actors only ⇒ **machine-confirmed**
- `verified` by a `human:<id>` actor ⇒ **human-reviewed**

Tiers are advisory signals, not access control. A concept with no trust
frontmatter is still fully consumable.

## Lifecycle: `status` and `stale_after`

```yaml
status: stable          # draft | stable | deprecated — absent means stable
stale_after: 2026-12-31 # absolute date; stale when today >= this day
```

- `draft` — not yet reviewed, possibly incomplete.
- `stable` — the default; ready for consumption.
- `deprecated` — kept for links and history; no longer current. Prefer this
  over deleting a concept other docs still link to.

`stale_after` is an **absolute date, not a relative TTL**, which keeps staleness
a plain date comparison. It is the one freshness signal that works for concepts
with no `resource` to diff against — set it on anything whose currency depends
on a review cycle rather than on a code change.

## Cross-linking

A link from A to B asserts an (untyped) relationship; the *kind* of
relationship is carried by the surrounding prose, not the link.

**Use file-relative paths** written from the *linking* document's directory —
these render correctly on GitHub and in the reference viewer:

- sibling: `[users](users.md)`
- parent group: `[dataset](../datasets/sales.md)`
- reference: `[event params](../references/event_parameters.md)`

The spec also permits bundle-absolute links (`/tables/users.md`), but relative
paths are what the real bundles and the GitHub/viewer renderers expect — prefer
them. Never leave a link starting with `/` if GitHub rendering matters: the
reference viewer silently drops absolute links from the graph.

Path-valued frontmatter fields (`resource`, `sources[].resource`, `computation`,
`executor.resource`, `attester.resource`) accept an absolute URL, a `/`-rooted
bundle-relative path, or a relative path. When a `sources[].resource` points at
another concept in the bundle, that derivation edge is part of the graph.

Rules of thumb: one link per concept-mention per section (don't over-link); do
not link a doc to itself; do not link from headings, code fences, or schema
field-name rows. Broken links are **tolerated** (they may be not-yet-written
knowledge) — never fail a bundle over them.

## Index files (progressive disclosure)

An `index.md` enumerates a directory's contents so a reader sees what's
available before opening documents. **No frontmatter** (except the bundle-root
index, which may carry `okf_version: "0.2"`). Group by section:

```markdown
# BigQuery Table

* [Orders](orders.md) - One row per completed order.
* [Customers](customers.md) - One row per customer.

# Subdirectories

* [references](references/index.md) - Enum and metric reference docs.
```

Entries should carry the linked concept's one-line `description`. **Generate
these with `scripts/gen_index.py` — don't hand-maintain them.**

## Log files (optional)

`log.md` records changes to its scope, newest first, date-grouped:

```markdown
# Update Log

## 2026-05-22
* **Update**: Added [Customer Metrics](tables/customer-metrics.md).
* **Creation**: Established the [Dataplex Playbook](playbooks/dataplex.md).
```

Date headings MUST be `## YYYY-MM-DD`. The leading bold word is a convention.

## Conformance (what the validator enforces)

A bundle is conformant with OKF v0.2 if:

1. every non-reserved `.md` file has a parseable YAML frontmatter block,
2. every such block has a non-empty `type`, and
3. reserved files (`index.md`, `log.md`) follow their formats when present.

That is the whole floor. Consumers must NOT reject a bundle for missing
optional fields, unknown types, extra keys, broken links, or missing index
files. When the optional families *are* present, consumers must read a bare
`verified` mapping as a one-element list, and must not reject a concept for
missing any optional family.

Author to the recommended shape, but know the hard floor is just `type`.

## Legacy v0.1 documents

v0.2 supersedes v0.1 with two deliberate breaking changes. Older bundles carry
the old shapes, and they remain readable — v0.2 consumers fall back:

| v0.1 | v0.2 | What to do |
|------|------|------------|
| `timestamp: <ISO 8601>` | `generated: { by, at }` | Don't write `timestamp` in new documents. Leave it alone in old ones. |
| body `# Citations` list | frontmatter `sources` + footnotes | Don't write `# Citations` in new documents. Leave it alone in old ones. |

Do **not** mass-migrate an existing bundle just because it is v0.1-shaped: the
old form is conformant-readable, and a rewrite churns git history and discards
hand-curated prose for no consumer benefit. Author new concepts in v0.2 shape,
and let old ones convert naturally if and when their content is next rewritten.
