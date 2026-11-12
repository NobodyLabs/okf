import { existsSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';

/**
 * Runtime configuration, validated from environment variables.
 * Fails fast (exits with a one-line reason) if the partner token is missing —
 * the server is exposed publicly and there is no safe default for it — or if
 * the bundle directory cannot be found.
 */
const schema = z.object({
  // Directory holding the OKF bundle. Unset: see `findBundle` — works from the
  // service dir, from the repo root and in the image without configuration.
  // A relative value is resolved against the working directory.
  KNOWLEDGE_BUNDLE_DIR: z.string().min(1).optional(),
  // Bearer token for the external audience (partner / заказчик): sees only the
  // product surface, with internal sections redacted.
  MCP_PARTNER_TOKEN: z.string({ error: 'MCP_PARTNER_TOKEN is required' }).min(1, 'MCP_PARTNER_TOKEN is required'),
  // Optional bearer token for the internal audience (our own team): full bundle,
  // no redaction. Unset means nobody can reach the internal view.
  MCP_INTERNAL_TOKEN: z.string().min(1).optional(),
  // Optional bearer token for the client audience — the in-app AI assistant
  // that talks to end users. Narrowest view: a hand-picked subset of the
  // product surface with every engineering detail stripped. Unset means the
  // client view is reachable by nobody.
  MCP_CLIENT_TOKEN: z.string().min(1).optional(),
  PORT: z.coerce.number().int().positive().default(8474),
});

export type Config = Omit<z.infer<typeof schema>, 'KNOWLEDGE_BUNDLE_DIR'> & {
  /** Absolute path of the bundle directory; checked to exist. */
  KNOWLEDGE_BUNDLE_DIR: string;
};

/** The package root: both `src/config.ts` and the bundled `dist/index.js` sit one level below it. */
const PACKAGE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');

const isDir = (path: string): boolean => existsSync(path) && statSync(path).isDirectory();

/**
 * Default bundle location, independent of the working directory: the nearest
 * `okf-bundle/` at or above the package. That is `/app/okf-bundle` in the image
 * and `<repo>/okf-bundle` in a checkout, wherever the service sits in the repo
 * (`knowledge-mcp/`, `apps/knowledge-mcp/`).
 */
function findBundle(): string | undefined {
  for (let dir = PACKAGE_DIR; ; dir = dirname(dir)) {
    const candidate = join(dir, 'okf-bundle');
    if (isDir(candidate)) return candidate;
    if (dirname(dir) === dir) return undefined;
  }
}

/** A misconfiguration is an operator error, not a bug: say what is wrong, no stack trace. */
function fail(message: string): never {
  console.error(`knowledge-mcp: ${message}`);
  process.exit(1);
}

function load(): Config {
  const parsed = schema.safeParse(process.env);
  if (!parsed.success) {
    fail(`invalid configuration — ${parsed.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('; ')}`);
  }
  const { KNOWLEDGE_BUNDLE_DIR: requested, ...rest } = parsed.data;

  let bundleDir: string;
  if (requested) {
    bundleDir = resolve(requested);
    if (!isDir(bundleDir)) fail(`KNOWLEDGE_BUNDLE_DIR=${requested} is not a directory (resolved to ${bundleDir})`);
  } else {
    const found = findBundle();
    if (!found) fail(`no okf-bundle/ found in ${PACKAGE_DIR} or any parent — set KNOWLEDGE_BUNDLE_DIR to the bundle directory`);
    bundleDir = found;
  }
  return { ...rest, KNOWLEDGE_BUNDLE_DIR: bundleDir };
}

export const config = load();
