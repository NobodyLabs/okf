import { defineConfig } from 'vitest/config';

export default defineConfig({
  // Inline config stops Vite from walking up and loading the host app's
  // postcss.config.js (Tailwind etc.), which this package does not have.
  css: { postcss: {} },
  test: {
    globals: true,
    environment: 'node',
    include: ['src/**/*.test.ts'],
    // config.ts validates at import, so this must exist before any module
    // loads. Not a real token — tests never start the HTTP server.
    // KNOWLEDGE_BUNDLE_DIR is left unset on purpose: the default resolves the
    // repo's real okf-bundle/ (see config.ts), so a redaction gap in an actual
    // concept fails the suite rather than passing on a fixture.
    env: {
      MCP_PARTNER_TOKEN: 'test-partner-token',
    },
  },
});
