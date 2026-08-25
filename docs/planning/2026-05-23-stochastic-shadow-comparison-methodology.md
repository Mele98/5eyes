# Stochastic Goal Engine — Shadow-Vergleichs-Methodologie

## Meta

- Titel: Methodischer Test-Plan für den `OPTIMIZER_MODE=stochastic`-Default-Wechsel
- Datum: 2026-05-23
- Owner: Emanuele Konzelmann
- Erfüllt: Spec `2026-05-23-stochastic-goal-engine-spec.md` §10 Acceptance #10
  *"Default-Wechsel auf `stochastic` erst nach grünem Shadow-Vergleich auf
  Foundation-Case + 3 realen Mandaten"*
- Adressiert: Codex Stage 5 (`shadow_stochastic`-Mode + Default-Wechsel)

## Zweck

Bevor der `OPTIMIZER_MODE`-Default von `house_matrix` auf `stochastic` umgestellt
wird, muss bewiesen sein, dass die stochastische Engine **fachlich vertretbare,
nicht überraschende Allokationen** liefert. „Vertretbar" heißt: die Drift gegen
die etablierte House-Matrix-Engine ist erklärbar, im erwarteten Korridor und
verbessert (oder lässt unverändert) die Zielerreichung — sie überrascht nicht.

Dieses Dokument definiert das **exakte Vorgehen**, die **messbaren Schwellen**
und das **Reporting-Format** für den Shadow-Vergleich. Ohne grünen Vergleich
nach dieser Methodologie wird der Default nicht gewechselt — egal wie grün die
Unit-Tests sind.

## 1. Voraussetzungen

Vor Start des Shadow-Vergleichs müssen erfüllt sein:

- Stages 1-4 committed auf `develop`, volle Backend-Suite grün (≥ 1700 Tests).
- Stage 5 `shadow_stochastic`-Mode implementiert: beide Engines laufen, House-
  Matrix-Resultat ist sichtbar in der App, Stochastic-Resultat ist persistiert
  in `TargetAllocation.shadow_optimization_json` (Drift-Vektor + Reasoning).
- Admin-Schalter `OptimizerPolicy.optimizer_mode ∈ {house_matrix,
  shadow_stochastic, stochastic}` ist im Admin-UI bedienbar.
- Foundation-Case (`services/foundation_example.py upsert_foundation_example_case`)
  läuft fehlerfrei durch und liefert ein gültiges `TargetAllocation`.
- Risk-Matrix-Daten-Foundation grün (`tests/test_risk_matrix_data_foundation.py`).

## 2. Test-Mandate

Vier Mandate werden im Shadow-Modus gegen House-Matrix verglichen. Drei davon
sind reale Berater-Mandate, eins ist die deterministische Foundation.

### 2.1 Foundation-Case (deterministisch)

- Mandat: `FOUNDATION_MANDATE_NUMBER` aus `services/foundation_example.py`.
- Profil: Wachstumsorientiert (Score 7-8), `final_score_x10 = 75`.
- Goals: 4 Stück (Pensionsvorsorge, 3a-Bezug, Hauskauf 2032, Sicherheitsreserve).
- Cashflows: 7 Einträge (Lohn, AHV, BVG, 3a, Lebenshaltung, Mietnebenkosten,
  Versicherungen).
- Vermögen: 6 Positionen, ~ CHF 1.2 Mio Beratungsvermögen.
- Zweck: deterministischer Smoke-Test, garantiert reproduzierbar.

### 2.2 Drei reale Mandat-Archetypen

Wahl aus echten Mandaten im System, anonymisiert dokumentiert. Vorgeschlagene
Archetypen (vom Berater auszuwählen):

1. **Defensiv-Pensionär**
   - Profil-Score ≤ 4 (Kapitalschutz oder Defensiv).
   - Mindestens 1 hartes Cashflow-Ziel (Pensionsausgabe).
   - Beratungsvermögen ≥ CHF 500'000.

2. **Wachstumsorientiert mit Vermögensziel**
   - Profil-Score 6-8 (Ausgewogen bis Wachstumsorientiert).
   - Mindestens 1 primäres Vermögensziel mit Horizont 8-15 Jahre.
   - 2-3 Cashflows in Akkumulationsphase.

