const { app, BrowserWindow, dialog, ipcMain, safeStorage, shell } = require('electron');
const { autoUpdater } = require('electron-updater');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');

function loadEnvIntoProcess() {
  const candidates = [
    path.join(process.cwd(), '.env'),
    path.join(__dirname, '.env'),
  ];

  if (app.isPackaged) {
    candidates.unshift(
      path.join(path.dirname(process.execPath), '.env'),
      path.join(process.resourcesPath, 'backend', '.env')
    );
  }

  for (const envPath of candidates) {
    if (!fs.existsSync(envPath)) continue;
    try {
      const content = fs.readFileSync(envPath, 'utf8');
      for (const rawLine of content.split(/\r?\n/)) {
        const line = rawLine.trim();
        if (!line || line.startsWith('#')) continue;
        const idx = line.indexOf('=');
        if (idx <= 0) continue;
        const key = line.slice(0, idx).trim();
        let value = line.slice(idx + 1).trim();
        if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
          value = value.slice(1, -1);
        }
        if (!(key in process.env)) {
          process.env[key] = value;
        }
      }
    } catch (error) {
      console.error(`Failed to load env file ${envPath}:`, error);
    }
  }
}

loadEnvIntoProcess();

const DEFAULT_BACKEND_HOST = process.env.APP_HOST || '127.0.0.1';
const DEFAULT_BACKEND_PORT = Number.parseInt(process.env.APP_PORT || '8000', 10);
const EXPECTED_BACKEND_APP = process.env.BACKEND_APP_NAME || '5Eyes WealthArchitekten API';
const BACKEND_READY_TIMEOUT_MS = 60_000;
const BACKEND_POLL_INTERVAL_MS = 500;

function isSafeExternalUrl(url) {
  try {
    const parsed = new URL(url);
    return (
      parsed.protocol === 'https:' ||
      (parsed.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(parsed.hostname))
    );
  } catch {
    return false;
  }
}

let mainWindow = null;
let backendProcess = null;
let backendManagedByApp = false;
let isQuitting = false;
let backendRuntime = buildBackendRuntime(DEFAULT_BACKEND_HOST, Number.isFinite(DEFAULT_BACKEND_PORT) ? DEFAULT_BACKEND_PORT : 8000);
let updateState = {
  enabled: false,
  checking: false,
  available: false,
  downloaded: false,
  error: null,
  currentVersion: app.getVersion(),
  latestVersion: null,
  lastCheckedAt: null,
};

function buildBackendRuntime(host, port) {
  const safePort = Number.isFinite(port) ? port : 8000;
  const baseUrl = `http://${host}:${safePort}`;
  return {
    host,
    port: safePort,
    baseUrl,
    healthUrl: `${baseUrl}/health/ready`,
  };
}

function setBackendRuntime(host, port) {
  backendRuntime = buildBackendRuntime(host, port);
  logLine(`Backend runtime configured | base_url=${backendRuntime.baseUrl}`);
  return backendRuntime;
}

function resolveUserLogDir() {
  const logDir = path.join(app.getPath('userData'), 'logs');
  fs.mkdirSync(logDir, { recursive: true });
  return logDir;
}

function resolveElectronLogFile() {
  return path.join(resolveUserLogDir(), 'electron.log');
}

function logLine(message) {
  const line = `${new Date().toISOString()} | ${message}\n`;
  try {
    fs.appendFileSync(resolveElectronLogFile(), line, 'utf8');
  } catch (error) {
    console.error('Failed to write Electron log:', error);
  }
}

function isAutoUpdateEnabled() {
  return app.isPackaged && process.env.ENABLE_AUTO_UPDATE === '1';
}

function notifyRendererUpdateState() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send('updates:state-changed', { ...updateState });
}

