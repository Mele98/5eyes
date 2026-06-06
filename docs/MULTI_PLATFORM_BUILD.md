# Multi-Platform Build (Windows / macOS / Linux)

Konfiguration und Workflow fuer plattformuebergreifende Electron-Builds.

**Stand:** 2026-06-06
**Roadmap-Punkt:** #108 (OPS, ~4h)
**Komplementaer zu:** [AUTO_UPDATE.md](AUTO_UPDATE.md) (#65),
[RELEASE_TAGS.md](RELEASE_TAGS.md)

---

## Targets

| Platform | Format | Architekturen | Script |
|----------|--------|---------------|--------|
| Windows | NSIS-Setup + Portable EXE | x64 | `npm run dist:win` / `dist:win:portable` |
| macOS | DMG | x64 + arm64 (Universal) | `npm run dist:mac` |
| Linux | AppImage | x64 | `npm run dist:linux` |

Alle 3 nutzen das gleiche `build:backend`-Pre-Step (PyInstaller-EXE
gebuendelt via `scripts/build-backend.js`).

## Voraussetzungen

### Windows
- Windows 10/11 oder Wine + Mono auf Linux
- Code-Signing-Cert (siehe #109)
- NSIS-Installer-Build via electron-builder

### macOS
- macOS-Host (electron-builder benoetigt native macOS-Tools fuer DMG)
- Apple Developer Cert + Notarization fuer Distribution
- arm64-Cross-Build via Rosetta moeglich

### Linux
- Linux-Host (Ubuntu/Debian empfohlen)
- AppImageKit zur Laufzeit gebuendelt
- Keine Code-Signing-Pflicht, aber AppArmor/SELinux beachten

## CI-Build-Matrix (Folge-Sprint)

GitHub Actions `release.yml` (Vorschlag, NICHT in U-108 enthalten):

```yaml
jobs:
  build:
    strategy:
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - run: npm ci
      - run: npm run dist:${{ matrix.os }}
      - uses: actions/upload-artifact@v4
```

Heute NICHT in CI weil:
- macOS-Runner ist 10x teurer als Linux
- Code-Signing-Secrets-Handling out-of-scope (#109)
- Release-Cadence noch zu klein fuer Multi-Platform-Auto-Build

## Manueller Multi-Platform-Build heute

```powershell
# Windows (auf Win11)
cd 5eyes-electron
npm ci
npm run dist:win

# macOS (auf macOS-Host)
cd 5eyes-electron
npm ci
npm run dist:mac

# Linux (auf Ubuntu)
cd 5eyes-electron
npm ci
npm run dist:linux
```

Output landet unter `5eyes-electron/dist/`:
- `5Eyes-0.4.0-x64.exe` (NSIS-Setup)
- `5Eyes-0.4.0-x64.dmg` (macOS)
- `5Eyes-0.4.0-x64.AppImage` (Linux)

## Auto-Update Multi-Platform

Auto-Update funktioniert via `electron-updater` ueber den
`generic`-Provider — gleicher URL fuer alle 3 Plattformen, aber pro
Platform eigene `latest-*.yml`:

- `latest.yml` (Windows)
- `latest-mac.yml`
- `latest-linux.yml`

Berater stellt alle 3 + ihre Setup-Binaries unter den gleichen
`https://updates.5eyes.local/` Endpoint.

## Bewusst NICHT in Scope (U-108)

- CI-Build-Matrix fuer alle 3 Plattformen (separater Sprint mit
  Secrets-Management)
- Notarization fuer macOS (braucht Apple-Dev-Account)
- Snap/Flatpak fuer Linux (heute nur AppImage)
- Universal-Binary fuer macOS (heute x64+arm64 als separate DMGs)
- ARM64-Linux (heute nur x64)

## Folge-Sprints

- **#109** Code-Signing-Cert beschaffen + Windows-Cert-Pipeline
- **#65 Folge:** Auto-Update Multi-Platform Smoke-Test
- CI-Build-Matrix in `.github/workflows/release.yml`

## Weiterfuehrendes

- [electron-builder Multi-Platform docs](https://www.electron.build/multi-platform-build)
- `5eyes-electron/PACKAGING.md` — Build-Pipeline-Diagramm
- `docs/AUTO_UPDATE.md` — Auto-Update-Workflow
