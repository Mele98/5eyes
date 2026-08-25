# Audit: Cashflow-Integration in den Monte-Carlo-Pfad

**Datum:** 2026-06-07
**Sprint:** A3 (Engine-Hardening Phase A)
**Auditor:** Claude (CTO-Modus)
**Scope:** Verifikation dass Cashflows korrekt in den stochastischen Wealth-Pfad einfließen.
**Trigger:** CTO-Engine-Audit 2026-06-06 markierte P6 "Cashflow-in-MC unverifiziert" als kritische Lücke.

---

## Executive Summary

**CF-Integration in `simulate_wealth_paths` ist STRUKTURELL KORREKT.**

Befund: Drei latente Limitierungen, eine echte Lücke.

| ID | Befund | Schwere | Status |
|----|--------|---------|--------|
| F1 | CFs sind 1D (pro Jahr), NICHT pro-Pfad | OK (by design) | Verifiziert |
| F2 | CF wird POST-Growth + POST-Tax addiert | OK (CH-konform) | Verifiziert |
| F3 | Inflation wird PRE-MC angewendet (cashflow_timeline.py) | OK (sauber separiert) | Verifiziert |
| F4 | Mortalitäts-Maske zeroisiert CF nach Todesjahr | OK | Verifiziert |
| F5 | `cashflow_timeline.py:totals_for_year` IGNORIERT das `currency`-Feld | **MAJOR** | **OPEN (B3)** |
| F6 | Zwei Engine-Pfade (`scenario_engine` + `portfolio_engine`) — beide haben CF, leicht verschiedene Mechanik | MINOR | Dokumentiert |
| F7 | Negativer Wealth (Lebensluecke) blockt Tax+Growth korrekt (W2.5) | OK | Verifiziert |

**Empfehlung:** F5 ist der einzige echte Bug. Wird in **B3 Multi-Currency-Sprint** behandelt. Keine sofortigen Code-Changes in A3 nötig — Drift-Tests pinnen das aktuelle korrekte Verhalten ab.

---

## 1. Methodik

**Code-Audit:** Manuelle Lesung der relevanten Funktionen mit File:Line-Verweis.

**Code-Pfade:**
- `services/optimizer/scenario_engine.py:simulate_wealth_paths` (Zeile 268-436) — Hauptpfad des stochastischen Optimizers
- `services/cashflow_timeline.py:net_cashflow_series` (Zeile 246-262) — CF-Generation aus Mandate-Daten
- `services/cashflow_timeline.py:totals_for_year` (Zeile 187-243) — Pro-Jahr-Aggregation mit Inflation
- `services/cashflow_timeline.py:_compound_inflation_factor` (Zeile 159-184) — Inflation-Compounding
- `services/portfolio_engine.py:_simulate_bucket_path` (Zeile 2050-2125) — Alternative deterministische Engine

**Methodische Annahme:** "CF korrekt" bedeutet:
1. CF wird im richtigen Jahr addiert (kein Off-by-One)
2. CF wird zu jedem Pfad gleich addiert (deterministisch pro Jahr)
3. Vorzeichen: Income positiv, Expense negativ
4. Inflation wird im richtigen Ort applied (pre-MC)
5. Mortality-Maske greift ab Todesjahr

---

## 2. Detail-Befunde

### F1 — CFs sind 1D pro Jahr, NICHT pro-Pfad

**Code:** `scenario_engine.py:286`

```python
cashflow_series_rappen: shape (horizon,) - Netto-Cashflow pro Jahr
```

**Mechanik:**
```python
wealth[:, t+1] = grown + cashflow[t] - liability[t]
```

Der `cashflow[t]`-Wert wird via NumPy-Broadcasting an ALLE n_paths gleich addiert.

**Bewertung:** Korrekt **by design**. Der Cashflow ist deterministisch im Mandate (Lohn, Pension, geplante Ausgaben), nicht stochastisch wie Asset-Returns. Wenn der Berater eine stochastische Einnahme modellieren will (z.B. unsichere Bonuszahlung), löst er das per `Goal.probability_pct` (bedingtes Goal), NICHT durch CF-Variation.

**Alternative die NICHT umgesetzt ist:** Stochastische CFs pro Pfad — wäre fundamental anderer Architektur-Ansatz (Mulvey-Style Multi-Stage SP). Nicht im Scope für 5eyes Stage 9.

