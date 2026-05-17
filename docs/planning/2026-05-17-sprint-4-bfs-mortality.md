# Sprint 4 — BFS-Sterbetafel & Mortalitaetsadjustierte Cashflows

**Datum:** 2026-05-17
**Status:** Spec / aktiv
**Vorgaenger:** Standortanalyse §A.3 — letzter P0-Compliance-Gap zu 3eyes.

## 0. Problem

Aktuell wird das **Lebensende** als fixer Wert modelliert:
`mandate.life_expectancy_year = 2068` → Simulation laeuft hart bis 2068.

Probleme:
- Berater raet eine Zahl, ohne empirische Basis
- Keine Unsicherheit ueber Lebensdauer (Langlebigkeitsrisiko!)
- Cashflow-Pfade alle gleich lang → P10/P50/P90 spiegeln nur Markt-, nicht
  Lebens-Unsicherheit
- 3eyes nutzt BFS-Sterbetafel → empirische Wahrscheinlichkeitsverteilung

**Allocation-Wirkung (wichtig fuer 5eyes-Scope):**
- Wer mit 95% Wahrscheinlichkeit 92 wird, braucht mehr Liquiditaet im
  Decumulation-Pfad als wer "im Schnitt 84" wird
- Risikoprofil und Pension-Pfad muessen langlebigkeitsrobust sein
- Direktes Asset-Allocation-Argument (mehr Bonds-Reserve fuer Langlebigkeit)

## 1. Loesung

**Stufenweise — kein Big-Bang:**

### Phase 1 (Foundation — diese Session, ~2h)
- `services/mortality/base.py`: MortalityTable-Interface
- `services/mortality/bfs.py`: BFSMortalityTable mit hardcoded Sterbe-
  wahrscheinlichkeiten q(x) pro Alter + Geschlecht
  - Quelle: Bundesamt fuer Statistik (BFS), Sterbetafel 2022/24, Periode
  - Datenpunkte: q(x) fuer x=0..119, m + w (240 Werte)
- `services/mortality/sampler.py`: sample_age_at_death(n_paths, current_age, sex)
  - Inverse-CDF-Sampling: U ~ Uniform(0,1), find x s.t. F(x) = U
  - Vektorisiert (numpy)
- Tests: BFS-Werte plausibel, Sampler-Distribution korrekt, Edge-Cases

### Phase 2 (Engine-Integration — diese Session, ~1.5h)
- `scenario_engine.simulate_wealth_paths()` bekommt optional:
  - `mortality_age_at_death_per_path: ndarray | None` (shape n_paths)
  - Wenn gesetzt: pro Pfad cashflow nach Tod = 0
- `optimize.build_scenario_paths()` ruft Sampler auf
- Backwards-Compat: keine Mortalitaet → keine Verhaltensaenderung
- Tests: Pfad nach Tod = 0, P10/P50/P90 Lebensdauer plausibel

### Phase 3 (Mandate-Integration — Codex oder naechste Session, ~1h)
- `Mandate.use_mortality_simulation` (Boolean, default False)
- `Mandate.client_birth_year` und `client_sex` (M/F)
- `portfolio_engine` resolved → Sampler aktiviert
- UI-Checkbox im Mandate-Formular
- Disclaimer "Schaetzwerte BFS-Daten, individuelle Faktoren nicht modelliert"

## 2. Datenquelle

**BFS Sterbetafel 2020/22 (Periode)** — letzte verfuegbare Vollerhebung:
- https://www.bfs.admin.ch/bfs/de/home/statistiken/bevoelkerung/geburten-todesfaelle/lebenserwartung.html
- File: je-d-01.04.02.02.xlsx (Sterbetafel 2020-2022)
- Spalten: Alter, q(x) Maenner, q(x) Frauen
- 0-99 Jahre + Schluss-Tafel >100 (Gompertz-Extrapolation)

**Wir hartcoden q(x)-Werte als Python-Tupel** — keine externe Datei-
Abhaengigkeit. Update alle 2-3 Jahre wenn neue Tafel raus.

## 3. Backwards-Compat

- `mandate.life_expectancy_year` bleibt als Fallback (Berater-Wunsch
  ueberschreibt Statistik)
- `use_mortality_simulation=False` (Default) → kein Verhalten geaendert
- Bestehende Tests laufen unveraendert

## 4. Erfolgskriterien

| Kriterium | Messbar |
|---|---|
| BFS-Daten korrekt | Mittlere Lebenserwartung Mann 65 = ca. 84.5, Frau 65 = ca. 87 |
| Sampler statistisch korrekt | 10k Samples → Mittel ±0.2 Jahre vom Soll |
| Engine-Integration | Wealth-Pfad nach Tod konstant (cashflow=0) |
| Backwards-Compat | Bestehende 1342 Tests gruen |
| Allocation-Wirkung | Test: P90-Lebensdauer → tieferer Equity-Anteil nach Decumulation-Start |

## 5. Out-of-Scope

- Selbst-Selektions-Effekt (Reiche leben laenger — wuerde DBM brauchen)
- Geschlecht-fluide-Identitaeten (M/F binaer fuer BFS-Konsistenz)
- Multi-Person-Mandate (Ehepaare als Joint-Survival — Phase 5+)
- Krankheits-/Lifestyle-Adjustments (Risiko-Faktoren)
- Periodensterbetafel vs Generationensterbetafel
  (wir nutzen Period — konservativ, kein Mortalitaets-Trend)
