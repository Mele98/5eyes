# WIP-Cleanup-Analyse (2026-05-13)

**Branch:** `codex/wip-cleanup-2026-05-13`
**Zweck:** Analyse + Klassifikation aller 25 untracked Dateien im Workspace.
**Wichtig:** Dieser Bericht **loescht nichts**. Vorschlag fuer User-Freigabe.

---

## Zusammenfassung

| Bucket | Dateien | Empfehlung | Risiko |
|---|---|---|---|
| **A — Loeschbar** | 13 | `git clean -fd tmp/ extracted_check.js` | Null (debug snapshots) |
| **B — Archivieren** | 8 | Move → `docs/archive/wip_2026-05-13/` | Null (historischer Record) |
| **C — Separater Branch** | 1+1 | Commit auf `codex/wip-fe-review-restructure-2026-05-08` | Mittel (WIP-FE-Code) |

---

## Bucket A — Loeschbar

Debug-Snapshots der inline `<script>`-Bloecke aus `5eyes_v2.html`, erstellt
waehrend Frontend-Audits / Mojibake-Untersuchungen. Reine Artefakte.

```
extracted_check.js
tmp/5eyes_v2.before_ftfy_backup.html
tmp/aa_layout_check.js
tmp/cashflow_block.txt
tmp/frontend_check.js
tmp/frontend_check_after_ftfy.js
tmp/frontend_check_cashflow.js
tmp/frontend_check_cf.js
tmp/frontend_check_final_unicode.js
tmp/goal_architecture_check.js
tmp/goal_pk_gaps_check.js
tmp/rp_frontend_check.js
tmp/mojibake_samples_after.txt
tmp/mojibake_samples_after_iter.txt
tmp/mojibake_samples_before.txt
tmp/mojibake_samples_latin1_utf8.txt
```

**Begruendung:** Alle Dateien haben den Header `/* Vendored Chart.js for offline desktop builds */` — sie sind alte Kopien des HTML-`<script>`-Blocks. Reproduzierbar via `extract_script.ps1` (falls jemals wieder noetig). Mojibake-Samples sind Encoding-Diff-Logs.

**Empfohlene Aktion:**
```powershell
git clean -fd tmp/ extracted_check.js
# oder selektiv:
Remove-Item tmp/*_check.js, tmp/mojibake_samples_*.txt, tmp/cashflow_block.txt, tmp/5eyes_v2.before_ftfy_backup.html
Remove-Item extracted_check.js
```

---

## Bucket B — Archivieren

Codex-Audit-Tasks (jeder Ordner enthaelt `apply.ps1` + Test-Skript / Spec). Diese sind nicht direkt im Code, aber dokumentieren vergangene Tasks, die vielleicht spaeter wieder relevant werden koennten.

```
tmp/codex-audit-f3-cma/         apply.ps1 + test_audit_f3_cma_drift.py
tmp/codex-audit-hardening/      apply.ps1 + test_audit_hardening.py
tmp/codex-audit-perm-hardening/ apply.ps1 + test_audit_perm_hardening.py
tmp/codex-audit-quick-fixes/    apply.ps1 + sandbox/ + test_audit_quick_fixes.py
tmp/codex-cashflow-baseline/    apply.ps1 + verify.ps1
tmp/codex-cashflow-footer/      README.md + SPEC.md + apply.ps1 + sandbox/ + test_cashflow_summary_contract.py
tmp/frontend_inventory/         frontend_inventory.csv + frontend_inventory_report.md + 2x .md
docs/CLAUDE_CODEX_SCOPE_SPLIT_NO_ASSET_ALLOCATION.md
```

**Begruendung:** Spec-Dokumente, Test-Drafts, Audit-Ergebnisse. Sollten erhalten bleiben (kostenlos in Git), aber nicht in `tmp/` herumliegen.

**Empfohlene Aktion:**
```powershell
mkdir docs/archive/wip_2026-05-13
Move-Item tmp/codex-audit-*, tmp/codex-cashflow-*, tmp/frontend_inventory docs/archive/wip_2026-05-13/
Move-Item docs/CLAUDE_CODEX_SCOPE_SPLIT_NO_ASSET_ALLOCATION.md docs/archive/wip_2026-05-13/
# dann committen:
git add docs/archive/wip_2026-05-13/
git commit -m "archive: WIP-Snapshot vom 2026-05-13"
```

---

## Bucket C — Separater Branch

```
5eyes-backend/tests/test_frontend_summary_contracts.py
```

**Begruendung:** Diese Datei testet **DOM-IDs** und **JS-Funktionen**, die nur in der **erweiterten WIP-Version** von `5eyes_v2.html` existieren (z.B. `id="sr-approval-grid"`, `function renderSrApprovalChecklist`, etc.). In der `develop`-HTML existieren diese Elemente NICHT — daher 36 Fehlschlaege lokal (CI sieht die Datei nicht, weil untracked).

**Gehoert zur WIP-Snapshot-Branch:** `codex/wip-fe-review-restructure-2026-05-08` — dort lebt die HTML-Erweiterung. Datei dort committen oder bis zum Merge der FE-Review parken.

**Empfohlene Aktion:**
```powershell
# Auf Codex-WIP-Branch wechseln und Test dort committen:
git checkout codex/wip-fe-review-restructure-2026-05-08
git add 5eyes-backend/tests/test_frontend_summary_contracts.py
git commit -m "chore(tests): FE-Summary-Contracts (WIP-Tests, keep with WIP-HTML)"

# Zurueck zur Arbeits-Branch:
git checkout codex/wip-cleanup-2026-05-13
```

---

## Was NICHT angefasst wird

- Alle `.gitignore`-Dateien
- Alle `5eyes-backend/` Module + Tests, die tracked sind
- Alle `docs/*.md` ausser dem o.g. ScopeSplit
- Die `5eyes-electron/frontend/5eyes_v2.html`-Aenderungen (das ist die WIP, gehoert zur FE-Review-Branch)

---

## Nach der Aufraeumung

`git status --short` sollte nur noch tracked Aenderungen anzeigen (idealerweise gar nichts auf `develop`). Workspace ist dann sauber genug fuer:
- Stress-frei PRs erstellen
- Branches wechseln ohne `tmp/`-Files mitziehen
- `.gitignore` ggf. um `tmp/` ergaenzen, damit zukuenftige Debug-Snapshots gar nicht erst auftauchen

**Vorschlag fuer `.gitignore` (separater Mini-PR):**
```
# Lokale Debug-Snapshots
tmp/
extracted_check.js
```
