# Sprint B1: Sub-Allocation-Aware Bucket-Returns

**Datum:** 2026-06-07
**Sprint:** B1 (Engine-Hardening Phase B, dritte und letzte Engine-Verbesserung)
**Trigger:** CTO-Audit 2026-06-06 markierte als BLOCKER für Premium-Segment: `scenario_inputs_from_cma` aggregierte Sub-Asset-Classes nur als simpler Durchschnitt (z.B. `equity = (CH + Intl) / 2`). Bei Sub-Tilt 80% CH / 20% EM unterschätzte der MC die Konzentrationsrisiken.

---

## Executive Summary

**Sub-Allocation-Aware Bucket-Returns via Single-Source-of-Truth-Reuse.**

| Metrik | Wert |
|--------|------|
| Geänderte Files | 2 (scenario_engine.py, solver.py) |
| Neue Tests | 9 (Backwards-Compat + Equity-Tilt + Cache-Isolation + Defensive) |
| Regression-Tests | 130 passing |
| Breaking-Changes | KEINE (sub_allocations Default None) |
| Code-Reuse | `_weighted_bucket_metrics` aus portfolio_engine.py |

---

## 1. Architektur

### Public-API-Erweiterung

```python
# services/optimizer/scenario_engine.py
def scenario_inputs_from_cma(
    cma,
    sub_allocations: list[dict] | None = None,   # NEU (B1)
) -> ScenarioInputs: ...

# services/optimizer/solver.py
def build_optimizer_context(
    *,
    cma,
    goals: list,
    ...,
    sub_allocations: list[dict] | None = None,   # NEU (B1)
) -> OptimizerContext: ...

def run_solver(
    *,
    cma,
    ...,
    sub_allocations: list[dict] | None = None,   # NEU (B1)
) -> OptimizerResult: ...
```

### Algorithmus

```python
# Wenn sub_allocations gegeben:
sub_returns, sub_vols = _weighted_bucket_metrics(cma, sub_allocations)
# Apply NS/KGV/RP-Market-Adjustments (Bucket-Level, sub-unabhängig):
sub_returns["equities"] += equity_kgv_adjustment_bps
sub_returns["bonds"] = bonds_return_from_ns or sub_returns["bonds"]
sub_returns["real_estate"] = re_return_from_premium or sub_returns["real_estate"]
sub_returns["alternatives"] = alt_return_from_premium or sub_returns["alternatives"]
bucket_returns = sub_returns
bucket_vols = sub_vols
```

### Cache-Layer-Isolation

```python
# Sprint B1: Cache-Key MUSS Sub-Allocation enthalten,
# sonst Stale-Pfad-Hit bei gleicher cma_id mit anderem Sub-Mix.
if sub_allocations:
    sub_hash = sha256(json.dumps(sub_allocations, sort_keys=True))[:12]
    cma_id_for_cache = f"{cma_id}::sub::{sub_hash}"
```

---

## 2. Mathematische Begründung

**Pre-B1 (Simpler Average):**
```
equity_return_bucket = (equity_ch_return + equity_intl_return) / 2
                     = (620 + 700) / 2 = 660 bps
```
→ Egal ob 80% CH oder 80% EM Tilt → MC sieht IMMER 660 bps.

**Post-B1 (Sub-Weighted):**
```
80% CH + 20% Global:
equity_return = 0.80 × 620 + 0.20 × 700 = 636 bps

20% CH + 80% Global:
equity_return = 0.20 × 620 + 0.80 × 700 = 684 bps
```
→ Differenz 48 bps p.a. — über 30J kumuliert ~1.4% End-Wealth-Diff.
→ Bei Tail-Pfaden (P5) noch ausgeprägter wegen Vola-Skalierung.

**Wirkung:** Berater sieht ECHTE Konzentrationsrisiken seiner Sub-Tilt-Entscheidungen.

---

## 3. Single-Source-of-Truth: Reuse aus portfolio_engine

`_weighted_bucket_metrics` existierte bereits in `portfolio_engine.py` (Sprint U-P2 Fix C3). Es:
- Aggregiert Sub-Returns gewichtet via `target_weight_bps`
- Berücksichtigt `sub_class_intra_correlation` Setting für Block-Diagonal-Vola (Sprint U-P8 Fix M1)
- Fallback auf CMA-Bucket-Defaults bei unbekanntem Sub-Label

