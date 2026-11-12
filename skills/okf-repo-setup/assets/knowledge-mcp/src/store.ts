import { loadBundle, type Concept } from './bundle.js';
import { config } from './config.js';

/**
 * The bundle is immutable for the lifetime of the process (it ships inside the
 * image), so it is parsed once at import time and shared by every request.
 */
export const CONCEPTS: Concept[] = loadBundle(config.KNOWLEDGE_BUNDLE_DIR);

export function conceptById(id: string): Concept | undefined {
  return CONCEPTS.find((c) => c.id === id);
}
