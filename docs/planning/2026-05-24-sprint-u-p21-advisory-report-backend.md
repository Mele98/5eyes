# Sprint U-P21 — Advisory-Report-Aggregator (Backend)

## Meta

- **Datum:** 2026-05-24
- **Auslöser:** Berater-Wunschliste für institutionelles Family-Office-Reporting
  (User-Spec mit 15-Seiten-Struktur, Tech-Stack React + Tailwind + Recharts).
- **Scope:** **Backend-Datenquelle only.** React-Sub-App (5eyes-electron/
  frontend/reporting/) folgt in U-P22. Server-PDF folgt in U-P26.
- **Branding:** Keine Dritt-Marken in Code/Texten/PDF (Memory-Regel),
  designerische Inspiration aus institutionellem Wealth-Management ist OK.

## Zweck

Bevor Frontend (React) und PDF (ReportLab) gebaut werden, braucht es **eine
stabile Datenquelle**: einen Aggregator, der alle 15 Sektionen aus einem
JSON-Endpoint liefert. Damit:

- Frontend und PDF konsumieren dieselbe Quelle — keine Daten-Doppelpflege
- Spec-Änderungen ändern Datenstruktur an genau einer Stelle
- Tests decken die Daten-Aggregation ab, unabhängig von UI-Iterationen

## Architektur

```
services/advisory_report.py
├── compute_advisory_report(db, mandate, advisor=None)  ← Entry-Point
├── _build_cover()                  Sektion 1
├── _build_inhaltsverzeichnis()     Sektion 2
├── _build_ausgangslage()           Sektion 3 (client_info, wealth_summary, key_metrics)
├── _build_positionen()             Sektion 4 (SOLL aus RecommendationRun)
├── _build_pruefpunkte()            Sektion 5 (10 statische Blöcke)
├── _build_erkenntnisse()           Sektion 6 (Ampel)
├── _build_asset_allocation()       Sektion 7
├── _build_risikowaehrungen()       Sektion 8 (7 Berichts-Kategorien)
├── _build_branchen()               Sektion 9 (11 GICS + "Übrige")
├── _build_goal_based_investing()   Sektion 10
├── _build_risikoprofilierung()     Sektion 11
├── _build_building_blocks()        Sektion 12 (iSAA)
├── _build_statement_pm()           Sektion 13 (7 Grundsätze)
├── _build_weiteres_vorgehen()      Sektion 14 (Berater-Platzhalter)
└── _build_disclaimer()             Sektion 15 (FINMA-Pflichthinweise)
```

**Single-Quelle-Prinzip:** `compute_depot_check(db, mandate)` wird einmal
pro Report-Aufbau berechnet und an alle Sektionen weitergereicht, die seine
Aggregationen brauchen (Erkenntnisse-Ampel, AA, Währungen, Branchen).

## JSON-Schema v1

```json
{
  "schema_version": 1,
  "mandate_id": "...",
  "generated_at": "2026-05-24T16:30:00.000Z",

  "cover": {
    "title": "Depotcheck",
    "subtitle": "Strategische Portfolioanalyse",
    "client_name": "...",
    "mandate_number": "...",
    "report_date": "2026-05-24",
    "advisor_name": "..."
  },

  "inhaltsverzeichnis": {
    "kapitel": [{"nr": 1, "title": "Ausgangslage"}, ...]
  },

  "ausgangslage": {
    "client_info": {alter, anlagehorizont_jahre, risikoprofil, anlageziel,
                    liquiditaetsbedarf_rappen, steuerdomizil, referenzwaehrung},
    "wealth_summary": {gesamtvermoegen_rappen, beratungsvermoegen_rappen,
                       immobilien_rappen, vorsorge_rappen, kredite_rappen,
                       cashflows: [...], ziele: [...]},
    "key_metrics": {risky_fraction_bps, zielerreichung_bps, exp_vol_bps,
                    exp_return_bps, max_drawdown_bps, var_95_bps}
  },

  "positionen": {
    "groups": [{key, label, positions: [...], total_rappen, share_bps}, ...],
    "total_rappen": int,
    "has_recommendation_run": bool,
    "hinweis": str
  },

  "pruefpunkte": {"bloecke": [{key, title, beschreibung}, ... (10x)]},

  "erkenntnisse": {
    "checks": [{pruefpunkt, bewertung, beurteilung, handlungsempfehlung}, ... (9x)]
    // bewertung ∈ {gruen, gelb, rot, nicht_beurteilbar}
  },

  "asset_allocation": {
    "items": [{key, label, ist_bps, soll_bps, drift_bps, band_min_bps,
               band_max_bps, in_band}, ... (5x)],
    "ist_bps": {...}, "soll_bps": {...}, "drift_bps": {...},
    "anmerkungen": str
  },

  "risikowaehrungen": {
    "items": [...], "ist_bps": {...}, "soll_bps": {...}, "drift_bps": {...},
    "erklaerung": str
    // 7 Kategorien: CHF, USD, EUR, GBP, JPY, EM FX, Andere
  },

  "branchen": {
    "items": [...], "ist_bps": {...}, "soll_bps": {...}, "drift_bps": {...},
    "analyse": str
    // 11 GICS + "Übrige" (nur wenn > 0)
  },

  "goal_based_investing": {
    "goals": [{goal_id, label, goal_type, target_amount_rappen, target_date,
               hardness, probability_bps, status}, ...],
    "goal_achievement_score_bps": int,
    "monte_carlo_paths": {"data_pending": true, "note": "..."}
    // MC-Pfade werden in U-P26 lazy berechnet und befüllt
  },

  "risikoprofilierung": {
    "risky_fraction_bps", "risk_capacity_score_x10", "risk_willingness_score_x10",
    "final_score_x10", "final_profile", "is_overridden", "override_reason",
    "questions": [...] // 8 Standard-Fragen
  },

  "building_blocks": {
    "blocks": [{key, label, target_bps, band_min_bps, band_max_bps}, ... (5x)],
    "constraints": [...],
    "methodologie": str
  },

  "statement_pm": {"principles": [{key, title, body}, ... (7x)]},

  "weiteres_vorgehen": {
    "block_optimierungen": str,
    "block_zielstrategie": str,
    "offene_fragen": [...],
    "naechster_termin": str | null,
    "todos": [...],
    "dokumente": [...]
  },

  "disclaimer": {"hinweise": [...]}  // 7 FINMA-konforme Pflichthinweise
}
```

