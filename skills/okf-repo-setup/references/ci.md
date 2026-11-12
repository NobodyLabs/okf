# CI для OKF-бандла и knowledge-mcp

CI-файлы в проектах разные (монорепа с `dorny/paths-filter` и десятком джоб или один
образ на весь репозиторий), поэтому CI правится
руками по этому документу, а не установщиком. Сначала прочитай существующий
workflow целиком. Исключение — гейт долга ветки (`okf-gate.yml`): он ни от чего в
проекте не зависит, и его кладёт `install.py`.

Сниппеты ниже — для GitHub Actions: действия закреплены по SHA с тегом в комментарии,
`permissions: contents: read`, `persist-credentials: false` у checkout, `ubuntu-24.04`.
Обновляешь версию действия — меняй SHA и тег вместе.

## 0. Ловушка `paths-ignore` (проверить первой)

Многие workflow игнорируют `**.md` / `docs/**`. Бандл — это `.md`-файлы, поэтому
пуш, который меняет **только** `okf-bundle/`, такой workflow не запустит вообще. На
первом проекте так и было: заказчик неделями получал ответы по старым концептам, сколько
бы бандл ни обновляли. Варианты:

- проверки бандла и сборку MCP вынести в **отдельный workflow** без `paths-ignore`
  (или с `paths: ['okf-bundle/**', '<mcp-dir>/**', 'scripts/okf/**']`);
- либо добавить в существующий `paths-ignore` исключение `'!okf-bundle/**'`. GitHub
  разрешает отрицательные шаблоны только в `paths`, **не** в `paths-ignore` — поэтому
  на деле это значит переход на `paths` или отдельный workflow.

Рекомендация: отдельный `.github/workflows/okf.yml`.

## 1. Валидация бандла (всегда)

```yaml
name: OKF bundle
on:
  push:
    branches: [main, develop]
    paths: ['okf-bundle/**', 'scripts/okf/**', '<mcp-dir>/**', '.github/workflows/okf.yml']
  pull_request:
    paths: ['okf-bundle/**', 'scripts/okf/**', '<mcp-dir>/**']

permissions:
  contents: read

jobs:
  validate:
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        with: { python-version: '3.12' }
      # PyYAML включает строгие проверки: дубли ключей, вложенные v0.2-поля.
      - run: pip install pyyaml
      - run: python3 scripts/okf/validate_bundle.py okf-bundle
      - run: python3 scripts/okf/gen_index.py okf-bundle --check
```

Дрейф от якоря (`drift.py` без флагов) в CI **не** гейтим: он накопительный и
эвристический (UNCOVERED по новому хелперу — не ошибка). Его видимость — строка SessionStart и
`okf-guardian`; проверку по расписанию с уведомлением команда добавляет сама
(`drift.py --quiet`: код 1 и одна строка, если бандл отстал).

### Гейт: долг ветки (всегда)

`drift.py --gate` — то же правило, что у Stop-хука, но для любого коммита: правки с
GitHub, Codex, руками, сессии с `OKF_SKIP=1`. Красным делает только долг ветки:
концепты, чей код ветка поменяла, а сами они не обновлены (правка из одних пробелов не в
счёт), и файлы мимо всех якорей при нетронутом бандле. UNCOVERED и EXPIRED печатаются
для сведения.

Отказ, если поведение не менялось, — строка `okf: n/a — <причина от 8 символов>` в
сообщении коммита. Покрывает файлы только своего коммита: тот же файл в следующем коммите
без отказа снова под проверкой. На PR есть ещё метка `okf-not-affected` — на всю ветку.
Отказ остаётся в истории git и в сводке джобы, его видно на ревью.

Отдельный workflow, а не джоба в `okf.yml`: гейту нужны **все** PR (долг рождается
правкой кода), а на фильтре `paths` в `okf.yml` держится запуск тестов MCP.

Workflow — `assets/ci/okf-gate.yml` этого скилла; `install.py` кладёт его в
`.github/workflows/okf-gate.yml` с интеграционной веткой из `--base-ref` в `on.push`.
Если в проекте уже есть workflow с `drift.py --gate`, второй не ставится. Руками его
не пиши: блок в `AGENTS.md` обещает агентам, что правило проверяет CI.

- `push` — только интеграционная ветка (её подставляет `install.py`). На PR база — его
  целевая ветка, на push — `github.event.before`.
