/**
 * Regression-Lock fuer DESK-002 (Codex-Audit 2026-08-26,
 * docs/audits/2026-08-26-electron-runtime-release-security-audit.md).
 *
 * build-backend.js kopierte frueher ein evtl. vorhandenes echtes
 * 5eyes-backend/.env (mit SECRET_KEY/DB_KEY/API-Keys des Build-Rechners)
 * in bundle/backend/, das package.json per `extraResources` komplett in
 * JEDEN Installer packt. Fix: der .env-Copy-Schritt wurde entfernt UND ein
 * neuer scripts/bundle-secret-scan.js scannt bundle/backend nach dem
 * Backend-Build (nicht davor, wie preflight:release) und blockt den Build
 * bei einem Fund.
 *
 * Dieser Test prueft die Scan-LOGIK direkt gegen temporaere Verzeichnisse,
 * ohne einen echten Electron/PyInstaller-Build zu brauchen.
 *
 * Lauf: `node tests/bundle-secret-scan.test.js` (Exit 0 = gruen).
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const { scanForSecrets } = require('../scripts/bundle-secret-scan.js');

let failed = 0;
function check(name, fn) {
  try {
    fn();
    console.log(`  ok - ${name}`);
  } catch (e) {
    failed++;
    console.error(`  FAIL - ${name}: ${e.message}`);
  }
}

function makeTmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), '5eyes-bundle-secret-scan-'));
}

check('leeres/nicht existentes Verzeichnis -> keine Funde', () => {
  const dir = path.join(makeTmpDir(), 'does-not-exist');
  const violations = scanForSecrets(dir);
  assert.deepStrictEqual(violations, []);
});

check('sauberer Bundle-Ordner (.exe + .env.example) -> keine Funde', () => {
  const dir = makeTmpDir();
  fs.writeFileSync(path.join(dir, '5eyes-api.exe'), 'fake-binary-content');
  fs.writeFileSync(path.join(dir, '.env.example'), 'SECRET_KEY=CHANGE_ME_IN_PRODUCTION_USE_STRONG_RANDOM_KEY\nDB_KEY=\n');
  const violations = scanForSecrets(dir);
  assert.deepStrictEqual(violations, []);
});

check('echtes .env im Bundle -> wird als Fund erkannt', () => {
  const dir = makeTmpDir();
  fs.writeFileSync(path.join(dir, '.env'), 'SECRET_KEY=super-real-production-secret\nDB_KEY=abc123\n');
  const violations = scanForSecrets(dir);
  assert.strictEqual(violations.length, 1);
  assert.ok(violations[0].file.endsWith('.env'));
});

check('.env in verschachteltem Unterordner -> wird ebenfalls erkannt', () => {
  const dir = makeTmpDir();
  const nested = path.join(dir, 'nested', 'deep');
  fs.mkdirSync(nested, { recursive: true });
  fs.writeFileSync(path.join(nested, '.env'), 'SECRET_KEY=real\n');
  const violations = scanForSecrets(dir);
  assert.strictEqual(violations.length, 1);
  assert.ok(violations[0].file.includes(path.join('nested', 'deep')));
});

check('.env.local / .env.production -> ebenfalls Funde (nicht nur nackte .env)', () => {
  const dir = makeTmpDir();
  fs.writeFileSync(path.join(dir, '.env.local'), 'SECRET_KEY=real\n');
  fs.writeFileSync(path.join(dir, '.env.production'), 'SECRET_KEY=real\n');
  const violations = scanForSecrets(dir);
  assert.strictEqual(violations.length, 2);
});

check('.env.sample / .env.template bleiben erlaubt (secret-freie Vorlagen)', () => {
  const dir = makeTmpDir();
  fs.writeFileSync(path.join(dir, '.env.sample'), 'SECRET_KEY=CHANGE_ME\n');
  fs.writeFileSync(path.join(dir, '.env.template'), 'SECRET_KEY=CHANGE_ME\n');
  const violations = scanForSecrets(dir);
  assert.deepStrictEqual(violations, []);
});

check('eingebetteter privater Schluessel (falscher Dateiname) -> wird per Inhalt erkannt', () => {
  const dir = makeTmpDir();
  fs.writeFileSync(
    path.join(dir, 'certificate.pfx.txt'),
    '-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAK...\n-----END RSA PRIVATE KEY-----\n'
  );
  const violations = scanForSecrets(dir);
  assert.strictEqual(violations.length, 1);
  assert.ok(violations[0].reason.includes('privatem Schluessel'));
});

console.log(failed === 0 ? '\nALL GREEN' : `\n${failed} FAILED`);
process.exit(failed === 0 ? 0 : 1);
