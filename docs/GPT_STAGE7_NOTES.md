# GPT Stage 7 notes

Additional Windows release polish added on top of stage 6:
- placeholder Windows icons in `5eyes-electron/assets/icons/`
- electron-builder NSIS/portable polish
- release preflight check (`scripts/release-check.js`)
- code-signing placeholders documented
- auto-update skeleton via `electron-updater`, disabled by default unless `ENABLE_AUTO_UPDATE=1`
- BrowserWindow icon + AppUserModelID configured
- update IPC exposed via preload for later UI wiring

Please review only for packaging/runtime correctness. No business logic was changed.
