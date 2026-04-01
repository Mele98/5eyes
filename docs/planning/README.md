# Collaboration Workflow

Diese Struktur ist die gemeinsame Arbeitsbasis fuer Claude, Codex und GitHub.

## Rollen

- Claude:
  - plant
  - zerlegt Features
  - dokumentiert Fachlogik
  - schreibt Akzeptanzkriterien
  - reviewed Diffs oder PRs
- Codex:
  - implementiert
  - verbindet APIs und UI
  - schreibt Tests
  - prueft Runtime und Regressionen

## Branch-Modell

- `main`: stabiler, produktionsnaher Stand
- `develop`: Integrationsbranch
- `codex/<slug>`: Implementierungsbranch fuer Codex
- `claude/<slug>`: optionaler Planungs-/Review-Branch fuer Claude

Claude soll moeglichst nicht direkt auf Produktivcode arbeiten, sondern ueber:
- GitHub Issues
- Spezifikationen in diesem Ordner
- Review-Kommentare / PR-Feedback

## Standardablauf

1. Claude erstellt einen Plan mit [CLAUDE_SPEC_TEMPLATE.md](C:/5eyes/5eyes_stage9_release_ready/docs/planning/CLAUDE_SPEC_TEMPLATE.md).
2. Die Spezifikation landet in `docs/planning/<datum>-<slug>.md` oder in einem GitHub Issue.
3. Codex startet mit `scripts/start_codex_branch.ps1` einen sauberen `codex/...`-Branch.
4. Codex setzt die Aufgabe um und prueft sie gegen die Akzeptanzkriterien.
5. Claude reviewed Diff, PR oder die von Codex verlinkten Dateien mit [REVIEW_CHECKLIST.md](C:/5eyes/5eyes_stage9_release_ready/docs/planning/REVIEW_CHECKLIST.md).
6. Merge geht nach `develop`.
7. `main` wird erst aktualisiert, wenn der Integrationsstand stabil ist.

## Minimale Uebergabe von Claude an Codex

Claude sollte pro Block genau diese Punkte liefern:

- Ziel
- Scope
- Nicht-Scope
- Dateien / Module
- API-Auswirkungen
- Datenmodell-Auswirkungen
- Akzeptanzkriterien
- Testfaelle
- offene Owner-Entscheide

## PowerShell-Helfer

- [start_codex_branch.ps1](C:/5eyes/5eyes_stage9_release_ready/scripts/start_codex_branch.ps1)
  - erzeugt einen sauberen `codex/...`-Branch
- [new_claude_spec.ps1](C:/5eyes/5eyes_stage9_release_ready/scripts/new_claude_spec.ps1)
  - legt eine neue Spezifikation aus dem Template an

## Wichtige Regel

Wenn eine Fachentscheidung nicht sauber dokumentiert ist, soll Claude sie explizit als `OWNER-DECISION` markieren statt still zu raten.
