# Integrations-Branch Spec — `codex/integration-phase6`

**Datum:** 2026-05-06
**Owner:** Emanuele
**Wer fuehrt aus:** Codex
**Workspace:** `C:\5eyes\5eyes_stage9_release_ready` (oder `_develop_security` — egal welcher, nur EINEN waehlen)

## Ziel

Vor dem direkten Merge in `develop` einen Integrations-Branch erstellen, in
dem alle 4 Feature-Branches zusammenkommen. Konflikte werden hier (sicher)
geloest, Tests laufen End-to-End, manueller Smoke-Test verifiziert die UI.

Erst wenn der Integrations-Branch gruen ist, gehen die Feature-Branches in
der **gleichen** Reihenfolge per PR in `develop`.

## Branches die gemerged werden (in dieser Reihenfolge)

| # | Branch | Origin-HEAD | Was drin ist |
|---|---|---|---|
| 1 | `origin/codex/audit-master` | `c071cc8` | Z1–Z9, B1–B6, W2.5, F23, Security, CI, Cashflow-Inflation. **357/357 Tests gruen lokal.** |
| 2 | `origin/codex/stochastic-optimizer` | `f6f30d9` | Phase 1–6.3 Optimizer (Solver, Stress, Cache, Persistenz, AuditLog, Sensitivity). **528/528 Tests gruen.** Baut auf audit-master auf — sollte FF sein. |
| 3 | `origin/codex/rp-ueberarbeitung` | `df3473b` | Risikoprofil-Ueberarbeitung + RP-Workflow + FE-Cleanup. **285/285 Tests gruen vor commit.** |
| 4 | `origin/codex/fe-optimizer-panel` | `6c9be04` | Phase 6 FE-Panel (HTML + 4 JS-Funktionen). **11/11 FE-Contract-Tests gruen.** |

## Schritt-fuer-Schritt

### 1. Vorbereitung

```powershell
# Workspace waehlen — Empfehlung _release_ready (FE ist da)
cd C:\5eyes\5eyes_stage9_release_ready
git fetch origin
git checkout develop
git pull origin develop

# Backup-Tag setzen (falls reset noetig)
git tag pre-integration-2026-05-06
```

### 2. Integrations-Branch erstellen

```powershell
git checkout -b codex/integration-phase6 origin/develop
```

### 3. Merge audit-master (sollte konfliktfrei sein)

```powershell
git merge origin/codex/audit-master --no-ff -m "Merge: audit-master (Z1-Z9 + B1-B6 + W2.5 + F23 + Security)"
# Wenn Konflikt: STOP, zuerst pruefen — audit-master sollte aber sauber von alter develop kommen
pytest 5eyes-backend/tests/ -x -q   # 357+ erwartet
```

### 4. Merge stochastic-optimizer (FF erwartet)

```powershell
git merge origin/codex/stochastic-optimizer --no-ff -m "Merge: Stochastic Optimizer Phase 1-6.3"
pytest 5eyes-backend/tests/ -x -q   # 528+ erwartet
```

### 5. Merge rp-ueberarbeitung (KONFLIKTE ERWARTET)

```powershell
git merge origin/codex/rp-ueberarbeitung --no-ff -m "Merge: RP-Ueberarbeitung"
```

**Konflikt-Dateien (vorhergesehen):**

| Datei | Audit/Optimizer-Aenderung | RP-Aenderung | Strategie |
|---|---|---|---|
| `services/portfolio_engine.py` | B1/B5/B6/W2.5/F23/Optimizer-Hooks (~3700 Zeilen Code) | Engine-Alignment Refactor (~600 Zeilen) | **Audit-Logik wins**, RP-Refactor anpassen. Bei Konflikt im Reserve-Block: Audit-B4 ist authoritativ. |
| `services/risk_scoring.py` | (minor) | RP-Logik | **RP wins** (eigener Scope) |
| `models/allocation.py` | Optimizer-Spalten + Phase-6.1+6.2 Persistenz | (minor) | **Audit/Optimizer wins** |
| `schemas/allocation.py` | TargetAllocationGenerateResponse + Sensitivity-Schemas | minor field changes | **Beide mergen** (additive) |
| `5eyes-electron/frontend/5eyes_v2.html` | (audit-master minor) | RP-Refactor (umfangreich, ~1200 Zeilen) | **RP wins** structure-mässig |
| `database.py` | optimizer-Spalten + Phase-6.1+6.2 + Cashflow-Erweiterungen | RP-Erweiterungen | **Beide mergen** (additive in `ensure_runtime_columns()`) |
| `routers/allocation.py` | Sensitivity-Endpoint | RP-Aenderungen | **Beide mergen** (additive) |

**Vorgehen pro Konfliktdatei:**
1. `git diff --name-only --diff-filter=U` listet Konflikte
2. Pro Datei: `git diff <branch1> <branch2> -- <file>` zum Verstehen
3. Section-weise mergen, niemals "ours" oder "theirs" pauschal
4. Nach jeder geloesten Datei: lokale Test-Suite anstossen

