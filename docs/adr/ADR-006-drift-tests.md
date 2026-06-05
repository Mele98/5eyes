# ADR-006: Drift-Tests als Konsistenz-Wall

- **Status:** Accepted
- **Datum:** 2026-05-25 (erstmals genutzt), 2026-06-05 (formalisiert)
- **Sprint:** querschnittlich (U-P21, U-21, U-22, U-66, U-80, U-81 etc.)

## Kontext

Das 5eyes-Repository hat **mehrere parallele Surfaces** die das gleiche
Wissen ausdrücken müssen:

- Backend-Aggregator (`compute_advisory_report()`) → liefert 23 Sektionen
- Frontend-Types (`src/api/types.ts`) → Spiegelung der Sektionen
- PDF-Renderer → erwartet feste Section-Keys
- Sub-App-Sidebar → listet alle Sektionen mit Nummer
- README → dokumentiert API-URLs + Aggregator-Stand
- GLOSSAR.md → definiert alle im Code/PDF auftauchenden Begriffe

Wenn eine Stelle wegläuft, schlägt nichts fehl — die Software läuft
weiter, aber Drift entsteht still. Und Drift ist FINMA-relevant:
PDF und Sub-App müssen denselben Inhalt zeigen.

## Entscheidung

Wir schreiben **Drift-Tests**: pytest-Cases die Quell-Dateien
**parsen** und vergleichen, statt Code auszuführen.

Beispiele:
- `test_sidebar_lists_all_17_sections_and_active_state` — parst
  `Sidebar.tsx`, prüft 17x `id: '` + Sektion-Titel
- `test_sidebar_has_stable_section_numbers` — parst `nr: <N>`
  Pattern, prüft `[1..17]`
- `test_readme_lists_all_23_aggregator_sections` — parst README,
  prüft dass alle Konsolidierungs-Keys auftauchen
- `test_glossar_defines_compliance_stack_layers` — parst GLOSSAR.md,
  prüft 3 Compliance-Layer-Pfade
- `test_liquidity_cascade_thresholds_match_portfolio_engine` —
  parst `portfolio_engine.py` und `liquidity_cascade_audit.py`,
  prüft dass 300/1000 bps identisch sind

## Konsequenzen

**Positiv:**
- Drift wird zu **CI-Fehler statt Silent-Bug**
- Jeder PR der einen Aggregator-Key umbenennt wird gezwungen die
  Spiegelung mitzuziehen
- Doku-Drift (README, GLOSSAR) wird genauso gefangen wie Code-Drift
- Keine Runtime-Kosten — Drift-Tests sind reines String-Matching

**Negativ:**
- Tests werden chatty (viele kleine Assertions)
- "Refactoring-Friction": Wer Section-Keys ändert muss in 3-4 Stellen
  gleichzeitig editieren. Genau das ist erwünscht.
- Drift-Test kann false-positive werden wenn Doku-Wording ändert
  → akzeptiert, Re-Wording braucht bewusste Test-Aktualisierung

**Pattern-Rezept:**
1. Identifiziere die N Stellen die synchron bleiben müssen
2. Wähle die kanonische Quelle (typischerweise Backend)
3. Schreibe einen Test der eine non-kanonische Stelle parst und
   gegen die kanonische prüft
4. Bei mehr als 2 Stellen: zentrale Pin-Liste im Test-File

**Beispiele im Repo (Stand 2026-06-05):**
- `5eyes-backend/tests/test_reporting_frontend_phase1.py`
- `5eyes-backend/tests/test_readme_consistency.py`
- `5eyes-backend/tests/test_glossar_consistency.py`
- `5eyes-backend/tests/test_liquidity_cascade_constants.py`
