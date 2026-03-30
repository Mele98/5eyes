# GPT Stage 8 notes

## What was added in this stage

### 1) Real backend EXE entrypoint
- `5eyes-backend/main.py` now has a real `run()` + `if __name__ == '__main__':` entrypoint.
- This fixes the packaging risk where a PyInstaller-built EXE would otherwise start, define `app`, and exit immediately.

### 2) Dynamic backend runtime selection in Electron
- `5eyes-electron/main.js` no longer blindly assumes `127.0.0.1:8000`.
- It now:
  - loads `.env` values into the Electron process if present,
  - probes `APP_HOST`/`APP_PORT`,
  - verifies that the service on that port is really the expected 5Eyes backend,
  - reuses it only if the app identity matches,
  - otherwise picks a free localhost port and starts the bundled backend there.
- The selected backend runtime is exposed through `preload.js`.

### 3) Better child-process logging
- Electron now captures backend stdout/stderr and writes it into `electron.log` with prefixes.
- This improves diagnostics for packaged runtime failures.

### 4) In-app first-run bootstrap
- New backend endpoints:
  - `GET /auth/bootstrap-status`
  - `POST /auth/bootstrap-admin`
- The frontend login overlay now supports a first-run setup flow to create the first admin directly inside the desktop app.
- `setup.py` still exists as CLI fallback.

### 5) Support bundle endpoint
- New admin endpoint:
  - `POST /admin/system/support-bundle`
- Creates a zip with:
  - redacted settings snapshot,
  - recent logs,
  - database path information,
  - backup manifest references.
- The admin modal now includes a **Support-Bundle** button.

### 6) Packaging hardening
- `scripts/build-backend.js` now:
  - checks that `main.py` has an executable entrypoint,
  - includes more PyInstaller hidden imports / collected submodules for the FastAPI + yfinance stack,
  - keeps the SQLCipher optional path.

### 7) Release preflight improvements
- `scripts/release-check.js` now also checks:
  - malformed HTML ending,
  - missing local Chart.js vendor file,
  - remaining external CDN/font references.

### 8) Frontend cleanup
- Removed the malformed trailing HTML fragment after the closing document.
- Added safer API error propagation.
- Added a guard so the UI still works even if Chart.js is not yet vendored locally.

## Important remaining point
- Because Chart.js could not be downloaded from within this execution environment, the project still keeps a jsDelivr fallback in the HTML for development convenience.
- For the final offline Windows release, `python vendor_assets.py` still needs to be run successfully so that local `frontend/vendor/chart.min.js` is present and the external fallback can be removed.

## What Claude should focus on now
1. Review the dynamic-port/runtime logic in Electron.
2. Review the bootstrap flow from empty DB to first admin.
3. Review whether any additional PyInstaller hidden imports are still needed in a real Windows build.
4. Run `vendor_assets.py` in a networked environment and then rerun `npm run preflight:release`.
5. Do the final runtime review for packaged Windows startup and shutdown.
