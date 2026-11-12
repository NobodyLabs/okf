import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { PROJECT } from './project.js';
import { registerTools } from './tools.js';
import type { Audience } from './visibility.js';

/**
 * Build a fresh MCP server instance scoped to one audience. The instructions
 * are told to the connecting agent up front: the bundle is written for
 * engineers, so without them the agent happily quotes function names and
 * database fields at a business reader.
 */
export function buildServer(audience: Audience): McpServer {
  const server = new McpServer(
    { name: PROJECT.serverName, version: '1.0.0' },
    { instructions: PROJECT.instructions[audience] },
  );
  registerTools(server, audience);
  return server;
}