### F2 — CF wird POST-Growth + POST-Tax addiert

**Reihenfolge in der Loop pro Jahr** (`scenario_engine.py:384-434`):

1. `portfolio_factor = Σ_b w_b · R_{p,t,b}` — gewichteter Return-Faktor pro Pfad
2. `grown = prev × portfolio_factor` (falls prev > 0, sonst grown=prev)
3. (Optional Tax-Drag): Dividende + Vermögenssteuer auf `grown`
4. `wealth[:, t+1] = grown + cashflow[t] - liability[t]`

**Bewertung:** Korrekt für CH-Mandat:
- Vermögenssteuer-Bemessungsbasis ist Wealth-after-Growth (= CH-Praxis Stichtag 31.12.)
- Dividenden-Steuer skaliert mit Yield-Komponente vom Wachstum
- CF kommt am Jahresende rein/raus (Lohn-Income, Pension-Expense)

**Alternative:** CF zur Jahresmitte applied (zinsen halb-jährlich). Wäre genauer aber komplexer. 5eyes-Scope: ganzjährlich.

### F3 — Inflation wird PRE-MC angewendet

**Code-Pfad:**
1. Berater erfasst CF mit `amount_rappen`, `is_inflation_linked` (0/1)
2. `totals_for_year` (cashflow_timeline.py:202-215):
   ```python
   is_linked = bool(getattr(cf, "is_inflation_linked", 0))
   cf_factor = inflation_factor_universal if is_linked else 1.0
   ```
3. Inflation-Faktor aus `_compound_inflation_factor(inflation_series_bps, start_year, target_year)`
4. `net_cashflow_series` liefert die Liste mit bereits inflationierten Beträgen
5. MC-Loop sieht diese als nominale CFs

**Bewertung:** Korrekt — Inflation ist **deterministisch im Mandate**, nicht stochastisch. Die Pre-MC-Anwendung ist saubere Separation-of-Concerns.

**Edge-Case:** Wenn `inflation_series_bps` zu kurz ist (z.B. nur 10 Jahre statt 27), wird der letzte Wert konstant fortgeschrieben (`cashflow_timeline.py:179-180`). Akzeptabel als Fallback.

### F4 — Mortalitäts-Maske

**Code:** `scenario_engine.py:351-365`

```python
if death_year_index_per_path is not None:
    t_range = np.arange(horizon, dtype=np.int32)
    alive_mask = t_range[None, :] < death_idx[:, None]
    cashflow_per_path = cashflow[None, :] * alive_mask
    liability_per_path = liability[None, :] * alive_mask
```

Pro Pfad p:
- Lebt in Jahren t=0..d_p-1 → CF + L aktiv
- Stirbt in Jahr d_p → ab dort CF=0 und L=0

**Bewertung:** Korrekt. Wealth läuft nominal weiter (Erbschaft-Verhalten, kein Schuldzins auf negative Werte W2.5).

**Edge-Case:** `death_idx[p] = 0` → kein einziges Jahr Cashflow. Pfad hat nur initial_wealth + Wachstum.

### F5 — Multi-Currency-Lücke (MAJOR)

**Code:** `services/cashflow_timeline.py:187-243` (`totals_for_year`)

```python
# Pseudocode:
for cf in cashflows:
    is_linked = bool(getattr(cf, "is_inflation_linked", 0))
    cf_factor = inflation_factor_universal if is_linked else 1.0
    amount = contribution_for_year(amount_rappen=int(getattr(cf, "amount_rappen", 0) or 0), ...)
    # currency wird NIRGENDS gelesen
```

**Befund:** `cf.currency` wird nicht in den Calc einbezogen. Das `models/wealth.py:Cashflow.currency`-Feld existiert (default "CHF") aber wird ignoriert.

**Konsequenz:**
- Berater erfasst USD-Income 100k/J → Backend speichert `amount_rappen=10_000_000` als "100 Mio Rappen" (= CHF 100k, falsch interpretiert)
- MC rechnet mit CHF 100k Income
- Bei aktuellem FX-Kurs ~0.90 USD/CHF wären 100k USD ≈ 90k CHF — Engine überschätzt Income um ~10%

**Schwere:** MAJOR für internationale Mandate (Expat, multi-currency portfolios).

**Status:** OPEN. Wird in **Sprint B3 (P4 Multi-Currency-Cashflow-Conversion)** behandelt.

