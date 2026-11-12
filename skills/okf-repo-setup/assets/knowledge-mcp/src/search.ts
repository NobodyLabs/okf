import type { Concept } from './bundle.js';
import { PROJECT } from './project.js';

export interface SearchHit {
  id: string;
  title: string;
  description: string;
  type: string;
  updatedAt: string;
  score: number;
}

/**
 * Question words and generic verbs carry no signal but appear in nearly every
 * concept, so without this a question is dominated by whichever page is longest.
 */
const STOPWORDS = new Set([
  'как', 'что', 'чем', 'кто', 'где', 'куда', 'зачем', 'почему', 'какие', 'какой', 'какая', 'каком',
  'это', 'этот', 'эта', 'все', 'всё', 'весь', 'для', 'при', 'если', 'или', 'его', 'ему', 'она', 'они',
  'нас', 'вас', 'мне', 'там', 'тот', 'так', 'уже', 'ещё', 'еще', 'над', 'под', 'без', 'про', 'из-за',
  'есть', 'быть', 'был', 'была', 'было', 'были', 'будет', 'будут', 'может', 'можно', 'нужно', 'должен',
  'работает', 'устроен', 'устроена', 'устроено', 'устроены', 'происходит', 'выглядит',
  'рассчитывается', 'считается', 'получает', 'делает', 'даёт', 'дает', 'нашем', 'наш',
]);

/**
 * Crude Russian stemming: drop the last two characters of longer words so that
 * "монеты" matches "монета"/"монетам". Good enough for a few-hundred-concept corpus
 * and has no dependencies; a real stemmer would be overkill here.
 */
function stem(token: string): string {
  if (token.length > 5) return token.slice(0, -2);
  // Short nouns inflect in their last letter only ("лиге" → "лиг", "день" → "ден").
  if (token.length >= 4) return token.slice(0, -1);
  return token;
}

/**
 * Bridges the gap between how a customer asks and how the knowledge base is
 * written (project-specific, see `PROJECT.synonyms`). Keyed by token prefix;
 * the expansions are scored at a reduced weight so a synonym can never outrank
 * a literal match.
 */
const SYNONYMS = PROJECT.synonyms;

interface QueryTerm {
  term: string;
  /** Literal query words score fully; synonym expansions score at half. */
  weight: number;
  /** Only literal words count toward "how much of the question this covers". */
  primary: boolean;
}

function buildQuery(text: string): QueryTerm[] {
  const words = text
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter((t) => t.length >= 3 && !STOPWORDS.has(t));

  const terms: QueryTerm[] = words.map((w) => ({ term: stem(w), weight: 1, primary: true }));
  const seen = new Set(terms.map((t) => t.term));

  for (const word of words) {
    for (const [prefix, expansions] of SYNONYMS) {
      if (!word.startsWith(prefix)) continue;
      for (const expansion of expansions) {
        if (seen.has(expansion)) continue;
        seen.add(expansion);
        terms.push({ term: expansion, weight: 0.5, primary: false });
      }
    }
  }
  return terms;
}

/** Count how many times `needle` occurs in `haystack` (both already lowercased). */
function occurrences(haystack: string, needle: string): number {
  let count = 0;
  let from = 0;
  for (;;) {
    const at = haystack.indexOf(needle, from);
    if (at === -1) return count;
    count += 1;
    from = at + needle.length;
  }
}

function headingsOf(body: string): string {
  return body
    .split('\n')
    .filter((l) => /^#{1,6}\s/.test(l))
    .join(' ')
    .toLowerCase();
}

interface IndexedConcept {
  concept: Concept;
  title: string;
  description: string;
  tags: string;
  headings: string;
  body: string;
  haystack: string;
}

function indexConcepts(concepts: Concept[]): IndexedConcept[] {
  return concepts.map((concept) => {
    const title = concept.title.toLowerCase();
    const description = concept.description.toLowerCase();
    const tags = concept.tags.join(' ').toLowerCase();
    const body = concept.body.toLowerCase();
    return {
      concept,
      title,
      description,
      tags,
      headings: headingsOf(concept.body),
      body,
      haystack: `${title} ${tags} ${description} ${body}`,
    };
  });
}

/**
 * Rank concepts against a natural-language question.
 *
 * Two things do the work. **Field weighting**: what a concept is *about* (title,
 * tags, description) counts far more than what it merely mentions, so the
 * longest page does not win every question. **IDF**: a term is worth its
 * rarity — a word every concept uses must not outweigh one that only a single
 * concept is actually about.
 */
export function search(concepts: Concept[], query: string, limit: number): SearchHit[] {
  const terms = buildQuery(query);
  if (terms.length === 0) return [];

  const docs = indexConcepts(concepts);
  const idf = new Map<string, number>();
  for (const { term } of terms) {
    if (idf.has(term)) continue;
    const df = docs.reduce((n, d) => n + (d.haystack.includes(term) ? 1 : 0), 0);
    // Floored rather than allowed to go negative: a ubiquitous term still counts
    // for a little, it just cannot decide the ranking.
    idf.set(term, Math.max(Math.log(docs.length / (1 + df)), 0.05));
  }

  const hits: SearchHit[] = [];
  for (const doc of docs) {
    let score = 0;
    let matched = 0;
    for (const { term, weight, primary } of terms) {
      let termScore = 0;
      if (doc.title.includes(term)) termScore += 12;
      if (doc.tags.includes(term)) termScore += 8;
      if (doc.description.includes(term)) termScore += 5;
      if (doc.headings.includes(term)) termScore += 2;
      termScore += Math.min(occurrences(doc.body, term), 3);
      if (termScore > 0 && primary) matched += 1;
      score += termScore * weight * idf.get(term)!;
    }
    // Mild bonus for covering more of the question, not a multiplier — IDF
    // already decides which words matter.
    if (score > 0) {
      const coverage = 1 + matched / terms.length;
      hits.push({ ...toHit(doc.concept), score: Math.round(score * coverage * 10) / 10 });
    }
  }

  return hits.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id)).slice(0, limit);
}

function toHit(concept: Concept): Omit<SearchHit, 'score'> {
  return {
    id: concept.id,
    title: concept.title,
    description: concept.description,
    type: concept.type,
    updatedAt: concept.updatedAt,
  };
}
