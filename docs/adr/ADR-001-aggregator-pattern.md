# ADR-001: Aggregator-Pattern als Single-Source-of-Truth

- **Status:** Accepted
- **Datum:** 2026-05-15 (formalisiert 2026-06-05)
- **Sprint:** U-P21 (initial), durchgehend gepflegt

## Kontext

Der Beratungsreport hat 23 Sektionen (Stand 2026-06-05). Jede Sektion
braucht Daten aus mehreren Quellen: Stammdaten, Mandat,
Risikoprofil, Optimizer-Run, CMA, Audit-Log, etc. Diese Sektionen werden
in **zwei Surfaces** angezeigt:

1. **PDF-Report** (Backend, ReportLab/HTML→PDF)
2. **Sub-App** (Frontend, React/Vite — Berater-Sicht ohne Druck)

Wenn beide Surfaces ihre Daten unabhängig zusammenstellen, driften sie
auseinander (anderer Rundung, andere Fallback-Logik, andere Reihenfolge).
Das ist ein FINMA-Risiko: was der Berater am Bildschirm sieht muss exakt
dem entsprechen was der Kunde im PDF bekommt.

## Entscheidung

Eine einzige Backend-Funktion `compute_advisory_report(db, mandate_id)`
in `5eyes-backend/services/advisory_report.py` ist die **einzige
Quelle** der 23 Sektionen.

- Return-Typ: `dict[str, Any]` mit festen Section-Keys
- Reihenfolge fix (Cover → Disclaimer → TOC → ... → WeiteresVorgehen
  → Compliance-Block 16-23)
- PDF-Renderer und Sub-App konsumieren beide diesen Dict
- Jede neue Sektion bekommt einen neuen Top-Level-Key

## Konsequenzen

**Positiv:**
- Surface-Drift ausgeschlossen — PDF und Sub-App können nur dasselbe
  rendern
- Drift-Tests prüfen Section-Liste + Reihenfolge gegen
  `frontend/reporting/src/api/types.ts` (siehe ADR-006)
- Cache-Layer (U-19) ist eine Schicht über genau dieser Funktion → 1
  Recompute pro Klick statt N
- N+1-Optimierung (U-18) konzentriert sich auf eine einzige Funktion

**Negativ:**
- Funktion wird länger. Mittlerweile ~600 Zeilen. Aufteilung in
  Sub-Module wäre denkbar aber bricht Cache-Key + Drift-Tests.
- Konflikte bei parallelen PRs die gleichzeitig Sektionen hinzufügen
  → gelöst via Aggregator-Konsolidierungs-Pattern (PR #163)
- Memory-Footprint: ganzer Dict im RAM. Bei 23 Sektionen vernachlässig-
  bar, bei 100+ wird es ein Thema.

**Folge-Entscheidungen:**
- ADR-002 baut die Compliance-Drilldown-Schicht **über** dem Aggregator,
  nicht parallel
- ADR-006 schreibt vor: Section-Keys werden in Drift-Test gepinnt
