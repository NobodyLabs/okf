/**
 * Redaction shared by every project of one team: infrastructure identifiers that
 * are the same whatever the product — the team's internal domain, its cluster
 * names, its chat ids. `project.ts` holds what is specific to this project.
 *
 * The engine already cuts what is recognisable without knowing the team: image
 * registry paths, repo paths, Telegram bot handles and chat ids. Add here what
 * only the team knows. A team that sets up several repos keeps one copy of this
 * file and installs it with `install.py --with-mcp --org-file <file>`; without
 * that flag the installer never overwrites it.
 */
export interface OrgConfig {
  /** Pattern → replacement, applied for partner and client before `PROJECT.sensitive`. */
  sensitive: Array<[RegExp, string]>;
  /** Label → pattern that must never appear in the partner or client corpus (checked by `npm test`). */
  forbidden: Array<[string, RegExp]>;
}

export const ORG: OrgConfig = {
  // Example: [/\b[a-z0-9-]+\.corp\.example\.com\b/gi, '[внутренний хост]']
  sensitive: [],
  // Example: ['internal hostname', /corp\.example\.com/i]
  forbidden: [],
};
