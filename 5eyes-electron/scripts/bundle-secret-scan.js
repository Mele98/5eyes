/**
 * DESK-002 (Codex-Audit 2026-08-26): scannt den gebauten Backend-Bundle-
 * Ordner (bundle/backend), der per package.json `extraResources` komplett
 * in JEDEN Installer gepackt wird, auf Dateien mit echten Geheimnissen.
 *
 * Muss NACH `npm run build:backend` und VOR `electron-builder` laufen --
 * vorher (wie der alte `preflight:release`-Lauf) waere der Scan strukturell
 * blind, weil bundle/backend erst durch build:backend entsteht.
 *
 * Kann sowohl als CLI (`node scripts/bundle-secret-scan.js [dir]`) als auch
 * per require() fuer Tests genutzt werden (siehe tests/bundle-secret-
 * scan.test.js).
 */
'use strict';
const fs = require('fs');
const path = require('path');

// .env.example / .env.sample / .env.template sind bewusst secret-freie
// Vorlagen und duerfen weiterhin ausgeliefert werden. Jede andere Datei,
// die wie eine echte dotenv-Datei aussieht (.env, .env.local,
// .env.production, ...), gilt als potenzieller Geheimnis-Traeger.
const ALLOWED_ENV_FILENAMES = new Set(['.env.example', '.env.sample', '.env.template']);
const ENV_FILENAME_PATTERN = /^\.env(\..+)?$/i;

// Datei-Inhalte, die unabhaengig vom Dateinamen auf ein eingebettetes
// Geheimnis hindeuten (privater Schluessel, Zertifikat).
const SECRET_CONTENT_PATTERNS = [
  /-----BEGIN (RSA |EC |OPENSSH |ENCRYPTED |)?PRIVATE KEY-----/,
];

function walk(rootDir) {
  const results = [];
  const stack = [rootDir];
  while (stack.length > 0) {
    const current = stack.pop();
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch (err) {
      continue;
    }
    for (const entry of entries) {
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(fullPath);
      } else if (entry.isFile()) {
        results.push(fullPath);
      }
    }
  }
  return results;
}

/**
 * Scans `rootDir` recursively and returns a list of {file, reason}
 * violations. Returns an empty array if rootDir does not exist or is
 * clean.
 */
function scanForSecrets(rootDir) {
  if (!fs.existsSync(rootDir)) {
    return [];
  }
  const violations = [];
  for (const filePath of walk(rootDir)) {
    const filename = path.basename(filePath);

    if (ENV_FILENAME_PATTERN.test(filename) && !ALLOWED_ENV_FILENAMES.has(filename)) {
      violations.push({
        file: filePath,
        reason: `dotenv-Datei mit potenziell echten Geheimniswerten: ${filename}`,
      });
      continue;
    }

    let content;
    try {
      content = fs.readFileSync(filePath, 'utf8');
    } catch (err) {
      // Binaerdatei oder nicht lesbar -- kein Text-Scan moeglich, kein Fund.
      continue;
    }
    for (const pattern of SECRET_CONTENT_PATTERNS) {
      if (pattern.test(content)) {
        violations.push({
          file: filePath,
          reason: `Dateiinhalt sieht nach eingebettetem privatem Schluessel aus (Muster: ${pattern})`,
        });
        break;
      }
    }
  }
  return violations;
}

module.exports = { scanForSecrets, ALLOWED_ENV_FILENAMES, ENV_FILENAME_PATTERN };

if (require.main === module) {
  const targetDir = process.argv[2]
    ? path.resolve(process.argv[2])
    : path.join(__dirname, '..', 'bundle', 'backend');

  const violations = scanForSecrets(targetDir);

  if (violations.length === 0) {
    console.log(`Bundle-Secret-Scan: keine Geheimnisse in ${targetDir} gefunden.`);
    process.exit(0);
  }

  console.error(`FEHLER: Bundle-Secret-Scan hat ${violations.length} Fund(e) in ${targetDir}:`);
  for (const v of violations) {
    console.error(`  - ${v.file}: ${v.reason}`);
  }
  console.error(
    'Der Build wird abgebrochen, damit keine echten Geheimnisse in den Installer gelangen. ' +
      'Datei entfernen (oder in .env.example/.env.sample/.env.template ohne echte Werte umbenennen) und erneut bauen.'
  );
  process.exit(1);
}