function configureAutoUpdates() {
  updateState.enabled = isAutoUpdateEnabled();
  if (!updateState.enabled) {
    logLine('Auto-update disabled (set ENABLE_AUTO_UPDATE=1 in packaged app to enable).');
    return;
  }

  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('checking-for-update', () => {
    updateState = { ...updateState, checking: true, error: null, lastCheckedAt: new Date().toISOString() };
    logLine('Checking for updates');
    notifyRendererUpdateState();
  });

  autoUpdater.on('update-available', (info) => {
    updateState = { ...updateState, checking: false, available: true, downloaded: false, latestVersion: info?.version || null, error: null };
    logLine(`Update available: ${info?.version || 'unknown version'}`);
    notifyRendererUpdateState();
  });

  autoUpdater.on('update-not-available', (info) => {
    updateState = { ...updateState, checking: false, available: false, downloaded: false, latestVersion: info?.version || null, error: null };
    logLine('No update available');
    notifyRendererUpdateState();
  });

  autoUpdater.on('error', (error) => {
    updateState = { ...updateState, checking: false, error: error?.message || String(error) };
    logLine(`Auto-update error: ${error?.message || error}`);
    notifyRendererUpdateState();
  });

  autoUpdater.on('update-downloaded', (info) => {
    updateState = { ...updateState, checking: false, available: true, downloaded: true, latestVersion: info?.version || null, error: null };
    logLine(`Update downloaded: ${info?.version || 'unknown version'}`);
    notifyRendererUpdateState();
  });
}

async function checkForUpdates() {
  if (!updateState.enabled) {
    return { ...updateState, message: 'Auto-update disabled' };
  }
  try {
    const result = await autoUpdater.checkForUpdates();
    return { ...updateState, checkResult: result?.updateInfo || null };
  } catch (error) {
    updateState = { ...updateState, checking: false, error: error?.message || String(error) };
    notifyRendererUpdateState();
    return { ...updateState };
  }
}

const AUTH_TOKEN_STORE_FILE = path.join(app.getPath('userData'), 'auth-token.bin');
// Roadmap #28 (2026-08-08 Backend, 2026-08-09 Frontend): Refresh-Token
// bekommt eine EIGENE, vom Access-Token getrennte Datei -- beide sind
// unterschiedlich langlebige Secrets (Access-Token Minuten/Stunden,
// Refresh-Token Tage) und werden unabhaengig voneinander rotiert/geleert
// (z.B. Logout loescht beide, aber ein abgelaufener Access-Token allein
// loescht den Refresh-Token NICHT -- der wird ja gerade benutzt, um einen
// neuen Access-Token zu holen).
const REFRESH_TOKEN_STORE_FILE = path.join(app.getPath('userData'), 'refresh-token.bin');

// Generische, dateibasierte Secret-Ablage (OS-Keychain/DPAPI via safeStorage)
// -- extrahiert aus der urspruenglichen Access-Token-Implementierung, damit
// der Refresh-Token denselben, bereits gehaerteten Mechanismus 1:1 wiederverwenden
// kann statt ihn zu duplizieren (EM-5-Fix unten gilt dann fuer beide Secrets).
function readStoredSecret(storeFile, label) {
  try {
    if (!fs.existsSync(storeFile)) return null;
    const raw = fs.readFileSync(storeFile);
    if (!raw || raw.length === 0) return null;
    if (safeStorage.isEncryptionAvailable()) {
      return safeStorage.decryptString(raw);
    }
    // EM-5: Encryption nur *vorübergehend* nicht verfügbar (z.B. Keychain/DPAPI noch
    // nicht bereit). writeStoredSecret persistiert NIE Klartext, die Datei ist also
    // immer ein gültiges Ciphertext. Datei daher NICHT löschen — nur ignorieren und
    // re-login erzwingen; sobald safeStorage wieder verfügbar ist, lässt sie sich
    // erneut entschlüsseln. (Vorher: clearStoredSecret() verwarf das Secret unnötig.)
    logLine(`WARNING: safeStorage encryption not available — stored ${label} will not be used this session. User must log in again.`);
    return null;
  } catch (error) {
    // Echte Entschlüsselungs-/Lesefehler eines vorhandenen Ciphertext: Datei ist
    // korrupt/fremd -> bereinigen, damit sie nicht bei jedem Start erneut scheitert.
    logLine(`Failed to read stored ${label} (clearing corrupt file): ${error.message || error}`);
    clearStoredSecret(storeFile, label);
    return null;
  }
}