```powershell
pytest 5eyes-backend/tests/ -x -q   # 800+ erwartet (kombiniert)
```

### 6. Merge fe-optimizer-panel (KONFLIKT in 5eyes_v2.html)

```powershell
git merge origin/codex/fe-optimizer-panel --no-ff -m "Merge: Phase 6 FE-Optimizer-Panel"
```

**Konflikt-Datei:** `5eyes-electron/frontend/5eyes_v2.html`
- `fe-optimizer-panel` hat HTML-Container + 4 JS-Funktionen + Hook
- `rp-ueberarbeitung` hat parallel den HTML-Body und JS umstrukturiert
- **Strategie:** RP-Struktur als Basis nehmen, Phase-6-FE-Code "draufpatchen":
  1. Container `#al-optimizer-panel` einfuegen vor `#al-planning-card` (Anker stabil)
  2. 4 JS-Funktionen (`renderOptimizerPanel`, `renderStressTable`, `renderSensitivitySlidersForResult`, `runSensitivityCall`) einfuegen vor `function renderActionCards`
  3. Hook `renderOptimizerPanel(result);` einfuegen vor `renderActionCards(result.reasoning);` in `applyAllocationEngineResult`
  - Vorlage: `docs/planning/2026-05-06-phase6-fe-implementation-patch.md`

```powershell
pytest 5eyes-backend/tests/test_frontend_*.py -x -q   # 11+ erwartet
```

### 7. End-to-End Smoke-Test

```powershell
# Backend in 2. Terminal
$env:OPTIMIZER_MODE = 'stochastic'
python -m uvicorn main:app --host 127.0.0.1 --port 8765

# Smoke-Skript ausfuehren
.\scripts\smoke_test_phase6_optimizer.ps1
```

Erwartet: alle 5 Endpoint-Calls erfolgreich, stress_evaluations + reasoning auf
beiden Pfaden (generate + /current/payload), Sensitivity gibt vernuenftiges Delta.

### 8. Manueller UI-Klick-Test

1. Electron-App starten
2. Test-Mandant mit Pension-Goal anlegen
3. Auf Allocation-Page wechseln, "Generate" druecken
4. Pruefen: `#al-optimizer-panel` erscheint mit gruener Pill
5. Reasoning-Trace expandiert: enthaelt Solver-Iter und Stress-Zeilen
6. Stress-Tabelle: 3 Zeilen, 1929-Zeile rot wegen >50% DD
7. Sensitivity-Slider auf -20%: Werte erscheinen mit "(besser erreichbar)"
8. Page-Reload: alle Werte identisch (Persistenz)

### 9. Push + PR-Sequenz

```powershell
git push --force-with-lease origin codex/integration-phase6

# JETZT die Feature-Branches per PR in develop mergen
# (Integration-Branch dient nur zur Verifikation, NICHT zum direkten Merge in develop)

gh pr create --base develop --head codex/audit-master --title "Audit Z1-Z9 + B1-B6 + W2.5 + F23"
# nach merge:
gh pr create --base develop --head codex/stochastic-optimizer --title "Stochastic Optimizer Phase 1-6.3"
# nach merge:
gh pr create --base develop --head codex/rp-ueberarbeitung --title "RP-Ueberarbeitung"
# nach merge:
gh pr create --base develop --head codex/fe-optimizer-panel --title "Phase 6 FE-Optimizer-Panel"
```

## Akzeptanzkriterien

1. ✅ Alle 4 Merges abgeschlossen, keine offenen Konflikt-Marker.
2. ✅ Vollstaendige Test-Suite gruen (~800 Tests kombiniert).
3. ✅ Smoke-Test-Skript laeuft fehlerfrei durch.
4. ✅ Manueller UI-Klick-Test ohne JS-Errors in der DevTools-Konsole.
5. ✅ `optimization_method/_status/_seed/_iterations` im UI-Audit-Footer korrekt angezeigt.

## Rollback-Plan

Falls etwas schief geht:

```powershell
git checkout develop
git branch -D codex/integration-phase6
# Tag bleibt als Sicherung
git checkout pre-integration-2026-05-06
```

Oder: einzelne Merge-Commits revertieren mit `git revert <commit>`.

## Was NICHT in dieser Spec ist

- Direktes Mergen in `develop` ohne Integrations-Branch (zu riskant).
- Squash-Merges (verlieren History).
- Phase 7 (PDF-Export) — eigene Spec, nach Phase 6 Live.

## Aufwand-Schaetzung

- Schritte 1–4: ~30 min (Routine)
- Schritte 5: ~60–90 min (umfangreiche Konflikte in portfolio_engine.py + 5eyes_v2.html)
- Schritte 6: ~15 min (FE-Patch ist klein, Anker stabil)
- Schritte 7–8: ~20 min (Smoke + UI-Klick)
- Schritte 9: ~15 min (PRs)
- **Gesamt: 2–3h**
