/**
 * UPDATE-001: Auto-Update ist im Produktionsbuild fail-closed deaktiviert.
 *
 * Geprueft wird das Build-/Packaging-Gate (nicht nur eine Laufzeit-Flag):
 *  - Default-Konfiguration: keine Publish-URL, Updater wird nie geladen,
 *    kein Netzwerkaufruf -- auch nicht in einer gepackten App mit
 *    ENABLE_AUTO_UPDATE=1.
 *  - UPDATES_ENABLED=true ohne vollstaendige Konfiguration (HTTPS-Feed-URL +
 *    Code-Signing) bricht Preflight und beforePack-Hook ab.
 *  - Keine Platzhalter-/Fremd-URL in den gepackten Dateien.
 *
 * Lauf: `node --test tests/update-gate.test.js` (keine Abhaengigkeit).
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const Module = require('module');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const ELECTRON_DIR = path.resolve(__dirname, '..');
const PACKAGE_JSON_PATH = path.join(ELECTRON_DIR, 'package.json');
const MAIN_JS_PATH = path.join(ELECTRON_DIR, 'main.js');
const repoPackageJson = () => JSON.parse(fs.readFileSync(PACKAGE_JSON_PATH, 'utf8'));

const gate = require('../update-gate.js');

// Test-Fixture (kein Produktwert): syntaktisch gueltige, nicht reservierte Adresse.
const FIXTURE_FEED_URL = 'https://updates.owner.internal/stable';
const FIXTURE_SIGNING_ENV = { CSC_LINK: 'fixture-certificate-reference', CSC_KEY_PASSWORD: 'fixture-password' };

function enabledPackageJson(feedUrl = FIXTURE_FEED_URL) {
  const pkg = repoPackageJson();
  pkg.desktopUpdates = { enabled: true, feedUrl };
  pkg.build.publish = [{ provider: 'generic', url: feedUrl }];
  return pkg;
}

// ── Feed-URL-Pruefung ───────────────────────────────────────────────────────
test('Feed-URL: fehlend, http, Platzhalter, localhost, IP und Credentials werden abgelehnt', () => {
  const rejected = [
    undefined,
    '',
    'http://updates.owner.internal/stable',
    'https://updates.example.invalid/channel',
    'https://example.com/updates',
    'https://updates.example.org/updates',
    'https://feed.example/updates',
    'https://updates.test/x',
    'https://localhost/updates',
    'https://updates.localhost/x',
    'https://updates.local/x',
    'https://intranet/updates',
    'https://192.168.1.10/updates',
    'https://[::1]/updates',
    'https://user:secret@updates.owner.internal/stable',
    'not a url',
  ];
  for (const url of rejected) {
    assert.strictEqual(gate.checkFeedUrl(url).ok, false, `muss abgelehnt werden: ${url}`);
  }
  assert.strictEqual(gate.checkFeedUrl(FIXTURE_FEED_URL).ok, true);
});

// ── Build-Gate ──────────────────────────────────────────────────────────────
test('Build-Gate: Default (UPDATES_ENABLED nicht gesetzt) mit Repo-Konfiguration ist gruen und deaktiviert', () => {
  const result = gate.evaluateBuildGate({ env: {}, packageJson: repoPackageJson() });
  assert.deepStrictEqual(result.errors, []);
  assert.strictEqual(result.updatesEnabled, false);
});

test('Build-Gate: Repo-Konfiguration hat keine Publish-URL und Updates sind aus', () => {
  const pkg = repoPackageJson();
  assert.strictEqual(pkg.build.publish, null, 'build.publish muss null sein (kein Platzhalter, keine Auto-Erkennung)');
  assert.deepStrictEqual(pkg.desktopUpdates, { enabled: false });
});

test('Build-Gate: UPDATES_ENABLED=true ohne Konfiguration bricht ab (URL + Signing gemeldet)', () => {
  const result = gate.evaluateBuildGate({ env: { UPDATES_ENABLED: 'true' }, packageJson: repoPackageJson() });
  assert.strictEqual(result.updatesEnabled, true);
  const text = result.errors.join('\n');
  assert.match(text, /UPDATE_FEED_URL/);
  assert.match(text, /Code-Signing/);
});

test('Build-Gate: UPDATES_ENABLED=true mit URL aber ohne Signing bricht ab', () => {
  const result = gate.evaluateBuildGate({
    env: { UPDATES_ENABLED: 'true', UPDATE_FEED_URL: FIXTURE_FEED_URL },
    packageJson: enabledPackageJson(),
  });
  assert.strictEqual(result.errors.length, 1, result.errors.join('\n'));
  assert.match(result.errors[0], /Code-Signing/);
});

test('Build-Gate: UPDATES_ENABLED=true mit Signing aber Platzhalter-URL bricht ab', () => {
  const placeholder = 'https://updates.example.invalid/channel';
  const result = gate.evaluateBuildGate({
    env: { UPDATES_ENABLED: 'true', UPDATE_FEED_URL: placeholder, ...FIXTURE_SIGNING_ENV },
    packageJson: enabledPackageJson(placeholder),
  });
  assert.ok(result.errors.some((e) => /UPDATE_FEED_URL/.test(e)), result.errors.join('\n'));
});

test('Build-Gate: UPDATES_ENABLED=true mit vollstaendiger Env, aber Paket-Konfig nicht aktiviert, bricht ab', () => {
  const result = gate.evaluateBuildGate({
    env: { UPDATES_ENABLED: 'true', UPDATE_FEED_URL: FIXTURE_FEED_URL, ...FIXTURE_SIGNING_ENV },
    packageJson: repoPackageJson(),
  });
  const text = result.errors.join('\n');
  assert.match(text, /desktopUpdates/);
  assert.match(text, /build\.publish/);
});

test('Build-Gate: Positivkontrolle -- vollstaendige, konsistente Konfiguration ist gruen', () => {
  const result = gate.evaluateBuildGate({
    env: { UPDATES_ENABLED: 'true', UPDATE_FEED_URL: FIXTURE_FEED_URL, ...FIXTURE_SIGNING_ENV },
    packageJson: enabledPackageJson(),
  });
  assert.deepStrictEqual(result.errors, []);
  assert.strictEqual(result.updatesEnabled, true);
});

test('Build-Gate: Signing auch ueber win.signtoolOptions/azureSignOptions erkannt, CSC_LINK allein reicht nicht', () => {
  const env = { UPDATES_ENABLED: 'true', UPDATE_FEED_URL: FIXTURE_FEED_URL };
  const withSigntool = enabledPackageJson();
  withSigntool.build.win.signtoolOptions = { certificateSha1: 'fixture-thumbprint' };
  assert.deepStrictEqual(gate.evaluateBuildGate({ env, packageJson: withSigntool }).errors, []);
  const withAzure = enabledPackageJson();
  withAzure.build.win.azureSignOptions = { endpoint: 'fixture' };
  assert.deepStrictEqual(gate.evaluateBuildGate({ env, packageJson: withAzure }).errors, []);
  const linkOnly = gate.evaluateBuildGate({ env: { ...env, CSC_LINK: 'fixture' }, packageJson: enabledPackageJson() });
  assert.ok(linkOnly.errors.some((e) => /Code-Signing/.test(e)));
});

test('Build-Gate: unbekannter Wert fuer UPDATES_ENABLED bricht ab (fail-closed)', () => {
  for (const value of ['1', 'yes', 'TRUE ', 'on']) {
    const result = gate.evaluateBuildGate({ env: { UPDATES_ENABLED: value }, packageJson: repoPackageJson() });
    assert.strictEqual(result.updatesEnabled, false, value);
    assert.ok(result.errors.some((e) => /UPDATES_ENABLED/.test(e)), `${value}: ${result.errors.join('\n')}`);
  }
});

test('Build-Gate: UPDATES_ENABLED=false, aber Publish-URL oder aktivierte Paket-Konfig bricht ab', () => {
  const result = gate.evaluateBuildGate({ env: {}, packageJson: enabledPackageJson() });
  const text = result.errors.join('\n');
  assert.match(text, /build\.publish/);
  assert.match(text, /desktopUpdates/);
});

test('Release-Preflight: UPDATES_ENABLED=true ohne Konfiguration meldet den Gate-Fehler und endet mit Exit 1', () => {
  const run = (extraEnv) => {
    const env = { ...process.env, ...extraEnv };
    for (const key of ['UPDATES_ENABLED', 'UPDATE_FEED_URL', 'CSC_LINK', 'CSC_KEY_PASSWORD', 'WIN_CSC_LINK', 'WIN_CSC_KEY_PASSWORD']) {
      if (!(key in extraEnv)) delete env[key];
    }
    return spawnSync(process.execPath, ['scripts/release-check.js'], { cwd: ELECTRON_DIR, env, encoding: 'utf8' });
  };
  const blocked = run({ UPDATES_ENABLED: 'true' });
  assert.strictEqual(blocked.status, 1);
  assert.match(blocked.stderr, /FEHLER: UPDATE-001/);
  // Default: kein UPDATE-001-Fehler (andere Preflight-Befunde wie fehlende
  // Build-Artefakte sind hier nicht Gegenstand).
  const defaultRun = run({});
  assert.doesNotMatch(defaultRun.stderr, /FEHLER: UPDATE-001/);
});

test('beforePack-Hook: bricht Packaging bei unvollstaendiger Konfiguration ab, laesst Default durch', async () => {
  const hook = require('../scripts/update-gate-before-pack.js');
  await assert.rejects(() => hook.runUpdateGate({ env: { UPDATES_ENABLED: 'true' }, packageJson: repoPackageJson() }), /UPDATE-001/);
  await hook.runUpdateGate({ env: {}, packageJson: repoPackageJson() });
  assert.strictEqual(typeof hook, 'function');
  const pkg = repoPackageJson();
  assert.strictEqual(pkg.build.beforePack, './scripts/update-gate-before-pack.js');
  assert.ok(fs.existsSync(path.join(ELECTRON_DIR, pkg.build.beforePack)));
});

// ── Paketinhalt ─────────────────────────────────────────────────────────────
test('Paket: keine Platzhalter-/reservierte Update-URL in den gepackten Dateien; Gate-Modul wird gepackt', () => {
  const pkg = repoPackageJson();
  assert.ok(pkg.build.files.includes('update-gate.js'), 'update-gate.js muss in build.files stehen');
  const plainFiles = pkg.build.files.filter((f) => !f.startsWith('!') && !/[*?]/.test(f));
  const urlPattern = /https?:\/\/([a-z0-9.-]+)/gi;
  const offenders = [];
  for (const rel of plainFiles) {
    const abs = path.join(ELECTRON_DIR, rel);
    if (!fs.existsSync(abs) || !/\.(js|json|html)$/.test(rel)) continue;
    const text = fs.readFileSync(abs, 'utf8');
    for (const match of text.matchAll(urlPattern)) {
      // Lokales Backend (http://localhost) ist legitim; gesucht sind Platzhalter-/Doku-Domains.
      if (match[1].toLowerCase() !== 'localhost' && gate.isReservedHost(match[1])) offenders.push(`${rel}: ${match[0]}`);
    }
  }
  assert.deepStrictEqual(offenders, []);
});

// ── Laufzeit: main.js registriert den Updater nur mit offenem Build-Gate ───
test('main.js: gepackte App mit ENABLE_AUTO_UPDATE=1 laedt den Updater nicht, solange das Build-Gate zu ist', async () => {
  const tmpUserData = fs.mkdtempSync(path.join(os.tmpdir(), 'update-gate-userdata-'));
  const appStub = {
    getPath: () => tmpUserData,
    getVersion: () => '0.0.0-test',
    isPackaged: false,
    setAppUserModelId() {},
    requestSingleInstanceLock: () => true,
    whenReady: () => new Promise(() => {}),
    on() {},
    quit() {},
  };
  const electronStub = {
    app: appStub,
    BrowserWindow: class { static getAllWindows() { return []; } },
    dialog: { showSaveDialog: async () => ({ canceled: true }), showErrorBox() {} },
    ipcMain: { handle() {}, on() {} },
    safeStorage: { isEncryptionAvailable: () => false, getSelectedStorageBackend: () => 'unknown' },
    shell: { openExternal: async () => true },
    Menu: { setApplicationMenu() {}, buildFromTemplate: () => ({}) },
    nativeTheme: {},
  };
  const updaterCalls = { loads: 0, on: 0, checks: 0 };
  const updaterStub = {
    autoUpdater: {
      on() { updaterCalls.on += 1; },
      async checkForUpdates() { updaterCalls.checks += 1; return null; },
      quitAndInstall() {},
    },
  };
  let packageOverride = null;
  const originalLoad = Module._load;
  Module._load = function (request, parent, isMain) {
    if (request === 'electron') return electronStub;
    if (request === 'electron-updater') { updaterCalls.loads += 1; return updaterStub; }
    if (packageOverride && request === './package.json' && parent && parent.filename === MAIN_JS_PATH) {
      return packageOverride;
    }
    return originalLoad.call(this, request, parent, isMain);
  };
  const previousFlag = process.env.ENABLE_AUTO_UPDATE;
  try {
    const mainExports = require(MAIN_JS_PATH);
    assert.strictEqual(updaterCalls.loads, 0, 'electron-updater darf beim Laden von main.js nicht geladen werden');

    // Gepackt + Laufzeit-Flag gesetzt, Build-Gate (Repo-Konfiguration) zu.
    appStub.isPackaged = true;
    process.env.ENABLE_AUTO_UPDATE = '1';
    mainExports._configureAutoUpdatesForTest();
    assert.strictEqual(mainExports._getUpdateStateForTest().enabled, false);
    const result = await mainExports._checkForUpdatesForTest();
    assert.strictEqual(result.enabled, false);
    assert.deepStrictEqual(updaterCalls, { loads: 0, on: 0, checks: 0 }, 'kein Updater, kein Netzwerkaufruf');

    // Paket-Konfig aktiviert, aber Laufzeit-Flag fehlt -> weiterhin aus.
    packageOverride = enabledPackageJson();
    delete process.env.ENABLE_AUTO_UPDATE;
    mainExports._configureAutoUpdatesForTest();
    assert.strictEqual(mainExports._getUpdateStateForTest().enabled, false);
    assert.strictEqual(updaterCalls.loads, 0);

    // Paket-Konfig mit Platzhalter-URL -> aus.
    packageOverride = enabledPackageJson('https://updates.example.invalid/channel');
    process.env.ENABLE_AUTO_UPDATE = '1';
    mainExports._configureAutoUpdatesForTest();
    assert.strictEqual(mainExports._getUpdateStateForTest().enabled, false);
    assert.strictEqual(updaterCalls.loads, 0);

    // Positivkontrolle: Build-Gate offen + gepackt + Flag -> Updater verdrahtet.
    packageOverride = enabledPackageJson();
    mainExports._configureAutoUpdatesForTest();
    assert.strictEqual(mainExports._getUpdateStateForTest().enabled, true);
    assert.strictEqual(updaterCalls.loads, 1);
    assert.ok(updaterCalls.on >= 5, 'Lifecycle-Events registriert');
    await mainExports._checkForUpdatesForTest();
    assert.strictEqual(updaterCalls.checks, 1);
  } finally {
    Module._load = originalLoad;
    if (previousFlag === undefined) delete process.env.ENABLE_AUTO_UPDATE;
    else process.env.ENABLE_AUTO_UPDATE = previousFlag;
  }
});