function writeStoredSecret(storeFile, value, label) {
  try {
    if (!safeStorage.isEncryptionAvailable()) {
      // Refuse to persist secret as plaintext — user will need to log in each session.
      logLine(`WARNING: safeStorage encryption not available — ${label} will not be persisted to disk.`);
      return false;
    }
    fs.mkdirSync(path.dirname(storeFile), { recursive: true });
    const payload = safeStorage.encryptString(String(value || ''));
    fs.writeFileSync(storeFile, payload);
    return true;
  } catch (error) {
    logLine(`Failed to store ${label}: ${error.message || error}`);
    return false;
  }
}

function clearStoredSecret(storeFile, label) {
  try {
    if (fs.existsSync(storeFile)) fs.unlinkSync(storeFile);
    return true;
  } catch (error) {
    logLine(`Failed to clear stored ${label}: ${error.message || error}`);
    return false;
  }
}

function readStoredToken() { return readStoredSecret(AUTH_TOKEN_STORE_FILE, 'token'); }
function writeStoredToken(token) { return writeStoredSecret(AUTH_TOKEN_STORE_FILE, token, 'token'); }
function clearStoredToken() { return clearStoredSecret(AUTH_TOKEN_STORE_FILE, 'token'); }
function readStoredRefreshToken() { return readStoredSecret(REFRESH_TOKEN_STORE_FILE, 'refresh token'); }
function writeStoredRefreshToken(token) { return writeStoredSecret(REFRESH_TOKEN_STORE_FILE, token, 'refresh token'); }
function clearStoredRefreshToken() { return clearStoredSecret(REFRESH_TOKEN_STORE_FILE, 'refresh token'); }

app.setAppUserModelId('ch.5eyes.wealtharchitekten');

// EM-4: Single-Instance-Lock-Ergebnis festhalten. app.quit() ist asynchron, daher
// darf der whenReady-Bootstrap (Backend-Spawn + Fenster) bei fehlendem Lock NICHT
// laufen — sonst startet eine zweite Instanz kurzzeitig ein zweites Backend/Fenster,
// bevor quit greift.
const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) {
  app.quit();
}

function resolveFrontendPath() {
  return path.join(__dirname, 'frontend', '5eyes_v2.html');
}

function resolvePackagedBackendExe() {
  return path.join(process.resourcesPath, 'backend', '5eyes-api.exe');
}

function attachBackendProcessLogging(proc) {
  if (!proc) return;
  const forward = (stream, label) => {
    if (!stream) return;
    stream.on('data', (chunk) => {
      const text = Buffer.isBuffer(chunk) ? chunk.toString('utf8') : String(chunk);
      for (const line of text.split(/\r?\n/)) {
        if (line.trim()) {
          logLine(`[backend:${label}] ${line}`);
        }
      }
    });
  };
  forward(proc.stdout, 'stdout');
  forward(proc.stderr, 'stderr');
  // EM-1: 'error' MUSS behandelt werden — sonst wird ein Spawn-Fehler (dev: python
  // nicht auf PATH -> ENOENT; packaged: exe von AV/EACCES blockiert) als uncaught
  // Exception geworfen und crasht den Electron-Main-Prozess, bevor irgendein Dialog
  // erscheint. Mit Listener läuft waitForBackendReady stattdessen sauber in den Timeout.
  proc.on('error', (err) => {
    logLine(`Backend-Prozess konnte nicht gestartet werden: ${err && err.message ? err.message : err}`);
  });
}

async function resolveFreePort(host) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen({ host, port: 0 }, () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : null;
      server.close(() => {
        if (!port) reject(new Error('No free port could be determined.'));
        else resolve(port);
      });
    });
  });
}

