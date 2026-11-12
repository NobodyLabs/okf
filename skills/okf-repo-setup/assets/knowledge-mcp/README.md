# knowledge-mcp

MCP-сервер, который отвечает на вопросы «как сейчас работает продукт __PRODUCT_NAME__»
по OKF-бандлу (`okf-bundle/`). Задуман для внешнего заказчика: он подключает сервер к
своему ИИ-агенту и спрашивает про механики продукта, не имея доступа к репозиторию.

Установлен скиллом `okf-repo-setup`. Всё проектное — в `src/project.ts`, остальное в
`src/` — общий движок; `src/org.ts` — редактирование, общее для проектов одной команды
(её внутренний домен, имена кластеров).

## Инструменты

| Инструмент | Назначение |
|---|---|
| `search_product_knowledge` | поиск по вопросу на естественном языке → список разделов |
| `get_product_concept` | полный текст одного раздела по id |
| `list_product_topics` | оглавление доступных разделов |
| `get_product_overview` | обзор продукта, точка входа |

## Аудитории

Аудитория определяется bearer-токеном:

- `MCP_PARTNER_TOKEN` — **заказчик**, обязательная. Видит `partner.allowPrefixes` /
  `allowIds` из `project.ts`, остальное недоступно по принципу default-deny. Секции
  «Ограничения и грабли», сноски на исходники, хосты, пути в репозитории вырезаются.
- `MCP_CLIENT_TOKEN` — **пользователь продукта** через ИИ-ассистента, опциональная.
  Только явный список `clientIds`, строгое подмножество партнёрского; вся инженерная
  часть (код, эндпоинты, стек, технические секции) вырезается машинно.
- `MCP_INTERNAL_TOKEN` — **команда**, опциональная. Весь бандл без правок.

Поиск и оглавление работают по **отредактированному** корпусу аудитории — иначе
вырезанный идентификатор можно было бы нащупать поиском.

## Как расширить доступ

Заказчику — `partner` в `src/project.ts`: новые концепты под `allowPrefixes`
открываются автоматически, всё прочее — только явным добавлением. Пользователю —
`clientIds`, и только после прочтения раздела его глазами. Тесты прогоняют сканеры
утечек по всему видимому корпусу каждой аудитории, так что открыть лишнее незаметно
не получится.

## Актуальность

Бандл **вшит в образ**: обновили `okf-bundle/` — CI пересобирает и передеплоивает
сервис. Дата проверки раздела отдаётся в `updatedAt`, агент обязан её упоминать.

## Локально

```bash
cd __MCP_DIR__ && npm ci && npm test && npm run typecheck
npm run build
MCP_PARTNER_TOKEN=dev node dist/index.js     # бандл найдётся сам, см. KNOWLEDGE_BUNDLE_DIR

# в другом терминале
curl -s localhost:8474/health
curl -s -X POST localhost:8474/mcp \
  -H 'Authorization: Bearer dev' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
curl -s -X POST localhost:8474/mcp \
  -H 'Authorization: Bearer dev' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_product_knowledge","arguments":{"query":"как начать пользоваться продуктом"}}}'
```

Ответ на `/mcp` приходит SSE-событием (`event: message` / `data: {...}`); без заголовка
`Authorization: Bearer <MCP_PARTNER_TOKEN>` — `401 Unauthorized`.

Зависимости зафиксированы в `package-lock.json`, который поставляется вместе с шаблоном:
ставь через `npm ci`. Lock держит vitest 4: на npm 10 `npm install` без lock-файла
падает (`Cannot read properties of null (reading 'edgesOut')`). С lock-файлом `npm install`
работает, но выкидывает поля `libc` (npm 11 их пишет) — коммить такой дифф незачем.

Тесты гоняются против **настоящего** `okf-bundle/`: парсинг всех концептов, видимость,
утечки, отсутствие пустых секций, golden set вопросов заказчика (топ-3). Пока
`src/project.ts` не заполнен (`tests.partnerGolden` пуст), падает guard-тест
`project.ts is configured` — это ожидаемо сразу после установки.

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `MCP_PARTNER_TOKEN` | — (обязательна) | токен заказчика |
| `MCP_CLIENT_TOKEN` | не задана | токен ИИ-ассистента для пользователей |
| `MCP_INTERNAL_TOKEN` | не задана | токен полного доступа |
| `KNOWLEDGE_BUNDLE_DIR` | ближайший `okf-bundle/` в каталоге сервиса или выше | где лежит бандл: в репозитории — `<repo>/okf-bundle` откуда ни запускай, в образе — `/app/okf-bundle`; относительный путь считается от текущего каталога |
| `PORT` | `8474` | порт HTTP-транспорта |
