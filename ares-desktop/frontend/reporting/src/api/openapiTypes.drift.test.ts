// @vitest-environment node
/**
 * U-1 (A3 P1-1): Drift-Gate fuer die generierten API-Typen.
 *
 * `src/api/generated/openapi.ts` muss exakt dem entsprechen, was
 * `scripts/gen-api-types.mjs` aus dem versionierten Artefakt
 * `api/openapi.json` erzeugt. Laeuft im bestehenden CI-Job "Frontend
 * Reporting Tests" (vitest). Bei Rot: `npm run gen:api-types` und committen.
 */
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const APP_DIR = path.resolve(__dirname, '..', '..');

describe('generierte API-Typen', () => {
  it('entsprechen api/openapi.json (npm run check:api-types)', () => {
    const result = spawnSync(
      process.execPath,
      [path.join(APP_DIR, 'scripts', 'gen-api-types.mjs'), '--check'],
      { cwd: APP_DIR, encoding: 'utf8' },
    );
    expect(result.stderr).toBe('');
    expect(result.status).toBe(0);
  }, 60_000);
});