async function isTcpPortInUse(host, port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once('error', (error) => {
      // EM-6: jeder Bind-Fehler bedeutet "Port nicht sicher nutzbar" -> als belegt
      // melden, damit pickBackendRuntime auf einen freien Ephemeral-Port ausweicht.
      // Vorher rejectete ein Nicht-EADDRINUSE-Fehler die Promise und riss den
      // gesamten Bootstrap (-> App-Quit) mit, statt nur den Port-Fallback zu nehmen.
      if (error && error.code !== 'EADDRINUSE') {
        logLine(`Port-Probe ${host}:${port} fehlgeschlagen (${error.code || error.message || error}) — behandle Port als belegt.`);
      }
      resolve(true);
    });
    server.listen({ host, port }, () => {
      server.close(() => resolve(false));
    });
  });
}

function httpGetJson(url) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        let json = null;
        try {
          json = body ? JSON.parse(body) : null;
        } catch (_error) {
          json = null;
        }
        resolve({
          ok: !!(res.statusCode && res.statusCode >= 200 && res.statusCode < 300),
          statusCode: res.statusCode || 0,
          json,
          body,
        });
      });
    });

    req.on('error', (error) => resolve({ ok: false, statusCode: 0, error }));
    req.setTimeout(1500, () => {
      req.destroy();
      resolve({ ok: false, statusCode: 0, timeout: true });
    });
  });
}

async function probeBackend(host, port) {
  const runtime = buildBackendRuntime(host, port);
  const result = await httpGetJson(runtime.healthUrl);
  const appName = result.json && typeof result.json === 'object' ? result.json.app : null;
  const matchesApp = appName === EXPECTED_BACKEND_APP;
  return {
    ...runtime,
    reachable: result.statusCode > 0,
    matchesApp,
    payload: result.json,
    statusCode: result.statusCode,
    error: result.error ? String(result.error.message || result.error) : null,
    ready: result.ok && matchesApp,
  };
}

async function pickBackendRuntime() {
  const defaultProbe = await probeBackend(DEFAULT_BACKEND_HOST, DEFAULT_BACKEND_PORT);
  if (defaultProbe.ready) {
    logLine(`Reusing compatible backend already running at ${defaultProbe.baseUrl}`);
    return defaultProbe;
  }

  const portInUse = await isTcpPortInUse(DEFAULT_BACKEND_HOST, DEFAULT_BACKEND_PORT);
  if (!portInUse) {
    return buildBackendRuntime(DEFAULT_BACKEND_HOST, DEFAULT_BACKEND_PORT);
  }

  logLine(`Default backend port ${DEFAULT_BACKEND_PORT} is occupied by another service; selecting a free local port.`);
  const fallbackPort = await resolveFreePort(DEFAULT_BACKEND_HOST);
  return buildBackendRuntime(DEFAULT_BACKEND_HOST, fallbackPort);
}

function spawnBackendProcess() {
  const childEnv = {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    APP_HOST: backendRuntime.host,
    APP_PORT: String(backendRuntime.port),
  };

  if (app.isPackaged) {
    const backendExe = resolvePackagedBackendExe();
    if (!fs.existsSync(backendExe)) {
      throw new Error(`Bundled backend executable not found: ${backendExe}`);
    }

    logLine(`Starting packaged backend: ${backendExe} on ${backendRuntime.baseUrl}`);
    backendProcess = spawn(backendExe, [], {
      cwd: path.dirname(backendExe),
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      env: childEnv,
    });
    attachBackendProcessLogging(backendProcess);
    backendManagedByApp = true;
    return;
  }

  const backendRoot = path.resolve(__dirname, '..', '5eyes-backend');
  const pythonBin = process.env.PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');
  logLine(`Starting development backend via ${pythonBin} in ${backendRoot} on ${backendRuntime.baseUrl}`);
  backendProcess = spawn(
    pythonBin,
    ['main.py'],
    {
      cwd: backendRoot,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      env: childEnv,
    }
  );
  attachBackendProcessLogging(backendProcess);
  backendManagedByApp = true;
}

// EM-7-Fix: child.killed bedeutet NUR "ein Signal wurde erfolgreich gesendet",
// nicht "der Prozess ist beendet". Für die SIGKILL-Eskalation muss echte
// Lebendigkeit geprüft werden: exitCode/signalCode sind null, solange der
// Prozess läuft, und werden beim Beenden gesetzt.
function backendProcessStillAlive(proc) {
  return !!proc && proc.exitCode === null && proc.signalCode === null;
}

