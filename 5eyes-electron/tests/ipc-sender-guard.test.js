/**
 * A3 P2-5 / U-6: IPC-Absender-Pruefung.
 *
 * Teil 1: reine Validierungsfunktion (ipc-sender-guard.js).
 * Teil 2: Verdrahtung in main.js mit gestubbtem `electron` -- JEDER
 *         registrierte Kanal lehnt fremde Absender ab, der Push-Kanal sendet
 *         nur an die lokale Entry, und preload.js nutzt nur bekannte Kanaele.
 *
 * Lauf: `node --test tests/ipc-sender-guard.test.js` (keine Abhaengigkeit,
 * kein echtes Electron, App wird nicht gestartet).
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const Module = require('module');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { pathToFileURL } = require('url');

const guard = require(path.join(__dirname, '..', 'ipc-sender-guard.js'));
const { checkTrustedRendererUrl, checkTrustedIpcSender, describeSenderForLog } = guard;

const WIN_ENTRY = 'C:\\Program Files\\App\\resources\\app.asar\\frontend\\index_v2.html';
const WIN_URL = 'file:///C:/Program%20Files/App/resources/app.asar/frontend/index_v2.html';
const POSIX_ENTRY = '/opt/App/resources/app.asar/frontend/index_v2.html';
const POSIX_URL = 'file:///opt/App/resources/app.asar/frontend/index_v2.html';

function frameEvent(url, parent = null) {
  return { senderFrame: { url, parent } };
}

// ── Teil 1: Validierungsfunktion ────────────────────────────────────────────
test('gueltige Entry (Windows) inkl. ?intro=1 und Fragment wird akzeptiert', () => {
  assert.deepStrictEqual(checkTrustedRendererUrl(WIN_URL, WIN_ENTRY, 'win32'), { ok: true });
  assert.deepStrictEqual(checkTrustedRendererUrl(`${WIN_URL}?intro=1`, WIN_ENTRY, 'win32'), { ok: true });
  assert.deepStrictEqual(checkTrustedRendererUrl(`${WIN_URL}?intro=1#client/7`, WIN_ENTRY, 'win32'), { ok: true });
});

test('gueltige Entry (POSIX) wird akzeptiert', () => {
  assert.deepStrictEqual(checkTrustedRendererUrl(`${POSIX_URL}?intro=1`, POSIX_ENTRY, 'linux'), { ok: true });
});

test('Umlaut/Leerzeichen im Pfad: unterschiedliche Kodierung bleibt derselbe Absender', () => {
  const entry = 'C:\\Daten\\Müller Hans\\App\\frontend\\index_v2.html';
  assert.strictEqual(checkTrustedRendererUrl('file:///C:/Daten/M%C3%BCller%20Hans/App/frontend/index_v2.html', entry, 'win32').ok, true);
  assert.strictEqual(checkTrustedRendererUrl('file:///home/M%C3%BCller%20Hans/index_v2.html', '/home/Müller Hans/index_v2.html', 'linux').ok, true);
});

test('fremde URLs werden abgelehnt (http, https, data, about, javascript, devtools)', () => {
  for (const url of [
    'http://127.0.0.1:8000/app/index_v2.html',
    'https://example.org/frontend/index_v2.html',
    'data:text/html,<script>1</script>',
    'about:blank',
    'javascript:alert(1)',
    'devtools://devtools/bundled/inspector.html',
  ]) {
    const verdict = checkTrustedRendererUrl(url, WIN_ENTRY, 'win32');
    assert.strictEqual(verdict.ok, false, url);
  }
});

test('andere lokale Datei wird abgelehnt', () => {
  assert.deepStrictEqual(
    checkTrustedRendererUrl('file:///C:/Program%20Files/App/resources/app.asar/frontend/evil.html', WIN_ENTRY, 'win32'),
    { ok: false, reason: 'path' },
  );
  assert.strictEqual(checkTrustedRendererUrl('file:///C:/Daten/x/Downloads/index_v2.html', WIN_ENTRY, 'win32').ok, false);
});

test('Pfad-Tricks mit .. und %2e%2e: nur wenn sie exakt auf die Entry aufloesen', () => {
  // Normalisiert auf die Entry -> dieselbe Datei -> erlaubt.
  assert.strictEqual(
    checkTrustedRendererUrl('file:///C:/Program%20Files/App/resources/app.asar/frontend/../frontend/index_v2.html', WIN_ENTRY, 'win32').ok,
    true,
  );
  // Entry-Name als Verzeichnis missbraucht -> fremde Datei.
  assert.strictEqual(
    checkTrustedRendererUrl(`${WIN_URL}/../../evil.html`, WIN_ENTRY, 'win32').ok,
    false,
  );
  assert.strictEqual(
    checkTrustedRendererUrl('file:///C:/Program%20Files/App/resources/app.asar/frontend/%2e%2e/evil/index_v2.html', WIN_ENTRY, 'win32').ok,
    false,
  );
  assert.strictEqual(
    checkTrustedRendererUrl(`${POSIX_URL}/../../../../etc/passwd`, POSIX_ENTRY, 'linux').ok,
    false,
  );
});

test('kodierte Separatoren und NUL werden abgelehnt', () => {
  assert.deepStrictEqual(
    checkTrustedRendererUrl('file:///C:/Program%20Files/App/resources/app.asar%2Ffrontend%2Findex_v2.html', WIN_ENTRY, 'win32'),
    { ok: false, reason: 'path-encoding' },
  );
  assert.strictEqual(
    checkTrustedRendererUrl('file:///C:/Program%20Files/App/resources/app.asar/frontend%5Cindex_v2.html', WIN_ENTRY, 'win32').ok,
    false,
  );
  assert.strictEqual(checkTrustedRendererUrl(`${POSIX_URL}%00.png`, POSIX_ENTRY, 'linux').ok, false);
  assert.strictEqual(checkTrustedRendererUrl('file:///opt/%E0%A4%A', POSIX_ENTRY, 'linux').ok, false);
});

test('Gross-/Kleinschreibung: Windows case-insensitiv, POSIX exakt', () => {
  assert.strictEqual(
    checkTrustedRendererUrl('file:///c:/PROGRAM%20FILES/App/resources/app.asar/frontend/INDEX_V2.html', WIN_ENTRY, 'win32').ok,
    true,
  );
  assert.deepStrictEqual(
    checkTrustedRendererUrl('file:///opt/App/resources/app.asar/frontend/INDEX_V2.html', POSIX_ENTRY, 'linux'),
    { ok: false, reason: 'path' },
  );
});

test('Query/Fragment koennen keinen fremden Pfad einschmuggeln', () => {
  assert.strictEqual(
    checkTrustedRendererUrl(`file:///C:/evil.html?x=${encodeURIComponent(WIN_URL)}`, WIN_ENTRY, 'win32').ok,
    false,
  );
  assert.strictEqual(
    checkTrustedRendererUrl(`file:///C:/evil.html#${WIN_URL}`, WIN_ENTRY, 'win32').ok,
    false,
  );
});

test('UNC-Host und Credentials werden abgelehnt', () => {
  assert.deepStrictEqual(
    checkTrustedRendererUrl('file://attacker-host/C:/Program%20Files/App/resources/app.asar/frontend/index_v2.html', WIN_ENTRY, 'win32'),
    { ok: false, reason: 'host' },
  );
  assert.strictEqual(checkTrustedRendererUrl('file://localhost/opt/App/resources/app.asar/frontend/index_v2.html', POSIX_ENTRY, 'linux').ok, true,
    'WHATWG normalisiert file://localhost auf leeren Host (dieselbe lokale Datei)');
});

test('ungueltige Eingaben werden abgelehnt', () => {
  assert.strictEqual(checkTrustedRendererUrl('', WIN_ENTRY, 'win32').ok, false);
  assert.strictEqual(checkTrustedRendererUrl(undefined, WIN_ENTRY, 'win32').ok, false);
  assert.strictEqual(checkTrustedRendererUrl('not a url', WIN_ENTRY, 'win32').ok, false);
  assert.strictEqual(checkTrustedRendererUrl(WIN_URL, '', 'win32').ok, false);
});

test('Event: null/fehlender senderFrame wird abgelehnt', () => {
  assert.deepStrictEqual(checkTrustedIpcSender(null, WIN_ENTRY, 'win32'), { ok: false, reason: 'no-sender-frame' });
  assert.deepStrictEqual(checkTrustedIpcSender({}, WIN_ENTRY, 'win32'), { ok: false, reason: 'no-sender-frame' });
  assert.deepStrictEqual(checkTrustedIpcSender({ senderFrame: null }, WIN_ENTRY, 'win32'), { ok: false, reason: 'no-sender-frame' });
});

test('Event: Subframe mit Entry-URL wird abgelehnt, Top-Level akzeptiert', () => {
  const parent = { url: WIN_URL, parent: null };
  assert.deepStrictEqual(checkTrustedIpcSender(frameEvent(WIN_URL, parent), WIN_ENTRY, 'win32'), { ok: false, reason: 'subframe' });
  assert.deepStrictEqual(checkTrustedIpcSender(frameEvent(`${WIN_URL}?intro=1`), WIN_ENTRY, 'win32'), { ok: true });
});

test('Log-Beschreibung enthaelt weder Pfad noch Query noch Fragment', () => {
  const desc = describeSenderForLog(frameEvent('https://example.org/secret/path?token=abc#token=def'));
  assert.strictEqual(desc, 'sender=https://example.org top_level=yes');
  assert.ok(!/token|secret|abc|def/.test(desc));
  assert.strictEqual(describeSenderForLog({}), 'sender=none');
  assert.strictEqual(describeSenderForLog(frameEvent('%%%')), 'sender=invalid top_level=yes');
});

// ── Teil 2: Verdrahtung in main.js ──────────────────────────────────────────
const tmpUserData = fs.mkdtempSync(path.join(os.tmpdir(), 'ipc-guard-userdata-'));
const ipcHandlers = {};
const sentMessages = [];
const fakeWindow = {
  currentUrl: '',
  isDestroyed: () => false,
  webContents: {
    getURL: () => fakeWindow.currentUrl,
    send: (channel, payload) => sentMessages.push({ channel, payload }),
  },
};
let appReadyCallback = null;
const appListeners = {};
const openedExternally = [];
const electronStub = {
  app: {
    getPath: () => tmpUserData,
    getVersion: () => '0.0.0-test',
    isPackaged: false,
    setAppUserModelId() {},
    requestSingleInstanceLock: () => true,
    whenReady: () => ({ then: (cb) => { appReadyCallback = cb; } }),
    on: (eventName, fn) => { appListeners[eventName] = fn; },
    quit() {},
  },
  BrowserWindow: class { static getAllWindows() { return []; } },
  dialog: { showSaveDialog: async () => ({ canceled: true }), showErrorBox() {} },
  ipcMain: { handle: (ch, fn) => { ipcHandlers[ch] = fn; } },
  safeStorage: {
    isEncryptionAvailable: () => true,
    getSelectedStorageBackend: () => 'dpapi',
    encryptString: (s) => Buffer.from(`enc:${s}`, 'utf8'),
    decryptString: (buf) => String(buf).replace(/^enc:/, ''),
  },
  shell: { openExternal: async (url) => { openedExternally.push(url); return true; } },
};
const updaterStub = { autoUpdater: { on() {}, checkForUpdates() {}, quitAndInstall() {} } };

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'electron') return electronStub;
  if (request === 'electron-updater') return updaterStub;
  return originalLoad.call(this, request, parent, isMain);
};
const mainExports = require(path.join(__dirname, '..', 'main.js'));
Module._load = originalLoad;
void appReadyCallback; // bootstrap (Backend-Spawn) wird bewusst nie ausgefuehrt

const entryPath = mainExports.resolveFrontendPath();
const trustedUrl = `${pathToFileURL(entryPath).href}?intro=1`;
const trustedEvent = frameEvent(trustedUrl);
const untrustedEvents = {
  'fremde https-Seite': frameEvent('https://example.org/'),
  'andere lokale Datei': frameEvent(pathToFileURL(path.join(path.dirname(entryPath), 'evil.html')).href),
  'Subframe der Entry': frameEvent(trustedUrl, { url: trustedUrl, parent: null }),
  'null senderFrame': { senderFrame: null },
  'Event ohne senderFrame': {},
};

const preloadSource = fs.readFileSync(path.join(__dirname, '..', 'preload.js'), 'utf8');
const preloadInvokeChannels = [...preloadSource.matchAll(/ipcRenderer\.invoke\('([^']+)'/g)].map((m) => m[1]);
const preloadOnChannels = [...preloadSource.matchAll(/ipcRenderer\.on\('([^']+)'/g)].map((m) => m[1]);

test('main.js registriert genau die Kanaele, die preload.js aufruft', () => {
  assert.ok(preloadInvokeChannels.length >= 15, 'preload-Kanaele nicht gefunden');
  assert.deepStrictEqual(Object.keys(ipcHandlers).sort(), [...new Set(preloadInvokeChannels)].sort());
});

test('preload.js: keine generische invoke/send-Bruecke (nur feste Kanal-Literale)', () => {
  const allInvokes = preloadSource.match(/ipcRenderer\.\w+\(/g) || [];
  const literalCalls = preloadSource.match(/ipcRenderer\.(invoke|on|removeListener)\('[^']+'/g) || [];
  assert.strictEqual(allInvokes.length, literalCalls.length, 'jeder ipcRenderer-Aufruf braucht ein festes Kanal-Literal');
  assert.ok(!/ipcRenderer\.(send|sendSync|postMessage)\(/.test(preloadSource));
  assert.deepStrictEqual(preloadOnChannels, ['updates:state-changed']);
});

test('JEDER Kanal lehnt fremde Absender ab, ohne den Handler auszufuehren', async () => {
  const tokenFile = path.join(tmpUserData, 'auth-token.bin');
  fs.writeFileSync(tokenFile, Buffer.from('enc:stored-secret', 'utf8'));
  for (const channel of Object.keys(ipcHandlers)) {
    for (const [label, event] of Object.entries(untrustedEvents)) {
      await assert.rejects(
        async () => ipcHandlers[channel](event, 'payload'),
        /IPC sender not allowed/,
        `${channel} muss ${label} ablehnen`,
      );
    }
  }
  // Seiteneffekt-Kontrolle: clear-token eines fremden Absenders hat die Datei nicht geloescht.
  assert.ok(fs.existsSync(tokenFile));
});

test('Ablehnung wird ohne Geheimnisse geloggt', async () => {
  const logFile = path.join(tmpUserData, 'logs', 'electron.log');
  const evil = frameEvent('https://example.org/x?token=leak-me#token=leak-me-too');
  await assert.rejects(async () => ipcHandlers['auth:set-token'](evil, 'my-secret-token'), /IPC sender not allowed/);
  const log = fs.readFileSync(logFile, 'utf8');
  assert.match(log, /IPC rejected \| channel=auth:set-token reason=protocol sender=https:\/\/example\.org top_level=yes/);
  assert.ok(!log.includes('leak-me'), 'Query/Fragment duerfen nicht ins Log');
  assert.ok(!log.includes('my-secret-token'), 'Argumente duerfen nicht ins Log');
});

test('vertrauter Absender (Entry, Top-Level) erreicht den Handler unveraendert', async () => {
  assert.strictEqual(ipcHandlers['app:get-version'](trustedEvent), '0.0.0-test');
  assert.strictEqual(ipcHandlers['auth:set-token'](trustedEvent, 'token-xyz'), true);
  assert.strictEqual(ipcHandlers['auth:get-token'](trustedEvent), 'token-xyz');
  assert.strictEqual(ipcHandlers['auth:set-refresh-token'](trustedEvent, 'refresh-xyz'), true);
  assert.strictEqual(ipcHandlers['auth:get-refresh-token'](trustedEvent), 'refresh-xyz');
  assert.strictEqual(ipcHandlers['auth:clear-token'](trustedEvent), true);
  assert.strictEqual(ipcHandlers['auth:get-token'](trustedEvent), null);
  assert.strictEqual(await ipcHandlers['shell:open-external'](trustedEvent, 'javascript:alert(1)'), false);
  const state = ipcHandlers['updates:get-state'](trustedEvent);
  assert.strictEqual(state.enabled, false);
});

test('Push-Kanal sendet nur an ein Fenster, das die lokale Entry zeigt', () => {
  mainExports._setMainWindowForTest(fakeWindow);
  try {
    sentMessages.length = 0;
    fakeWindow.currentUrl = 'https://example.org/';
    mainExports.notifyRendererUpdateState();
    assert.strictEqual(sentMessages.length, 0, 'fremde Seite darf keinen Push bekommen');

    fakeWindow.currentUrl = '';
    mainExports.notifyRendererUpdateState();
    assert.strictEqual(sentMessages.length, 0, 'noch nicht geladenes Fenster bekommt keinen Push');

    fakeWindow.currentUrl = trustedUrl;
    mainExports.notifyRendererUpdateState();
    assert.strictEqual(sentMessages.length, 1);
    assert.strictEqual(sentMessages[0].channel, 'updates:state-changed');
  } finally {
    mainExports._setMainWindowForTest(null);
  }
});

// ── Teil 3: Navigation (ELECTRON-NAV-URL-001) ───────────────────────────────
// will-navigate, will-redirect und window.open entscheiden ueber dieselbe
// Pruefung (checkTrustedRendererUrl): nur die lokale Entry (inkl. Query und
// Fragment) darf geladen werden; erlaubte externe Links gehen an den
// System-Browser, alles andere wird verhindert.

test('Navigationsziele (Windows): Laufwerksbuchstabe, Schreibweise, Kodierung, .., UNC', () => {
  const ok = (url) => checkTrustedRendererUrl(url, WIN_ENTRY, 'win32').ok;
  // Entry in Chromium-Form, mit Query/Fragment, kleiner Laufwerksbuchstabe.
  assert.strictEqual(ok(`${WIN_URL}?intro=1#mandate/3`), true);
  assert.strictEqual(ok('file:///c:/Program%20Files/App/resources/app.asar/frontend/index_v2.html'), true);
  // Zwei-Slash-Form, wie sie der fruehere String-Vergleich erzeugte: der
  // URL-Parser erkennt den Laufwerksbuchstaben, dieselbe Datei bleibt erlaubt.
  assert.strictEqual(ok('file://C:/Program Files/App/resources/app.asar/frontend/index_v2.html'), true);
  // Kodierte, aber unkritische Zeichen adressieren dieselbe Datei.
  assert.strictEqual(ok('file:///C:/Program%20Files/App/resources/app.asar/frontend/index%5Fv2.html'), true);
  // `..` wird aufgeloest: zurueck zur Entry ist erlaubt, heraus nicht.
  assert.strictEqual(ok('file:///C:/Program%20Files/App/resources/app.asar/x/../frontend/index_v2.html'), true);
  assert.strictEqual(ok(`${WIN_URL}/../../../../../Windows/win.ini`), false);
  assert.strictEqual(ok('file:///C:/Program%20Files/App/resources/app.asar/frontend/%2E%2E/%2E%2E/evil.html'), false);
  // UNC in allen Schreibweisen.
  assert.strictEqual(ok('file://fileserver/share/frontend/index_v2.html'), false);
  assert.strictEqual(ok('file:////fileserver/share/frontend/index_v2.html'), false);
  assert.strictEqual(ok('file:///%5C%5Cfileserver/share/frontend/index_v2.html'), false);
  // Fremde file-URL auf anderem Laufwerk / gleicher Dateiname anderswo.
  assert.strictEqual(ok('file:///D:/Program%20Files/App/resources/app.asar/frontend/index_v2.html'), false);
  assert.strictEqual(ok('file:///C:/Users/Public/index_v2.html'), false);
});

test('Navigationsziele: fremde Schemata werden nie als Entry erkannt', () => {
  for (const url of [
    'https://example.org/',
    'http://localhost:8000/app/index_v2.html',
    'javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'blob:file:///6d4c-11ee',
    'about:blank',
    `view-source:${WIN_URL}`,
  ]) {
    assert.strictEqual(checkTrustedRendererUrl(url, WIN_ENTRY, 'win32').ok, false, url);
  }
});

function fakeWebContents() {
  const listeners = {};
  const contents = {
    listeners,
    windowOpenHandler: null,
    session: { setPermissionRequestHandler() {} },
    on(eventName, fn) { (listeners[eventName] = listeners[eventName] || []).push(fn); },
    setWindowOpenHandler(fn) { contents.windowOpenHandler = fn; },
  };
  appListeners['web-contents-created']({}, contents);
  return contents;
}

function fire(contents, eventName, url) {
  const handlers = contents.listeners[eventName] || [];
  assert.ok(handlers.length > 0, `${eventName}-Hook fehlt`);
  let prevented = 0;
  const event = { url, preventDefault: () => { prevented += 1; } };
  for (const fn of handlers) fn(event, url);
  return prevented > 0;
}

const entryUrl = pathToFileURL(entryPath).href;
const navCases = [
  // [Bezeichnung, URL, erlaubt?, an System-Browser?]
  ['Entry', entryUrl, true, false],
  ['Entry mit ?intro=1', `${entryUrl}?intro=1`, true, false],
  ['Entry mit Fragment', `${entryUrl}#client/7`, true, false],
  ['andere Datei im Frontend-Ordner', pathToFileURL(path.join(path.dirname(entryPath), 'evil.html')).href, false, false],
  ['fremde file-URL', pathToFileURL(path.join(os.tmpdir(), 'evil.html')).href, false, false],
  ['UNC-Host', 'file://fileserver/share/index_v2.html', false, false],
  ['Entry ueber .. verlassen', `${entryUrl}/../../evil.html`, false, false],
  ['https', 'https://example.org/docs', false, true],
  ['http localhost', 'http://localhost:8000/docs', false, true],
  ['http fremder Host', 'http://example.org/', false, false],
  ['javascript:', 'javascript:alert(1)', false, false],
  ['data:', 'data:text/html,<h1>x</h1>', false, false],
];

for (const eventName of ['will-navigate', 'will-redirect']) {
  test(`${eventName}: nur die lokale Entry wird geladen, erlaubte Links gehen an den System-Browser`, () => {
    const contents = fakeWebContents();
    for (const [label, url, allowed, external] of navCases) {
      openedExternally.length = 0;
      const prevented = fire(contents, eventName, url);
      assert.strictEqual(prevented, !allowed, `${label}: ${allowed ? 'muss erlaubt' : 'muss verhindert'} werden`);
      assert.deepStrictEqual(openedExternally, external ? [url] : [], `${label}: System-Browser`);
    }
  });
}

if (process.platform === 'win32') {
  test('will-navigate (Windows): Entry in anderer Schreibweise bleibt erlaubt', () => {
    const contents = fakeWebContents();
    assert.strictEqual(fire(contents, 'will-navigate', entryUrl.toUpperCase().replace(/^FILE:/, 'file:')), false);
  });
}

test('window.open: nie ein neues Fenster; erlaubte Links genau einmal an den System-Browser', () => {
  const contents = fakeWebContents();
  assert.strictEqual(typeof contents.windowOpenHandler, 'function', 'setWindowOpenHandler fehlt');
  for (const [label, url, , external] of navCases) {
    openedExternally.length = 0;
    assert.deepStrictEqual(contents.windowOpenHandler({ url }), { action: 'deny' }, label);
    assert.deepStrictEqual(openedExternally, external ? [url] : [], `${label}: System-Browser`);
  }
});
