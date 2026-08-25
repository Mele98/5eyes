# Standortanalyse v2 — Realitaets-Check nach 5-Sprint-Marathon

**Datum:** 2026-05-17 (Abend)
**Status:** Aktiv — ersetzt v1 (vormittag) als Roadmap-Anker
**Vorgaenger:** docs/planning/2026-05-17-standortanalyse-vs-3eyes.md (v1)

## 0. Was sich seit v1 geaendert hat

| v1 (vormittag) | v2 (jetzt) |
|---|---|
| §A 1/3 — nur Sprint-1-UX | §A **3/3** — Tax/Dividenden/Mortalitaet alle done |
| §C 2/3 | §C **3/3** — PDF-Engine fertig |
| ~1340 Tests | **~1490 Tests** (+150) |
| Backend ≈ Frontend | **Backend 3 Sprints vor Frontend** |

## 1. Realitaets-Check: Was lebt, was ist tot

| Feature | Backend | UI | Verdict | Aktion |
|---|---|---|---|---|
| **PDF-Engine** | ✅ Endpoints `/mandates/{id}/reports/*.pdf` | ❌ keine Buttons | **TOT** | P1 — UI-Buttons |
| **PDF Audit-Hash** | ⚠️ liest fehlende DB-Felder | — | **BUG** | P0 — fixen |
| **BFS-Sterbetafel** | ✅ Engine ruft Sampler | ❌ keine Eingabe-Felder | **TOT** | P3 — UI + DB |
| **Tax-Plugin-System** | ✅ Engine-Parameter | ❌ keine Auswahl | **TOT** | P4 — sekundaer |
| **Importance-Sampling** | ✅ in scenario_engine | ❌ Optimizer ruft nicht | TOT | spaeter |
| **life_expectancy_year / retirement_year** | ✅ DB-Feld | ❌ kein Input | TOT | mit P3 mit |
| **investment_universe** | ✅ DB + Schema | ⚠️ kein Selector | TEILWEISE | spaeter |
| **default_building_blocks_json** (B1) | ✅ | ✅ Checkboxes | **LEBT** | — |
| **Auto-Recompute** (Sprint 1) | ✅ | ✅ Debounce | **LEBT** | — |

**Kern-Befund**: 3 Backend-Features heute gebaut, 0 sind im UI sichtbar. Backend-Vorsprung
ist ein Schuldenberg. UI-Catch-up vor weiterem Backend-Feature.

## 2. Codex-WIP-Branch — Entscheidung

`codex/wip-risikoprofil-2026-05-17` (3 Commits: d62ea85, 657d716, 95eb990)

**Verdict (per separate Analyse)**: **MERGE-faehig, kohaerente Arbeit**.

| Aenderung | Wert | Risiko |
|---|---|---|
| portfolio_engine: alle 11 Fragen Pflicht (vorher 9) | sinnvoll — Compliance-Schaerfung | bricht Legacy-Mandate ohne Frage 1-2 |
| `override_reason` Pflichtfeld bei Risk-Override | sinnvoll — kein undokumentierter Override | API-Konsumenten muessen Feld liefern |
| tests/risk_fixture_helpers.py | sinnvoll — zentrale Fixtures | — |
| 5eyes_v2.html: 88 Lines UI fuer Fragen 1-2 | sinnvoll | — |

**Migration-Strategie vor Merge**:
- DB-Script: alle alten `RiskAssessment` bekommen `knowledge_services_json='{}' if null`
- Oder: `_risk_assessment_has_current_schema_markers()` toleriert Legacy
- Tests muessen alle gruen sein nach Merge

## 3. Architektur-Konsistenz-Check

3 Plugin-Systeme heute gebaut, leicht inkonsistent aber **nicht kritisch**:

