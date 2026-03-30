# 5Eyes Electron Wrapper (Windows skeleton)

This desktop shell starts the local FastAPI backend, verifies that the reachable service is really the 5Eyes API, chooses a free localhost port when 8000 is already occupied by something else, and then opens the current `5eyes_v2.html` frontend inside Electron.

## What is included

- `main.js`
  - starts the backend automatically or reuses a compatible already running local backend
  - selects a free localhost port if the default port is occupied by another service
  - waits for backend readiness and validates the reported app identity
  - opens a hardened `BrowserWindow`
  - prevents navigation away from the local app shell
  - terminates the backend on app quit
  - writes Electron-side logs to the user log directory
- `preload.js`
  - exposes a minimal `window.desktop` bridge
- `frontend/desktop-api.js`
  - resolves the backend base URL from Electron and wraps `fetch()`
- `package.json`
  - Electron + `electron-builder` config for a Windows NSIS installer (`.exe`)
- `scripts/build-backend.js`
  - bundles the Python FastAPI backend into `5eyes-api.exe` via PyInstaller
  - checks that `main.py` has an executable entrypoint before building
  - optionally includes SQLCipher when `BUILD_WITH_SQLCIPHER=1`
- `frontend/5eyes_v2.html`
  - frontend including login flow, bootstrap flow for the first admin, and admin maintenance modal

## Important runtime notes

- Windows only for now.
- Placeholder Windows app icon is included under `assets/icons/` and can be replaced later without changing code.
- The backend scheduler only needs to run while the app is open.
- SQLCipher is controlled centrally through `DB_USE_SQLCIPHER=true` and `DB_KEY=...` in `.env`.
- Electron writes a local support log to `%APPDATA%/5Eyes WealthArchitekten/logs/electron.log` (or the platform equivalent).
- The packaged backend looks for a `.env` file next to the bundled backend executable first, then falls back to the normal project locations.
- The frontend contains an in-app bootstrap flow for the first admin account if the database has no users yet.
- For a fully offline release, run `python vendor_assets.py` successfully before the final installer build.

## Setup

### 1) Python dependencies for the backend

From `5eyes-backend/`:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
python setup.py
```

For encrypted builds additionally:

```bash
pip install sqlcipher3-binary
```

### 2) Node dependencies for Electron

From `5eyes-electron/`:

```bash
npm install
```

## Local development run

Make sure the backend dependencies are installed. Then from `5eyes-electron/`:

```bash
npm start
```

If your Python executable is not on PATH, set it explicitly before starting Electron:

```bash
set PYTHON_BIN=C:\path\to\python.exe
npm start
```

## Local browser test

Start the backend in `5eyes-backend/`:

```bash
python main.py
```

Then open `frontend/5eyes_v2.html` in the browser.

## First-run bootstrap

When no user exists yet, the frontend shows an **Ersteinrichtung** screen and can create the first local admin directly via the API.

You can still use the CLI setup script if you prefer:

```bash
python setup.py
```

## Vendor offline assets

From `5eyes-electron/`:

```bash
python vendor_assets.py
```

That downloads Chart.js locally and rewrites the HTML to use local Chart.js plus system fonts.

## Build the Windows installer

Unencrypted build:

```bash
npm run dist:win
```

Encrypted build with SQLCipher included in the backend EXE:

```bash
set BUILD_WITH_SQLCIPHER=1
npm run dist:win
```

What happens during this command:
1. `scripts/build-backend.js` runs PyInstaller in `5eyes-backend/`
2. PyInstaller builds `5eyes-api.exe`
3. the executable plus `.env` / `.env.example` are copied to `5eyes-electron/bundle/backend/`
4. `electron-builder` packages the app and produces an NSIS installer in `5eyes-electron/dist/`

## Quick smoke test

After setup and backend startup, run this from `5eyes-backend/`:

```bash
python smoke_test.py --username admin --password <dein-passwort>
```

This checks root health, readiness, login, `/auth/me`, `/clients`, and the price status endpoint.

## Windows installer polish

Included in this stage:
- placeholder app/installer/uninstaller icons in `assets/icons/`
- NSIS shortcuts + uninstall display name
- portable Windows target (`npm run dist:win:portable`)
- release preflight check via `npm run preflight:release`
- code-signing placeholders through standard Electron Builder environment variables
- auto-update skeleton via `electron-updater`

### Release preflight

From `5eyes-electron/`:

```bash
npm run preflight:release
```

This warns you when:
- icons are missing
- the auto-update URL is still the placeholder
- Windows code-signing variables are missing
- local Chart.js is missing for an offline release
- the frontend still contains external CDN/font references

Set `STRICT_RELEASE=1` to fail the preflight on unresolved release placeholders.

### Windows code-signing placeholders

Electron Builder uses the standard variables:

```bash
set CSC_LINK=C:\path\to\certificate.pfx
set CSC_KEY_PASSWORD=your-password
```

If these are not set, the installer is built unsigned.

### Auto-update skeleton

The package includes a generic provider placeholder and `electron-updater` wiring.
Auto-update remains disabled by default and only activates in the packaged app when:

```bash
set ENABLE_AUTO_UPDATE=1
```

Before enabling it for a real release, replace the placeholder publish URL in `package.json`.