### F6 — Zwei Engine-Pfade

**Code:** Es existieren zwei Wealth-Simulationen:
- `services/optimizer/scenario_engine.py:simulate_wealth_paths` — vollstochastisch mit MC, Cornish-Fisher, IS, Tax
- `services/portfolio_engine.py:_simulate_bucket_path` — deterministisch mit Itô-Korrektur, Bucket-Rebalancing-Mechanismus

**Bewertung:** Beide korrekt für ihren Use-Case:
- `scenario_engine` → Solver-Optimierung mit Tail-Risiko
- `portfolio_engine` → Reporting/Projection mit Asset-Class-Aufschlüsselung + Rebalancing-Events

**Konsistenz:** Beide nutzen identische Korrelationsmatrix (Sprint U-P0 Fix C7: Single-Source-of-Truth `_DEFAULT_CORRELATION_MATRIX`).

**Drift-Risiko:** Wenn nur einer der Engines geupdated wird (z.B. neue CMA-Param), kann es zur Inkonsistenz kommen.

**Mitigation:** Drift-Tests (test_engine_reference_mandates.py) pinnen das stochastische Verhalten; Drift-Tests am `portfolio_engine` (separater Test-Korpus) pinnen das deterministische.

### F7 — Lebensluecke-Verhalten (W2.5)

**Code:** `scenario_engine.py:388-389`

```python
grown = np.where(prev > 0, prev * portfolio_factor, prev)
```

Wenn `prev < 0` (Lebenslücke):
- KEIN Wachstum (würde negative Wealth noch weiter ins Minus tragen via z.B. -100 × 1.05 = -105 — Schuldzins-Effekt unrealistisch)
- KEINE Steuer-Anwendung
- CF wird normal addiert → Wealth steigt wenn CF positiv ist (Income > Expense in der Lücke)

**Bewertung:** Mathematisch konsistent. Realistische Modellierung der Lebenslücke ohne Kredit-Mechanismus. Konsistent mit W2.5-Sprint.

---

## 3. Cross-Check gegen Reference-Mandate

Die 5 Reference-Mandate aus A2 testen indirekt die CF-Integration:

| Mandate | CF-Aspekt verifiziert |
|---------|----------------------|
| M1 Pensionär | Negative CF (-80k/J Entnahme) reduziert Wealth korrekt |
| M2 Wachstum | Positive CF (+10k/J Sparen) erhöht Wealth über 30J |
| M3 HNW | Positive CF mit langem Horizont (200k/J × 25J) — Tax-Drag sichtbar |
| M4 Override | CF unchanged egal welcher Score — Engine separiert sauber |
| M5 AHV+BVG | Positive CF + Hart-Goal in Decumulation — Wealth bleibt positiv |

Alle 5 Tests passing (A2 PR #216 merged) — verifiziert dass CF-Integration in den geprüften Szenarien korrekt arbeitet.

---

## 4. Empfehlungen

### Sofortig (in A3 abgedeckt)

1. **Audit-Doku committen** (dieses Dokument)
2. **Drift-Tests schreiben** (`tests/test_cashflow_in_mc_integration.py`) die das aktuelle korrekte Verhalten pinnen — Schutz gegen Regression

### Deferred (B3 Sprint)

3. **F5 Multi-Currency-Fix** in `cashflow_timeline.py` — CF in Lokalwährung × FX-Kurs zu CHF konvertieren

### Out-of-Scope

4. Stochastische CFs (Mulvey-Style Multi-Stage SP) — Architektur-Refactor, nicht in Stage 9
5. Half-yearly CF-Application (statt Year-End) — minor accuracy improvement, nicht business-critical

---

## 5. Referenzen

- `services/optimizer/scenario_engine.py:268` — `simulate_wealth_paths`
- `services/cashflow_timeline.py:187` — `totals_for_year`
- `services/cashflow_timeline.py:246` — `net_cashflow_series`
- `services/cashflow_timeline.py:159` — `_compound_inflation_factor`
- `models/wealth.py:Cashflow.currency` — ignorierte Field
- `docs/engine-spec.md` — Section 3 (Wealth-Simulation)
- `tests/test_engine_reference_mandates.py` — Indirekte CF-Verifikation (M1-M5)

---

**Signiert:** Claude (CTO-Audit), 2026-06-07
**Review-Pflicht:** Codex bei nächstem Audit-Cycle
