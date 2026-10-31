# Plattformumfang des Desktop-Builds

Ares wird nur fuer Windows ausgeliefert.

**Stand:** 2026-10-31
**Entscheid:** W2-804-03 (Owner-Default: Windows-only)
**Komplementaer zu:** [AUTO_UPDATE.md](AUTO_UPDATE.md),
[CODE_SIGNING.md](CODE_SIGNING.md), [RELEASE_TAGS.md](RELEASE_TAGS.md)

---

## Unterstuetzte Targets

| Platform | Format | Architektur | Script |
|----------|--------|-------------|--------|
| Windows 10/11 | NSIS-Setup | x64 | `npm run dist:win` |
| Windows 10/11 | Portable EXE | x64 | `npm run dist:win:portable` |

`npm run pack` erzeugt nur das entpackte Staging-Verzeichnis (`--dir`) fuer
lokale Pruefungen auf einem Windows-Host.

Alle Ketten laufen ueber `preflight:release` -> `build:reporting` ->
`build:backend` -> `scan:bundle-secrets` -> `electron-builder`. Das
gebuendelte Backend ist genau ein natives Artefakt, die PyInstaller-EXE
`ares-api.exe` (Vertrag: `ares-backend/tests/test_backend_exe_name_contract.py`).

## Nicht unterstuetzt: macOS und Linux

Frueher waren zusaetzlich macOS- und Linux-Targets konfiguriert. Sie besassen
nie einen nativen Backend-Pfad: Build, Bundle, Preflight und App-Start haetten
dieselbe Windows-EXE erwartet. Diese Targets sind entfernt. Statt still zu
scheitern, brechen ausserhalb von Windows sofort mit klarer Meldung ab:

- `scripts/build-backend.js` (vor jedem Loeschen von Build-Ordnern und vor
  PyInstaller),
- `scripts/release-check.js` (Release-Preflight),
- `main.js` beim Start einer gepackten App (Dialog "App-Start
  fehlgeschlagen").

Der Entwicklungsmodus (`npm start` mit `python main.py`) bleibt davon
unberuehrt; er ist kein Release-Pfad.

Wer macOS oder Linux spaeter liefern will, braucht einen eigenen Entscheid
mit nativen Backend-Namen, Dateirechten, Ressourcenlayout, Signierung und
Build-/Start-/Readiness-/Shutdown-Smokes pro Plattform. Ein reines
Wiedereinfuegen von Scripts oder Builder-Bloecken scheitert am Vertragstest
`ares-backend/tests/test_desktop_windows_only_contract.py`.

## Auto-Update

`electron-updater` verwendet nur den Windows-Feed (`latest.yml`), siehe
[AUTO_UPDATE.md](AUTO_UPDATE.md). Das Build-Gate bleibt fail-closed.

## Code-Signing

Relevant ist nur das Windows-Authenticode-Zertifikat, siehe
[CODE_SIGNING.md](CODE_SIGNING.md).

## Weiterfuehrendes

- `ares-desktop/PACKAGING.md` — Build-Pipeline
- `ares-desktop/WINDOWS_RELEASE.md` — Windows-Release-Ablauf
- `docs/AUTO_UPDATE.md` — Auto-Update-Workflow
