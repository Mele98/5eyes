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

const tmpUserData = fs.mkdtempSync(path.join(os.tmpdir(), '5eyes-userdata-'));
const tmpDownloads = fs.mkdtempSync(path.join(os.tmpdir(), '5eyes-downloads-'));

// ── Test-steuerbarer State ───────────────────────────────────────────────────
const state = {
  encryptionAvailable: true,
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

  const savePdf = ipcHandlers['file:save-pdf'];

  // EM-2: fehlende Daten -> {ok:false} statt throw
  await check('EM-2 fehlende PDF-Daten -> ok:false (kein throw)', async () => {
    const r = await savePdf({}, { filename: 'x.pdf', base64: '' });
    assert.strictEqual(r.ok, false);
    assert.ok(r.error && /fehlen/i.test(r.error));
  });

  // EM-2: ungültiges Base64 -> {ok:false}
  await check('EM-2 ungültiges Base64 -> ok:false', async () => {
    const r = await savePdf({}, { filename: 'x.pdf', base64: '!!!nicht base64!!!' });
    assert.strictEqual(r.ok, false);
    assert.ok(r.error);
  });

  // EM-2: Abbruch durch User -> canceled
  await check('EM-2 Dialog-Abbruch -> canceled', async () => {
    state.saveDialogResult = { canceled: true };
    const good = Buffer.from('%PDF-1.4 test', 'utf8').toString('base64');
    const r = await savePdf({}, { filename: 'x.pdf', base64: good });
    assert.strictEqual(r.ok, false);
    assert.strictEqual(r.canceled, true);
  });

  // EM-2: erfolgreicher Schreibvorgang
  await check('EM-2 gültiges PDF -> Datei geschrieben', async () => {
    const out = path.join(tmpDownloads, 'out.pdf');
    state.saveDialogResult = { canceled: false, filePath: out };
    const good = Buffer.from('%PDF-1.4 hello', 'utf8').toString('base64');
    const r = await savePdf({}, { filename: 'out.pdf', base64: good });
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
    assert.strictEqual(setToken({}, 'secret-123'), true);
    assert.ok(fs.existsSync(tokenFile), 'Token-Datei sollte nach set existieren');

    state.encryptionAvailable = false;          // Encryption „temporär" weg
    const t = getToken({});
    assert.strictEqual(t, null, 'kein Klartext-Token zurückgeben');
    assert.ok(fs.existsSync(tokenFile), 'EM-5: Datei darf NICHT gelöscht werden');

    state.encryptionAvailable = true;            // Recovery
    assert.strictEqual(getToken({}), 'secret-123', 'Token nach Recovery wieder lesbar');
  });

  // EM-2 (Review-LOW): Base64 mit Whitespace/Newlines (tolerant dekodiert) muss
  // jetzt akzeptiert werden — vorher hätte der strikte Round-Trip valide PDFs
  // fälschlich abgelehnt.
  await check('EM-2 Base64 mit Whitespace -> akzeptiert', async () => {
    const out = path.join(tmpDownloads, 'ws.pdf');
    state.saveDialogResult = { canceled: false, filePath: out };
    const raw = Buffer.from('%PDF-1.4 whitespace', 'utf8').toString('base64');
    const chunked = raw.replace(/(.{8})/g, '$1\n');  // Zeilenumbrüche einstreuen
    const r = await savePdf({}, { filename: 'ws.pdf', base64: chunked });
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

  console.log(failed === 0 ? '\nALL GREEN' : `\n${failed} FAILED`);
  process.exit(failed === 0 ? 0 : 1);
})();