function terminateBackendProcess() {
  if (!backendManagedByApp || !backendProcess || backendProcess.killed) {
    return;
  }

  const pid = backendProcess.pid;
  const proc = backendProcess;
  try {
    logLine(`Terminating managed backend process pid=${pid}`);
    if (process.platform === 'win32') {
      // EM-7: spawnSync-Ergebnis auswerten — taskkill kann fehlschlagen (Prozess
      // schon weg, fehlende Rechte). status/error explizit loggen statt blind
      // anzunehmen, dass terminiert wurde.
      const result = spawnSync('taskkill', ['/pid', String(pid), '/t', '/f'], { windowsHide: true });
      if (result.error) {
        logLine(`taskkill spawn failed for pid=${pid}: ${result.error.message || result.error}`);
      } else if (result.status !== 0) {
        const stderr = result.stderr ? String(result.stderr).trim() : '';
        logLine(`taskkill exited status=${result.status} for pid=${pid}${stderr ? ` (${stderr})` : ''}`);
      }
    } else {
      // EM-7: POSIX-Eskalation SIGTERM -> SIGKILL. Nach kurzer Gnadenfrist
      // hart killen, falls der Prozess SIGTERM ignoriert.
      proc.kill('SIGTERM');
      setTimeout(() => {
        try {
          // EM-7-Fix: NICHT proc.killed prüfen — das ist nach kill('SIGTERM')
          // sofort true (= "Signal gesendet", nicht "Prozess tot"), wodurch die
          // Eskalation nie feuerte. Echte Lebendigkeit über exit-/signalCode.
          if (backendProcessStillAlive(proc)) {
            logLine(`Backend pid=${pid} did not exit on SIGTERM — escalating to SIGKILL`);
            proc.kill('SIGKILL');
          }
        } catch (escErr) {
          logLine(`SIGKILL escalation failed for pid=${pid}: ${escErr.message || escErr}`);
        }
      }, 2000).unref();
    }
  } catch (error) {
    logLine(`Failed to terminate backend process: ${error.message || error}`);
  } finally {
    backendProcess = null;
    backendManagedByApp = false;
  }
}

function sanitizePdfFilename(name) {
  const fallback = `report_${new Date().toISOString().slice(0, 10)}.pdf`;
  const raw = String(name || fallback).trim() || fallback;
  const base = path.basename(raw).replace(/[<>:"/\\|?*\x00-\x1F]/g, '_');
  const withExtension = base.toLowerCase().endsWith('.pdf') ? base : `${base}.pdf`;
  return withExtension.slice(0, 180) || fallback;
}

async function waitForBackendReady() {
  const startedAt = Date.now();
  while (Date.now() - startedAt < BACKEND_READY_TIMEOUT_MS) {
    if (backendManagedByApp && backendProcess && backendProcess.exitCode !== null) {
      throw new Error(`Backend exited early with code ${backendProcess.exitCode}`);
    }

    const probe = await probeBackend(backendRuntime.host, backendRuntime.port);
    if (probe.ready) {
      logLine(`Backend is ready at ${probe.baseUrl}`);
      setBackendRuntime(probe.host, probe.port);
      return;
    }

    await new Promise((resolve) => setTimeout(resolve, BACKEND_POLL_INTERVAL_MS));
  }

  throw new Error(`Backend did not become ready within ${Math.round(BACKEND_READY_TIMEOUT_MS / 1000)} seconds.`);
}

async function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 980,
    minWidth: 1280,
    minHeight: 820,
    autoHideMenuBar: true,
    backgroundColor: '#0f1e34',
    show: false,
    icon: path.join(__dirname, 'assets', 'icons', 'app.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      experimentalFeatures: false,
      devTools: !app.isPackaged,
    },
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    logLine('Main window shown');
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isSafeExternalUrl(url)) {
      shell.openExternal(url);
    }
    return { action: 'deny' };
  });

  mainWindow.webContents.on('will-navigate', (event, url) => {
    const localEntry = `file://${resolveFrontendPath().replace(/\\/g, '/')}`;
    if (url !== localEntry) {
      event.preventDefault();
      if (isSafeExternalUrl(url)) {
        shell.openExternal(url);
      }
    }
  });

  mainWindow.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    const severity = ['verbose', 'info', 'warning', 'error'][level] || String(level);
    logLine(`Renderer ${severity}: ${message} (${sourceId || 'unknown'}:${line || 0})`);
  });

  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    logLine(`Renderer process gone: ${JSON.stringify(details || {})}`);
  });

  // Intro bei jedem echten Desktop-Start zeigen. Das Query-Flag umgeht nur
  // den persistenten Renderer-Sessionstatus; Reloads innerhalb derselben
  // laufenden App werden dadurch nicht zusätzlich ausgelöst.
  await mainWindow.loadFile(resolveFrontendPath(), {
    query: { intro: '1' },
  });
}