3. **Dynamisch-Akkumulation**
   - Profil-Score ≥ 8 (Dynamisch oder Aktien).
   - Hauptziel: Maximierung oder Renditeziel.
   - Berater muss bestätigen, dass die Hardness-Verteilung der Goals plausibel
     ist (kein hartes Renditeziel — sonst Schema-Verstoß per OD-F).

Jeder Archetyp wird **anonymisiert** in den Report eingetragen
(Mandat-Nr → Pseudonym `archetype-1` etc.).

## 3. Gemessene Metriken

Pro Mandat werden folgende Metriken zwischen House-Matrix-Ergebnis (HM) und
Stochastic-Ergebnis (ST) verglichen:

### 3.1 Allokations-Drift (Primärmetrik)

Pro Bucket (equities, bonds, real_estate, alternatives, liquidity):

```
drift_bps_b = |target_b_HM - target_b_ST|
total_drift_bps = max_b drift_bps_b    # größte Single-Bucket-Drift
```

### 3.2 Risikobudget-Konformität

```
risky_HM = compute_portfolio_risky_fraction_bps(HM, building_blocks)
risky_ST = compute_portfolio_risky_fraction_bps(ST, building_blocks)
max_risky = max_risky_fraction_for_mandate(...)

risky_drift_bps = |risky_HM - risky_ST|
budget_compliance_HM = (risky_HM ≤ max_risky)
budget_compliance_ST = (risky_ST ≤ max_risky)
```