B1 macht es für den Optimizer-Engine-Pfad verfügbar — keine Code-Duplikation.

---

## 4. Backwards-Compat-Garantien

| Test | Resultat |
|------|----------|
| `sub_allocations=None` → identisch zu pre-B1 | ✓ |
| `sub_allocations=[]` → identisch zu None | ✓ |
| Existierende Mandate (PR #213/216/218/219/220/221) bleiben grün | ✓ (130/130) |
| Korruptes sub_allocations-Format → defensiver Fallback | ✓ |

---

## 5. Cache-Isolation

**Kritischer Punkt:** Ohne Cache-Key-Erweiterung würde der zweite Aufruf mit gleicher cma_id aber anderem sub_mix die GLEICHEN MC-Pfade aus dem Cache holen (basierend auf alter mu/sigma). 

**Lösung:** SHA-256-Hash der sub_allocations wird an cma_id_for_cache angehängt. So getrennte Cache-Slots pro Sub-Mix-Variante.

---

## 6. Test-Coverage

`tests/test_sub_allocation_aware_returns.py` (9 Tests):

| Test | Was wird verifiziert |
|------|----------------------|
| `test_b1_backwards_compat_ohne_sub_allocations` | None-Default identisch zu pre-B1 |
| `test_b1_backwards_compat_leere_sub_allocations` | Leere Liste identisch zu None |
| `test_b1_equity_tilt_ch_vs_intl_differiert_im_return` | CH-Heavy vs Intl-Heavy → unterschiedliche mu_bps |
| `test_b1_equity_tilt_pre_b1_unterscheidet_nicht` | Beweis dass pre-B1 beide Tilts gleich sah |
| `test_b1_solver_mit_sub_allocations_konvergiert` | End-to-End run_solver mit sub_allocations |
| `test_b1_cache_isolation_verschiedene_sub_allocations` | Cache-Slot-Isolation pro Sub-Mix |
| `test_b1_cache_konsistenz_gleiche_sub_allocations` | Determinismus |
| `test_b1_invalid_sub_alloc_fallback_zu_default` | Defensive bei korruptem Format |
| `test_b1_bond_mix_ig_vs_fx_hedged_returns` | Bond-Sub-Class strukturelle Asserts |

---

## 7. Bewusste Out-of-Scope-Entscheidungen

| Punkt | Begründung |
|-------|-----------|
| Volle 5D-Sub-Correlation-Matrix | Aktuell Block-Diagonal via `sub_class_intra_correlation` Setting. Full-Matrix wäre Architektur-Refactor |
| Sub-Allocation-spezifische Skew/Kurt | Nutzt Bucket-Level Skew/Kurt aus CMA (gleicher Wert für CH/EM Equity). Verfeinerung in V2 |
| Sub-Allocation Drift-Tracking | Berater setzt Sub-Allocations als Strategic-Target. Drift-Monitoring ist Reporting-Layer, nicht Optimizer |
| Dynamische Sub-Allocation pro Pfad | Würde Stage-9-Scope sprengen. Aktuell Buy-and-Hold |

---

## 8. Lifecycle

- **Drift-Protection:** test_sub_allocation_aware_returns permanente Regression-Coverage
- **Reviewer-Pflicht:** Engine-Changes an `scenario_inputs_from_cma` müssen alle 9 B1-Tests grün lassen
- **Future-Evolution:** Vollvektorisierte Sub-Class-Engine (Phase 2) wäre nächster Schritt

---

## 9. Referenzen

- `services/optimizer/scenario_engine.py:scenario_inputs_from_cma` (Public-API)
- `services/optimizer/solver.py:build_optimizer_context` (Wiring)
- `services/optimizer/solver.py:run_solver` (Top-Level-Wrapper)
- `services/portfolio_engine.py:_weighted_bucket_metrics` (Source-of-Truth)
- `services/portfolio_engine.py:_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS` (Default Sub-Class CMA-Werte)
- `docs/engine-spec.md` Section 9 (war "Sub-Allocation Bucket-Returns = einfache Durchschnitt — Sprint B1 geplant" → jetzt umgesetzt)

---

**Status:** B1 komplett. **Phase B des Engine-Hardening-Plans damit ABGESCHLOSSEN.**

Nächste Sprints: Phase C (UX) — C1 Goal-Achievability-Ampel + C2 IS-Status im PDF-Audit-Block.
