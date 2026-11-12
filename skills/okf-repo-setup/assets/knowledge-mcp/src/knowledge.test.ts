import { describe, expect, it } from 'vitest';
import { ORG } from './org.js';
import { PROJECT } from './project.js';
import { CONCEPTS } from './store.js';
import { search } from './search.js';
import { CONTAINER_REGISTRY, REPO_PATH, isVisible, renderBody, renderText, renderedCorpus, visibleConcepts } from './visibility.js';

// Runs against the REAL bundle (see vitest.config.ts), not a fixture: a
// redaction gap in an actual concept must fail the suite.

const T = PROJECT.tests;
const partner = visibleConcepts(CONCEPTS, 'partner');
const client = visibleConcepts(CONCEPTS, 'client');
const hasClient = PROJECT.clientIds.length > 0;

// Titles and descriptions leave the server through search results and the topic
// list without touching renderBody, so leakage scans cover them too.
const outputOf = (audience: 'partner' | 'client') => (c: (typeof CONCEPTS)[number]) => ({
  id: c.id,
  text: [renderText(c.title, audience), renderText(c.description, audience), renderBody(c, audience)].join('\n'),
});
const partnerOutput = partner.map(outputOf('partner'));
const clientOutput = client.map(outputOf('client'));
const repoPath = () => new RegExp(REPO_PATH.source);

describe('project.ts is configured', () => {
  // The installed stub passes every other check vacuously (empty golden set,
  // nothing to hide), so a green suite would prove nothing. Every real config
  // has customer questions; until it does, this is the one failing test.
  it('has the partner golden set filled', () => {
    expect(
      T.partnerGolden.length,
      'src/project.ts is still the unconfigured stub: tests.partnerGolden is empty. ' +
        'Fill project.ts per the okf-repo-setup skill, references/mcp-config.md',
    ).toBeGreaterThan(0);
  });
});

