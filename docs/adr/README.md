# Architecture Decision Records (ADRs)

Hier liegen die wichtigsten Architektur-Entscheidungen des 5eyes-Projekts
in dauerhafter Form. Jeder ADR beantwortet ein "Warum X und nicht Y?"
sodass kein Engineer das Rad neu erfinden muss.

## Format

Jeder ADR folgt einem schlanken Schema:

- **Status** — `Accepted` / `Superseded by ADR-NNN` / `Deprecated`
- **Datum** — Tag der Entscheidung
- **Kontext** — Was war das Problem?
- **Entscheidung** — Was haben wir gemacht?
- **Konsequenzen** — Was bedeutet das (Trade-offs, Folge-Sprints)?

## Liste

| Nr | Titel | Status | Sprint |
|----|-------|--------|--------|
| [001](ADR-001-aggregator-pattern.md) | Aggregator-Pattern als Single-Source-of-Truth | Accepted | U-P21 |
| [002](ADR-002-compliance-stack-3-layer.md) | Compliance-Stack 3-Schichten-Trennung | Accepted | U-66/U-71/U-73/U-74 |
| [003](ADR-003-anlagephilosophie-no-market-timing.md) | Anlagephilosophie ohne Markt-Timing | Accepted | (Kerndoktrin) |
| [004](ADR-004-editorial-no-recharts.md) | Editorial-Design ohne Chart-Library | Accepted | U-12/U-14 |
| [005](ADR-005-free-data-pipeline.md) | Gratis-Marktdaten-Pipeline (CHF 0/Jahr) | Accepted | U-30 |
| [006](ADR-006-drift-tests.md) | Drift-Tests als Konsistenz-Wall | Accepted | (querschnittlich) |
| [014](ADR-014-engine-module-split-plan.md) | Engine-God-Modul `portfolio_engine.py` — Split-Plan | Accepted (Plan) | Welle 3.2 |

## Wann einen neuen ADR schreiben?

- Bei jeder Architektur-Entscheidung die nicht aus dem Code ablesbar ist
- Bei jeder bewussten Ablehnung einer "Standard"-Lösung
- Bei jeder Trade-off-Entscheidung die ein Engineer in 6 Monaten infrage
  stellen könnte

**NICHT** für: Code-Style, Naming, lokale Refactorings, Bug-Fixes.
