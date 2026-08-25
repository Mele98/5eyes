# Code-Signing fuer 5eyes-Electron (Windows + macOS)

Setup-Anleitung sobald der User ein Code-Signing-Zertifikat besorgt hat.

**Stand:** 2026-06-06
**Roadmap-Punkt:** #109 (OPS, externer Cert-Kauf + ~2h Setup)
**Status:** Vorbereitung — wartet auf Cert-Beschaffung durch den User.

---

## Warum?

**Ohne Code-Signing:**
- Windows SmartScreen blockt Installation: "Unbekannter Herausgeber"
- macOS Gatekeeper: "Dieser App kann nicht vertraut werden"
- Berater muss `Mehr-Info -> Trotzdem ausfuehren` klicken
- Auto-Update (#65) bricht ab — `electron-updater` rejected unsigned
  Binaries

**Mit Code-Signing:**
- App-Installation laeuft ohne SmartScreen-Warning
- Auto-Update funktioniert
- Berater-Vertrauen + FINMA-Audit-Pluspunkt

## Welche Zertifikate?

### Windows: EV oder OV?

| Typ | Kosten | SmartScreen-Reputation | Empfehlung |
|-----|--------|-----------------------|------------|
| OV (Organization Validation) | ~CHF 300/Jahr | Muss erst Reputation aufbauen (Wochen) | Klein-Berater |
| EV (Extended Validation) | ~CHF 600/Jahr + Hardware-Token | Sofort vertraut | Grosse Praxis |

**Empfehlung fuer Einzel-Berater:** OV-Cert via Sectigo/DigiCert.

### macOS: Apple Developer Cert

- Apple Developer Program: USD 99/Jahr
- Cert wird via App-Store-Connect generiert
- Notarization-Service inklusive (zwingend fuer macOS 10.15+)
- Apple-Account muss "Individual" oder "Organization" sein

## Setup nach Cert-Erhalt

### Windows EV/OV-Cert in `electron-builder`

`5eyes-electron/package.json`:

```json
{
  "build": {
    "win": {
      "certificateFile": "${env.WIN_CERT_PATH}",
      "certificatePassword": "${env.WIN_CERT_PASSWORD}",
      "signingHashAlgorithms": ["sha256"]
    }
  }
}
```

Environment-Variablen (lokal + CI):

```
WIN_CERT_PATH=C:\path\to\cert.pfx
WIN_CERT_PASSWORD=<secret>
```

Bei EV-Cert mit Hardware-Token: `certificateSubjectName` statt
`certificateFile` setzen (Token erlaubt kein File-Export).

### macOS Apple-Cert in `electron-builder`

`5eyes-electron/package.json`:

```json
{
  "build": {
    "mac": {
      "identity": "Developer ID Application: <Name> (TEAMID)",
      "hardenedRuntime": true,
      "gatekeeperAssess": false,
      "entitlements": "build/entitlements.mac.plist",
      "entitlementsInherit": "build/entitlements.mac.plist"
    }
  }
}
```

Plus Notarization via `notarytool` (separater Step):

```powershell
npx electron-notarize \
  --bundle-id ch.5eyes.wealtharchitekten \
  --app dist/mac/5Eyes.app \
  --apple-id <email> \
  --apple-id-password <app-specific-pwd> \
  --team-id <TEAMID>
```

## CI-Integration (GitHub Actions)

Secrets:
- `WIN_CERT_PATH` (Base64-Inhalt oder File-Path)
- `WIN_CERT_PASSWORD`
- `APPLE_ID`
- `APPLE_ID_PASSWORD`
- `APPLE_TEAM_ID`

```yaml
# Snippet — vollstaendig in release.yml
- name: Decode Cert
  if: matrix.os == 'windows-latest'
  run: |
    echo "${{ secrets.WIN_CERT_PFX_BASE64 }}" | base64 -d > cert.pfx
    echo "WIN_CERT_PATH=$(pwd)/cert.pfx" >> $env:GITHUB_ENV
  shell: pwsh
```

## Sicherheits-Hygiene

- **NIE** Cert-Files committen
- **NIE** Cert-Password im Code/Logs
- **NIE** Cert auf Berater-Laptops verteilen
- Cert in **dedicated Build-Maschine** oder CI-Secret-Store
- EV-Cert-Token an **separatem sicheren Ort** (nicht in der Bauluxe)

## Wenn das Cert ablaeuft

- Renewal 30 Tage vor Ablauf
- Alter Cert wird nicht widerrufen (alte Binaries bleiben signiert)
- Neuer Cert: in `electron-builder`-Config + CI-Secrets ersetzen
- Folge-Sprint: Smoke-Test "alte Auto-Update-Cascade funktioniert"

## Bewusst NICHT in Scope (U-109)

- Cert-Kauf selbst (User-Action, externe Kosten)
- Hardware-Token-Beschaffung fuer EV (User-Action)
- CI-Workflow-Komplett-Implementation (Folge-Sprint nach Cert-Eingang)
- Notarization-Smoke-Test (Folge-Sprint mit echtem Cert)
- Cross-Sign mit zweitem Cert (Backup-Pattern)

## Folge-Sprints

1. **Sobald Cert da:** Konfig anwenden + Smoke-Test (`dist:win` mit
   signiertem Output)
2. **CI-Workflow:** `release.yml` mit Cert-Secrets
3. **Auto-Update Smoke:** Verifikation dass Update von altem zu neuem
   Build sauber laeuft
4. **Cert-Renewal-Reminder** in `docs/RELEASE_TAGS.md`

## Kosten-Disziplin

ADR-005 (CHF 0/Jahr) gilt fuer **Marktdaten-Pipeline**, NICHT fuer
Code-Signing. Code-Signing ist Berater-Vertrauens-Investition,
nicht Software-Cost.

Empfehlung: Sectigo OV Standard ~CHF 280/Jahr fuer Windows + Apple
Developer Program USD 99/Jahr fuer macOS = ~CHF 380/Jahr.

## Weiterfuehrendes

- [electron-builder Code Signing](https://www.electron.build/code-signing)
- [Apple Developer Program](https://developer.apple.com/programs/)
- [Windows Authenticode](https://docs.microsoft.com/windows-hardware/drivers/install/authenticode)
- `docs/AUTO_UPDATE.md` — Auto-Update braucht Cert
- `docs/MULTI_PLATFORM_BUILD.md` — Build-Targets pro Platform
