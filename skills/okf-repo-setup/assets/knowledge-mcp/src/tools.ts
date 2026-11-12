import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { CONCEPTS, conceptById } from './store.js';
import { PROJECT } from './project.js';
import { search } from './search.js';
import { isVisible, renderBody, renderText, renderedCorpus, type Audience } from './visibility.js';

type ToolResult = {
  content: Array<{ type: 'text'; text: string }>;
  isError?: boolean;
};

function ok(payload: unknown): ToolResult {
  return { content: [{ type: 'text', text: JSON.stringify(payload, null, 2) }] };
}

function fail(message: string): ToolResult {
  return { content: [{ type: 'text', text: message }], isError: true };
}

export function registerTools(server: McpServer, audience: Audience): void {
  // Everything the tools hand out is taken from the rendered corpus, so search
  // and the topic list can only surface words this audience is allowed to read.
  const visible = renderedCorpus(CONCEPTS, audience);

  server.registerTool(
    'search_product_knowledge',
    {
      title: 'Найти описание механики продукта',
      description:
        `Поиск по базе знаний ${PROJECT.productName} на естественном языке. Принимает вопрос целиком ` +
        'и возвращает ' +
        'список подходящих разделов с кратким описанием и датой актуальности. ' +
        'Чтобы прочитать раздел целиком, передай его id в get_product_concept.',
      inputSchema: {
        query: z.string().min(2).describe('Вопрос или ключевые слова на русском языке'),
        limit: z.number().int().min(1).max(20).default(8),
      },
    },
    async ({ query, limit }) => {
      const hits = search(visible, query, limit);
      if (hits.length === 0) {
        return ok({
          results: [],
          hint: 'Ничего не найдено. Попробуй другие слова или посмотри list_product_topics.',
        });
      }
      return ok({ results: hits });
    },
  );

  server.registerTool(
    'get_product_concept',
    {
      title: 'Прочитать раздел базы знаний',
      description:
        `Полный текст одного раздела по его id (например, ${PROJECT.exampleConceptId}). ` +
        'Возвращает описание механики с таблицами значений и датой, на которую оно проверено по коду.',
      inputSchema: {
        id: z.string().min(1).describe('Идентификатор раздела из search_product_knowledge'),
      },
    },
    async ({ id }) => {
      const normalized = id.replace(/\.md$/, '').replace(/^\/+/, '');
      const concept = conceptById(normalized);
      // Same answer for "does not exist" and "not visible to you" — the set of
      // internal concepts is not something an external client should be able to
      // probe for.
      if (!concept || !isVisible(concept.id, audience)) {
        return fail(`Раздел "${id}" не найден. Список доступных разделов — list_product_topics.`);
      }
      return ok({
        id: concept.id,
        title: renderText(concept.title, audience),
        description: renderText(concept.description, audience),
        type: concept.type,
        updatedAt: concept.updatedAt,
        status: concept.status,
        content: renderBody(concept, audience),
      });
    },
  );

  server.registerTool(
    'list_product_topics',
    {
      title: 'Оглавление базы знаний',
      description:
        'Все доступные разделы, сгруппированные по темам, с описанием каждого. ' +
        'Полезно, чтобы понять, что вообще можно спросить, или когда поиск ничего не нашёл.',
      inputSchema: {},
    },
    async () => {
      const groups = new Map<string, Array<{ id: string; title: string; description: string; updatedAt: string }>>();
      for (const c of visible) {
        const key = c.category || 'общее';
        const list = groups.get(key) ?? [];
        list.push({ id: c.id, title: c.title, description: c.description, updatedAt: c.updatedAt });
        groups.set(key, list);
      }
      return ok({
        total: visible.length,
        topics: [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([category, concepts]) => ({
          category,
          concepts,
        })),
      });
    },
  );

  server.registerTool(
    'get_product_overview',
    {
      title: 'Обзор продукта',
      description:
        `Общее описание ${PROJECT.productName}: что это за продукт, кто в нём участвует и как устроен ` +
        'путь пользователя. Хорошая отправная точка перед частными вопросами.',
      inputSchema: {},
    },
    async () => {
      const overview = conceptById(PROJECT.overviewId);
      if (!overview || !isVisible(overview.id, audience)) return fail('Обзор недоступен.');
      return ok({
        title: renderText(overview.title, audience),
        updatedAt: overview.updatedAt,
        content: renderBody(overview, audience),
      });
    },
  );
}
