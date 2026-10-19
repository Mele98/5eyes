---
finding: RESERVE-FUNDING-LEDGER-001
follows: RESERVE-DOUBLE-COUNT-001 (PR #638)
review_basis: docs/audits/2026-10-18-liquidity-reserve-double-count-pr638-current-review.md (Codex, Branch codex/asset-allocation-stochastic-core)
status: implemented
---

# Reserve-Funding-Ledger (Folgefix zu PR #638)

## 1. Ausgangslage

PR #638 hat den Doppelverbrauch der externen Reserve `E` im Generate-Solver
behoben: Start `I = A - E`, und `E` fliesst als Bargeld in den Jahren mit
Abfluessen zurueck. Codex' adversarialer Review hat drei offene Vertraege
reproduziert (3 strict-xfail):

1. **Herkunft:** Das Release kannte nur das aggregierte `E` und hat einen
   reinen `minReserve`-/Policy-Floor in ein sachfremdes spaetes Ziel
   umetikettiert (Floor CHF 50k, Ziel in Jahr 8 -> Release CHF 50k statt 0).
2. **Sensitivity:** zog `E` vom Startvermoegen ab, gab es nie zurueck und
   bemass `E` fuer den Gegenlauf nicht neu.
3. **Reporting-MC:** verglich IST auf `A` mit SOLL auf `A - E` -- eine
   kuenstliche Differenz `E` selbst bei Nullrendite und 100 % Liquiditaet.

## 2. Umsetzung

### 2.1 `ReserveFundingLedgerV1` (`services/reserve_funding_ledger.py`)

Felder: `tranches` (Quelle `goal` / `cashflow_deficit` / `policy_floor`,
Quell-ID, Bedarf, extern gehaltener Betrag, Freigabefenster, `releasable`,
Goal-Rang, Hardness), `releases` (Jahr, Tranche, Ziel, Betrag),
`release_series_rappen`, `unspent_floor_rappen`, `unreleased_need_rappen`,
`total_external_rappen`, `total_internal_rappen`, `version`,
`policy_version`, `contract_hash` (SHA-256 ueber alles andere;
`ledger_contract_hash()` rechnet nach -> Manipulation/Policywechsel erkennbar).

### 2.2 Zerlegungsregel (`need_first_pro_rata_source_bound_v1`)

* Der Bedarf kommt aus **derselben** Herleitung wie die Reservehoehe:
  `_compute_reserve_for_inputs(need_breakdown=...)` legt Ziel-Beitraege und
  Cashflow-Fehlbetrag offen. Keine zweite Formel.
* `R = max(Floor, Bedarf)` -- Floor und Bedarf ueberlappen. Der ueber den
  Bedarf hinausgehende Teil ist ein dauerhafter Mindestbestand.
* `E` deckt **zuerst den Bedarf**, der Rest ist Floor (`releasable=false`).
  Begruendung: Die Reservehoehe selbst modelliert Floor und Bedarf als
  ueberlappend (`max`). Nach Zahlung aller Bedarfe muss also genau
  `R - Bedarf` uebrig bleiben. Need-first erfuellt das exakt; Floor-first
  wuerde einen Teil des Bedarfs aus dem Portfolio bezahlen lassen und
  gleichzeitig mehr Bargeld als `R - Bedarf` dauerhaft blockieren.
  Beispiel: Floor 80k, Bedarf 60k, intern 10k -> `R = 80k`, `E = 70k`
  = 60k Bedarf (freigebbar) + 10k Floor-Rest (nie). Nach den Zielen bleiben
  10k extern + 10k intern = 20k = `R - Bedarf`. Floor-first haette nur 50k
  freigegeben, 10k des Ziels aus dem Portfolio bezahlt und 30k blockiert.
* Reicht `E` nicht fuer den ganzen Bedarf: anteilig nach Bedarf, groesster
  Rest, Tiebreak Tranche-ID -> eingabereihenfolgeunabhaengig (getestet ueber
  alle Permutationen, identischer Hash).
* Release je Tranche nur in die Abfluesse **ihrer eigenen Quelle**:
  Ziel-Tranche -> Liability-Pfad genau dieses Ziels (aus demselben
  `goals_to_liabilities` wie der Solver); Cashflow-Tranche -> negative
  Cashflows im 3-Jahres-Bemessungsfenster, nie in ein Ziel. Chronologisch,
  je Jahr hoechstens der Abfluss, ohne Rendite. Das Primitiv dafuer ist der
  bestehende `_external_reserve_release_series` aus PR #638 -- nur noch je
  Tranche aufgerufen, nie mit aggregiertem `E`.
* Bedingte Ziele: Reservebeitrag ist bereits `target * p`; die Tranche kann
  nie mehr als diesen Betrag freigeben. Ziele ausserhalb des Horizonts:
  Tranche bleibt `unreleased_need` (sichtbar, nicht umetikettiert).

### 2.3 Ein Compiler, alle Konsumenten

`compile_reserve_funding_ledger_for_inputs()` ist der eine Compiler.

| Konsument | Anschluss |
|---|---|
| Generate-Solver | `_run_stochastic_optimizer_pass(reserve_ledger=...)` -> `raw + release`; Horizont muss gleich sein (sonst `ValueError`). Shadow-Vergleich, Explainability und House-Fallback teilen das daraus gebaute `optimizer_context` (unveraendert). |
| Sensitivity Baseline + Gegenlauf | `compile_goal_set_funding()` je Goal-Set: eigenes `R`, `E`, `A - E`, Steuer-Rebasing auf diesen Startwert, eigener Ledger. Ledger-Hash geht in `model_input_hash` (Version `sensitivity_live_context_v4_reserve_ledger`); beide Ledger werden publiziert. |
| Deterministische Simulation, Reporting-MC | `reserve_release_series_rappen=ledger.release_series_rappen`. SOLL = Strategiepfad auf `A - E` + **Reservekonto** (Bargeld, startet bei `A - E`-Differenz zum IST-Start, sinkt nur durch Release). IST und SOLL erklaeren dieselbe Basis. Marker `reserve_accounting_basis`, Serie `external_reserve_balance_series_rappen`. |
| Goal-Analyse | `reserve_ledger=`: Projektion auf `A - E` mit `Cashflows + Release` plus nicht freigegebener Rest; `external_wealth` zaehlt `E` nicht mehr doppelt. |
| Reload | kompiliert denselben Ledger aus den Live-Inputs (gleiche Funktion, gleiche Optimizer-Cashflow-Serie). |
| Publikation | `reserve_funding_ledger` im Allocation-Payload/Schema; Sensitivity `baseline_/modified_reserve_funding_ledger`. |
| Frontend/PDF | Haben bisher `external_reserve_rappen` als konstanten "Sockel" auf die SOLL-Kurve addiert -- mit Reservekonto im SOLL waere das doppelt. Neu: Aufschlag nur noch fuer Legacy-Payloads ohne `reserve_accounting_basis` (`aaReserveSockelRappen`, PDF analog). |

Fachliche Folge fuer die Anzeige: Der alte konstante Sockel zeigte die
Reserve als "geschuetzten Boden", obwohl sie fuer Nahziele ausgegeben wird --
genau die Doppelzaehlung in der Grafik. Jetzt sinkt das Reservekonto mit den
Releases; nur der echte Floor-Rest bleibt stehen.

## 3. Bewusst NICHT umgesetzt (Ueberbau oder eigener Schritt)

* **Persistenz des Ledgers auf der TargetAllocation + fail-closed Replay**
  (Codex Schritt 5). Braeuchte eine Migration und wuerde jede bestehende
  Allokation stale machen. Heute: Reload kompiliert mit derselben Funktion
  aus denselben Inputs, die bereits per `input_snapshot_hash` gebunden sind;
  der Ledger traegt `policy_version` + `contract_hash`. Offen bleibt, eine
  kuenftige Policyaenderung am gespeicherten Entscheid zu erkennen ->
  Folgeticket (Hash in den Projection-Context aufnehmen, mit
  Migrationsstrategie fuer Altbestaende).
* **Tranche `external_asset`** (Goal-Funding-Schloss auf anderem Vermoegen):
  reduziert `E` bereits vor dem Ledger; kein eigener Release noetig.
* **Sensitivity-Liquiditaetsuntergrenze je Goal-Set:** Die Bandbreiten
  (inkl. Reserve-Floor auf der SAA-Liquiditaet) bleiben die der Baseline
  (gemeinsamer Constraint-Vertrag wie CMA/Szenarien). Nur Finanzierung
  (`E`, `A - E`, Release, Steuer-Rebasing) wird je Goal-Set neu kompiliert.

## 4. Abweichungen vom Codex-Reproducer

* Vertrag 1 rief das Primitiv mit aggregiertem `E` auf. Ohne Herkunft ist
  der Vertrag unerfuellbar (genau der Befund) -- er wird am Ledger geprueft;
  ein zweiter Test dokumentiert, dass das Primitiv quellenblind bleibt und
  deshalb nur je Tranche verwendet wird.
* Vertrag 2 erwartete als Sollwert die greedy Aggregat-Release -- die in
  Vertrag 1 widerlegte Regel. Geprueft wird die Geldidentitaet
  `Start + Release + Floor-Rest + nicht freigegebener Bedarf = A` und
  `Solver-Cashflows = roh + Release` fuer beide Laeufe gegen deren
  publizierten Ledger; zusaetzlich: Delta 0 -> identischer Ledger-Hash,
  Delta +20 % -> eigener, groesserer Ledger.
* Vertrag 3 unveraendert (plus Release-Variante fuer MC und Simulation).

## 5. Tests

`tests/test_reserve_funding_ledger.py` (neu), Erweiterungen in
`tests/test_reserve_double_count_solver.py` (Generate publiziert den Ledger,
den der Solver konsumiert hat; IST/SOLL starten bei `A`) und
`tests/test_aa_view_numbers_and_labels.py` (kein zweiter Sockel bei
`reserve_accounting_basis`).
