# Attested Computations (OKF v0.2 §10)

## When this applies — and when it doesn't

An **Attested Computation** concept carries not just what a value *means* but a
sanctioned way to *compute* it, so a consumer can confirm an agent ran the
blessed computation instead of improvising its own.

Reach for it when a number is **governed**: a finance metric with a policy
behind it, a KPI whose definition is contested, a figure someone will act on.
Typical homes are data platforms and semantic layers — BigQuery, dbt, Looker,
a warehouse.

**Skip it entirely for an ordinary codebase bundle.** Documenting services,
endpoints, and models needs none of this; adding `runtime`/`executor`/`attester`
to concepts nobody computes from is pure noise. If you are not sure whether a
bundle needs the type, it doesn't.

Provenance (`sources`) answers *where did this claim come from*; attestation
answers *was this number produced the way we said it must be*. OKF records the
computation and the means to check it — it never executes anything itself.

## A computation is its own concept

A sanctioned computation is a standalone concept of `type: Attested
Computation`. A concept that needs the value (a `Metric`, a table) links to it
with a normal markdown link. Three reasons it isn't just frontmatter on the
metric:

- **`runtime` defines what `parameters` mean.** A parameter is a SQL bind
  variable, a dbt var, or a Python argument depending on the runtime. Keeping
  the two in one frontmatter makes binding semantics self-evident.
- **One computation, many consumers.** The same computation can back a metric, a
  dashboard, and a report — referenced once, reused.
- **Trust state is per computation.** `verified`, `stale_after`, and one
  `attester` describe one thing. Revenue, profit, and margin verify and attest
  independently: three concepts, not three entries in one frontmatter.

So an income-statement overview stays one readable concept and links out to one
Attested Computation per figure. Revenue can be fresh while profit is past its
`stale_after`.

## Contract fields

In addition to the provenance, trust, and lifecycle families every concept may
carry, an Attested Computation carries:

| Field | Required | Notes |
|-------|----------|-------|
| `runtime` | **yes, for this type** | How to run it, and so how `parameters` bind. Values like `bigquery`, `postgres`, `dbt`, `python`, `Looker`. |
| `parameters` | rec. | List of the typed, named holes an agent may fill: `{ name, type, required }`. |
| `computation` | opt. | Path to a file holding the computation, used *instead of* the body fence. Absent ⇒ the `# Computation` fence in the body is the computation. |
| `executor` | rec. | `{ resource, receipt }`. `resource` names run instructions or code; `receipt` declares the fields a run must return as evidence. |
| `attester` | rec. | `{ resource }` naming deterministic, **no-LLM** code that takes a receipt and returns a verdict. Runs consumer-side. |

What sits behind a `resource` — a skill doc, a script, a container — is a
packaging choice. OKF fixes the interface, not the packaging.

## The computation itself

Two ways, pick one:

- **Inline** — a single fenced code block in the body under `# Computation`.
  Best for a short computation reviewed alongside its contract.
- **File** — set `computation` to a path and omit the body fence. Best for a
  long or generated computation, or one already shared with non-OKF tooling.

An agent may supply **values for the declared `parameters` only**. It MUST NOT
author or edit the computation. That typed, parameter-only surface is what makes
"did the sanctioned thing run" a mechanical comparison rather than a judgement
call: the attester re-derives the binding and compares it against the expanded
artifact the receipt carries (`executed_sql`, `compiled_sql`), so a rewritten
query, a swapped computation file, or a mutated dependency all fail the check.

## Worked example

```markdown
---
type: Attested Computation
title: Gross margin for a period
description: Sanctioned SQL producing the gross-margin figure for a period, per the FY2026 Cost Allocation Standard.
tags: [finance, margin, attested]
runtime: bigquery
parameters:
  - { name: period_start, type: date, required: true }
  - { name: period_end, type: date, required: true }
executor:
  resource: skills/run-on-bq.md
  receipt: [job_id, executed_sql, result]
attester:
  resource: attesters/sql_equality.py
generated: { by: claude-code/opus-5, at: 2026-06-30T14:00:00Z }
verified:
  - { by: human:jsmith@acme, at: 2026-07-01T09:00:00Z }
status: stable
stale_after: 2026-12-31
sources:
  - id: margin-standard
    resource: policies/margin-standard.md
    title: Cost Allocation & Margin Standard (FY2026)
---

# Computation

```sql
SELECT SUM(revenue_usd) - SUM(cogs_usd) AS gross_margin_usd
FROM `acme.finance.margin_base`
WHERE order_date BETWEEN @period_start AND @period_end
```

# Notes

Every COGS component is required per the standard.[^margin-standard] A receipt
whose executed SQL drops one will fail attestation, because canonicalized-SQL
equality includes the join graph.

[^margin-standard]: Cost Allocation & Margin Standard (FY2026)
```

## How a consumer uses it (informative)

Runtime artifacts are **not** stored in the bundle:

1. **Discover** via `type: Attested Computation`, directly or by following a
   link from a concept that uses it.
2. **Load** the contract from frontmatter, the computation from the body or the
   `computation` file.
3. **Parameterize** — the agent supplies values for declared parameters.
4. **Execute** — the executor runs the bound computation, returning a receipt
   shaped by `executor.receipt`.
5. **Attest** — the consumer runs the attester over the receipt, confirming
   provenance (the sanctioned computation ran, not agent-authored SQL) and
   fidelity (the displayed value matches the receipt, re-read by job id).
6. **Gate** — refuse to display a failing attestation; warn or refuse when
   `today >= stale_after`. On success, surface the verdict so trust is visible.

## `verified` vs attestation

Both exist and they are not the same thing:

- **`verified`** confirms the *definition* still matches policy. Doc-level,
  slow, recorded in the bundle.
- **Attestation** confirms a single *run* produced the value the sanctioned way.
  Per-call, runtime, never stored in the bundle.

A concept with a stale definition can still attest cleanly, and a freshly
verified definition still requires attestation on every run.
