import { posix } from 'node:path';
import type { Concept } from './bundle.js';
import { ORG } from './org.js';
import { PROJECT } from './project.js';

/** Who is reading — see `project.ts` for what each audience is. */
export type Audience = 'client' | 'partner' | 'internal';

const ALLOW_PREFIXES = PROJECT.partner.allowPrefixes;
const ALLOW_IDS = new Set(PROJECT.partner.allowIds);
const DENY_IDS = new Set(PROJECT.partner.denyIds);
const CLIENT_IDS = new Set(PROJECT.clientIds);

export function isVisible(id: string, audience: Audience): boolean {
  if (audience === 'internal') return true;
  if (DENY_IDS.has(id)) return false;
  const partnerVisible = ALLOW_IDS.has(id) || ALLOW_PREFIXES.some((p) => id.startsWith(p));
  if (audience === 'partner') return partnerVisible;
  // Client visibility is gated by the partner rules too, so it can never
  // exceed them even if `clientIds` is edited carelessly.
  return partnerVisible && CLIENT_IDS.has(id);
}

export function visibleConcepts(concepts: Concept[], audience: Audience): Concept[] {
  return concepts.filter((c) => isVisible(c.id, audience));
}

// ── Redaction ───────────────────────────────────────────────────────────────

/**
 * Sections that exist for our engineers: known divergences between code and the
 * internal docs, unimplemented promises, workarounds. Valuable internally,
 * misleading (and none of their business) for a partner.
 */
const INTERNAL_SECTION = /^(#{1,6})\s*(ограничени|грабл|известные проблем|расхождени|todo|limitations|gotchas|known issues|caveats)/i;

/**
 * Infrastructure identifiers that must never reach an external reader. The
 * replacements are bracketed so they read as a redaction mark rather than as a
 * noun spliced into the sentence — the prose around them was not written with a
 * substitution in mind.
 */
const escapeRe = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Paths into the repo (`lib/foo.ts`) — built from `PROJECT.repoDirs`. */
export const REPO_PATH = new RegExp(`\\b(?:${PROJECT.repoDirs.map(escapeRe).join('|')})\\/[A-Za-z0-9._\\-/]+`, 'g');

/** An image path in a hosted registry (`ghcr.io/acme/app`): names the team's account and its services. */
export const CONTAINER_REGISTRY =
  /\b(?:registry\.digitalocean\.com|ghcr\.io|gcr\.io|quay\.io|registry\.gitlab\.com|[a-z0-9-]+\.pkg\.dev|[a-z0-9.-]+\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com|[a-z0-9-]+\.azurecr\.io)\/[^\s`)]+/gi;

const SENSITIVE: Array<[RegExp, string]> = [
  // Recognisable without knowing the team: where its images live, its bots and chats.
  [CONTAINER_REGISTRY, '[внутренний реестр образов]'],
  [/@[A-Za-z0-9_]{3,}_?[Bb]ot\b/g, '[бот]'],
  [/-100\d{9,}/g, '[внутренний чат]'],
  // What only the team knows (its domain, its clusters), then the project's own.
  ...ORG.sensitive,
  ...PROJECT.sensitive,
  // Repo-relative paths that survived outside frontmatter/footnotes.
  [REPO_PATH, '[внутренний модуль]'],
  [/\bdocs\/[^\s`)]*\.md\b/g, '[внутренний документ]'],
];

/** Drop every heading block the predicate selects, including its sub-headings. */
function dropSections(body: string, isDropped: (heading: string) => boolean): string {
  const lines = body.split('\n');
  const kept: string[] = [];
  let dropUntilLevel: number | null = null;

  for (const line of lines) {
    const heading = /^(#{1,6})\s/.exec(line);
    if (heading) {
      const level = heading[1].length;
      // A heading at the same level or higher ends the dropped block.
      if (dropUntilLevel !== null && level <= dropUntilLevel) dropUntilLevel = null;
      if (isDropped(line)) {
        dropUntilLevel = level;
        continue;
      }
    }
    if (dropUntilLevel === null) kept.push(line);
  }
  return kept.join('\n');
}

function dropInternalSections(body: string): string {
  return dropSections(body, (heading) => INTERNAL_SECTION.test(heading));
}

/** Remove footnote markers and their definitions — both point at source files. */
function stripFootnotes(body: string): string {
  return body
    .split('\n')
    .filter((line) => !/^\s*\[\^[^\]]+\]:/.test(line))
    .join('\n')
    .replace(/\[\^[^\]]+\]/g, '');
}

