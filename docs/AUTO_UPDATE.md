# Electron Auto-Update — Operations-Doku

Wie das Auto-Update der 5eyes-Electron-App funktioniert, wie es
aktiviert wird, und wie Releases publiziert werden.

**Stand:** 2026-06-06
**Roadmap-Punkt:** #65 (OPS, ~2-3h)
**Status:** Implementiert in `5eyes-electron/main.js` (autoUpdater),
opt-in via Environment-Variable.

---

## Aktivierung

Auto-Update ist **standardmaessig deaktiviert** — es laeuft nur in
einer gepackten App (`app.isPackaged === true`) wenn:

```
ENABLE_AUTO_UPDATE=1
```

als Environment-Variable gesetzt ist. Der DEV-Modus (`npm start` /
Vite-Dev) laeuft NIE Auto-Update.

## Provider-Konfiguration

`5eyes-electron/package.json` (`build.publish`):

```json
{
  "provider": "generic",
  "url": "https://updates.5eyes.local"
}
```

`generic`-Provider: ein simpler HTTP(S)-Endpoint mit einer
`latest.yml` und den NSIS-Setup-Binaries. Kein GitHub-Releases-Lock-in,
keine S3/CDN-Pflicht — Berater kann eigenes File-Hosting nutzen.

## Lifecycle-Events

Wired in `main.js#L120-L165`:

| Event | Aktion |
|-------|--------|
| `checking-for-update` | Status -> `checking=true`, Renderer-Notify |
| `update-available` | Status -> `available=true`, Latest-Version cachen |
| `update-not-available` | Status -> `available=false` |
| `update-downloaded` | Status -> `downloaded=true`, Restart-Prompt |
| `error` | Status -> `error=message`, Log + Renderer-Notify |

Auto-Behaviors:
- `autoDownload=true`: Update-Binary wird im Hintergrund geladen
- `autoInstallOnAppQuit=true`: Install passiert beim naechsten App-Close

## Berater-UI

Renderer kommuniziert via `notifyRendererUpdateState()` (siehe
`main.js`). Hauptapp-HTML zeigt:
- Update-Banner wenn `available=true` UND `downloaded=true`
- Button "Jetzt neustarten" -> `autoUpdater.quitAndInstall()`

## Release-Workflow

1. **Version-Bump:** `package.json#version` + `setup.py#version` (drift-test
   `test_release_version_consistency.py` faengt Drift)
2. **CHANGELOG:** `docs/CHANGELOG_TEMPLATE.md` Pattern befolgen
3. **Build:** `npm run dist:win` baut NSIS-Setup
4. **Publish:** Upload `latest.yml` + `5eyes-Setup-X.Y.Z.exe` auf
   den `generic`-URL-Endpoint
5. **Smoke-Test:** alte Installation startet, Auto-Update findet
   Update, Restart installiert sauber

## Sicherheit

- **Code-Signing:** ohne Cert wird die Update-Binary von Windows
  SmartScreen geblockt. Siehe Roadmap-Punkt #109 (Cert noch nicht
  beschafft).
- **HTTPS:** der Provider-URL muss `https://` sein. `electron-updater`
  rejected unsigned HTTP-Endpoints.
- **integrity:** electron-updater verifiziert SHA512 aus `latest.yml`
  vs heruntergeladener Binary.

## Bewusst NICHT in Scope (U-65)

- GitHub-Releases-Provider (Vendor-Lock-in)
- Auto-Update von Backend-PyInstaller-EXE (Backend wird mit Electron
  gebundelt, single-binary-Update)
- Update-Channel-Logik (alpha/beta/stable) — heute nur einer
- Delta-Updates (electron-updater unterstuetzt, aber separater Sprint)
- Auto-Update-Telemetrie via U-64 Telemetry-Adapter

## Folge-Sprints

- **#109** Code-Signing-Zertifikat beschaffen + setup (External-Cost)
- **#108** macOS/Linux-Build (Multi-Platform-Auto-Update)
- Update-Channel-Switching in Berater-UI

## Weiterfuehrendes

- [electron-updater docs](https://www.electron.build/auto-update)
- `5eyes-electron/main.js#L60-L180` — Implementation
- `docs/RELEASE_TAGS.md` — Versionierungs-Workflow
- `5eyes-electron/PACKAGING.md` — Build-Pipeline-Diagramm
