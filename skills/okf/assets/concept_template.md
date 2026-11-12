---
type: <Concept type, e.g. Service, API Endpoint, Data Model, Metric, Playbook, Reference, Attested Computation>
title: <Human-readable display name>
description: <One sentence — reused verbatim in index.md, so keep it tight>
resource: <Canonical URI of the underlying asset — omit for purely abstract concepts>
tags: [<tag>, <tag>]
generated: { by: <actor — e.g. claude-code/opus-5; use human:<id> only if a person wrote it>, at: <ISO 8601, e.g. 2026-08-07T00:00:00Z> }
sources:
  - id: <stable key — footnotes in the body join to this>
    resource: <URL or repo path you actually read>
    title: <Human-readable label for the source>
# Optional lifecycle/trust keys — add only when they carry real information:
# status: draft            # draft | stable | deprecated; absent means stable
# stale_after: 2026-12-31  # absolute date; the concept is stale on/after this day
# verified:                # only when someone/something actually confirmed the content
#   - { by: human:<id>, at: <ISO 8601> }
---

<One to three paragraphs: what this concept is, what it represents, and how it
is typically used. Weave in cross-links to related concepts as prose flows —
e.g. it belongs to the [payments service](../services/payments.md).>

# <Conventional section — choose what fits the type>

<Favor structural markdown (tables, lists, fenced code) over long prose; it
aids both human reading and agent retrieval. Common section headings:
`# Schema`, `# Interface`, `# Examples`, `# Configuration`, `# Dependencies`,
`# Metrics`, `# Runbook`, `# Computation` (Attested Computation only). Use only
the ones that apply.>

<To attribute one specific claim to one specific source, use a markdown
footnote whose label is a `sources[].id`. The label is the join key — consumers
resolve attribution through the matching frontmatter entry, not by reading the
footnote prose. Do not add a `# Citations` section; that was v0.1.>

The retry budget is three attempts with exponential backoff.[^<stable-key>]

[^<stable-key>]: <short label of the source, matching its `title`>
