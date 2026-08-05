# Mutation-Testing fuer 5eyes-Backend

Wegweiser fuer Mutation-Testing mit `mutmut` — wann es lohnt, wie es
laeuft, wie Surviving Mutanten interpretiert werden.

**Stand:** 2026-06-05
**Roadmap-Punkt:** #106 (QA, opt-in)
**Konfig:** `5eyes-backend/mutmut.cfg`

---

## Was ist Mutation-Testing?

Mutation-Testing aendert (mutiert) deinen Code an einer Stelle und
prueft ob deine Tests den Defekt entdecken. **Survives** ein Mutant
alle Tests, hast du eine Test-Luecke an dieser Stelle (NICHT
zwangslaeufig einen Bug).

Beispiel:
```python
# Original
if score > 0:
    return "positiv"

# Mutation A: > zu >=
if score >= 0:
    return "positiv"

# Mutation B: > zu <
if score < 0:
    return "positiv"
```

Wenn alle Tests gruen bleiben obwohl der Code mutiert wurde -> Tests
treffen die Verzweigung nicht hart genug.

## Wann lohnt es sich?

- **Bei wert-starken Modulen** mit hoher Coverage aber unklarer
  Branch-Tiefe (Beispiele: services/risk_metrics_kpi.py,
  services/recommendation_run_cleanup.py,
  services/override_reason_quality.py)
- **NICHT bei Modellen** (models/) — Mutationen brechen
  hauptsaechlich Imports
- **NICHT bei Main/Bootstrap** (main.py) — testet App-Wiring nicht
  Logik

## Setup

Mutmut ist als **opt-in** Tool gedacht — NICHT in requirements.txt.
Installation manuell wenn du es brauchst:

```powershell
cd 5eyes-backend
.venv\Scripts\Activate.ps1
pip install mutmut
```

Konfig liegt unter `5eyes-backend/mutmut.cfg`. Default-Pfade:
- `paths_to_mutate=services/,routers/`
- `tests_dir=tests/`
- `runner=python -m pytest -x -q`

## Lauf

```powershell
cd 5eyes-backend

# Vollstaendiger Lauf — KANN STUNDEN DAUERN!
mutmut run

# Auf einem Modul — empfohlen fuer Erst-Audit
mutmut run --paths-to-mutate=services/risk_metrics_kpi.py
mutmut run --paths-to-mutate=services/recommendation_run_cleanup.py
mutmut run --paths-to-mutate=services/override_reason_quality.py
```

## Ergebnisse lesen

```powershell
# Uebersicht
mutmut results

# Survivor anschauen
mutmut show <id>
```

**Output-Interpretation:**

| Status | Bedeutung |
|--------|-----------|
| `killed` | Tests fangen die Mutation — gut |
| `survived` | Test-Luecke: kein Test scheitert -> Test ergaenzen |
| `timeout` | Mutation fuehrt zu Endlos-Loop -> Test-Fix oder Code-Audit |
| `suspicious` | Test-Suite verhaelt sich sprunghaft -> Re-Run mit `--rerun` |

## Was tun bei Survivors?

1. **Mutmut Show** schauen welche Aenderung der Survivor war
2. Pruefen: ist die Mutation **aequivalent** (kein
   Verhaltensunterschied) oder **echte Test-Luecke**?
3. Bei Aequivalenz: in Skip-Liste aufnehmen (`# pragma: no mutate`)
4. Bei Test-Luecke: gezielten Test schreiben, dann erneut laufen

## Empfohlene Module fuer Erst-Audit

Hohe Coverage + klare Branch-Tiefe + relevant fuer Compliance:

| Modul | Sprint | Bemerkung |
|-------|--------|-----------|
| `services/risk_metrics_kpi.py` | U-96 | Sortino/Calmar/Information-Ratio, 21 Tests |
| `services/recommendation_run_cleanup.py` | U-104 | Cleanup-Logik mit Edge-Cases |
| `services/override_reason_quality.py` | U-28+U-29 | Phrase-Blacklist Phrase-Detection |
| `services/liquidity_cascade_audit.py` | U-21 | Stage-Klassifikation |
| `services/mandate_lock_audit.py` | U-22 | Lock-Reason-Codes |
| `services/rates/ns_calibration_2024.py` | U-100 | Calibrate + Apply + Roundtrip |
| `services/rates/nelson_siegel.py` | Pre-U-100 | NS-Formel + Forward-Rate |

## CI-Integration (Folge-Sprint)

Heute laeuft mutmut **NICHT** in CI (Laufzeit ~Stunden, nicht
sinnvoll pro PR).

Geplanter Folge-Sprint: nightly-Cron-Job in GitHub Actions der
mutmut auf einem rotierenden Modul-Subset laeuft + Survivor-Report
ins Issue-Tracker schreibt.

## Bewusst NICHT in Scope

- mutmut wird **nicht** zur requirements.txt hinzugefuegt
  (User-Konvention: keine neue Dependency ohne Auth)
- mutmut wird **nicht** zur Coverage-Gate hinzugefuegt
  (Mega-Audit 2026-08-04: es gibt bewusst KEINEN Coverage-Floor, siehe
  pyproject.toml -- `--cov-fail-under` wird erst nach Baseline-Messung
  gesetzt; mutmut-Ergebnisse fliessen also in gar keine harte Schwelle ein)
- Equivalence-Mutant-Detection automatisiert wird nicht versucht
  (manual review per Modul)

## Weiterfuehrendes

- [mutmut docs](https://github.com/boxed/mutmut)
- Roadmap-Punkt #107 (hypothesis property-based-tests) — komplementaere
  QA-Strategie
- Roadmap-Punkt #105 (Backend-Coverage Hotspots auf 0%) —
  Voraussetzung fuer sinnvolle Mutation-Tests
