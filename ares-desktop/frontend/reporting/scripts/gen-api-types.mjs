#!/usr/bin/env node
/**
 * U-1 (A3 P1-1): TypeScript-Typen aus dem versionierten OpenAPI-Artefakt
 * `api/openapi.json` (Repo-Root) erzeugen.
 *
 * Quelle der Wahrheit ist das Artefakt, das
 * `ares-backend/scripts/export_openapi.py` ohne App-Lifespan schreibt und
 * dessen Drift die Backend-CI prueft. Dieses Skript zieht die Typen nach:
 *
 *   npm run gen:api-types     # src/api/generated/openapi.ts schreiben
 *   npm run check:api-types   # nur vergleichen; Exit 1 bei Drift
 *
 * Nur Typen, keine Laufzeit: der Generator ist eine exakt gepinnte
 * devDependency und landet nie im Bundle.
 */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, resolve, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import openapiTS, { astToString } from 'openapi-typescript';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP_DIR = resolve(HERE, '..');
const REPO_ROOT = resolve(APP_DIR, '..', '..', '..');
export const ARTIFACT_PATH = resolve(REPO_ROOT, 'api', 'openapi.json');
export const OUTPUT_PATH = resolve(APP_DIR, 'src', 'api', 'generated', 'openapi.ts');

const HEADER = [
  '/**',
  ' * GENERIERT - NICHT EDITIEREN.',
  ' *',
  ' * Quelle: api/openapi.json (Repo-Root), erzeugt von',
  ' * ares-desktop/frontend/reporting/scripts/gen-api-types.mjs mit',
  ' * openapi-typescript (exakt gepinnt in package.json).',
  ' * Neu erzeugen: `npm run gen:api-types`; Drift-Check: `npm run check:api-types`.',
  ' */',
  '',
].join('\n');

/**
 * Generator-Optionen. `defaultNonNullable: false`: ein Feld ist nur dann
 * Pflicht, wenn das Schema es unter `required` fuehrt. Der Default (true)
 * wuerde jedes Feld mit `default` zur Pflicht machen und damit Request-Bodies
 * strenger typisieren, als der Server sie annimmt.
 * `emptyObjectsUnknown: true`: ein Schema `{"type": "object"}` ohne
 * Properties (Pydantic `dict`) erlaubt beliebige Keys und wird daher zu
 * `Record<string, unknown>`; der Default waere `Record<string, never>`.
 */
const OPTIONS = { defaultNonNullable: false, emptyObjectsUnknown: true };

export async function render() {
  const schema = JSON.parse(await readFile(ARTIFACT_PATH, 'utf8'));
  const ast = await openapiTS(schema, OPTIONS);
  const body = astToString(ast).replace(/\r\n/g, '\n');
  return HEADER + body.trimEnd() + '\n';
}

async function main(argv) {
  const check = argv.includes('--check');
  const fresh = await render();
  const rel = relative(APP_DIR, OUTPUT_PATH).split('\\').join('/');
  if (check) {
    let current = null;
    try {
      current = (await readFile(OUTPUT_PATH, 'utf8')).replace(/\r\n/g, '\n');
    } catch {
      current = null;
    }
    if (current !== fresh) {
      console.error(
        `API-Typen-Drift: ${rel} entspricht nicht api/openapi.json. ` +
          'Neu erzeugen mit `npm run gen:api-types` und committen.',
      );
      return 1;
    }
    console.log(`${rel} ist aktuell.`);
    return 0;
  }
  await mkdir(dirname(OUTPUT_PATH), { recursive: true });
  await writeFile(OUTPUT_PATH, fresh, 'utf8');
  console.log(`${rel} geschrieben.`);
  return 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  main(process.argv.slice(2)).then(
    (code) => process.exit(code),
    (err) => {
      console.error(err);
      process.exit(2);
    },
  );
}