- Код `2` (нет бандла, нет merge-base) красит джобу: модуль поставлен неправильно.
- Squash-merge: GitHub собирает сообщения всех коммитов PR в одно, поэтому на push-проверке
  отказ из любого коммита покроет весь squash. Точная проверка по коммитам — на PR.
- Сделать джобу обязательной (branch protection) — решение команды. Без этого красный
  статус виден, но мерж не блокирует.

## 2. Тесты knowledge-mcp (если есть MCP)

Они гоняются по **реальному** бандлу, поэтому триггер — и бандл, и код сервиса:

```yaml
  mcp-test:
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    defaults: { run: { working-directory: <mcp-dir> } }
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
        with: { node-version: '24' }
      - run: if [ -f package-lock.json ]; then npm ci; else npm install; fi
      - run: npm run typecheck
      - run: npm test
```

## 3. Сборка образа knowledge-mcp и деплой

Образ: `<registry>/<app>-knowledge-mcp` — в том же реестре, что и образ приложения.
Контекст сборки — **корень репозитория** (образу нужен `okf-bundle/`), файл —
`<mcp-dir>/Dockerfile`.

Сборку делай в том же workflow, где уже живёт сборка и деплой приложения, отдельной
джобой с фильтром путей. Вход в реестр, `env.REGISTRY`, условие `if` и `needs` возьми
из джобы сборки приложения — ниже на их месте заглушки:

```yaml
  detect-changes:
    runs-on: ubuntu-24.04
    outputs:
      knowledge-mcp: ${{ steps.filter.outputs.knowledge-mcp }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false, fetch-depth: 0 }
      - uses: dorny/paths-filter@ceb8a2b8f2d89434be7ff52d3de7ec3738c5cc9d # v4.0.3
        id: filter
        with:
          base: ${{ github.event.before }}
          filters: |
            knowledge-mcp:
              - '<mcp-dir>/**'
              # Бандл вшит в образ: рефреш знаний обязан пересобрать сервис.
              - 'okf-bundle/**'

  build-knowledge-mcp:
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    needs: [detect-changes]
    if: github.event_name == 'push' && needs.detect-changes.outputs.knowledge-mcp == 'true'
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      # Тесты — до сборки: okf.yml отдельный workflow и сборку не блокирует, а без этого
      # концепт с утечкой внутреннего уедет к заказчику вместе с образом.
      - uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
        with: { node-version: '24' }
      - working-directory: <mcp-dir>
        run: npm ci && npm run typecheck && npm test
      - uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1
      - uses: docker/login-action@81c6f93d4bc991e510b342a00b419b3bb4efc5c6 # v4.7.0
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ secrets.REGISTRY_USERNAME }}   # как у сборки приложения
          password: ${{ secrets.REGISTRY_PASSWORD }}
      - id: meta
        uses: docker/metadata-action@dc802804100637a589fabce1cb79ff13a1411302 # v6.2.0
        with:
          images: ${{ env.REGISTRY }}/<app>-knowledge-mcp
          tags: |
            type=ref,event=branch
            type=sha,prefix={{branch}}-
            type=raw,value=latest,enable={{is_default_branch}}
      - uses: docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc # v7.4.0
        with:
          context: .
          file: ./<mcp-dir>/Dockerfile
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha,scope=knowledge-mcp
          cache-to: type=gha,mode=max,scope=knowledge-mcp
```

Если `paths-ignore` основного workflow режет `.md` (см. §0), пуш только бандла сюда не
дойдёт — тогда фильтр путей для бандла не сработает никогда. Проверь это явно.

### Передать образ в деплой

Как собранный образ попадает в окружение, зависит от команды: CI правит тег в
репозитории манифестов (GitOps), сам вызывает `helm upgrade`/`kubectl set image`, или
платформа забирает образ по тегу. Что важно при любом способе:

- деплой срабатывает, когда собралось **хотя бы одно** из двух (приложение или MCP), и
  выкатывает только собранное: `build-knowledge-mcp` в `needs` deploy-джобы с условием
  `success || skipped`, а не жёсткое `needs: build`;
- пуш одного бандла не должен пересобирать и перевыкатывать приложение — его сборку тоже
  фильтруй по путям;
- тег у обоих образов одного формата (`<branch>-<sha7>`);
- ручной запуск с готовым тегом MCP не пересобирает — убедись, что образ MCP с этим тегом
  существует, или не выкатывай MCP в этом режиме;
- если CI правит тег в values чарта, секция `knowledgeMcp.image.tag` должна быть там до
  первого пуша (см. `k8s.md`).
