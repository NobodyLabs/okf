/**
 * Everything project-specific about this knowledge server lives here; the rest
 * of `src/` is a generic engine (installed by the `okf-repo-setup` skill), and
 * `org.ts` holds the redaction a team shares across its projects. Filling this file is a judgement call, not a
 * mechanical step: read the concepts with each audience's eyes first.
 *
 * Audiences, narrowest to widest:
 * - `client`   — an end user of the product, via an in-app AI assistant.
 *                Hand-picked subset of the partner surface, engineering stripped.
 *                Optional: leave `clientIds` empty and the audience stays closed.
 * - `partner`  — the external customer who owns the product. Product surface,
 *                infrastructure redacted. Default-deny outside the allowlist.
 * - `internal` — our own team. Whole bundle, verbatim.
 */

export interface ProjectConfig {
  /** Product name as the customer knows it — used in tool descriptions. */
  productName: string;
  /** MCP server name reported to clients. */
  serverName: string;
  /** Concept served by `get_product_overview`. */
  overviewId: string;
  /** A real partner-visible concept id, shown as an example in tool descriptions. */
  exampleConceptId: string;
  instructions: { partner: string; client: string; internal: string };

  /** Partner surface. Default-deny: only these prefixes/ids are visible. */
  partner: { allowPrefixes: string[]; allowIds: string[]; denyIds: string[] };
  /** Client surface — explicit ids only, never prefixes; must be partner-visible. */
  clientIds: string[];

  /** Top-level repo directories; paths into them are redacted for partner and client. */
  repoDirs: string[];
  /** Extra infrastructure identifiers to redact, on top of the engine's and `org.ts`. */
  sensitive: Array<[RegExp, string]>;
  /** Bundle categories whose bare concept ids must not reach a client. */
  hiddenCategories: string[];
  /** Extra stack words to cut for the client (Latin, whole-word). */
  techNouns: string[];
  /** Code spans a client may see verbatim (product labels, bot commands). */
  keepCodes: string[];
  /** Extra heading stems whose sections a client must not see (e.g. `куратору`). */
  clientHiddenHeadings: string[];
  /** Extra UPPER_SNAKE prefixes that mark a constant, not a product label (e.g. `QUIET_HOURS`). */
  constantPrefixes: string[];
  /** How customers ask vs how the bundle is written: token prefix → expansions. */
  synonyms: Array<[string, string[]]>;

  tests: {
    minConcepts: number;
    /** A rendered body shorter than this was gutted by redaction. */
    minBodyLength: number;
    partnerMustSee: string[];
    partnerMustHide: string[];
    clientMustSee: string[];
    clientMustHide: string[];
    /** Extra patterns that must never appear in the partner corpus. */
    partnerForbidden: Array<[string, RegExp]>;
    /** Extra patterns that must never appear in the client corpus. */
    clientForbidden: Array<[string, RegExp]>;
    /** Customer questions → acceptable concepts; one must be in the top 3. */
    partnerGolden: Array<[string, string[]]>;
    clientGolden: Array<[string, string[]]>;
  };
}

// TODO(okf-repo-setup): fill every field below from the real bundle.
// `npm test` fails on purpose while `tests.partnerGolden` is empty.
export const PROJECT: ProjectConfig = {
  productName: '__PRODUCT_NAME__',
  serverName: '__APP_SLUG__-product-knowledge',
  overviewId: 'overview',
  exampleConceptId: 'overview',

  instructions: {
    partner: `Ты отвечаешь на вопросы о том, как сейчас работает продукт __PRODUCT_NAME__.

Правила:
1. Отвечай ТОЛЬКО на основе разделов, полученных из этих инструментов. Если ответа в них нет —
   так и скажи, не додумывай. Особенно это касается цен, планов развития и причин, по которым
   механика сделана именно так: этого в базе знаний нет.
2. Пиши простым деловым языком, без технических подробностей: не упоминай названия функций,
   полей базы данных, эндпоинтов и файлов, даже если они встречаются в тексте раздела.
   Переводи их в описание поведения продукта.
3. Сначала ищи через search_product_knowledge, затем читай найденное через get_product_concept.
   Один вопрос часто закрывается двумя-тремя разделами — прочитай их все, прежде чем отвечать.
4. У каждого раздела есть дата актуальности (updatedAt). Если вопрос про текущее поведение,
   упомяни, на какую дату описание проверялось.`,
    client: `Ты помогаешь пользователю __PRODUCT_NAME__ разобраться, как работает продукт.

Правила:
1. Отвечай ТОЛЬКО на основе разделов, полученных из этих инструментов. Если ответа в них нет —
   скажи, что не знаешь, и предложи обратиться в поддержку. Не додумывай цены, сроки и планы.
2. Пометка […] в тексте раздела означает вырезанную техническую деталь. Никогда не пытайся
   угадать, что там было, и не упоминай, что что-то вырезано — просто опирайся на остальной текст.
3. Говори простым языком о том, что пользователь видит и делает. Не упоминай названия внутренних
   статусов, констант, функций и таблиц, даже если они встречаются в тексте.
4. Сначала ищи через search_product_knowledge, затем читай найденное через get_product_concept.`,
    internal: `База знаний по проекту __PRODUCT_NAME__ (OKF-бандл), полный доступ, включая разделы
«Ограничения и грабли» и ссылки на исходники. Ищи через search_product_knowledge,
читай через get_product_concept.`,
  },

  partner: {
    allowPrefixes: ['product/'],
    allowIds: ['overview'],
    denyIds: [],
  },
  clientIds: [],

  repoDirs: ['apps', 'packages', 'scripts', 'src', 'lib', 'app', 'db'],
  sensitive: [],
  hiddenCategories: ['data', 'ops', 'api', 'integrations', 'frontend', 'architecture', 'libraries', 'queues', 'decisions'],
  techNouns: [],
  keepCodes: [],
  clientHiddenHeadings: [],
  constantPrefixes: [],
  synonyms: [],

  tests: {
    minConcepts: 10,
    minBodyLength: 400,
    partnerMustSee: ['overview'],
    partnerMustHide: [],
    clientMustSee: [],
    clientMustHide: [],
    partnerForbidden: [],
    clientForbidden: [],
    partnerGolden: [],
    clientGolden: [],
  },
};
