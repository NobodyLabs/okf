# Build context is the REPO ROOT (not __MCP_DIR__), because the image has to
# carry okf-bundle/ — the knowledge base this server answers from.
FROM node:24-alpine AS build
WORKDIR /app
COPY __MCP_DIR__/package*.json ./
# Standalone package: no workspace deps, so it resolves on its own. The lock
# ships with the template — `npm ci` keeps the image reproducible.
RUN npm ci
COPY __MCP_DIR__/tsconfig.json __MCP_DIR__/tsup.config.ts ./
COPY __MCP_DIR__/src ./src
RUN npm run build && npm prune --omit=dev

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV KNOWLEDGE_BUNDLE_DIR=/app/okf-bundle
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY __MCP_DIR__/package.json ./
# The bundle is baked in: refreshing the knowledge base means rebuilding the
# image, which is why CI rebuilds this service on okf-bundle/** changes too.
COPY okf-bundle ./okf-bundle
USER node
EXPOSE 8474
CMD ["node", "dist/index.js"]