## Endpoint

```
GET /mandates/{mandate_id}/advisory-report
  Auth: get_current_user (Berater)
  Returns: 200 application/json (Schema v1)
          404 mandat nicht gefunden / kein Zugriff
```

## Defensive Disziplin

- **Fehlende Daten → strukturierte Defaults**, kein 500-Crash:
  - Kein RecommendationRun → 5 leere Positions-Gruppen + Hinweis
  - Keine TA → `key_metrics` und `building_blocks` haben `target_bps=0`
  - Kein RiskAssessment → Erkenntnisse-Ampel "rot" mit Begründung, NICHT Crash
  - Kein `goal_achievability_json` → leere Goal-Liste, score=0
  - Keine Sektor-/Country-Daten → Erkenntnisse-Ampel "nicht_beurteilbar"
- **Mandat ohne client_id → ValueError** (echte Daten-Inkonsistenz, kein
  silent recovery)
- **Ampel-Logik mit 4. Status `nicht_beurteilbar`** statt falsches Grün

## Branding-Disziplin (per Memory)

- Pruefpunkte-Test prüft expliziert: keine "ubs/pictet/julius bär/swiss life/3eyes"
  in den statischen Beschreibungen.
- Statement-PM-Test zusätzlich: keine "garantiert/Garantie" (FINMA-Compliance).
- Disclaimer-Test (von U-P21.1) prüft alle 7 FINMA-Pflichtphrasen + Branding.

## Tests

`tests/test_advisory_report.py` — **31 Tests, alle grün**:

| Sektion | Tests | Was geprüft |
|---|---|---|
| Entry-Point | 2 | Top-Level-Struktur, ValueError ohne client_id |
| 1 Cover | 2 | Vollständiger Name, Fallback auf "—" |
| 2 Inhaltsverzeichnis | 1 | 11 Kapitel, stabile Reihenfolge |
| 3 Ausgangslage | 4 | client_info Defaults, wealth_summary 5 Kategorien, Cashflows+Goals, key_metrics None-Behandlung |
| 4 Positionen | 2 | 5 leere Gruppen ohne Run, Aggregation+Shares |
| 5 Pruefpunkte | 1 | 10 stabile Keys, Branding-Compliance |
| 6 Erkenntnisse | 4 | 9 Checks Struktur, Risikoprofil rot/grün, Zielkompatibilität nicht_beurteilbar |
| 7 AA | 2 | Reihenfolge 5 Buckets, Drift+Band |
| 8 Währungen | 2 | 7 Buckets, EM-FX Bucketing |
| 9 Branchen | 1 | 11 GICS, "Übrige" nur wenn > 0 |
| 10 Goal-Based | 2 | Empty-State, Achievement-Score |
| 11 Risikoprofil | 2 | Defaults, mit RA-Daten |
| 12 Building Blocks | 2 | Empty-TA, mit TA + Constraints |
| 13 Statement | 1 | 7 Prinzipien, Branding+keine Garantieversprechen |
| 14 Vorgehen | 1 | Platzhalter |
| Endpoint | 1 | Smoketest GET /advisory-report |
| 15 Disclaimer | 1 | 7 FINMA-Pflichthinweise + Branding |

## Nicht im Sprint (geplant in Folge-Sprints)

| Sprint | Was |
|---|---|
| **U-P22** | React-Sub-App Setup (Vite + Tailwind + Recharts + Framer Motion) + Cover + 1. Seite als Proof |
| U-P23 | Frontend-Komponenten Seiten 2-5 |
| U-P24 | Seiten 6-10 (inkl. echte Monte-Carlo-Pfade) |
| U-P25 | Seiten 11-15 |
| U-P26 | Server-PDF (ReportLab) im identischen Layout |
| U-P27 | Polish + Electron-Integration + Export-Flows |
| separat | `MandateReportNotes`-DB-Tabelle für Berater-Overrides
  (Anmerkungen, Erklärung, Analyse, Weiteres Vorgehen, naechster_termin) |

## Auswirkung

- 5eyes hat ab jetzt eine **stabile, getestete API** für institutionelles
  Wealth-Reporting.
- Berater kann den Endpoint heute schon konsumieren (curl/Postman) und
  manuelle Reports zusammenstellen.
- React + PDF in den Folge-Sprints können sich rein auf Layout +
  Visualisierung konzentrieren — die Daten-Frage ist gelöst.
