# Codex-Kollaborations-Doku

Das 5eyes-Repo wird parallel von zwei AI-Agenten beackert:
**Claude** (architektur-getrieben, Sub-App + Aggregator + Compliance) und
**Codex** (PDF-Rendering + Design-Audits). Damit das ohne Konflikt
funktioniert, gelten ein paar feste Regeln.

**Stand:** 2026-06-05

---

## Datei-Trennung

| Bereich | Verantwortlich | Pfade |
|---------|---------------|-------|
| Aggregator (Datenstruktur 23 Sektionen) | Claude | `5eyes-backend/services/advisory_report.py` |
| Backend-Services (Audit, Lifecycle, Cleanup) | Claude | `5eyes-backend/services/*.py` (ohne `pdf/`) |
| Admin-Endpoints | Claude | `5eyes-backend/routers/*.py` (ohne `pdf_reports.py`) |
| Sub-App (React/Vite) | Claude | `5eyes-electron/frontend/reporting/` |
| Doku | Claude | `docs/` |
| PDF-Renderer | Codex | `5eyes-backend/services/pdf/**` |
| PDF-Endpoint | Codex | `5eyes-backend/routers/pdf_reports.py` |
| PDF-Tests | Codex | `5eyes-backend/tests/pdf/`, `5eyes-backend/tests/test_*_pdf*.py` |
| Hauptapp HTML | Codex / User | `5eyes-electron/frontend/5eyes_v2.html` |

Ueberlapp passiert nur am Aggregator-Output (Datenstruktur) — Codex liest,
Claude schreibt. Strukturelle Aenderungen sind Claude-Pflicht und werden
in ADR-001 dokumentiert.

---

## Workflow vor jedem Commit

Aus [feedback-branch-check-before-commit](../../../Users/Emanuele/.claude/projects/C--Users-Emanuele/memory/feedback_branch_check_before_commit.md):

```bash
BR=$(git branch --show-current) && [ "$BR" = "<expected>" ] || (echo ABORT; exit 1)
```

Pflicht, weil `Bash` zwischen Aufrufen die `cwd` resetten und Codex'
parallele Branch-Wechsel mich aufs falsche Branch werfen koennen.

---

## Race-Recovery-Pattern

Wenn ein Branch-Race waehrend der Arbeit auftritt:

1. **NICHT** `git checkout` ohne Stash — Codex' Working-Tree-Mods koennen
   die Edits ueberschreiben.
2. **Backup-First:** kritische Files nach `/tmp/_<sprint>_backup.<ext>` kopieren.
3. **Stash-Pop oder Re-Apply:** Branch wechseln, Backup zurueckspielen.
4. **Stage-Only-My-Files:** `git add <konkrete-Pfade>`, niemals `git add -A`.

Dieses Pattern hat heute mehrfach gerettet (U-81 + U-83 + U-103+104).

---

## Codex-Prompt-Format

Am Ende jeder Claude-Antwort kommt ein Codex-Prompt-Block. Aufbau:

```text
HINWEIS: Du arbeitest am <Codex-Sprint>.
Claude hat <Sprints> gepusht — PRs #<N> bis #<M>.
Datei-Overlap: KEINE / <Liste>.
Wenn du fertig bist: rebase auf neuestes origin/develop.
<Optional: Sicherheits-Hinweis fuer Codex-Sprint>
```

Aus [feedback-codex-output](../../../Users/Emanuele/.claude/projects/C--Users-Emanuele/memory/feedback_codex_output.md).

---

## Konflikt-Klassen die wir aktiv vermeiden

| Konflikt-Typ | Mitigation |
|--------------|-----------|
| Frozenset-Literal (z.B. `AUDIT_LOG_VALID_ACTIONS`) | wenn moeglich `action="DELETE"` statt neue Action wenn parallele PR aktiv ist (siehe U-104) |
| Aggregator-Dict-Order | beide Branches addieren am Ende — Aggregator-Konsolidierungs-Pattern bei PR-Konflikt (U-163-style) |
| Sidebar-Section-Count | Drift-Test pinned die Zahl → bewusster Update notwendig (U-87 reportet Konflikt early) |
| package.json | nur Claude editiert dependencies (Sub-App) — Codex laesst Hauptapp-Hauptapp-Hauptapp-package-lock |

---

## Bekannte historische Race-Recovery-Aktionen

- 2026-06-04: 28 race-recovery Stashes via `preserve-u*`-Prefix, cleanup
  in PR #159 dokumentiert (`docs/REPO_HYGIENE_2026-06-04.md`)
- 2026-06-05: 12 weitere Stashes (preserve-u*) manuell aufgeloest
- 2026-06-05: U-81 + U-83 + U-103+104: jeweils Branch-Race waehrend Push;
  geloest via Backup/Re-Apply-Pattern

---

## Wenn dieser Doc veraltet

Aktualisieren wenn:
- neue Datei-Bereiche entstehen (z.B. neuer Service-Layer)
- neue Konflikt-Klassen auftauchen
- Codex' Scope sich aendert (z.B. wenn Codex Sub-App-Arbeit uebernimmt)

`git log -- docs/CODEX_WIP.md` zeigt Aenderungs-Historie.
