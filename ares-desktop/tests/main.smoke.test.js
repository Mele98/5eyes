/**
 * Leichtgewichtiger Smoke-/Verhaltenstest für main.js ohne echtes Electron.
 *
 * Stubt `electron` + `electron-updater` via Module._load und lädt main.js, um die
 * Hardening-Fixes EM-2 (file:save-pdf try/catch + Base64-Validierung) und EM-5
 * (Token-Datei nicht löschen wenn Encryption nur unavailable) real auszuführen.
 *
 * Lauf: `node tests/main.smoke.test.js` (Exit 0 = grün).
 */
'use strict';
const Module = require('module');
const path = require('path');
const fs = require('fs');
const os = require('os');
const assert = require('assert');

const tmpUserData = fs.mkdtempSync(path.join(os.tmpdir(), 'ares-userdata-'));
const tmpDownloads = fs.mkdtempSync(path.join(os.tmpdir(), 'ares-downloads-'));

// DESK-001-Tests brauchen einen deterministischen, unwahrscheinlich belegten
// Port fuer den Fake-Backend-Dienst -- nicht den echten Default (8000), um
// keine Kollision mit einer evtl. lokal laufenden echten Backend-Instanz zu
// riskieren.
process.env.APP_PORT = process.env.APP_PORT || '58421';

// W2-i: Eine Umgebungsvariable darf die erwartete Backend-Kennung nicht
// verschieben. Gesetzt VOR dem Laden von main.js; die Probe muss trotzdem
// genau 'Ares API' erwarten.
process.env.BACKEND_APP_NAME = 'Other API';

// ── Test-steuerbarer State ───────────────────────────────────────────────────
const state = {
  encryptionAvailable: true,
  storageBackend: 'dpapi', // DESK-003: Default = starkes Backend (wie auf Windows/macOS)
  saveDialogResult: { canceled: true },
};
const ipcHandlers = {};

// ── Electron-Stub ────────────────────────────────────────────────────────────
const electronStub = {
  app: {
    getPath: (k) => (k === 'downloads' ? tmpDownloads : tmpUserData),
    getVersion: () => '0.0.0-test',
    isPackaged: false,
    setAppUserModelId() {},
    requestSingleInstanceLock: () => true,
    // whenReady NIE auflösen -> bootstrap() (Backend-Spawn) läuft im Test nicht.
    whenReady: () => new Promise(() => {}),
    on() {},
    quit() {},
  },
  BrowserWindow: class { static getAllWindows() { return []; } },
  dialog: {
    showSaveDialog: async () => state.saveDialogResult,
    showErrorBox() {},
  },
  ipcMain: { handle: (ch, fn) => { ipcHandlers[ch] = fn; } },
  safeStorage: {
    isEncryptionAvailable: () => state.encryptionAvailable,
    getSelectedStorageBackend: () => state.storageBackend,
    encryptString: (s) => Buffer.from('enc:' + s, 'utf8'),
    decryptString: (buf) => String(buf).replace(/^enc:/, ''),
  },
  shell: { openExternal: async () => true },
  Menu: { setApplicationMenu() {}, buildFromTemplate: () => ({}) },
  nativeTheme: {},
};
const updaterStub = { autoUpdater: { on() {}, checkForUpdates() {}, quitAndInstall() {} } };

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'electron') return electronStub;
  if (request === 'electron-updater') return updaterStub;
  return originalLoad.call(this, request, parent, isMain);
};

// main.js laden (registriert ipc-Handler in unseren Stub).
const mainExports = require(path.join(__dirname, '..', 'main.js'));
Module._load = originalLoad;

// A3 P2-5: alle Kanaele pruefen den Absender -> Aufrufe kommen hier aus der
// lokalen Entry-Datei (Top-Level-Frame), wie im echten Renderer.
const { pathToFileURL } = require('url');
const trustedEvent = {
  senderFrame: { url: `${pathToFileURL(mainExports.resolveFrontendPath()).href}?intro=1`, parent: null },
};