/**
 * Rewrite cross-links. Links to concepts the reader may open become bare concept
 * ids (which they can pass straight back to `get_product_concept`); links to
 * hidden concepts collapse to their anchor text so no internal path is exposed.
 */
function rewriteLinks(body: string, category: string, audience: Audience): string {
  return body.replace(/\[([^\]]+)\]\(([^)\s]+\.md)(?:#[^)]*)?\)/g, (_m, text: string, href: string) => {
    if (/^[a-z]+:\/\//i.test(href)) return `[${text}](${href})`;
    const target = posix.normalize(posix.join(category, href)).replace(/\.md$/, '');
    if (isVisible(target, audience)) return `[${text}](${target})`;
    // A hidden concept whose anchor text is its own id would still name it: the
    // partner loses the reference, the client gets a redaction mark.
    if (ID_LIKE.test(text)) return audience === 'client' ? CUT : '';
    return text;
  });
}

const ID_LIKE = /^[a-z]+\/[a-z0-9/-]+$/;

/**
 * "Связанные концепты" / "See also" sections are navigation into the bundle,
 * mostly into its engineering half. For an external reader an item that points
 * at a hidden concept is a list of internal module names, so it goes; a section
 * left with nothing goes with its heading.
 */
const RELATED_SECTION = /^(#{1,6})\s*(связанн|см\.? также|смотри также|related|see also)/i;

function dropHiddenRelated(body: string, category: string, audience: Audience): string {
  const linksHidden = (line: string): boolean =>
    [...line.matchAll(/\]\(([^)\s]+\.md)(?:#[^)]*)?\)/g)].some(([, href]) => {
      if (/^[a-z]+:\/\//i.test(href)) return false;
      return !isVisible(posix.normalize(posix.join(category, href)).replace(/\.md$/, ''), audience);
    });
  const out: string[] = [];
  let related: { level: number; heading: number; kept: number } | null = null;
  const close = () => {
    if (related && related.kept === 0) out.splice(related.heading);
    related = null;
  };
  for (const line of body.split('\n')) {
    const heading = /^(#{1,6})\s/.exec(line);
    if (heading && related && heading[1].length <= related.level) close();
    if (heading && RELATED_SECTION.test(line)) {
      close();
      related = { level: heading[1].length, heading: out.length, kept: 0 };
      out.push(line);
      continue;
    }
    if (related && !heading) {
      if (/^\s*(?:[-*]|\d+\.)\s/.test(line) && linksHidden(line)) continue;
      if (line.trim() !== '') related.kept += 1;
    }
    out.push(line);
  }
  close();
  return out.join('\n');
}

function scrubSensitive(body: string): string {
  let out = body;
  for (const [pattern, replacement] of SENSITIVE) out = out.replace(pattern, replacement);
  return out;
}

/** Collapse the blank-line runs and empty parentheses left behind by removals. */
function tidy(body: string): string {
  return body.replace(/[ \t]+\(\s*\)/g, '').replace(/\n{3,}/g, '\n\n').trim();
}

// ── Client-grade redaction ──────────────────────────────────────────────────
//
// The partner reader is a business owner who may see how the product is built
// as long as infrastructure stays hidden. A client must see only *behaviour*:
// no code identifiers, no endpoints, no data model, no engineering sections.
// The partner pipeline leaves all of that in place because stripping it guts
// the reference tables the partner relies on; here the tables are the price.

/** Marks a technical detail that was removed. Bracketed, like the other marks. */
const CUT = '[…]';

/**
 * Headings that introduce implementation rather than behaviour. Anything with a
 * code span or a URL path in the heading is technical by construction.
 */
const TECHNICAL_HEADING = new RegExp(
  String.raw`\x60|\/[a-z]|(?:^|[^\p{L}])(?:api|enum|jwt|initdata|роут|эндпоинт|схем|реализац|хранилищ|транспорт|фоновы[ех]|синхронизац|модел[ьи]|на фронте|админ|состояние|гейт|резолв|интерфейс|как это устроено|зависимост|потребител|тест|конфигурац|сборк|инвариант|где в коде|данные|таблиц|поля|формул|алгоритм|расписани|разработк|чтени|идемпотент${PROJECT.clientHiddenHeadings.map((h) => '|' + escapeRe(h)).join('')})`,
  'iu',
);

function dropTechnicalSections(body: string): string {
  return dropSections(body, (heading) => TECHNICAL_HEADING.test(heading.replace(/^#+\s*/, '')));
}

/** Fenced blocks are code, config or diagrams — never client-facing prose. */
function dropFencedBlocks(body: string): string {
  return body.replace(/^```[^\n]*\n[\s\S]*?^```[^\n]*$/gm, '');
}

const HTTP_ENDPOINT = /\b(?:GET|POST|PUT|PATCH|DELETE)(?:\\?\|(?:GET|POST|PUT|PATCH|DELETE))*\s+\/\S*/g;
/** A URL-ish path with at least two segments, outside code spans. */
const BARE_PATH = /(?<![\w/.:])\/[a-z][\w-]*(?:\/[\w:*.<>-]+)+/g;
/** Words that name our stack rather than the product. Latin with `\b`, Cyrillic via letter lookarounds (`\b` is ASCII-only). */
const TECH_NOUN_LATIN = new RegExp(
  String.raw`@[a-z0-9-]+\/[a-z0-9-]+|\b(?:Prisma|Postgres(?:QL)?|Redis|BullMQ|ChromaDB|Fastify|Vite|Express|localStorage|JWT|initData|srcdoc|iframe|webhook|cron|enum'?ы?|API|SQL|JSON|HTML|CSP|Docker|Kubernetes|k8s|DISTINCT|upsert|FK|NaN|Infinity|testid'?ы?|env|legacy|job|SSE${PROJECT.techNouns.map((n) => '|' + escapeRe(n)).join('')})\b`,
  'g',
);
const TECH_NOUN_CYRILLIC = /(?<!\p{L})(?:БД|бэкенд[а-я]*|роут[а-я]*|дедуп[а-я]*|эндпоинт[а-я]*)(?!\p{L})/gu;
/** HTTP status + error code (`403 DEMO_MODE`) and Prisma error codes (`P2002`). */
const STATUS_CODE = /\b(?:20[014]|4\d\d|5\d\d)\s+[A-Z][A-Z_]+\b|\bP2\d{3}\b/g;
/** Unbackticked camelCase identifiers (`defaultEnabled`). Latin only, so Russian prose is untouched. */
const CAMEL_CASE = /\b[a-z]+(?:[A-Z][a-z0-9]+)+\b/g;
/**
 * Issue and PR references in every form the bundle uses — `(#365)`, `(баги /#232)`,
 * `(#442/#449)`, a bare `#303`.
 */
/** Bare ids of bundle concepts a client cannot open (`data/schema-overview`) — outside markdown links. */
const HIDDEN_CONCEPT_ID = new RegExp(
  String.raw`(?<!\]\()\b(?:${PROJECT.hiddenCategories.map(escapeRe).join('|')})\/[a-z0-9-]+`,
  'g',
);
const ISSUE_REF = /\s*\([^()]*#\d+[^()]*\)|\/?#\d+\b/g;

/**
 * An UPPER_SNAKE code span is kept when it is a *label* the product shows
 * (`DEMO`, `TEST_WEEK`) and cut when it names a constant, an env
 * variable or a collection (`FREEZE_THRESHOLD_HOURS`, `LECTURES_VISIBLE_XL_COURSE_IDS`).
 */
const CONSTANT_SUFFIX =
  /_(?:HOURS|DAYS|MINUTES|MS|LIMITS?|BONUSES|REQUIREMENTS|DEFINITIONS|TIERS|RULES|TYPES|ACCESS|TIMERS|OPTIONS|METRICS|FIELDS|SLOTS|CAP|IDS?|URL|TOKEN|KEY|CONFIG|SETTINGS|ITEMS|REWARDS|FEATURE|PER_DAY|SINCE_LAST|SIZE|ZONES|SCREENS|MILESTONES|MINIMUM|POINTS|TIMEZONE|GOAL|THRESHOLD|INTERVAL|WINDOW|COUNT)$/;
const CONSTANT_PREFIX = new RegExp(`^(?:${['MAX', 'MIN', 'DEFAULT', 'STARTING', 'INITIAL', ...PROJECT.constantPrefixes].map(escapeRe).join('|')})_`);
function isProductLabel(code: string): boolean {
  if (!/^[A-Z][A-Z0-9_]*$/.test(code)) return false;
  if ((code.match(/_/g) ?? []).length > 2) return false;
  return !CONSTANT_SUFFIX.test(code) && !CONSTANT_PREFIX.test(code);
}
/** The same label-vs-constant rule for UPPER_SNAKE words written without backticks. */
const BARE_UPPER_SNAKE = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g;

/**
 * A code span is a technical detail unless it is a bare label the product
 * itself shows (`DEMO`, `TEST_WEEK`) or listed in `PROJECT.keepCodes`. Labels lose their backticks so
 * that "no backtick in the client corpus" holds as an invariant.
 */
function stripCodeSpans(text: string): string {
  return text.replace(/`([^`\n]+)`/g, (_m, code: string) => {
    const trimmed = code.trim();
    if (isProductLabel(trimmed) || PROJECT.keepCodes.includes(trimmed)) return trimmed;
    return CUT;
  });
}

/** Letters left in a line once every code span and redaction mark is gone. */
function proseLength(line: string): number {
  return line.replace(/`[^`]*`/g, '').replace(/\[[^\]]*\]/g, '').replace(/[^\p{L}]/gu, '').length;
}

const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_RULE = /^\s*\|(?:\s*:?-+:?\s*\|)+\s*$/;

const LIST_ITEM = /^\s*(?:[-*]|\d+\.)\s/;
const cutsIn = (text: string): number => (text.match(/\[…\]/g) ?? []).length;

/**
 * Text that has lost most of itself to redaction reads as noise
 * ("[…] в […]: […], […], […]") and tempts the agent to guess what was there.
 *
 * Paragraphs are handled sentence by sentence, because the bundle mixes
 * "how it is implemented" and "what the client sees" inside one paragraph
 * and only the former is cut-dense. Table rows and list items are atomic.
 */
function dropGuttedLines(body: string): string {
  const gutted = (text: string, minProse: number): boolean => {
    const cuts = cutsIn(text);
    if (cuts === 0) return false;
    if (cuts >= 6) return true;
    if (cuts >= 3 && proseLength(text) < minProse) return true;
    return proseLength(text) === 0;
  };

  const lines = body.split('\n');
  return lines
    .map((line, i) => {
      if (/^#{1,6}\s/.test(line) || TABLE_RULE.test(line) || line.trim() === '') return line;
      // A table header stays as long as the table does (`dropEmptyTables` decides).
      if (TABLE_ROW.test(line) && TABLE_RULE.test(lines[i + 1] ?? '')) return line;
      if (TABLE_ROW.test(line)) {
        // A row whose every cell but one is a cut names a topic and says nothing about it.
        const cells = line.trim().slice(1, -1).split('|').map((c) => c.trim()).filter(Boolean);
        if (cells.length >= 2 && cells.filter((c) => c === CUT).length >= cells.length - 1) return null;
      }
      if (TABLE_ROW.test(line)) {
        if (cutsIn(line) >= 1 && proseLength(line) < 20) return null;
        return gutted(line, 120) ? null : line;
      }
      // Paragraphs and list items are handled sentence by sentence; a list item
      // keeps its marker in front of whatever survives.
      const marker = LIST_ITEM.exec(line)?.[0] ?? '';
      const text = line.slice(marker.length);
      const sentences = text.split(/(?<=[.!?;])\s+/).filter((sentence) => {
        const cuts = cutsIn(sentence);
        const prose = proseLength(sentence);
        if (gutted(sentence, 60)) return false;
        if (cuts >= 2 && prose < 40) return false;
        if (cuts >= 1 && prose < 25) return false;
        // An orphan fragment left by an earlier removal: starts mid-sentence.
        if (/^[a-zа-яё]/.test(sentence.trim()) && prose < 30) return false;
        return true;
      });
      if (sentences.length === 0) return null;
      if (marker && proseLength(sentences.join(' ')) < 20) return null;
      return marker + sentences.join(' ');
    })
    .filter((line): line is string => line !== null)
    .join('\n');
}

/**
 * Cleanup after removal: a heading with nothing under it, and an intro line
 * ("Разблокировка идёт по трём каналам:") whose list or table is gone.
 */
function dropEmptySections(body: string): string {
  // Removing an intro can leave its heading empty in turn — iterate to a fixpoint.
  let out = dropEmptySectionsOnce(body);
  for (let i = 0; i < 3; i++) {
    const next = dropEmptySectionsOnce(out);
    if (next === out) break;
    out = next;
  }
  return out;
}

function dropEmptySectionsOnce(body: string): string {
  const lines = body.split('\n');
  const isHeading = (l: string | undefined) => l !== undefined && /^#{1,6}\s/.test(l);
  const out: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    // Next non-blank line after this one.
    let j = i + 1;
    while (j < lines.length && lines[j].trim() === '') j++;
    const next = lines[j];
    if (isHeading(line)) {
      const level = /^(#{1,6})\s/.exec(line)![1].length;
      const nextLevel = isHeading(next) ? /^(#{1,6})\s/.exec(next!)![1].length : 0;
      if (next === undefined || (isHeading(next) && nextLevel <= level)) continue;
    } else if (/:\s*$/.test(line) && !LIST_ITEM.test(line) && !TABLE_ROW.test(line)) {
      // An intro to a list or table that is no longer there.
      if (next === undefined || !(LIST_ITEM.test(next) || TABLE_ROW.test(next))) continue;
    }
    out.push(line);
  }
  return out.join('\n');
}

function scrubTechnical(text: string): string {
  return stripCodeSpans(text)
    .replace(HTTP_ENDPOINT, CUT)
    .replace(BARE_PATH, CUT)
    .replace(TECH_NOUN_LATIN, CUT)
    .replace(TECH_NOUN_CYRILLIC, CUT)
    .replace(STATUS_CODE, CUT)
    .replace(CAMEL_CASE, CUT)
    .replace(BARE_UPPER_SNAKE, (word) => (isProductLabel(word) ? word : CUT))
    .replace(HIDDEN_CONCEPT_ID, CUT)
    .replace(ISSUE_REF, '');
}

/**
 * Drop table rows and list items that are *about* an identifier — a cell that
 * is nothing but a code span, or a row that mentions an endpoint. Tables left
 * with only a header are dropped whole.
 */
function dropCodeRows(body: string): string {
  const mentionsEndpoint = (line: string): boolean =>
    new RegExp(HTTP_ENDPOINT.source).test(line) || new RegExp(BARE_PATH.source).test(line);

  // A table row or list item that mentions an endpoint is *about* the API.
  // Rows about constants and identifiers are not dropped here: their code
  // cells become cuts in `scrubTechnical`, and `dropGuttedLines` removes the
  // rows left with no prose — while rows that also carry product text survive.
  const isApiRow = (line: string): boolean => (TABLE_ROW.test(line) || LIST_ITEM.test(line)) && mentionsEndpoint(line);

  // Tables are handled as blocks: one that loses more than half of its rows to
  // endpoints was an API table, and the survivors would mislead.
  const lines = body.split('\n');
  const out: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    if (!(TABLE_ROW.test(lines[i]) && TABLE_RULE.test(lines[i + 1] ?? ''))) {
      if (!isApiRow(lines[i])) out.push(lines[i]);
      continue;
    }
    const header = [lines[i], lines[i + 1]];
    let j = i + 2;
    const rows: string[] = [];
    while (j < lines.length && TABLE_ROW.test(lines[j])) rows.push(lines[j++]);
    const kept = rows.filter((r) => !isApiRow(r));
    if (kept.length > 0 && kept.length * 2 >= rows.length) out.push(...header, ...kept);
    i = j - 1;
  }
  return out.join('\n');
}

/**
 * Reference tables carry a column that points into the code ("Где закреплено",
 * "Функция", "Константа"). For a client the column is either a cut or a name of
 * an internal module; drop it and keep the rest of the table.
 */
const POINTER_COLUMN = /^(?:где(?!\p{L})|функци|констант|источник|файл|модел|поле|роут|эндпоинт|тип шага|реализац|событие в бд|кто исполняет|исполнител)/iu;

function dropPointerColumns(body: string): string {
  const lines = body.split('\n');
  const out: string[] = [];
  const cellsOf = (row: string) => row.trim().slice(1, -1).split('|').map((c) => c.trim());
  for (let i = 0; i < lines.length; i++) {
    if (!(TABLE_ROW.test(lines[i]) && TABLE_RULE.test(lines[i + 1] ?? ''))) {
      out.push(lines[i]);
      continue;
    }
    const header = cellsOf(lines[i]);
    const drop = new Set(header.map((h, idx) => (POINTER_COLUMN.test(h.replace(/\*/g, '')) ? idx : -1)).filter((x) => x >= 0));
    let j = i + 2;
    const rows: string[] = [];
    while (j < lines.length && TABLE_ROW.test(lines[j])) rows.push(lines[j++]);
    const keepIdx = header.map((_, idx) => idx).filter((idx) => !drop.has(idx));
    if (drop.size > 0 && keepIdx.length >= 2) {
      const project = (row: string) => '| ' + keepIdx.map((idx) => cellsOf(row)[idx] ?? '').join(' | ') + ' |';
      out.push(project(lines[i]), '|' + keepIdx.map(() => '---').join('|') + '|', ...rows.map(project));
    } else if (drop.size === 0 || keepIdx.length >= 2) {
      out.push(lines[i], lines[i + 1], ...rows);
    }
    // else: only pointer columns would remain — drop the table.
    i = j - 1;
  }
  return out.join('\n');
}

/** Remove tables reduced to header + rule (or a rule that lost its header). */
function dropEmptyTables(body: string): string {
  const kept = body.split('\n');
  const out: string[] = [];
  for (let i = 0; i < kept.length; i++) {
    const line = kept[i];
    if (TABLE_ROW.test(line) && !TABLE_RULE.test(line)) {
      const next = kept[i + 1] ?? '';
      const after = kept[i + 2] ?? '';
      const isHeader = TABLE_RULE.test(next);
      const hasBody = TABLE_ROW.test(after) && !TABLE_RULE.test(after);
      if (isHeader && !hasBody) {
        i += 1; // skip the rule too
        continue;
      }
    }
    if (TABLE_RULE.test(line) && !TABLE_ROW.test(out[out.length - 1] ?? '')) continue;
    out.push(line);
  }
  return out.join('\n');
}

/**
 * Redact a short metadata string (title, description). These are returned by
 * search and the topic list without ever passing through `renderBody`, so they
 * need the same scrub — concept descriptions are written for engineers and do
 * cite source files.
 */
export function renderText(text: string, audience: Audience): string {
  if (audience === 'internal') return text;
  const scrubbed = scrubSensitive(text);
  return audience === 'client' ? scrubTechnical(scrubbed).replace(/\s{2,}/g, ' ').trim() : scrubbed;
}

/**
 * Produce the body a given audience is allowed to read. The internal audience
 * gets the concept verbatim; the partner audience gets it redacted; the client
 * audience gets it redacted and stripped of implementation detail.
 */
export function renderBody(concept: Concept, audience: Audience): string {
  if (audience === 'internal') return concept.body.trim();
  const stages: Array<(b: string) => string> = [
    dropInternalSections,
    (b) => dropHiddenRelated(b, concept.category, audience),
    stripFootnotes,
    (b) => rewriteLinks(b, concept.category, audience),
    scrubSensitive,
  ];
  if (audience === 'client') {
    stages.push(
      dropTechnicalSections,
      dropFencedBlocks,
      dropCodeRows,
      dropPointerColumns,
      scrubTechnical,
      dropGuttedLines,
      dropEmptyTables,
      dropEmptySections,
    );
  }
  stages.push(tidy);
  return stages.reduce((body, stage) => stage(body), concept.body);
}

/**
 * The concepts as a given audience receives them — visibility applied and every
 * field rendered. Search must run over *this*, not over raw bodies: otherwise a
 * query for a redacted identifier still ranks the concept that mentions it, and
 * the redaction is probeable.
 */
export function renderedCorpus(concepts: Concept[], audience: Audience): Concept[] {
  return visibleConcepts(concepts, audience).map((c) => ({
    ...c,
    title: renderText(c.title, audience),
    description: renderText(c.description, audience),
    body: renderBody(c, audience),
  }));
}
