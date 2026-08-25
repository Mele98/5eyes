# Property-Based-Testing fuer 5eyes-Backend

Wegweiser fuer Property-Based-Testing mit `hypothesis` — wann es lohnt,
wie es laeuft, wie Counter-Examples interpretiert werden.

**Stand:** 2026-06-05
**Roadmap-Punkt:** #107 (QA, opt-in)
**Komplementaer zu:** [MUTATION_TESTING.md](MUTATION_TESTING.md)
(Roadmap #106) und Backend-Coverage (Roadmap #105)

---

## Was ist Property-Based-Testing?

Klassisches Test-Pattern (example-based):
```python
def test_sortino_with_specific_inputs():
    assert compute_sortino_ratio_x100(700, 1000, 100) == 84
```

Property-Based-Pattern (hypothesis-generated):
```python
@given(
    return_bps=st.integers(min_value=0, max_value=2000),
    vol_bps=st.integers(min_value=1, max_value=3000),
    rf_bps=st.integers(min_value=0, max_value=500),
)
def test_sortino_higher_or_equal_to_sharpe(return_bps, vol_bps, rf_bps):
    sortino = compute_sortino_ratio_x100(return_bps, vol_bps, rf_bps)
    sharpe = int(round(((return_bps - rf_bps) / vol_bps) * 100))
    # Property: bei Gaussian-Annahme ist Sortino >= Sharpe (downside_vol < vol)
    if return_bps >= rf_bps:
        assert sortino >= sharpe
```

hypothesis generiert hunderte Random-Inputs und sucht systematisch
nach Counter-Examples die das Property brechen. **Shrinking**:
findet hypothesis ein Counter-Example, reduziert es auf die minimale
Form damit du den Bug verstehst.

## Wann lohnt es sich?

- **Pure-Math-Funktionen** mit klaren Invarianten
  (Beispiele: services/risk_metrics_kpi.py,
  services/rates/nelson_siegel.py,
  services/rates/ns_calibration_2024.py)
- **State-Machines** mit klaren Pre/Post-Conditions
  (Beispiele: services/recommendation_run_cleanup.py,
  services/override_reason_quality.py)
- **Codec/Roundtrip** (JSON-Serialisierung, ISO-Date-Parsing)

- **NICHT bei** Aggregator-Sektionen mit DB-Abhaengigkeit
  (zu viel Fixture-Aufwand pro Property)
- **NICHT bei** UI-Layer (Sub-App vitest hat eigene Strategie)

## Setup

hypothesis ist als **opt-in** Tool gedacht — NICHT in requirements.txt.
Installation manuell wenn du es brauchst:

```powershell
cd 5eyes-backend
.venv\Scripts\Activate.ps1
pip install hypothesis
```

Property-Tests liegen unter `5eyes-backend/tests/property/`.
Datei-Pattern: `test_*_properties.py`.

**Wichtig:** Property-Tests pruefen mit `try: import hypothesis except
ImportError: pytest.skip(...)` — wenn hypothesis NICHT installiert ist,
wird der Test als skipped markiert (kein Collection-Error). So bleibt
die normale CI gruen ohne hypothesis-Dep.

## Lauf

```powershell
cd 5eyes-backend

# Alle Property-Tests
pytest tests/property/

# Mehr Examples (statt Default 100)
pytest tests/property/ --hypothesis-seed=42 -p hypothesis

# Statistik anzeigen
pytest tests/property/ --hypothesis-show-statistics
```

## Beispiel im Repo

`5eyes-backend/tests/property/test_risk_metrics_kpi_properties.py`
enthaelt 4 Properties fuer Sortino/Calmar/Information-Ratio:

1. **Sortino-vs-Sharpe**: bei positive Excess-Return ist Sortino >= Sharpe
2. **Calmar-Sign**: Calmar > 0 wenn Return > 0 und Drawdown > 0
3. **IR-Symmetry**: Tausch von Portfolio und Benchmark negiert die IR
4. **Helper-Consistency**: Konsolidierter Helper liefert dieselben
   Werte wie die Einzel-Funktionen

## Counter-Example interpretieren

hypothesis schreibt Counter-Examples in `.hypothesis/examples/`
(im .gitignore). Wenn ein Test failt:

```
Falsifying example: test_sortino_higher_or_equal_to_sharpe(
    return_bps=0, vol_bps=1, rf_bps=0,
)
```

Bedeutung: bei return=0, vol=1, rf=0 bricht das Property. Du hast nun:
1. **Echte Bug-Fundstelle** → Code fixen
2. **Property zu streng** → Property erweitern um Edge-Case (z.B. Sortino=Sharpe=0 erlauben)
3. **Property falsch formuliert** → Annahme dokumentieren

## Empfohlene Module fuer Erst-Audit

Pure-Math + klare Invarianten:

| Modul | Sprint | Vorgeschlagene Properties |
|-------|--------|---------------------------|
| `services/risk_metrics_kpi.py` | U-96 | Sortino>=Sharpe, Calmar-Sign, IR-Symmetry |
| `services/rates/nelson_siegel.py` | Pre-U-100 | yield_at-Monotonie, short_rate==yield_at(0+), Forward-Rate Konsistenz |
| `services/rates/ns_calibration_2024.py` | U-100 | Roundtrip (calibrate->apply->reconstruct), Fit-Qualitaet, Bound-Check |
| `services/override_reason_quality.py` | U-28+U-29 | Length-Property: >=20 Zeichen pass, <20 fail; Word-Count-Property |
| `services/recommendation_run_cleanup.py` | U-104 | Retention-Property: Runs aelter cutoff sind alle weg, juenger sind alle da |
| `services/liquidity_cascade_audit.py` | U-21 | Stage-Klassifikation: bps<hard_cap -> normal, bps>=emergency -> emergency |

## CI-Integration (Folge-Sprint)

Heute laufen Property-Tests **NICHT** in CI weil hypothesis als opt-in
nicht in requirements.txt steht.

Geplanter Folge-Sprint:
- Optional Job in test.yml mit `pip install hypothesis` als
  separater Step + `pytest tests/property/`
- Failed Properties als Issue automatisch erzeugen

## Bewusst NICHT in Scope

- hypothesis wird **nicht** zur requirements.txt hinzugefuegt
  (User-Konvention: keine neuen Dependencies ohne Auth)
- Property-Tests werden **nicht** zur Coverage-Gate hinzugefuegt
  (Mega-Audit 2026-08-04: es gibt bewusst KEINEN Coverage-Floor, siehe
  pyproject.toml -- `--cov-fail-under` wird erst nach Baseline-Messung
  gesetzt; Property-Test-Ergebnisse fliessen also in gar keine harte
  Schwelle ein)
- Stateful-Testing (hypothesis.stateful) wird heute nicht
  konfiguriert (komplexer Setup-Aufwand, Folge-Sprint)

## Weiterfuehrendes

- [hypothesis docs](https://hypothesis.readthedocs.io)
- [MUTATION_TESTING.md](MUTATION_TESTING.md) — Roadmap #106,
  komplementaere QA-Strategie
- Roadmap-Punkt #105 (Backend-Coverage Hotspots auf 0%) —
  Voraussetzung fuer sinnvolle Property-Tests
