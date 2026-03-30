(function () {
  async function resolveBaseUrl() {
    if (window.desktop && typeof window.desktop.getBackendBaseUrl === 'function') {
      return window.desktop.getBackendBaseUrl();
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

  window.FiveEyesAPI = {
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
