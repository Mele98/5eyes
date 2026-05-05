# Stand 2026-05-06 — Was ist fertig, was kommt als naechstes

## Was FERTIG ist (Backend + Doku)

### codex/audit-master (18 Commits, unpushed)
- Z1–Z9, B1–B6, W2.5, Security, F23, CI, Cashflow-Inflation, etc.
- Tests: 357/357 gruen

### codex/stochastic-optimizer (17 Commits ueber audit-master, unpushed)
- Phase 1–5 Optimizer (Solver, Stress, GA-Fallback, Cache)
- Phase 6 Backend (passthrough, sensitivity, persist, audit-log)
- Tests: 528/528 gruen + 1 erwarteter Skip

### Dokumentation (alles in `docs/planning/`)
- `2026-05-05-stochastic-optimizer-spec.md` — Master-Spec
- `2026-05-05-fe-optimizer-panel-spec.md` — FE-Spec (Backend = FERTIG)
- `2026-05-06-phase6-fe-implementation-patch.md` — fertige Code-Snippets fuer Codex
- `2026-05-06-merge-plan-three-branches.md` — Reihenfolge + Konflikt-Strategie
- `2026-05-06-phase7-pdf-export-spec.md` — Vor-Spec PDF-Trace
- `2026-05-06-risk-free-rate-spec.md` — Vor-Spec Risk-Free in CMA
- `scripts/smoke_test_phase6_optimizer.ps1` — manueller End-to-End-Test

## Was OFFEN ist

### 1. gh-Auth wieder zum Laufen bringen
**Wer:** Owner.
**Wie:**
```powershell
# Token im Keyring ist tot. Re-Login:
gh auth login -h github.com
# Wizard: Browser-Authentifizierung waehlen, Mele98 als account.
gh auth status   # bestaetigt "Logged in"
```

Sobald das durch ist: kann ich (Claude) die 35 Commits pushen.

### 2. Phase 6 FE implementieren
**Wer:** Codex (im Workspace `_release_ready`).
**Spec:** `2026-05-06-phase6-fe-implementation-patch.md` — enthaelt fertige
HTML/CSS/JS-Snippets zum 1:1-Einsetzen plus exakte Anker.
**Aufwand:** ~2h (3 Edits in `5eyes_v2.html` + Mock + manueller Smoke-Test).

### 3. B3/B5/B6 FE-Wiring
**Wer:** Codex.
**Was:** 3 unabhaengige FE-Tasks (siehe `project_5eyes_audit.md` Memory):
- B3: 422-Fehler bei Hypothek-Tilgung menschenlesbar im Cashflow-Save-Handler
- B5: α-Hardness-Werte (0.8/0.5/0.2) als Tooltip in Goal-Anzeige
- B6: weighted_score + weakest_hard_score in Mandats-Uebersicht rendern

### 4. Manueller End-to-End-Test
**Wer:** Owner.
**Wie:**
```powershell
.\scripts\smoke_test_phase6_optimizer.ps1
```
Backend muss vorher mit `OPTIMIZER_MODE=stochastic` laufen.

### 5. Merge in develop
**Wer:** Owner.
**Wie:** siehe `2026-05-06-merge-plan-three-branches.md`. Reihenfolge:
audit-master → develop, stochastic-optimizer → develop, rp-ueberarbeitung
rebase + merge, fe-optimizer-panel rebase + merge.

**Konflikt-Vorhersage** dokumentiert. Backup-Bundle existiert.

## Was KEINE Eile hat

- Phase 7 PDF-Export — Vor-Spec da, implementieren sobald Phase 6 FE live ist.
- Risk-Free Rate — Vor-Spec da, implementieren wenn Sharpe-Ratio o.ae. einen
  Konsumer bekommt.
- Audit-Punkte SKIPPED: #41 Playwright-Setup, #47 SQLCipher-Migration manuell.

## Kritischer Pfad

```
gh auth login   →   push 35 commits   →   PR audit-master   →   merge develop
                                          ↓
                                     PR optimizer   →   merge develop
                                                        ↓
Codex implementiert FE-Phase 6  ←   rebase rp-ueberarbeitung
   ↓
manueller Smoke-Test
   ↓
PR FE-Phase 6   →   merge develop   →   FERTIG
```

## Risiko-Liste

| Risiko | Likelihood | Mitigation |
|---|---|---|
| Merge-Konflikt rp-ueberarbeitung in `portfolio_engine.py` | hoch | Section-weise mergen, Tests lokal vor push |
| Solver-Performance bei realem Mandat >10s | mittel | Phase 5.4 Cache + Sensitivity-Caching nachruesten |
| FE-Patch passt nicht zu Codex' aktuellem `5eyes_v2.html` | mittel | Anker-Strings sind robust; Codex passt manuell an |
| gh-Auth bleibt blockiert | niedrig | Bundle-Backup ist vorhanden, kann manuell ueber GitHub-UI |