Beide MÜSSEN compliant sein (Acceptance §10 #1). Stochastic darf nicht über
House-Matrix-Cap gehen — wäre ein harter Bruch.

### 3.3 Zielerreichungs-Drift (nur Stochastic, da HM keine Achievability liefert)

Pro Goal:

```
ST_goal_achievability = [{goal_id, probability, status, hardness}, ...]
```

Aus dieser Liste wird abgeleitet:

```
n_goals_achievable_st = count(status == "erreichbar")
n_goals_tight_st      = count(status == "knapp")
n_goals_unreachable_st = count(status == "nicht_erreichbar")
n_hard_unreachable_st  = count(status == "nicht_erreichbar" AND hardness == "hart")
```

`n_hard_unreachable_st` MUSS 0 sein, falls die Foundation-Goals erfüllt sind —
sonst entweder Daten-Problem oder echter Konflikt, in jedem Fall Stop-Bedingung.

### 3.4 Sekundäre Risikomaße (Diagnose)

- Erwartete annualisierte Volatilität (`expected_volatility_bps`).
- Erwarteter Endwert P50 in 10 Jahren (`expected_terminal_p50_rappen`).
- Solver-Run-Zeit (`elapsed_ms`, Spec-Budget < 8s).
- `optimization_status` (`converged`, `diverged`, `fallback_house_matrix`).

### 3.5 Reasoning-Trace-Vollständigkeit

Stochastic MUSS liefern:
- `limiting_factor` ∈ {`risikoprofil`, `liquiditaetsreserve`, `bandbreite`,
  `zielkonflikt`, `solver_konvergenz`}.
- `binding_constraints` als Liste (kann leer sein).
- `driving_goal_id` (falls ≥ 1 Goal vorhanden, sonst `null`).
- `achievability` für alle Goals (außer `maximize`).

## 4. Acceptance-Schwellen

Pro Mandat wird der Vergleich klassifiziert:

### 🟢 GREEN (Default-Wechsel freigegeben)

ALLE folgende Bedingungen erfüllt:

- `total_drift_bps ≤ 1000` (≤ 10 Prozentpunkte größte Single-Bucket-Drift).
- `risky_drift_bps ≤ 500` (≤ 5 Prozentpunkte Drift in Risiko-Gesamt).
- `budget_compliance_ST == True`.
- `n_hard_unreachable_st == 0` (kein hartes Ziel als unerreichbar markiert,
  außer der Berater bestätigt explizit den Konflikt).
- Stochastic-Run-Zeit ≤ 8s (Performance-Budget).
- `limiting_factor` ist gesetzt und plausibel (Berater-Augenmaß).
- `optimization_status == "converged"`.

### 🟡 YELLOW (Default-Wechsel zurückgestellt, Review nötig)

EINE der folgenden Bedingungen:

- `1000 < total_drift_bps ≤ 2000` (10-20 Prozentpunkte).
- `500 < risky_drift_bps ≤ 1000` (5-10 Prozentpunkte).
- Run-Zeit zwischen 8s und 15s.
- `limiting_factor` unerwartet (Berater erwartet z.B. `bandbreite`,
  bekommt `zielkonflikt`).
- Single-Goal P-Drift unerwartet (z.B. nicht plausibel für die Goal-Struktur).

Bei YELLOW: Owner-Review nötig. Wenn Berater die Drift fachlich erklären kann
und akzeptiert → Reklassifikation auf GREEN möglich; sonst bleibt YELLOW =
blockt Default-Wechsel.

### 🔴 RED (Default-Wechsel hart blockiert)

EINE der folgenden Bedingungen:

- `total_drift_bps > 2000` (> 20 Prozentpunkte — fachlich nicht erklärbar).
- `risky_drift_bps > 1000` (Stochastic deutlich risikoreicher).
- `budget_compliance_ST == False` (Cap-Verstoß — FINMA-Bruch).
- `optimization_status != "converged"` (Solver hat versagt).
- `n_hard_unreachable_st > 0` ohne dokumentierten Berater-Konflikt.

RED = Stochastic-Engine darf nicht Default werden, bevor die Ursache gefunden
und behoben ist (Bug-Report, Spec-Anpassung oder Daten-Korrektur).

### Gesamt-Verdikt

Default-Wechsel ist freigegeben, wenn:
- **Foundation-Case = GREEN** (deterministische Reproduzierbarkeit).
- **≥ 2 von 3 realen Mandaten = GREEN**, 0 = RED.
- Wenn 1 realer YELLOW vorhanden: Owner-Review schriftlich dokumentiert.

## 5. Vorgehen (Berater-Protokoll)

### Schritt 1 — Setup (einmalig)
1. `OptimizerPolicy.optimizer_mode = "shadow_stochastic"` im Admin-UI.
2. Foundation-Case neu erzeugen: Admin → System → Foundation-Beispiel.
3. Drei reale Mandate auswählen und Mandat-IDs notieren.

### Schritt 2 — Vergleich durchführen (pro Mandat)
1. Mandat öffnen → Asset Allokation → „Anlagestrategie berechnen".
2. Engine läuft im `shadow_stochastic`-Modus: House-Matrix-Resultat wird in der
   UI angezeigt, Stochastic-Resultat in `TargetAllocation.shadow_optimization_json`
   persistiert.
3. Admin → System → Shadow-Vergleich (neuer Admin-Endpoint, siehe §6) liefert
   die Vergleichs-Metriken als JSON.

### Schritt 3 — Report ausfüllen
Ein Report-Eintrag pro Mandat ins Compliance-Dossier
(Format §6, ein Eintrag pro Mandat).

### Schritt 4 — Owner-Entscheid
Bei Gesamt-Verdikt GREEN: Codex setzt `OPTIMIZER_MODE`-Default auf
`stochastic` (Stage 5 letzte Codex-Aktion). Bei YELLOW: Owner-Review erst.
Bei RED: Bug-Fix-Sprint einplanen.

## 6. Reporting-Format

Ein Report pro Mandat als Markdown-Eintrag in `docs/compliance/shadow-vergleich-2026-MM-DD.md`:

```markdown
## Mandat: <pseudonym>

| Metrik | House-Matrix | Stochastic | Drift |
|---|---|---|---|
| equities_bps | 6000 | 6300 | +300 |
| bonds_bps | 3000 | 2700 | -300 |
| real_estate_bps | 500 | 500 | 0 |
| alternatives_bps | 0 | 100 | +100 |
| liquidity_bps | 500 | 400 | -100 |
| **total_drift_bps** | — | — | **300** |
| risky_fraction_bps | 6500 | 6800 | +300 |
| max_risky_fraction_bps | 8000 | 8000 | (Limit) |
| budget_compliance | ✓ | ✓ | — |
| expected_volatility_bps | 1100 | 1140 | +40 |
| expected_terminal_p50_rappen | 1'850'000_00 | 1'880'000_00 | +30k |
| elapsed_ms | 50 | 4200 | +4150 |
| optimization_status | n/a | converged | — |
| limiting_factor | n/a | bandbreite | — |

### Goal-Achievability (nur Stochastic)
| Goal | Hardness | P | Status |
|---|---|---|---|
| Pensionsentnahme 2035 | hart | 92% | erreichbar |
| Hauskauf 2032 | primär | 71% | knapp |
| Renditeziel 5% p.a. | primär | 58% | knapp |

### Verdikt: 🟢 GREEN
Drift unter 1000bps, Cap-konform, alle harten Ziele erreichbar.

### Berater-Notiz (optional)
Stochastic verschiebt 3pp von Bonds zu Equities; passt zur höheren
Renditeziel-Erwartung. Acceptable für Default-Wechsel.
```

## 7. Was passiert, wenn der Vergleich RED ist

Stop-Bedingungen + Vorgehen:

| Befund | Mögliche Ursache | Behandlung |
|---|---|---|
| `budget_compliance_ST == False` | Bug im Cap-Constraint | Sofort-Hotfix in `services/risk_matrix.py` / `portfolio_engine.py`, Acceptance §10 #1 erneut testen. |
| `total_drift_bps > 2000` | Unterschiedliche Goal-Interpretation oder Risky-Fraction-Math-Drift | Reasoning-Trace beider Engines vergleichen; ggf. Spec OD-E (priority_weight) refinen. |
| `optimization_status == "diverged"` | Solver-Constraints inkonsistent | `constraint_slacks(...)` debuggen, GA-Fallback prüfen. |
| `n_hard_unreachable_st > 0` | Echter Zielkonflikt ODER falsche Hardness-Klassifikation | Berater-Gespräch: ist das Ziel wirklich nicht erreichbar (Datenproblem) oder ist der Constraint falsch? |
| `elapsed_ms > 15s` | Scenario-Cache-Miss oder zu viele Goals | Performance-Profiling; ggf. N=2000 reduzieren oder Cache prüfen. |

## 8. Verantwortungen

- **Claude (Spec/Methodology):** dieses Dokument hält die Methodologie fest;
  Stage 5 Codex-Prompt verlinkt darauf.
- **Codex (Stage 5):** implementiert `shadow_stochastic`-Mode + Admin-Endpoint
  `GET /admin/system/shadow-comparison/{mandate_id}` der die §3-Metriken
  liefert (oder mindestens die Roh-Daten, damit der Vergleich berechnet werden
  kann).
- **Owner (Berater):** wählt die 3 realen Mandate, führt die Vergleiche aus,
  füllt die Reports, entscheidet GREEN/YELLOW/RED. Der Default-Wechsel
  passiert nur nach Owner-OK.
- **Compliance-Trail:** Reports liegen unter `docs/compliance/` (anonymisiert)
  und sind Teil des FINMA-relevanten Audit-Pfads für die Engine-Umstellung.

## 9. Vorbereitende Annahmen (zur Validierung in Stage 5)

Für die Implementation des `shadow_stochastic`-Modes:

- `TargetAllocation.shadow_optimization_json` als neues additive_column (TEXT,
  nullable). Inhalt:
  ```json
  {
    "engine": "stochastic",
    "allocation_bps": {...},
    "risky_fraction_bps": ...,
    "limiting_factor": "...",
    "achievability": [...],
    "elapsed_ms": ...,
    "optimization_status": "converged"
  }
  ```
- Admin-Endpoint `GET /admin/system/shadow-comparison/{mandate_id}`
  serialisiert die §3-Metriken aus TA + shadow_optimization_json.
- Sichtbare Allocation in der Berater-UI bleibt unverändert (House-Matrix-
  Resultat) — Shadow ist NUR im Admin-Bereich sichtbar.
- Acceptance §10 #7 ("Shadow-Modus verändert sichtbare Allocation nicht")
  wird via Contract-Test geprüft.

## 10. Offene Fragen an Owner

1. **Auswahl der 3 realen Mandate:** soll ich (Claude) Pseudokriterien für
   die Auswahl präzisieren (z.B. „aktiv seit ≥ 6 Monaten, ≥ 2 Goals
   gepflegt"), oder wählt der Berater frei?
2. **Owner-Review-Format bei YELLOW:** soll das ein strukturiertes Markdown-
   Template sein (analog zu §6) oder reicht ein freier Kommentar im Compliance-
   Doc?
3. **Re-Run-Frequenz:** soll der Shadow-Vergleich nach dem Default-Wechsel
   periodisch laufen (z.B. quartalsweise als Regression-Check) oder einmalig?