async function bootstrap() {
  const selectedRuntime = await pickBackendRuntime();
  setBackendRuntime(selectedRuntime.host, selectedRuntime.port);

  if (selectedRuntime.ready) {
    logLine(`Reusing already running backend at ${selectedRuntime.baseUrl}`);
  } else {
    spawnBackendProcess();

    if (backendManagedByApp && backendProcess) {
      backendProcess.on('exit', (code, signal) => {
        logLine(`Backend process exited code=${code ?? 'n/a'} signal=${signal ?? 'n/a'}`);
        if (!isQuitting) {
          dialog.showErrorBox(
            'Backend beendet',
            `Der lokale Python-Server wurde unerwartet beendet. Code: ${code ?? 'n/a'}, Signal: ${signal ?? 'n/a'}.`
          );
          app.quit();
        }
      });
    }
  }

  await waitForBackendReady();
  await createMainWindow();
  notifyRendererUpdateState();
}

ipcMain.handle('app:get-version', () => app.getVersion());
ipcMain.handle('backend:get-base-url', () => backendRuntime.baseUrl);
ipcMain.handle('backend:get-runtime', () => ({ ...backendRuntime }));
ipcMain.handle('backend:health', async () => probeBackend(backendRuntime.host, backendRuntime.port));
ipcMain.handle('shell:open-external', async (_event, targetUrl) => {
  if (!isSafeExternalUrl(targetUrl)) {
    return false;
  }
  await shell.openExternal(targetUrl);
  return true;
});
ipcMain.handle('auth:get-token', () => readStoredToken());
ipcMain.handle('auth:set-token', (_event, token) => writeStoredToken(token));
ipcMain.handle('auth:clear-token', () => clearStoredToken());
// Roadmap #28 (2026-08-09 Frontend-Wiring): Refresh-Token separat gespeichert,
// siehe Kommentar bei REFRESH_TOKEN_STORE_FILE weiter oben.
ipcMain.handle('auth:get-refresh-token', () => readStoredRefreshToken());
ipcMain.handle('auth:set-refresh-token', (_event, token) => writeStoredRefreshToken(token));
ipcMain.handle('auth:clear-refresh-token', () => clearStoredRefreshToken());
ipcMain.handle('file:save-pdf', async (_event, payload) => {
  // EM-2: Handler-Body komplett in try/catch — fehlende Daten und fs-Fehler
  // (ENOSPC, EACCES/EPERM auf gewähltem Pfad) als strukturiertes Ergebnis
  // zurückgeben statt als rejected Promise, das der Renderer als unbehandelte
  // Exception sieht.
  try {
    const filename = sanitizePdfFilename(payload && payload.filename);
    const base64 = String((payload && payload.base64) || '');
    if (!base64) {
      return { ok: false, error: 'PDF-Daten fehlen.' };
    }
    // Base64 validieren: zuerst Whitespace/Zeilenumbrüche entfernen (manche Renderer
    // chunken Base64), DANN Round-Trip-Vergleich. So werden valide, nur anders
    // formatierte PDFs akzeptiert, echter Müll (Nicht-Base64) aber weiterhin
    // abgelehnt — Buffer.from ist beim Dekodieren tolerant und würde sonst Bytes
    // aus Garbage erzeugen.
    const compact = base64.replace(/\s+/g, '');
    const buffer = Buffer.from(compact, 'base64');
    if (buffer.length === 0 || buffer.toString('base64').replace(/=+$/, '') !== compact.replace(/=+$/, '')) {
      return { ok: false, error: 'PDF-Daten sind ungültig (kein valides Base64).' };
    }
    const target = await dialog.showSaveDialog(mainWindow || undefined, {
      title: 'PDF speichern',
      defaultPath: path.join(app.getPath('downloads'), filename),
      filters: [{ name: 'PDF', extensions: ['pdf'] }],
    });
    if (target.canceled || !target.filePath) {
      return { ok: false, canceled: true };
    }
    await fs.promises.writeFile(target.filePath, buffer);
    return { ok: true, path: target.filePath };
  } catch (error) {
    logLine(`file:save-pdf failed: ${error && error.message ? error.message : error}`);
    return { ok: false, error: String((error && error.message) || error) };
  }
});
ipcMain.handle('updates:get-state', () => ({ ...updateState }));
ipcMain.handle('updates:check', async () => checkForUpdates());
ipcMain.handle('updates:install-downloaded', async () => {
  if (updateState.downloaded) {
    setImmediate(() => autoUpdater.quitAndInstall(false, true));
    return { ok: true };
  }
  return { ok: false, message: 'No downloaded update available.' };
});