| System | Pattern | Konsistenz |
|---|---|---|
| `services/tax/` | Strategy + Registry mit Glob | Vollausbau |
| `services/mortality/` | Strategy (nur 1 Impl: BFS) | Registry weggelassen — OK fuer 1 Impl |
| `services/pdf/` | Strategy + Components | Renderer-Lookup nicht noetig |

**Verdict**: keine Refactor-Notwendigkeit. Patterns sind je nach Bedarf justiert.

## 4. Prioritaeten — neue Roadmap

Sortiert nach **Hebel pro Aufwand**, NICHT nach Sprint-Reihenfolge:

| Prio | Aufgabe | Aufwand | Wert |
|---|---|---|---|
| **P0** | PDF Audit-Hash Bug fixen | 10 min | verhindert User-Bug |
| **P1** | PDF-Buttons im Mandate-Tab | 30-45 min | macht heutige PDF-Engine sofort sichtbar |
| **P2** | Codex-WIP mergen + Legacy-Migration | 1-2h | linearer develop-Stand |
| **P3** | BFS-Mortalitaets-UI + Mandate-Felder + Optimizer-Integration | 1-2h | macht heutige BFS-Engine im Workflow nutzbar |
| **P4** | Tax-UI light (Dropdown + Disclaimer) | 1h | sekundaer (User-Direktive) |
| **P5** | Sprint 6 — Nelson-Siegel Yield-Curve (§B.4) | 3-4h | Bonds-Bewertung deutlich besser |
| **P6** | Sprint 7 — Multi-Currency (§D.10) | 4-5h | internationale Mandate |
| **P7** | Sprint 8 — ISIN-Recommendation-Engine (§D.11) | 5-6h | konkrete Produkt-Vorschlaege |
| **P8** | KGV-Mean-Reversion (§B.5) + Risikopraemien-Modell (§B.6) | je 2-3h | feinere Equity-/Alts-Bewertung |

## 5. Demo-Faehigkeit jetzt

Was kann man **heute** einem Berater zeigen?

✅ **Funktioniert end-to-end**:
- Mandant anlegen → Stammdaten + Cashflows + Goals → Risikoprofil → SAA generieren → Auto-Recompute
- Optimizer mit stochastic-mode default
- Building Blocks pro Mandant

❌ **Nicht zeigbar** (Backend da, UI fehlt):
- PDF-Download (Endpoint da, kein Button)
- Mortalitaets-adjustierte Projektion
- Steuer-Drag

⚠️ **Halb-Demo**:
- Risikoprofil-Validation (Codex-WIP nicht gemerged, daher inkonsistent zwischen Backend-Branches)

## 6. Erfolgskriterien fuer Demo-Reife

Nach Erledigung P0-P4 sollte gelten:
- Berater klickt "PDF Anlagestrategie" → bekommt fertiges PDF (P0+P1)
- Berater setzt "Mortalitaet beruecksichtigen" Haken → MC-Pfade variieren in Lebensdauer (P3)
- Berater waehlt Steuersitz CH/DE → SAA-Wirkung sichtbar (P4)
- develop-Branch ist linear, alle Tests gruen (P2)

**Nach P0-P4 ist 5eyes Demo-reif fuer ersten externen Berater-Beta-Test.**

## 7. Was NICHT machen

- Sprint 6+ vor P0-P4 starten → Tech-Schulden eskalieren
- Tax-UI ueberbauen → war User-explizit als sekundaer eingestuft
- Codex-WIP einfach ignorieren → Drift wird groesser pro Tag
- Importance-Sampling im Optimizer aktivieren ohne UI-Toggle

## 8. Out-of-Scope (bewusst)

- Whitelabel-Branding fuer PDFs (Phase 4+ wenn ein 2. Berater dazukommt)
- Multi-Tenant-Tax-Sets (Tax ist sekundaer)
- Asien/USA-TaxRegimes (Tax ist sekundaer)
- Selbst-Selektions-Effekte fuer BFS (Sterblichkeits-DBM zu komplex)
- ISO-Sprachen ausser de-CH (Phase 4+)