describe('bundle loading', () => {
  it('parses every concept in the repo bundle', () => {
    expect(CONCEPTS.length).toBeGreaterThanOrEqual(T.minConcepts);
    for (const c of CONCEPTS) {
      expect(c.title, `${c.id} has no title`).not.toBe('');
      expect(c.description, `${c.id} has no description`).not.toBe('');
      expect(c.updatedAt, `${c.id} has no generated.at`).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });

  it('excludes navigation and changelog files', () => {
    expect(CONCEPTS.some((c) => c.id.endsWith('index'))).toBe(false);
    expect(CONCEPTS.some((c) => c.id === 'log')).toBe(false);
  });

  it('every configured id exists in the bundle', () => {
    const ids = new Set(CONCEPTS.map((c) => c.id));
    const configured = [
      PROJECT.overviewId,
      PROJECT.exampleConceptId,
      ...PROJECT.partner.allowIds,
      ...PROJECT.partner.denyIds,
      ...PROJECT.clientIds,
      ...T.partnerMustSee,
      ...T.clientMustSee,
      ...T.partnerGolden.flatMap(([, e]) => e),
      ...T.clientGolden.flatMap(([, e]) => e),
    ];
    const missing = [...new Set(configured)].filter((id) => !ids.has(id));
    expect(missing, `project.ts names concepts that do not exist: ${missing.join(', ')}`).toEqual([]);
  });
});

describe('partner visibility', () => {
  it('exposes the configured product surface', () => {
    expect(isVisible(PROJECT.overviewId, 'partner')).toBe(true);
    expect(isVisible(PROJECT.exampleConceptId, 'partner')).toBe(true);
    for (const id of T.partnerMustSee) expect(isVisible(id, 'partner'), `${id} should be visible`).toBe(true);
  });

  it('hides what must stay internal', () => {
    for (const id of T.partnerMustHide) expect(isVisible(id, 'partner'), `${id} must stay hidden`).toBe(false);
  });

  it('default-denies everything outside the allowlist', () => {
    const allowIds = new Set(PROJECT.partner.allowIds);
    for (const c of partner) {
      const byPrefix = PROJECT.partner.allowPrefixes.some((p) => c.id.startsWith(p));
      expect(byPrefix || allowIds.has(c.id), `${c.id} slipped through`).toBe(true);
    }
  });

  it('gives the internal audience the whole bundle', () => {
    expect(visibleConcepts(CONCEPTS, 'internal').length).toBe(CONCEPTS.length);
  });
});

describe('redaction for partners', () => {
  it('drops internal sections (limitations, gotchas, known divergences)', () => {
    for (const c of partner) {
      expect(renderBody(c, 'partner'), `${c.id} still carries an internal section`).not.toMatch(
        /^#{1,6}\s*(ограничени|грабл|известные проблем|limitations|gotchas|known issues)/im,
      );
    }
  });

  it('drops footnote markers and their source citations', () => {
    for (const c of partner) expect(renderBody(c, 'partner'), `${c.id} still carries footnotes`).not.toMatch(/\[\^/);
  });

  it('keeps the substance — bodies stay non-trivial after redaction', () => {
    for (const c of partner) {
      expect(renderBody(c, 'partner').length, `${c.id} was gutted by redaction`).toBeGreaterThan(T.minBodyLength);
    }
  });

  it('rewrites cross-links to hidden concepts into plain text', () => {
    for (const c of partner) {
      const links = [...renderBody(c, 'partner').matchAll(/\]\(([^)\s]+)\)/g)].map((m) => m[1]);
      for (const link of links) {
        if (/^[a-z]+:\/\//i.test(link) || link.startsWith('#')) continue;
        expect(isVisible(link, 'partner'), `${c.id} links to hidden ${link}`).toBe(true);
      }
    }
  });

  it('never names a hidden concept by its id', () => {
    // A link to a hidden concept collapses to its anchor text; when that text is
    // the id itself, the partner would read a list of internal modules.
    const hidden = CONCEPTS.filter((c) => c.id.includes('/') && !isVisible(c.id, 'partner')).map((c) => c.id);
    for (const { id, text } of partnerOutput) {
      const named = hidden.filter((h) => new RegExp(`(?<![\\w/-])${h.replace(/[/-]/g, '\\$&')}(?![\\w/-])`).test(text));
      expect(named, `${id} names hidden concepts`).toEqual([]);
    }
  });

  it('scrubs repo paths from metadata, not just bodies', () => {
    for (const c of partner) {
      expect(renderText(c.description, 'partner'), `${c.id} description cites a repo path`).not.toMatch(repoPath());
    }
  });
});

describe('no leakage in the partner corpus', () => {
  const FORBIDDEN: Array<[string, RegExp]> = [
    ['repo path', repoPath()],
    ['container registry', new RegExp(CONTAINER_REGISTRY.source, 'i')],
    ['telegram bot handle', /@[A-Za-z0-9_]{3,}_?[Bb]ot\b/],
    ['telegram chat id', /-100\d{9,}/],
    ...ORG.forbidden,
    ...T.partnerForbidden,
  ];
  for (const [label, pattern] of FORBIDDEN) {
    it(`never exposes a ${label}`, () => {
      const offenders = partnerOutput.filter(({ text }) => pattern.test(text)).map(({ id }) => id);
      expect(offenders, `${label} leaked in: ${offenders.join(', ')}`).toEqual([]);
    });
  }
});

describe('search answers the questions a customer actually asks', () => {
  const corpus = renderedCorpus(CONCEPTS, 'partner');
  for (const [question, expected] of T.partnerGolden) {
    it(`«${question}» → ${expected[0]}`, () => {
      const top = search(corpus, question, 3).map((h) => h.id);
      expect(expected.some((id) => top.includes(id)), `got ${top.join(', ')}`).toBe(true);
    });
  }

  it('returns nothing for a question with no overlap', () => {
    expect(search(corpus, 'квантовая криптография блокчейн', 5)).toEqual([]);
  });
});

describe.runIf(hasClient)('client visibility', () => {
  it('exposes the configured mechanics', () => {
    for (const id of T.clientMustSee) expect(isVisible(id, 'client'), `${id} should be visible to clients`).toBe(true);
  });

  it('hides what clients must not see', () => {
    for (const id of T.clientMustHide) expect(isVisible(id, 'client'), `${id} must stay hidden from clients`).toBe(false);
  });

  it('is a strict subset of the partner surface', () => {
    for (const id of PROJECT.clientIds) expect(isVisible(id, 'partner'), `${id} is client-listed but partner-hidden`).toBe(true);
    expect(client.length).toBeLessThan(partner.length);
  });

  it('does not open new product concepts automatically', () => {
    const prefix = PROJECT.partner.allowPrefixes[0];
    if (!prefix) return;
    expect(isVisible(`${prefix}some-future-feature`, 'partner')).toBe(true);
    expect(isVisible(`${prefix}some-future-feature`, 'client')).toBe(false);
  });
});

describe.runIf(hasClient)('no engineering detail in the client corpus', () => {
  const FORBIDDEN: Array<[string, RegExp]> = [
    ['repo path', repoPath()],
    ['telegram bot handle', /@[A-Za-z0-9_]{3,}_?[Bb]ot\b/],
    ['telegram chat id', /-100\d{9,}/],
    ...ORG.forbidden,
    ['code span', /`/],
    ['http endpoint', /\b(?:GET|POST|PUT|PATCH|DELETE)\s+\//],
    ['admin or internal route', /\/(?:admin|internal)\b/],
    ['scoped package', /@[a-z0-9-]+\/[a-z0-9-]+/],
    ['stack noun', /\b(?:Prisma|Postgres(?:QL)?|Redis|BullMQ|JWT|iframe|localStorage)\b/],
    ['database abbreviation', /(?<!\p{L})БД(?!\p{L})/u],
    ['function call', /\w\(\)/],
    ['camelCase identifier', /\b[a-z]+(?:[A-Z][a-z0-9]+)+\b/],
    ['issue reference', /#\d{2,}/],
    ...T.clientForbidden,
  ];
  for (const [label, pattern] of FORBIDDEN) {
    it(`never exposes a ${label}`, () => {
      const offenders = clientOutput.filter(({ text }) => pattern.test(text)).map(({ id }) => id);
      expect(offenders, `${label} leaked in: ${offenders.join(', ')}`).toEqual([]);
    });
  }

  it('keeps the substance — bodies stay non-trivial after stripping', () => {
    for (const c of client) expect(renderBody(c, 'client').length, `${c.id} was gutted`).toBeGreaterThan(T.minBodyLength);
  });

  it('leaves no empty sections behind', () => {
    for (const c of client) {
      const lines = renderBody(c, 'client').split('\n');
      lines.forEach((line, i) => {
        const heading = /^(#{1,6})\s/.exec(line);
        if (!heading) return;
        const next = lines.slice(i + 1).find((l) => l.trim() !== '');
        const nextHeading = next ? /^(#{1,6})\s/.exec(next) : null;
        const empty = next === undefined || (nextHeading !== null && nextHeading[1].length <= heading[1].length);
        expect(empty, `${c.id}: empty section "${line}"`).toBe(false);
      });
    }
  });

  it('a redacted identifier is unsearchable for the client', () => {
    // Search must run over the rendered corpus: otherwise a query for a cut
    // identifier still ranks the concept that mentions it, and the redaction
    // can be probed. Every camelCase identifier in a raw client body must be
    // absent from everything client search matches against.
    const haystack = renderedCorpus(CONCEPTS, 'client')
      .map((c) => [c.title, c.description, c.body].join('\n'))
      .join('\n');
    const idents = new Set(client.flatMap((c) => [...c.body.matchAll(/\b[a-z]+(?:[A-Z][a-z0-9]+)+\b/g)].map((m) => m[0])));
    const leaked = [...idents].filter((ident) => new RegExp(`\\b${ident}\\b`).test(haystack));
    expect(leaked).toEqual([]);
  });
});

describe.runIf(hasClient)('search answers the questions a user actually asks', () => {
  const corpus = renderedCorpus(CONCEPTS, 'client');
  for (const [question, expected] of T.clientGolden) {
    it(`«${question}» → ${expected[0]}`, () => {
      const top = search(corpus, question, 3).map((h) => h.id);
      expect(expected.some((id) => top.includes(id)), `got ${top.join(', ')}`).toBe(true);
    });
  }

  it('never surfaces a hidden concept', () => {
    for (const [question] of [...T.clientGolden, ...T.partnerGolden]) {
      const ids = search(corpus, question, 10).map((h) => h.id);
      expect(ids.filter((id) => !isVisible(id, 'client')), question).toEqual([]);
    }
  });
});