// Sprint U-61 (2026-06-01): Globaler Security-Hook fuer alle WebContents.
// Greift auch fuer kuenftige Fenster/PDF-Viewer/etc. — zentraler Audit-Punkt.
app.on('web-contents-created', (_event, contents) => {
  // 1. Permission-Requests (geolocation, notifications, midi, media, ...)
  //    -> default deny. Whitelist hinzufuegen wenn ein konkreter Use-Case kommt.
  contents.session.setPermissionRequestHandler((_wc, _permission, callback) => {
    callback(false);
  });

  // 2. Globaler will-navigate-Filter (zusaetzlich zum window-spezifischen Hook).
  contents.on('will-navigate', (event, url) => {
    const localEntry = `file://${resolveFrontendPath().replace(/\\/g, '/')}`;
    if (url !== localEntry) {
      event.preventDefault();
      if (isSafeExternalUrl(url)) {
        shell.openExternal(url);
      }
    }
  });

  // 3. setWindowOpenHandler global — alle Popups/window.open() -> deny + Shell.
  contents.setWindowOpenHandler(({ url }) => {
    if (isSafeExternalUrl(url)) {
      shell.openExternal(url);
    }
    return { action: 'deny' };
  });

  // 4. WebView-Attachments blockieren (FINMA: keine eingebetteten Renderer).
  contents.on('will-attach-webview', (event, webPreferences, _params) => {
    event.preventDefault();
    delete webPreferences.preload;
    webPreferences.nodeIntegration = false;
    webPreferences.contextIsolation = true;
    webPreferences.sandbox = true;
  });
});

app.whenReady().then(async () => {
  // EM-4: zweite Instanz hat keinen Lock — Bootstrap überspringen (quit läuft bereits).
  if (!hasSingleInstanceLock) return;
  try {
    logLine(`App starting | version=${app.getVersion()} packaged=${app.isPackaged}`);
    configureAutoUpdates();
    await bootstrap();
    if (updateState.enabled) {
      void checkForUpdates();
    }
  } catch (error) {
    logLine(`App bootstrap failed: ${error.message || error}`);
    terminateBackendProcess();
    dialog.showErrorBox('App-Start fehlgeschlagen', String(error.message || error));
    app.quit();
  }
});

app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.focus();
  }
});

app.on('before-quit', () => {
  isQuitting = true;
  terminateBackendProcess();
});

app.on('window-all-closed', () => {
  app.quit();
});

app.on('activate', async () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    await createMainWindow();
  }
});

// Nur für Tests exportiert (Electron ignoriert module.exports am Entrypoint).
// Erlaubt das deterministische Prüfen der EM-7-Lebendigkeitslogik.
if (typeof module !== 'undefined' && module.exports) {
  module.exports.backendProcessStillAlive = backendProcessStillAlive;
}
