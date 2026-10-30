# Windows release guide

## 1) Replace placeholder branding
- Replace `assets/icons/app.ico`
- Replace `assets/icons/installer-icon.ico`
- Replace `assets/icons/uninstaller-icon.ico`

## 2) Run the offline asset step

```bash
cd 5eyes-electron
python vendor_assets.py
```

Then verify with:

```bash
npm run preflight:release
```

## 3) Auto-update stays disabled (UPDATE-001)
Production builds ship without an update URL (`build.publish: null`).
Do not set `UPDATES_ENABLED=true` until an owner-controlled HTTPS update
address and code signing are in place and approved; otherwise the build
aborts. Requirements: `docs/AUTO_UPDATE.md`.

## 4) Optional code signing
Set these environment variables before building:

```bash
set CSC_LINK=C:\path\to\certificate.pfx
set CSC_KEY_PASSWORD=your-password
```

## 5) Strict preflight for a real release

```bash
set STRICT_RELEASE=1
npm run preflight:release
```

## 6) Build commands

NSIS installer:

```bash
npm run dist:win
```

Portable build:

```bash
npm run dist:win:portable
```

## 7) Auto-update in packaged runtime
`ENABLE_AUTO_UPDATE=1` has no effect unless the build gate was opened at
build time (see step 3). Until then, ship updates as a new installer.

## 8) Recommended final smoke test
- launch the packaged app
- verify the backend starts and logs into the expected user data directory
- verify first-run bootstrap only appears on an empty DB
- verify admin maintenance buttons work
- verify `electron.log` and backend log are both created
