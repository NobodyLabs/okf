# Деплой knowledge-mcp в Kubernetes (пример для Helm-чарта)

Сервису нужно немного: образ, порт `8474`, три переменные с токенами и HTTPS-хост. Ни базы,
ни доступа к приложению — он отвечает только из бандла, вшитого в образ. Ниже — как
добавить его в Helm-чарт приложения; для другого способа деплоя возьми отсюда требования
к контейнеру (§«Что добавить в чарт», п.1) и к прокси (п.3).

Манифесты часто живут не в репозитории проекта, а в отдельном, из которого деплоится
прод. **Правки там спроси у пользователя перед коммитом и пушем**, чужой локальный клон
не трогай — работай в своём временном.

**Порядок: манифесты — до первого пуша проекта.** Если CI после сборки правит тег образа
в values, а секции `knowledgeMcp:` там ещё нет, обновлять нечего, и MCP не задеплоится.

Шаблоны — `assets/k8s/` этого скилла: в `templates/` — deployment, service, ingress и
хелперы меток (отдельным `_knowledge-mcp-helpers.tpl`, Helm подхватит его сам), в
`values-knowledge-mcp.yaml` — блоки для `values.yaml` и values окружений. Шаблоны
опираются на то, что есть в чарте от `helm create`: хелперы `<chart>.fullname`, `.labels`,
`.selectorLabels`, `.serviceAccountName` — и на два значения: `global.imagePullSecrets` и
`secret.name` (имя секрета приложения, откуда берутся токены). Нет таких значений в
чарте — поправь шаблон под свои имена. В каталоге с чартом:

```bash
A="<каталог этого скилла>/assets/k8s"
cp "$A"/templates/* <chart>/templates/
sed -i '' 's/<chart>/<имя чарта>/g' <chart>/templates/*knowledge-mcp*   # GNU sed: -i без ''
helm lint <chart> -f <values окружения>
```

## Что добавить в чарт

1. **Deployment** — контейнер на порту `8474`, пробы `GET /health`, env:
   `PORT=8474`, `MCP_PARTNER_TOKEN` / `MCP_CLIENT_TOKEN` / `MCP_INTERNAL_TOKEN` через
   `secretKeyRef` из секрета приложения (ключи `KNOWLEDGE_MCP_PARTNER_TOKEN`,
   `KNOWLEDGE_MCP_CLIENT_TOKEN`, `KNOWLEDGE_MCP_INTERNAL_TOKEN`, `optional: true`).
   Никакого доступа к БД и API: сервер отвечает только из бандла в образе.
   Без партнёрского токена под падает на старте — это намеренно.
2. **Service** — ClusterIP, `80 → http`.
3. **Ingress** — отдельный хост (`<app>-kb-mcp.<domain>`, для dev —
   `<app>-kb-mcp-dev.<domain>`), TLS (в шаблоне — cert-manager с issuer
   `letsencrypt-prod`; свой issuer — поправь аннотацию), и обязательно для Streamable
   HTTP (аннотации ingress-nginx; у другого контроллера — его аналоги: без буферизации,
   HTTP/1.1, длинные таймауты):
   ```yaml
   nginx.ingress.kubernetes.io/proxy-buffering: "off"
   nginx.ingress.kubernetes.io/proxy-http-version: "1.1"
   nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
   nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
   ```
   Ингресс публичный — доступ контролирует bearer-токен в самом приложении.
4. **values.yaml** — секция верхнего уровня `knowledgeMcp` из
   `values-knowledge-mcp.yaml`: образ, ресурсы, хост и TLS-секрет в
   `knowledgeMcp.ingress`.
5. **values окружений** — `knowledgeMcp.enabled: true`, `image.tag` (его дальше
   обновляет CI или деплой) и хост окружения. Включай по окружению осознанно: prod —
   только когда токен заказчика заведён.

## Токены

Сгенерировать: `openssl rand -hex 32` на каждый токен и окружение (dev ≠ prod).
Три ключа добавляются в секрет приложения тем способом, которым команда уже заводит
секреты (менеджер секретов с синхронизацией в кластер, `kubectl create secret`, цель в
`Makefile`). Меняешь документ в хранилище секретов — добавляй ключи, не перезаписывая
остальные. Значения сам не выдумывай и в репозиторий не пиши: попроси пользователя
завести их или сгенерируй командой, которая кладёт значение сразу в хранилище.

Токен заказчика передаётся ему вне репозитория. Подключение с его стороны — MCP
по Streamable HTTP: `https://<host>/mcp`, заголовок `Authorization: Bearer <token>`.

## DNS

Каждому хосту MCP нужна своя запись, если у домена нет wildcard: пользователь заводит
A-запись на внешний адрес ingress-контроллера кластера
(`kubectl -n ingress-nginx get svc ingress-nginx-controller`). Доехало ли —
`dig +short <host>`.

## Проверка после деплоя

```bash
curl -s https://<host>/health                       # {"status":"ok","concepts":N}
curl -s -X POST https://<host>/mcp -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
Без токена `/mcp` обязан отвечать 401.
