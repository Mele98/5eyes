(function () {
  async function resolveBaseUrl() {
    if (window.desktop && typeof window.desktop.getBackendBaseUrl === 'function') {
      return window.desktop.getBackendBaseUrl();
    }
    // Browser-Hosting (Tunnel/Server, 2026-06-18): ohne Electron-Bridge wird die
    // App ueber das Backend ausgeliefert -> die API ist SAME-ORIGIN wie das HTML,
    // NICHT 127.0.0.1 (das waere der localhost des Remote-Browsers -> "Backend
    // nicht erreichbar"). Nur der echte file://-Electron-Dev-Fall faellt auf
    // 127.0.0.1:8000 zurueck.
    if (typeof window !== 'undefined' && window.location &&
        (window.location.protocol === 'http:' || window.location.protocol === 'https:')) {
      return window.location.origin;
    }
    return 'http://127.0.0.1:8000';
  }

  async function apiFetch(path, options) {
    const baseUrl = await resolveBaseUrl();
    const response = await fetch(`${baseUrl}${path}`, options);
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`API ${response.status}: ${text}`);
    }
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      return response.json();
    }
    return response.text();
  }

  async function getBackendRuntime() {
    if (window.desktop && typeof window.desktop.getBackendRuntime === 'function') {
      return window.desktop.getBackendRuntime();
    }
    return { host: '127.0.0.1', port: 8000, baseUrl: await resolveBaseUrl() };
  }

  async function getUpdateState() {
    if (window.desktop && typeof window.desktop.getUpdateState === 'function') {
      return window.desktop.getUpdateState();
    }
    return { enabled: false, checking: false, available: false, downloaded: false };
  }

  async function checkForUpdates() {
    if (window.desktop && typeof window.desktop.checkForUpdates === 'function') {
      return window.desktop.checkForUpdates();
    }
    return { enabled: false, message: 'Desktop auto-update unavailable in browser mode.' };
  }

  async function installDownloadedUpdate() {
    if (window.desktop && typeof window.desktop.installDownloadedUpdate === 'function') {
      return window.desktop.installDownloadedUpdate();
    }
    return { ok: false, message: 'Desktop auto-update unavailable in browser mode.' };
  }

  window.AresAPI = {
    resolveBaseUrl,
    getBackendRuntime,
    apiFetch,
    updates: {
      getState: getUpdateState,
      check: checkForUpdates,
      install: installDownloadedUpdate,
    },
  };
})();

// H-180 (EXE-03): Version/Build-Kennung im Anmeldefenster. Eigenes Modul
// (frontend/build-info.js), nachgeladen statt im Monolithen eingebunden
// (Groessenbudget von ares.html).
(function () {
  if (typeof document === 'undefined' || typeof document.createElement !== 'function') return;
  var script = document.createElement('script');
  script.src = './build-info.js';
  script.defer = true;
  (document.head || document.documentElement).appendChild(script);
})();

// H-180 Paket ROL (ROL-04/-05/-06): Rollenanzeige (Lesend ohne Schreibknoepfe,
// Portfolio Management ohne Kundenmaske, Freigabe-Inbox fuer Admin/Pruefperson).
// Eigenes Modul (frontend/role-ui.js), nachgeladen wie build-info.js.
(function () {
  if (typeof document === 'undefined' || typeof document.createElement !== 'function') return;
  var script = document.createElement('script');
  script.src = './role-ui.js';
  script.defer = true;
  (document.head || document.documentElement).appendChild(script);
})();
