# Release-Tag-Strategie für 5eyes Wealth Architects

**Sprint U-78 (2026-06-04)** — Versionsdiskpline für reproduzierbare Berater-Builds.

---

## Pourquoi (Warum)

5eyes hat zwei zusammengehörige Subsysteme:

- **5eyes-backend** (Python/FastAPI) — `settings.app_version`
- **5eyes-electron** (Node/Electron) — `package.json.version`

Ohne Tag-Strategie hatten wir:

- Keine versionierten Builds für Berater (welcher Code läuft hier eigentlich?)
- Kein Rollback-Anker (was war Stand X vor dem Bug?)
- Versions-Drift zwischen Subsystemen möglich (Backend 1.3.0 vs Electron 0.4.0 → kein Mensch weiß welche Backend-API der Electron-Build braucht)
- Keine reproduzierbare CI-Build-Identifikation

---

## Versionierungs-Schema

### Semantic Versioning 2.0

Format: `MAJOR.MINOR.PATCH` mit optionalem Pre-Release-Suffix.

| Increment | Wann | Beispiel |
|-----------|------|----------|
| `MAJOR` | Breaking-Change im Berater-Workflow (Schema-Drop, Auth-Modell wechselt, Aggregator-Sektion entfernt) | 1.x.x → 2.0.0 |
| `MINOR` | Neue Sektion / Feature additiv (Aggregator-Sektion 24, neuer FE-Tab, neuer Audit-Service) | 1.3.x → 1.4.0 |
| `PATCH` | Bugfix, Doku-Update, Test-Coverage, Refactor ohne API-Change | 1.3.0 → 1.3.1 |

### Pre-Release-Suffixe

| Suffix | Bedeutung | Beispiel |
|--------|-----------|----------|
| `-alpha.N` | Interne Entwicklungs-Builds | `v1.4.0-alpha.3` |
| `-beta.N` | Berater-Smoke-Test-Phase | `v1.4.0-beta.1` |
| `-rc.N` | Release-Candidate (Compliance-Review pendent) | `v1.4.0-rc.2` |

Production-Release ohne Suffix: `v1.4.0`.

### Backend-Frontend-Synchronisation

**Pflicht-Pattern:** Backend `app_version` und Electron `package.json.version` müssen bei jedem Release übereinstimmen.

Sprint U-78 macht diese Konsistenz testbar (siehe `tests/test_release_version_consistency.py`).

---

## Tag-Konvention

| Element | Format |
|---------|--------|
| Tag-Name | `v{MAJOR}.{MINOR}.{PATCH}[-{suffix}]` |
| Tag-Typ | Annotated (signed bei Möglichkeit) |
| Branch | `main` (production) oder `release/v{X.Y.Z}` (RC) |
| Tag-Message | siehe Template unten |

### Tag-Message-Template

```
v{X.Y.Z} — {short-title}

Release-Datum: YYYY-MM-DD
Backend: {backend-version}
Electron: {electron-version}

Neue Features:
- Roadmap-Punkt {N}: {description}
...

Bugfixes:
- {description}

Compliance-Review: {Compliance-Officer-Name}, YYYY-MM-DD
```

---

## Workflow

### Bei Release-Vorbereitung

1. **Branch-Wahl:** Production-Release auf `main`. RC auf `release/vX.Y.Z`.
2. **Version-Bumps:**
   - `5eyes-backend/config.py` → `app_version`
   - `5eyes-electron/package.json` → `version`
   - Sind via `tests/test_release_version_consistency.py` validiert.
3. **CHANGELOG.md** Eintrag (Template siehe `docs/CHANGELOG_TEMPLATE.md`)
4. **Smoke-Test:**
   - Backend startet (`pytest 5eyes-backend/tests/`)
   - Electron-Build erzeugt (`npm run pack`)
   - MX-FOUNDATION-01 PDF generiert (`POST /mandates/MX-FOUNDATION-01/reports/advisory-report.pdf`)
5. **Tag erstellen:**
   ```powershell
   .\scripts\release-tag.ps1 -Version "1.4.0" -Title "Q2 2026 Compliance-Erweiterung"
   ```
6. **Push:** `git push origin main --tags`
7. **GitHub-Release:** UI nutzen oder `gh release create v1.4.0 --notes-file CHANGELOG.md`

### Bei Hotfix

Hotfix-Branch von letztem Production-Tag:

```powershell
git checkout -b hotfix/v1.4.1 v1.4.0
# Fix anwenden, Version bump 1.4.0 -> 1.4.1, Tag erstellen
```

---

## Bestehende Tags

Stand 2026-06-04: **keine Production-Tags vorhanden**. U-78 etabliert die Discipline; erstes offizielles Tag-Set folgt mit dem nächsten Berater-Release (vermutlich `v1.4.0` nach Merge der heutigen 28 PRs).

---

## Out-of-Scope (Folge-Sprints)

- **Auto-Build via GitHub-Actions** bei Tag-Push (heute: lokaler `release-tag.ps1`)
- **Code-Signing** der Electron-Builds (abhängig von Apple/Microsoft-Cert)
- **CI-Smoke** vor Tag-Erstellung erzwingen
- **Berater-Update-Notification** über `electron-updater` (siehe U-65)
- **Multi-Channel-Release** (stable/beta/internal)

---

## Verwandte Specs

- `5eyes-backend/config.py` — `app_version` Source-of-Truth Backend
- `5eyes-electron/package.json` — `version` Source-of-Truth Electron
- `5eyes-electron/PACKAGING.md` — Build-Pipeline-Doku
- `docs/CHANGELOG_TEMPLATE.md` — Changelog-Format
