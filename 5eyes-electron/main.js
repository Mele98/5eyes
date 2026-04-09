const { app, BrowserWindow, dialog, ipcMain, safeStorage, shell } = require('electron');
const { autoUpdater } = require('electron-updater');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');

function isSafeExternalUrl(url) {
  try {
    const parsed = new URL(url);
    return (
      parsed.protocol === 'https:' ||
      (parsed.protocol === 'http:' && parsed.hostname === 'localhost')
    );
  } catch {
    return false;
  }
}

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

function readStoredToken() {
  try {
    if (!fs.existsSync(AUTH_TOKEN_STORE_FILE)) return null;
    const raw = fs.readFileSync(AUTH_TOKEN_STORE_FILE);
    if (!raw || raw.length === 0) return null;
    if (safeStorage.isEncryptionAvailable()) {
      return safeStorage.decryptString(raw);
    }
    return raw.toString('utf8');
  } catch (error) {
    logLine(`Failed to read stored token: ${error.message || error}`);
    return null;
  }
}

function writeStoredToken(token) {
  try {
    fs.mkdirSync(path.dirname(AUTH_TOKEN_STORE_FILE), { recursive: true });
    const payload = safeStorage.isEncryptionAvailable()
      ? safeStorage.encryptString(String(token || ''))
      : Buffer.from(String(token || ''), 'utf8');
    fs.writeFileSync(AUTH_TOKEN_STORE_FILE, payload);
    return true;
  } catch (error) {
    logLine(`Failed to store token: ${error.message || error}`);
    return false;
  }
}

function clearStoredToken() {
  try {
    if (fs.existsSync(AUTH_TOKEN_STORE_FILE)) fs.unlinkSync(AUTH_TOKEN_STORE_FILE);
    return true;
  } catch (error) {
    logLine(`Failed to clear stored token: ${error.message || error}`);
    return false;
  }
}

app.setAppUserModelId('ch.5eyes.wealtharchitekten');

if (!app.requestSingleInstanceLock()) {
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
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once('error', (error) => {
      if (error && error.code === 'EADDRINUSE') resolve(true);
      else reject(error);
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

function terminateBackendProcess() {
  if (!backendManagedByApp || !backendProcess || backendProcess.killed) {
    return;
  }

  const pid = backendProcess.pid;
  try {
    logLine(`Terminating managed backend process pid=${pid}`);
    if (process.platform === 'win32') {
      spawnSync('taskkill', ['/pid', String(pid), '/t', '/f'], { windowsHide: true });
    } else {
      backendProcess.kill('SIGTERM');
    }
  } catch (error) {
    logLine(`Failed to terminate backend process: ${error.message || error}`);
  } finally {
    backendProcess = null;
    backendManagedByApp = false;
  }
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
      if (/^https?:/i.test(url)) {
        shell.openExternal(url);
      }
    }
  });

  await mainWindow.loadFile(resolveFrontendPath());
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
ipcMain.handle('updates:get-state', () => ({ ...updateState }));
ipcMain.handle('updates:check', async () => checkForUpdates());
ipcMain.handle('updates:install-downloaded', async () => {
  if (updateState.downloaded) {
    setImmediate(() => autoUpdater.quitAndInstall(false, true));
    return { ok: true };
  }
  return { ok: false, message: 'No downloaded update available.' };
});

app.whenReady().then(async () => {
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
