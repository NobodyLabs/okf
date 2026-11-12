import express, { type Request, type Response } from 'express';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { config } from './config.js';
import { buildServer } from './server.js';
import { CONCEPTS } from './store.js';
import { visibleConcepts, type Audience } from './visibility.js';

const app = express();
app.use(express.json({ limit: '1mb' }));

/** Liveness/readiness probe — no auth, used by k8s. */
app.get('/health', (_req: Request, res: Response) => {
  res.status(200).json({ status: 'ok', concepts: CONCEPTS.length });
});

/**
 * Resolve the bearer token to an audience. The partner token sees the redacted
 * product surface; the optional client token a stripped-down subset of it; the
 * optional internal token sees everything.
 */
function audienceOf(req: Request): Audience | null {
  const auth = req.headers.authorization;
  if (!auth) return null;
  if (auth === `Bearer ${config.MCP_PARTNER_TOKEN}`) return 'partner';
  if (config.MCP_CLIENT_TOKEN && auth === `Bearer ${config.MCP_CLIENT_TOKEN}`) return 'client';
  if (config.MCP_INTERNAL_TOKEN && auth === `Bearer ${config.MCP_INTERNAL_TOKEN}`) return 'internal';
  return null;
}

/**
 * Stateless Streamable HTTP MCP endpoint: a fresh server + transport per
 * request, no session affinity. The bundle is read-only and held in memory, so
 * requests are independent and the deployment scales horizontally.
 */
app.post('/mcp', async (req: Request, res: Response) => {
  const audience = audienceOf(req);
  if (!audience) {
    res.status(401).json({ jsonrpc: '2.0', error: { code: -32001, message: 'Unauthorized' }, id: null });
    return;
  }

  const server = buildServer(audience);
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });

  res.on('close', () => {
    void transport.close();
    void server.close();
  });

  try {
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (err) {
    console.error('[mcp] request handling error:', err);
    if (!res.headersSent) {
      res.status(500).json({ jsonrpc: '2.0', error: { code: -32603, message: 'Internal server error' }, id: null });
    }
  }
});

// Stateless mode does not support server-initiated streams or session teardown.
const methodNotAllowed = (_req: Request, res: Response) => {
  res.status(405).json({
    jsonrpc: '2.0',
    error: { code: -32000, message: 'Method not allowed (stateless server).' },
    id: null,
  });
};
app.get('/mcp', methodNotAllowed);
app.delete('/mcp', methodNotAllowed);

app.listen(config.PORT, () => {
  const partner = visibleConcepts(CONCEPTS, 'partner').length;
  const client = visibleConcepts(CONCEPTS, 'client').length;
  console.log(
    `knowledge-mcp listening on :${config.PORT} — ${CONCEPTS.length} concepts loaded, ` +
      `${partner} visible to partners, ${client} to clients (client token ${config.MCP_CLIENT_TOKEN ? 'set' : 'unset'})`,
  );
});
