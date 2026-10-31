/**
 * W4-a4: userData-Vertrag zwischen package.json und main.js.
 *
 * Electron leitet `app.getName()` und damit `app.getPath('userData')`
 * (Windows: `%APPDATA%\<Name>`) aus `productName`, sonst `name` der
 * package.json ab, die die App laedt:
 *   - Dev (`electron .`): diese Datei.
 *   - Gepackt: dieselbe Datei, von electron-builder nur um `extraMetadata`
 *     ergaenzt und um Build-Felder (`build`, `scripts`, `devDependencies`)
 *     bereinigt. `build.productName` wird dabei NICHT uebernommen.
 *
 * Damit Dev und Paket denselben Ordner `%APPDATA%\Ares` nutzen, muss das
 * Top-Level-`productName` "Ares" sein, darf `extraMetadata` Name/Produktname
 * nicht ueberschreiben und darf main.js Name/userData nicht selbst setzen.
 * Single-Instance-Sperre, Token-Dateien und `logs/electron.log` haengen am
 * userData-Pfad und folgen ihm ohne eigene Konfiguration.
 *
 * Lauf: `node --test tests/user-data-identity.test.js`
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
const mainJs = fs.readFileSync(path.join(ROOT, 'main.js'), 'utf8');

// Regel von Electron fuer app.getName().
function electronAppName(packageJson) {
  return packageJson.productName || packageJson.name;
}

// Nachbildung von electron-builder (app-builder-lib, modifyMainPackageJson):
// extraMetadata tief einmischen, dann Build-Felder entfernen.
function packagedPackageJson(source) {
  const out = JSON.parse(JSON.stringify(source));
  const extra = (source.build && source.build.extraMetadata) || {};
  Object.assign(out, JSON.parse(JSON.stringify(extra)));
  for (const prop of ['build', 'scripts', 'devDependencies', 'dist', 'gitHead']) delete out[prop];
  return out;
}

test('Top-Level-productName ist "Ares"', () => {
  assert.strictEqual(pkg.productName, 'Ares');
});

test('Dev und Paket ergeben denselben App-Namen und damit denselben userData-Ordner', () => {
  const devName = electronAppName(pkg);
  const packaged = packagedPackageJson(pkg);
  assert.ok(packaged.productName, 'productName muss im gepackten package.json erhalten bleiben');
  assert.strictEqual(devName, 'Ares');
  assert.strictEqual(electronAppName(packaged), devName);
  const appData = '%APPDATA%';
  assert.strictEqual(path.win32.join(appData, electronAppName(packaged)), `${appData}\\Ares`);
});

test('extraMetadata ueberschreibt weder name noch productName', () => {
  const extra = (pkg.build && pkg.build.extraMetadata) || {};
  assert.ok(!('name' in extra), 'extraMetadata.name wuerde den gepackten App-Namen aendern');
  assert.ok(!('productName' in extra), 'extraMetadata.productName wuerde den gepackten App-Namen aendern');
});

test('main.js setzt weder App-Namen noch userData-Pfad selbst', () => {
  assert.ok(!/\bapp\.setName\s*\(/.test(mainJs), 'app.setName() entkoppelt userData vom package.json');
  assert.ok(!/\bapp\.setPath\s*\(\s*['"]userData['"]/.test(mainJs), "app.setPath('userData') entkoppelt den Pfad");
  // Sperre, Logs und Token-Dateien haengen am userData-Pfad.
  assert.ok(/app\.requestSingleInstanceLock\(\)/.test(mainJs));
  assert.ok(/path\.join\(app\.getPath\('userData'\), 'logs'\)/.test(mainJs));
  assert.ok(/path\.join\(app\.getPath\('userData'\), 'auth-token\.bin'\)/.test(mainJs));
});

test('Installer-Anzeigenamen sind "Ares"', () => {
  assert.strictEqual(pkg.build.productName, 'Ares');
  assert.strictEqual(pkg.build.nsis.shortcutName, 'Ares');
  assert.strictEqual(pkg.build.nsis.uninstallDisplayName, 'Ares');
});

test('AppUserModelID in main.js ist identisch mit build.appId', () => {
  const m = mainJs.match(/app\.setAppUserModelId\('([^']+)'\)/);
  assert.ok(m, 'setAppUserModelId-Literal fehlt');
  assert.strictEqual(m[1], pkg.build.appId);
});
