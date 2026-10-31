# Electron Auto-Update — Operations-Doku

Wie das Auto-Update der 5eyes-Electron-App funktioniert, wie es
aktiviert wird, und wie Releases publiziert werden.

**Stand:** 2026-06-06
**Roadmap-Punkt:** #65 (OPS, ~2-3h)
**Status:** Code vorhanden, im Produktionsbuild per Build-Gate
deaktiviert (UPDATE-001, Aktivierung blockiert bis Freigabe).

---

## Aktivierung (UPDATE-001: fail-closed Build-Gate)

Auto-Update ist im Produktionsbuild **deaktiviert**, bis eine echte,
eigentuemerkontrollierte HTTPS-Update-Adresse **und** Code-Signing
vorhanden und abgenommen sind (Owner + Security/Release). Das ist ein
Build- und Packaging-Gate, keine reine Laufzeit-Flag:

- Build-Default `UPDATES_ENABLED=false`: `build.publish` ist `null`
  (keine Update-URL, kein `app-update.yml` im Artefakt) und die gepackte
  `package.json` traegt `"desktopUpdates": { "enabled": false }`.
- `main.js` laedt `electron-updater` nur, wenn die gepackte
  `package.json` `desktopUpdates.enabled === true` mit gueltiger
  HTTPS-Feed-URL traegt **und** zur Laufzeit `ENABLE_AUTO_UPDATE=1`
  gesetzt ist. Sonst: kein Updater, kein Netzwerkaufruf, UI zeigt
  "deaktiviert".
- `UPDATES_ENABLED=true` ohne vollstaendige Konfiguration bricht den
  Build ab: `npm run preflight:release` (`scripts/release-check.js`) und
  der electron-builder-Hook `beforePack`
  (`scripts/update-gate-before-pack.js`, greift auch bei direktem
  electron-builder-Aufruf). Regeln in `update-gate.js`.

Der DEV-Modus (`npm start` / Vite-Dev) laeuft NIE Auto-Update.

## Provider-Konfiguration (erst nach Freigabe)

Fuer eine spaetere Aktivierung muessen alle Punkte zusammen erfuellt sein
(sonst bricht der Build ab):

1. `UPDATES_ENABLED=true` und `UPDATE_FEED_URL=<https-Adresse>` im Build-Env;
   die Adresse muss HTTPS sein, ohne Zugangsdaten, kein IP-Literal, keine
   reservierte/Platzhalter-Domain (`.invalid`, `.example`, `.test`,
   `.local`, `localhost`, `example.com/.net/.org`).
2. `build.publish` = genau ein `generic`-Provider mit dieser URL und
   `desktopUpdates` = `{ "enabled": true, "feedUrl": <dieselbe URL> }`.
3. Code-Signing-Konfiguration: `CSC_LINK`+`CSC_KEY_PASSWORD`,
   `WIN_CSC_LINK`+`WIN_CSC_KEY_PASSWORD`, `win.signtoolOptions` oder
   `win.azureSignOptions`. Ob Schluessel und Verfahren den Release-Vorgaben
   entsprechen (HSM/Key Vault), ist eine Freigabe, die der Code nicht prueft.

`generic`-Provider: ein HTTPS-Endpoint mit einer `latest.yml` und den
NSIS-Setup-Binaries. Bis zur Freigabe werden Sicherheitsupdates als
kontrolliert verteilter Installer mit manueller Upgrade-Anleitung
ausgeliefert.

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
- ~~**#108** macOS/Linux-Build~~ — verworfen: Ares wird nur fuer Windows
  ausgeliefert (W2-804-03, siehe `MULTI_PLATFORM_BUILD.md`)
- Update-Channel-Switching in Berater-UI

## Weiterfuehrendes

- [electron-updater docs](https://www.electron.build/auto-update)
- `ares-desktop/main.js#L60-L180` — Implementation
- `docs/RELEASE_TAGS.md` — Versionierungs-Workflow
- `ares-desktop/PACKAGING.md` — Build-Pipeline-Diagramm
