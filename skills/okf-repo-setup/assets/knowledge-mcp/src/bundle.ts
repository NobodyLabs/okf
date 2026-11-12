import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, posix, relative } from 'node:path';
import { parse as parseYaml } from 'yaml';

/** One OKF concept file, parsed into frontmatter metadata + raw markdown body. */
export interface Concept {
  /** Bundle-relative path without the .md suffix, e.g. `product/streak-lives-freeze`. */
  id: string;
  /** Directory the concept lives in (`product`, `product/journeys`, `''` for root). */
  category: string;
  /** OKF `type:` — Feature, Policy, User Journey, Business Process, … */
  type: string;
  title: string;
  description: string;
  tags: string[];
  /** `generated.at` — the date this concept was last verified against the code. */
  updatedAt: string;
  /** OKF `status:` when present (e.g. `deprecated`). */
  status?: string;
  /** Markdown body with the frontmatter block stripped. */
  body: string;
}

/** Files that are navigation or bookkeeping rather than knowledge. */
const NON_CONCEPT_FILES = new Set(['index.md', 'log.md']);

const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/;

/** Recursively collect every concept-bearing .md file under `dir`. */
function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir).sort()) {
    if (entry.startsWith('.')) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, out);
    } else if (entry.endsWith('.md') && !NON_CONCEPT_FILES.has(entry)) {
      out.push(full);
    }
  }
  return out;
}

/** Coerce a frontmatter value that may be a string, array, or absent into string[]. */
function toTags(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((v) => String(v));
  if (typeof value === 'string') return value.split(',').map((s) => s.trim()).filter(Boolean);
  return [];
}

function parseConcept(root: string, file: string): Concept {
  const raw = readFileSync(file, 'utf8');
  const match = FRONTMATTER.exec(raw);
  if (!match) throw new Error('no YAML frontmatter block');

  let meta: Record<string, unknown>;
  try {
    meta = (parseYaml(match[1]) ?? {}) as Record<string, unknown>;
  } catch (err) {
    // Never swallow this: a concept that fails to parse would silently vanish
    // from the knowledge base, and the agent would confidently answer "нет
    // такой информации" about a documented feature.
    throw new Error(`invalid YAML frontmatter — ${String(err).split('\n')[0]}`);
  }

  const id = relative(root, file).split(/[\\/]/).join(posix.sep).replace(/\.md$/, '');
  const generated = meta.generated as { at?: unknown } | undefined;

  return {
    id,
    category: id.includes('/') ? id.slice(0, id.lastIndexOf('/')) : '',
    type: String(meta.type ?? 'Concept'),
    title: String(meta.title ?? id),
    description: String(meta.description ?? ''),
    tags: toTags(meta.tags),
    updatedAt: generated?.at ? String(generated.at).slice(0, 10) : 'unknown',
    status: meta.status ? String(meta.status) : undefined,
    body: raw.slice(match[0].length),
  };
}

/**
 * Load the whole bundle into memory once at startup. The bundle ships inside the
 * image and never changes at runtime, so there is no cache invalidation to do —
 * a new bundle means a new image.
 */
export function loadBundle(root: string): Concept[] {
  const concepts: Concept[] = [];
  const broken: string[] = [];

  for (const file of walk(root)) {
    try {
      concepts.push(parseConcept(root, file));
    } catch (err) {
      broken.push(`  - ${relative(root, file)}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  // Refuse to serve a partial bundle — better a failed deploy than a server that
  // quietly answers from 120 of 142 concepts.
  if (broken.length > 0) {
    throw new Error(`${broken.length} unparseable concept(s) in ${root}:\n${broken.join('\n')}`);
  }
  if (concepts.length === 0) {
    throw new Error(`No OKF concepts found under ${root} — is KNOWLEDGE_BUNDLE_DIR correct?`);
  }
  return concepts;
}
