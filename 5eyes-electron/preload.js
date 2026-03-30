const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktop', {
  getVersion: () => ipcRenderer.invoke('app:get-version'),
  getBackendBaseUrl: () => ipcRenderer.invoke('backend:get-base-url'),
  getBackendRuntime: () => ipcRenderer.invoke('backend:get-runtime'),
  checkBackend: () => ipcRenderer.invoke('backend:health'),
  openExternal: (url) => ipcRenderer.invoke('shell:open-external', url),
  getAuthToken: () => ipcRenderer.invoke('auth:get-token'),
  setAuthToken: (token) => ipcRenderer.invoke('auth:set-token', token),
  clearAuthToken: () => ipcRenderer.invoke('auth:clear-token'),
  getUpdateState: () => ipcRenderer.invoke('updates:get-state'),
  checkForUpdates: () => ipcRenderer.invoke('updates:check'),
  installDownloadedUpdate: () => ipcRenderer.invoke('updates:install-downloaded'),
  onUpdateStateChanged: (callback) => {
    const handler = (_event, state) => callback(state);
    ipcRenderer.on('updates:state-changed', handler);
    return () => ipcRenderer.removeListener('updates:state-changed', handler);
  },
});