// ── Assertions ───────────────────────────────────────────────────────────────
let failed = 0;
function check(name, fn) {
  return Promise.resolve()
    .then(fn)
    .then(() => console.log(`  ok - ${name}`))
    .catch((e) => { failed++; console.error(`  FAIL - ${name}: ${e.message}`); });
}

(async () => {
  // Handler-Registrierung
  await check('file:save-pdf handler registriert', () => {
    assert.strictEqual(typeof ipcHandlers['file:save-pdf'], 'function');
  });
  await check('auth:get-token handler registriert', () => {
    assert.strictEqual(typeof ipcHandlers['auth:get-token'], 'function');
  });
  await check('auth:get-refresh-token handler registriert (Roadmap #28 Frontend-Wiring)', () => {
    assert.strictEqual(typeof ipcHandlers['auth:get-refresh-token'], 'function');
    assert.strictEqual(typeof ipcHandlers['auth:set-refresh-token'], 'function');
    assert.strictEqual(typeof ipcHandlers['auth:clear-refresh-token'], 'function');
  });

  const savePdf = ipcHandlers['file:save-pdf'];

  // EM-2: fehlende Daten -> {ok:false} statt throw
  await check('EM-2 fehlende PDF-Daten -> ok:false (kein throw)', async () => {
    const r = await savePdf(trustedEvent, { filename: 'x.pdf', base64: '' });
    assert.strictEqual(r.ok, false);
    assert.ok(r.error && /fehlen/i.test(r.error));
  });

  // EM-2: ungültiges Base64 -> {ok:false}
  await check('EM-2 ungültiges Base64 -> ok:false', async () => {
    const r = await savePdf(trustedEvent, { filename: 'x.pdf', base64: '!!!nicht base64!!!' });
    assert.strictEqual(r.ok, false);
    assert.ok(r.error);
  });

  // EM-2: Abbruch durch User -> canceled
  await check('EM-2 Dialog-Abbruch -> canceled', async () => {
    state.saveDialogResult = { canceled: true };
    const good = Buffer.from('%PDF-1.4 test', 'utf8').toString('base64');
    const r = await savePdf(trustedEvent, { filename: 'x.pdf', base64: good });
    assert.strictEqual(r.ok, false);
    assert.strictEqual(r.canceled, true);
  });

  // EM-2: erfolgreicher Schreibvorgang
  await check('EM-2 gültiges PDF -> Datei geschrieben', async () => {
    const out = path.join(tmpDownloads, 'out.pdf');
    state.saveDialogResult = { canceled: false, filePath: out };
    const good = Buffer.from('%PDF-1.4 hello', 'utf8').toString('base64');
    const r = await savePdf(trustedEvent, { filename: 'out.pdf', base64: good });
    assert.strictEqual(r.ok, true);
    assert.ok(fs.existsSync(out));
    assert.strictEqual(fs.readFileSync(out, 'utf8'), '%PDF-1.4 hello');
  });

  // EM-5: Encryption unavailable -> Token nicht zurückgeben UND Datei NICHT löschen
  const getToken = ipcHandlers['auth:get-token'];
  const setToken = ipcHandlers['auth:set-token'];
  const tokenFile = path.join(tmpUserData, 'auth-token.bin');

  await check('EM-5 Encryption unavailable -> null + Datei bleibt erhalten', async () => {
    state.encryptionAvailable = true;
    assert.strictEqual(setToken(trustedEvent, 'secret-123'), true);
    assert.ok(fs.existsSync(tokenFile), 'Token-Datei sollte nach set existieren');

    state.encryptionAvailable = false;          // Encryption „temporär" weg
    const t = getToken(trustedEvent);
    assert.strictEqual(t, null, 'kein Klartext-Token zurückgeben');
    assert.ok(fs.existsSync(tokenFile), 'EM-5: Datei darf NICHT gelöscht werden');

    state.encryptionAvailable = true;            // Recovery
    assert.strictEqual(getToken(trustedEvent), 'secret-123', 'Token nach Recovery wieder lesbar');
  });

  // Roadmap #28 (2026-08-09 Frontend-Wiring): Refresh-Token bekommt eine
  // EIGENE Datei, unabhaengig vom Access-Token (unterschiedliche Lebensdauer,
  // unabhaengige Rotation).
  const getRefreshToken = ipcHandlers['auth:get-refresh-token'];
  const setRefreshToken = ipcHandlers['auth:set-refresh-token'];
  const clearRefreshToken = ipcHandlers['auth:clear-refresh-token'];
  const refreshTokenFile = path.join(tmpUserData, 'refresh-token.bin');

  await check('Refresh-Token: eigener Speicherplatz, getrennt vom Access-Token', async () => {
    state.encryptionAvailable = true;
    assert.strictEqual(setToken(trustedEvent, 'access-secret'), true);
    assert.strictEqual(setRefreshToken(trustedEvent, 'refresh-secret'), true);
    assert.ok(fs.existsSync(refreshTokenFile), 'Refresh-Token-Datei sollte nach set existieren');
    assert.notStrictEqual(refreshTokenFile, tokenFile, 'muss eine andere Datei als der Access-Token sein');

    assert.strictEqual(getToken(trustedEvent), 'access-secret');
    assert.strictEqual(getRefreshToken(trustedEvent), 'refresh-secret');

    clearRefreshToken(trustedEvent);
    assert.strictEqual(fs.existsSync(refreshTokenFile), false, 'clear muss nur die Refresh-Token-Datei loeschen');
    assert.ok(fs.existsSync(tokenFile), 'Access-Token-Datei bleibt beim Refresh-Token-Clear unangetastet');
    assert.strictEqual(getToken(trustedEvent), 'access-secret', 'Access-Token unveraendert nach Refresh-Token-Clear');
  });

  // EM-2 (Review-LOW): Base64 mit Whitespace/Newlines (tolerant dekodiert) muss
  // jetzt akzeptiert werden — vorher hätte der strikte Round-Trip valide PDFs
  // fälschlich abgelehnt.
  await check('EM-2 Base64 mit Whitespace -> akzeptiert', async () => {
    const out = path.join(tmpDownloads, 'ws.pdf');
    state.saveDialogResult = { canceled: false, filePath: out };
    const raw = Buffer.from('%PDF-1.4 whitespace', 'utf8').toString('base64');
    const chunked = raw.replace(/(.{8})/g, '$1\n');  // Zeilenumbrüche einstreuen
    const r = await savePdf(trustedEvent, { filename: 'ws.pdf', base64: chunked });
    assert.strictEqual(r.ok, true);
    assert.strictEqual(fs.readFileSync(out, 'utf8'), '%PDF-1.4 whitespace');
  });

  // EM-7-Fix: backendProcessStillAlive prüft echte Lebendigkeit, NICHT proc.killed.
  await check('EM-7 backendProcessStillAlive exportiert', () => {
    assert.strictEqual(typeof mainExports.backendProcessStillAlive, 'function');
  });
  await check('EM-7 killed=true aber laufend -> noch lebendig (SIGKILL würde feuern)', () => {
    const alive = mainExports.backendProcessStillAlive;
    // Nach kill('SIGTERM'): killed=true, aber Prozess läuft noch (exit/signal null).
    assert.strictEqual(alive({ killed: true, exitCode: null, signalCode: null }), true);
  });
  await check('EM-7 beendet -> nicht mehr lebendig (kein SIGKILL)', () => {
    const alive = mainExports.backendProcessStillAlive;
    assert.strictEqual(alive({ killed: true, exitCode: 0, signalCode: null }), false);
    assert.strictEqual(alive({ killed: true, exitCode: null, signalCode: 'SIGTERM' }), false);
    assert.strictEqual(alive(null), false);
  });

  // ── DESK-001 (Codex-Audit 2026-08-26): gepackte App darf niemals einen
  // bereits laufenden Fremdprozess als Backend uebernehmen, nur weil er den
  // (nicht-geheimen) app-String auf /health/ready spiegelt. ─────────────────
  await check('DESK-001 Dev-Modus uebernimmt kompatiblen Fake-Dienst wie bisher', async () => {
    const http = require('http');
    const fakeServer = http.createServer((req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json', Connection: 'close' });
      res.end(JSON.stringify({ app: 'Ares API', status: 'ok' }));
    });
    await new Promise((resolve) => fakeServer.listen(58421, '127.0.0.1', resolve));
    try {
      electronStub.app.isPackaged = false;
      const runtime = await mainExports.pickBackendRuntime();
      assert.strictEqual(runtime.ready, true, 'Dev-Modus soll den kompatiblen Fake-Dienst uebernehmen');
      assert.strictEqual(runtime.port, 58421);
    } finally {
      await new Promise((resolve) => fakeServer.close(resolve));
    }
  });

  await check('W2-i Probe erwartet genau Ares API (kein Env-Override)', () => {
    assert.strictEqual(mainExports.EXPECTED_BACKEND_APP, 'Ares API');
  });

  await check('W2-i Dev-Modus uebernimmt keinen Dienst mit fremder Kennung', async () => {
    const http = require('http');
    const fakeServer = http.createServer((req, res) => {
      // Connection: close, damit keine Keep-Alive-Verbindung aus einem
      // vorherigen Fake-Dienst die Probe verfaelscht.
      res.writeHead(200, { 'Content-Type': 'application/json', Connection: 'close' });
      res.end(JSON.stringify({ app: 'Other API', status: 'ok' }));
    });
    await new Promise((resolve) => fakeServer.listen(58421, '127.0.0.1', resolve));
    try {
      electronStub.app.isPackaged = false;
      const runtime = await mainExports.pickBackendRuntime();
      assert.notStrictEqual(runtime.ready, true, 'Fremde Kennung darf nicht als kompatibel gelten');
      assert.notStrictEqual(runtime.port, 58421);
      // Gegenprobe: der Dienst war erreichbar, abgelehnt wurde nur die Kennung.
      const probe = await new Promise((resolve) => {
        require('http').get('http://127.0.0.1:58421/health/ready', { agent: false }, (res) => {
          let body = '';
          res.on('data', (c) => { body += c; });
          res.on('end', () => resolve(JSON.parse(body)));
        }).on('error', () => resolve(null));
      });
      assert.strictEqual(probe && probe.app, 'Other API');
    } finally {
      await new Promise((resolve) => fakeServer.close(resolve));
    }
  });

  await check('DESK-001 gepackte App ignoriert denselben Fake-Dienst und weicht aus', async () => {
    const http = require('http');
    const fakeServer = http.createServer((req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json', Connection: 'close' });
      res.end(JSON.stringify({ app: 'Ares API', status: 'ok' }));
    });
    await new Promise((resolve) => fakeServer.listen(58421, '127.0.0.1', resolve));
    try {
      electronStub.app.isPackaged = true;
      const runtime = await mainExports.pickBackendRuntime();
      assert.notStrictEqual(runtime.ready, true, 'Gepackte App darf den Fake-Dienst NICHT als ready uebernehmen');
      assert.notStrictEqual(runtime.port, 58421, 'Gepackte App muss auf einen anderen Port als den belegten ausweichen (eigener Kindprozess)');
    } finally {
      electronStub.app.isPackaged = false;
      await new Promise((resolve) => fakeServer.close(resolve));
    }
  });

  // ── DESK-003 (Codex-Audit 2026-08-26): safeStorage.isEncryptionAvailable()
  // kann unter Linux `true` liefern, obwohl das gewaehlte Backend `basic_text`
  // ist (kein GNOME-Keyring/KWallet -> Klartext-Speicherung). Der geschaerfte
  // Gate `_isStrongEncryptionAvailable()` muss das als "nicht verfuegbar"
  // werten, waehrend starke Backends (dpapi/keychain_access/gnome_libsecret/
  // kwallet*) weiterhin durchgehen. ─────────────────────────────────────────
  await check('DESK-003 _isStrongEncryptionAvailable exportiert', () => {
    assert.strictEqual(typeof mainExports._isStrongEncryptionAvailable, 'function');
  });

  await check('DESK-003 starke Backends (dpapi/keychain_access/gnome_libsecret/kwallet*) gelten als verfuegbar', () => {
    state.encryptionAvailable = true;
    for (const backend of ['dpapi', 'keychain_access', 'gnome_libsecret', 'kwallet', 'kwallet5', 'kwallet6']) {
      state.storageBackend = backend;
      assert.strictEqual(mainExports._isStrongEncryptionAvailable(), true, `Backend ${backend} sollte als stark gelten`);
    }
    state.storageBackend = 'dpapi';
  });

  await check('DESK-003 basic_text/unknown gelten NICHT als verfuegbar (Linux-Fallback ohne Keyring)', () => {
    state.encryptionAvailable = true;
    for (const backend of ['basic_text', 'unknown']) {
      state.storageBackend = backend;
      assert.strictEqual(mainExports._isStrongEncryptionAvailable(), false, `Backend ${backend} sollte NICHT als stark gelten`);
    }
    state.storageBackend = 'dpapi';
  });

  await check('DESK-003 isEncryptionAvailable=false bleibt fuehrend, egal welches Backend gemeldet wird', () => {
    state.encryptionAvailable = false;
    state.storageBackend = 'gnome_libsecret';
    assert.strictEqual(mainExports._isStrongEncryptionAvailable(), false);
    state.encryptionAvailable = true;
    state.storageBackend = 'dpapi';
  });

  await check('DESK-003 basic_text-Backend blockiert Token-Persistierung wie "encryption unavailable"', async () => {
    state.encryptionAvailable = true;
    state.storageBackend = 'basic_text';
    const tokenFile2 = path.join(tmpUserData, 'auth-token.bin');
    fs.rmSync(tokenFile2, { force: true });
    const ok = setToken(trustedEvent, 'weak-backend-secret');
    assert.strictEqual(ok, false, 'Schreiben mit basic_text-Backend muss abgelehnt werden');
    assert.strictEqual(fs.existsSync(tokenFile2), false, 'Es darf keine Klartext-Datei entstehen');
    assert.strictEqual(getToken(trustedEvent), null, 'Kein Secret verfuegbar, solange nur basic_text vorliegt');
    state.storageBackend = 'dpapi';
  });

  // ── W2-804-03: Ares ist Windows-only. Der Packaged-Resolver bricht auf jeder
  // anderen Plattform mit klarer Meldung ab, statt still `ares-api.exe` zu
  // erwarten; unter win32 liefert er genau resources/backend/ares-api.exe. ──
  const withPlatform = (platform, fn) => {
    const original = Object.getOwnPropertyDescriptor(process, 'platform');
    const originalResources = process.resourcesPath;
    Object.defineProperty(process, 'platform', { value: platform, configurable: true });
    process.resourcesPath = path.join(tmpUserData, 'resources');
    try {
      return fn();
    } finally {
      Object.defineProperty(process, 'platform', original);
      process.resourcesPath = originalResources;
    }
  };

  await check('W2-804-03 resolvePackagedBackendExe exportiert', () => {
    assert.strictEqual(typeof mainExports.resolvePackagedBackendExe, 'function');
  });

  await check('W2-804-03 gepackter Resolver lehnt darwin/linux mit klarer Meldung ab', () => {
    for (const platform of ['darwin', 'linux', 'freebsd']) {
      assert.throws(
        () => withPlatform(platform, () => mainExports.resolvePackagedBackendExe()),
        (err) => /nur fuer Windows/.test(err.message) && err.message.includes(platform),
        `Plattform ${platform} muss abgelehnt werden`
      );
    }
  });

  await check('W2-804-03 gepackter Resolver liefert unter win32 resources/backend/ares-api.exe', () => {
    const resolved = withPlatform('win32', () => mainExports.resolvePackagedBackendExe());
    assert.strictEqual(resolved, path.join(tmpUserData, 'resources', 'backend', 'ares-api.exe'));
  });

  console.log(failed === 0 ? '\nALL GREEN' : `\n${failed} FAILED`);
  process.exit(failed === 0 ? 0 : 1);
})();
