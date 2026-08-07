"""ADR-014 Schritt 7 (2026-08-02): Payload-Bau Phase B (Goal-Analyse-
Formatierung + Produktselektion) aus services/portfolio_engine.py extrahiert.

0 Zeilen Fachlogik-Aenderung — Byte-fuer-Byte-Kopie der Funktionskoerper
(einzige Abweichung: pro Funktion wurde, wo noetig, ein function-local Lazy-
Import fuer Namen ergaenzt, die weiterhin in portfolio_engine.py bzw. in
bereits extrahierten Geschwister-Modulen (CMA/Reserve/Gesamtvermoegen)
leben — exakt das gleiche Muster wie in den 6 vorherigen Extraktionsschritten
(Gesamtvermoegen, Live-Rebalancing, CMA, Reserve, MC-Simulation, Optimizer-
Integration)). Diff-Skript gegen das Original verifiziert 0 Abweichungen in
den eigentlichen Statements (siehe PR-Beschreibung / Task-Output).

## Kontiguitaets-Scan-Befund (Lehre aus dem Beinahe-Fehler in Schritt 5)

Die im ADR als "Payload-Bau Phase B" benannte Funktionsliste ist NICHT ein
einziger zusammenhaengender Block, sondern liegt in der aktuellen Datei
(Stand: nach Schritten 1-6) in DREI physisch getrennten Bloecken:

- **Block A** (Zeilen 957-1531 im Ausgangszustand vor dieser Extraktion):
  `_build_asset_class_assumptions` bis `_merge_goal_analysis_with_monte_carlo`.
  Ein vollstaendiger `def`-Scan ueber genau diesen Bereich foerderte ZWEI
  Funktionen zutage, die NICHT auf der Zielliste standen:
    - `_growth_goals_for_equity_tilt` (Zeilen 1194-1216 im Ausgangszustand) —
      gehoert laut ADR-014 zum House-Matrix/Tilt-Cluster (Kandidat 8, noch
      nicht extrahiert) und wird ausschliesslich vom Haupt-Orchestrator
      `generate_target_allocation` aufgerufen. **Bleibt bewusst in
      portfolio_engine.py** — NICHT Teil dieser Extraktion.
    - `_parse_iso_date` (Zeilen 1219-1226 im Ausgangszustand) — stand in
      KEINER ADR-014-Funktionsliste, ist aber eine direkte, ausschliessliche
      Abhaengigkeit von `_goal_projection_years` (Zielliste dieses Schritts)
      und wird zusaetzlich bereits HEUTE von `services/
      portfolio_engine_mc_simulation.py` (`_year_index_for_goal`,
      `_full_goal_duration_years`, `_goal_duration_years`) per Lazy-Import
      aus `services.portfolio_engine` zurueckgeholt. Da sie nur von
      Payload-Bau-Funktionen direkt aufgerufen wird (kein anderer Cluster
      RUFT sie auf, andere Cluster importieren sie nur zurueck), wandert sie
      MIT in dieses Modul — siehe Re-Export-Konsequenz unten.
- **Block B**: `_build_bucket_response` — isolierte Einzelfunktion, umgeben
  von CORE-Helfern (`_target_allocation_context_warnings` davor,
  `_assert_allocation_has_basis` danach), die beide in portfolio_engine.py
  bleiben. Kein unerwarteter Fund.
- **Block C**: `_product_matches_constraints` bis
  `_filter_products_by_universe` — 14 Funktionen, alle zur Produktfilter-/
  Scoring-/TER-Aggregations-/Konzentrationslimiten-Familie gehoerend, exakt
  wie in der ADR-Beschreibung ("Produktfilter ... Produkt-Scoring, TER-
  Aggregation, Konzentrationslimiten, Produktuniversum-Filter"). Kein
  unerwarteter Fund in diesem Block.

## Transitive Re-Export-Pflicht (verifiziert per Lazy-Import-Grep in den
## bereits extrahierten Geschwister-Modulen)

Der ADR nennt explizit `_goal_projection_years`/`_annualize_goal_amount` als
Namen, die `services/portfolio_engine_reserve.py` per Lazy-Import aus
`services.portfolio_engine` zurueckholt (bestaetigt: Zeilen 259+310-312 dort).
Beim Draften dieses Schritts wurden per Grep ZUSAETZLICH VIER weitere Namen
gefunden, die `services/portfolio_engine_mc_simulation.py`
(`_monte_carlo_goal_summary`, `_year_index_for_goal`,
`_full_goal_duration_years`, `_goal_duration_years`) per Lazy-Import aus
`services.portfolio_engine` zurueckholt und die JETZT in dieses Modul
verschoben werden:

    _goal_projection_years          (Reserve L259/312 + MC L621)
    _annualize_goal_amount          (Reserve L259/310 + MC L669)
    _parse_iso_date                 (MC L629, L640)
    _compute_goal_score             (MC L670, L715 etc.)
    _goal_hardness_key              (MC L672, L694)
    _goal_target_wealth_rappen      (MC L676)

Damit muss der Re-Export-Block, den der Koordinator in portfolio_engine.py
fuer diesen Schritt ergaenzt, ALLE SECHS dieser Namen enthalten (nicht nur
die zwei im ADR explizit genannten) — sonst brechen die bestehenden Lazy-
Imports in portfolio_engine_reserve.py UND portfolio_engine_mc_simulation.py.

## Externe (Nicht-Test) Konsumenten

Exhaustive Grep (ganzes Repo, `tests/` ausgeschlossen) nach jedem der 30
Funktionsnamen dieses Moduls: **0 echte externe Konsumenten**. Es gibt
mehrere False-Positives mit identischem Funktionsnamen, aber komplett
unabhaengiger, eigener Implementierung (z.B. `routers/wealth.py::
_goal_hardness_key(value)` und `schemas/wealth.py::_goal_hardness_key(value)`
haben eine andere Signatur als diese `_goal_hardness_key(goal)` — genauso
`services/review_engine.py::_parse_iso_date`). Diese lokalen Doppel-Namen
werden von dieser Extraktion nicht beruehrt. Damit unterscheidet sich dieser
Cluster von allen 6 vorherigen — dort gab es je 1-2 echte externe Importe
(`backtest_ab.py`, `review_engine.py`, `advisory_report.py`,
`foundation_example.py`, `routers/clients.py`, `routers/wealth.py`,
`services/optimizer/scenario_engine.py`).

## Interne Konsumenten (alle in portfolio_engine.py, bleiben dort)

Alle internen Call-Sites dieser 30 Funktionen liegen ausschliesslich in den
5 Orchestrator-Funktionen, die laut ADR-014 NICHT extrahiert werden:
`generate_target_allocation`, `build_target_payload_from_allocation`,
`build_recommendation_payload_from_run`, `generate_recommendation_run`.

## Geflaggter Test-Risiko-Fund (Raw-Text-Scan)

`tests/test_frontend_goal_soll_ist.py::test_backend_exposes_current_goal_analysis`
liest `services/portfolio_engine.py` als rohen Text und prueft u.a. die
literalen Substrings `"median_achievement_pct"` und
`"pessimistic_shortfall_rappen"`. Beide Strings kamen im Ausgangszustand
AUSSCHLIESSLICH innerhalb von `_merge_goal_analysis_with_monte_carlo` vor
(jetzt in diesem Modul). Nach der Extraktion verschwinden sie aus dem
Rohtext von `portfolio_engine.py` — dieser Test wuerde ohne Anpassung ROT
werden (analog zur in Schritt 5 gefundenen Text-Scan-Falle). Die geprüfte
dritte Zeichenkette `'"current_goal_analysis"'` bleibt dagegen unberuehrt
(kommt aus den Orchestratoren, die in portfolio_engine.py bleiben).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from models.allocation import CapitalMarketAssumption, OptimizerPolicy, TargetAllocation
from models.mandates import Mandate
from models.review import Product, ProductUniverseEntry
from models.wealth import Goal
from services.cashflow_timeline import future_value_with_cashflow_series, normalize_frequency


_GOAL_HARDNESS_MULTIPLIER_BPS = {
    "hart": 20000,
    "primaer": 10000,
    "opportunistisch": 4000,
}


# B5: Hardness-abhaengige Gewichtung von Wahrscheinlichkeit vs. Magnitude.
# Hart: success_rate dominiert (Mindestleistung muss eingehalten werden).
# Opportunistisch: funded_ratio dominiert (Magnitude wichtiger als Schwellwert).
# Primaer: balanciert.
# Quellen: Brunel (2003), Das/Markowitz/Scheid/Statman (2010), Vanguard 2015.
_GOAL_SCORE_ALPHA = {
    "hart": 0.8,
    "primaer": 0.5,
    "opportunistisch": 0.2,
}


def _build_asset_class_assumptions(
    *,
    current_amounts: dict[str, int],
    advisory_wealth_rappen: int,
    targets: dict[str, int],
    asset_risky_weights: dict[str, int],
    cma: CapitalMarketAssumption,
    sub_allocations: list[dict] | None = None,
) -> list[dict]:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import (
        ASSET_LIQUIDITY_PROFILES,
        BUCKET_FIELDS,
        BUCKET_LABELS,
        _bps,
        _weighted_bucket_metrics,
    )

    # C3: Bucket-Metriken aus tatsaechlicher Sub-Allocation-Gewichtung,
    # nicht aus ungewichtetem Sub-Annahmen-Mittel.
    returns, vols = _weighted_bucket_metrics(cma, sub_allocations)
    assumptions = []
    for key in BUCKET_FIELDS:
        assumptions.append(
            {
                "asset_class": BUCKET_LABELS[key],
                "current_weight_bps": _bps(int(current_amounts.get(key, 0)), advisory_wealth_rappen),
                "target_weight_bps": int(targets.get(key, 0)),
                "risky_fraction_bps": int(asset_risky_weights.get(key, 0)),
                "expected_return_bps": int(returns.get(key, 0)),
                "expected_volatility_bps": int(vols.get(key, 0)),
                "liquidity_profile": ASSET_LIQUIDITY_PROFILES.get(key, "n/a"),
                "market_data_role": "Live-Preise fuer Drift / Bewertung, manuelle CMA fuer Strategie",
            }
        )
    return assumptions


def _build_sub_asset_class_assumption_reference(
    sub_allocations: list[dict],
    cma: CapitalMarketAssumption,
) -> list[dict]:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import (
        _asset_class_expected_metrics,
        _sub_asset_class_assumption_map,
        _sub_asset_class_metrics,
    )

    returns, vols = _asset_class_expected_metrics(cma)
    assumption_map = _sub_asset_class_assumption_map(cma)
    seen: set[tuple[str, str]] = set()
    items: list[dict] = []
    for item in sub_allocations:
        asset_class = str(item.get("asset_class") or "")
        sub_asset_class = str(item.get("sub_asset_class") or "")
        if not asset_class or not sub_asset_class:
            continue
        marker = (asset_class, sub_asset_class)
        if marker in seen:
            continue
        seen.add(marker)
        expected_return_bps, expected_volatility_bps = _sub_asset_class_metrics(
            sub_asset_class,
            asset_class,
            cma,
            returns,
            vols,
        )
        items.append(
            {
                "asset_class": asset_class,
                "sub_asset_class": sub_asset_class,
                "expected_return_bps": expected_return_bps,
                "expected_volatility_bps": expected_volatility_bps,
                "source": "CMA Sub-Asset-Class" if sub_asset_class in assumption_map else "Asset-Class fallback",
            }
        )
    return items


def _goal_hardness_key(goal: Goal | None) -> str:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _norm_text

    raw = _norm_text(getattr(goal, "hardness", None) or "Primaer").strip().lower()
    if raw == "hart":
        return "hart"
    if raw == "opportunistisch":
        return "opportunistisch"
    return "primaer"


def _goal_weight(goal: Goal) -> int:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import GOAL_WEIGHT_BY_RANK

    base = int(goal.weight_bps) if goal.weight_bps else GOAL_WEIGHT_BY_RANK.get(int(goal.rank or 5), 312)
    multiplier = _GOAL_HARDNESS_MULTIPLIER_BPS.get(_goal_hardness_key(goal), 10000)
    return int(round(base * multiplier / 10000))


def _build_mandate_score(goal_analysis: list[dict]) -> dict:
    """B6: Mandate-Aggregation aus goal_analysis.

    Liefert ZWEI Aggregate (PK-konsistent, ASIP §3.2):
    - weighted_score: gewichteter Mittelwert aller goal_scores nach
      weight_bps * hardness_multiplier_bps. Strategie-Sicht. None wenn
      keine Goals.
    - weakest_hard_score: min(score) ueber Goals mit hardness=Hart.
      Compliance-Sicht. None wenn keine harten Goals.

    Methodisch: Mandate haben oft heterogene Goals (PK-Pflicht vs.
    ueberobligatorisch vs. Reisefonds). Pure Aggregation maskiert harte
    Verfehlungen; daher beide Sichten parallel.
    """
    if not goal_analysis:
        return {
            "weighted_score": None,
            "weakest_hard_score": None,
            "weakest_hard_goal_id": None,
            "method": "weighted_avg + weakest_hard_min",
        }

    # weighted: weight_bps * hardness multiplier
    weighted_sum = 0.0
    weight_sum = 0.0
    for item in goal_analysis:
        score = float(item.get("achievement_score") or 0)
        base_weight = max(0, int(item.get("weight_bps") or 0))
        hardness_raw = str(item.get("hardness") or "Primaer").strip().lower()
        if hardness_raw == "hart":
            hardness_key = "hart"
        elif hardness_raw == "opportunistisch":
            hardness_key = "opportunistisch"
        else:
            hardness_key = "primaer"
        multiplier = _GOAL_HARDNESS_MULTIPLIER_BPS.get(hardness_key, 10000)
        effective_weight = base_weight * multiplier
        weighted_sum += score * effective_weight
        weight_sum += effective_weight
    weighted_score = int(round(weighted_sum / weight_sum)) if weight_sum > 0 else None

    # weakest hard
    hard_goals = [
        item for item in goal_analysis
        if str(item.get("hardness") or "").strip().lower() == "hart"
    ]
    if hard_goals:
        worst = min(hard_goals, key=lambda x: int(x.get("achievement_score") or 0))
        weakest_hard_score = int(worst.get("achievement_score") or 0)
        weakest_hard_goal_id = worst.get("goal_id")
    else:
        weakest_hard_score = None
        weakest_hard_goal_id = None

    return {
        "weighted_score": weighted_score,
        "weakest_hard_score": weakest_hard_score,
        "weakest_hard_goal_id": weakest_hard_goal_id,
        "method": "weighted_avg + weakest_hard_min",
    }


def _compute_goal_score(
    *,
    success_rate_pct: int,
    funded_ratio_pct: int,
    hardness_key: str,
) -> int:
    """B5 zentrale Score-Formel:
    score = alpha * success_rate_pct + (1 - alpha) * funded_ratio_pct
    mit alpha aus _GOAL_SCORE_ALPHA[hardness_key], default primaer.

    Beide Inputs werden auf [0, 100] geclampt; Ergebnis liegt damit in [0, 100].
    """
    alpha = _GOAL_SCORE_ALPHA.get(hardness_key, _GOAL_SCORE_ALPHA["primaer"])
    sr = max(0, min(100, int(success_rate_pct)))
    fr = max(0, min(100, int(funded_ratio_pct)))
    raw = alpha * sr + (1.0 - alpha) * fr
    return int(round(max(0.0, min(100.0, raw))))


def _inflate_real_goal_target_rappen(target_rappen: int, years: int, inflation_series_bps: list[int] | None) -> int:
    target = max(1, int(target_rappen or 0))
    factor = 1.0
    series = list(inflation_series_bps or [150])
    last_bps = int(series[-1] if series else 150)
    for idx in range(max(0, int(years or 0))):
        infl_bps = int(series[idx]) if idx < len(series) else last_bps
        factor *= 1 + (infl_bps / 10000)
    return int(round(target * factor))


def _goal_target_wealth_rappen(goal: Goal, years: int, inflation_series_bps: list[int] | None) -> int:
    nominal_target = max(1, int(goal.target_wealth_rappen or 0))
    if str(getattr(goal, "value_mode", "nominal") or "nominal").strip().lower() != "real":
        return nominal_target
    return _inflate_real_goal_target_rappen(nominal_target, years, inflation_series_bps)


def _parse_iso_date(value) -> date | None:
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _goal_projection_years(goal: Goal) -> int:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _norm_text

    target_date = _parse_iso_date(goal.target_date)
    start_date = _parse_iso_date(goal.start_date)
    anchor = target_date or (
        start_date if _norm_text(goal.goal_type) in ("Wiederkehrende_Ausgabe", "Pensionsausgabe") else None
    )
    if anchor:
        delta_days = (anchor - date.today()).days
        if delta_days <= 0:
            return 1
        return max(1, int((delta_days + 364) // 365))
    return max(1, int(goal.horizon_years or 1))


def _annualize_goal_amount(goal: Goal) -> int:
    amount = int(goal.target_amount_rappen or 0)
    frequency = normalize_frequency(goal.frequency)
    if frequency == "monatlich":
        return amount * 12
    if frequency == "quartalsweise":
        return amount * 4
    if frequency in ("halbjaehrlich", "halbjährlich"):
        return amount * 2
    return amount


def _goal_timing_label(goal: Goal, years: int) -> str:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _norm_text

    goal_type = _norm_text(goal.goal_type).strip()
    if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe"):
        parts = []
        if goal.frequency:
            parts.append(normalize_frequency(goal.frequency))
        if goal.start_date:
            parts.append(f"ab {goal.start_date}")
        if goal.is_ongoing:
            parts.append("laufend")
        elif goal.target_date:
            parts.append(f"bis {goal.target_date}")
        elif years:
            parts.append(f"Horizont {years} J.")
        return " | ".join(parts) if parts else f"Horizont {years} J."
    if goal_type == "Einmalige_Ausgabe" and goal.start_date:
        return f"am {goal.start_date}"
    if goal.target_date:
        return f"bis {goal.target_date}"
    return f"Horizont {years} J."


def _expected_death_year_offset_from_mandate(mandate) -> int | None:
    """Sprint U-P5 Fix H12: leitet aus Mandate-Feldern den erwarteten
    Sterbe-Zeitpunkt als Years-from-now ab.
    - Priorität 1: life_expectancy_year (manuell gepflegt im Mandate)
    - Priorität 2: BFS-Default basierend auf client_birth_year + client_sex
                   (median life expectancy aus BFS_2020_2022) -- NUR fuer
                   CH-Mandate (siehe Jurisdiktions-Gate unten)
    - Sonst None (kein Cutoff)

    Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): BFS_2020_2022 ist eine Schweizer
    Sterbetafel. Fuer ein DE/AT-Mandat (mandate.jurisdiction != CH) haette
    sie das Sterbealter systematisch falsch geschaetzt und damit das
    Verzehr-/Depletion-Risiko in der Monte-Carlo-Simulation verzerrt. Da
    aktuell keine DE/AT-Sterbetafel vorliegt, ist "kein Cutoff" (konservativ,
    unbefristeter Horizont) die richtige Wahl, statt eine falsche Zahl zu
    zeigen. Bewusst NUR die direkte mandate.jurisdiction-Prüfung (wie an den
    2 anderen bestehenden Stellen in dieser Codebase) -- NICHT der noch nicht
    freigegebene services.jurisdiction.resolve-Resolver (siehe dessen
    Modul-Docstring: WP2, exklusiver Schreibzugriff noetig).
    """
    from datetime import date as _date
    today_year = _date.today().year
    life_expectancy_year = int(getattr(mandate, "life_expectancy_year", 0) or 0)
    if life_expectancy_year and life_expectancy_year > today_year:
        return life_expectancy_year - today_year
    jurisdiction = str(getattr(mandate, "jurisdiction", None) or "CH")
    birth_year = int(getattr(mandate, "client_birth_year", 0) or 0)
    sex = str(getattr(mandate, "client_sex", "") or "")
    if jurisdiction == "CH" and birth_year and sex in ("M", "F"):
        try:
            from services.mortality.bfs import BFS_2020_2022
            current_age = max(0, today_year - birth_year)
            # Median life expectancy = remaining years until S(t)=0.5
            survival = 1.0
            for age_offset in range(BFS_2020_2022.max_age - current_age):
                q = BFS_2020_2022.qx(current_age + age_offset, sex)
                survival *= max(0.0, 1.0 - float(q))
                if survival < 0.5:
                    return max(1, age_offset + 1)
        except Exception:
            pass
    return None


def _build_goal_analysis(
    goals: list[Goal],
    advisory_wealth_rappen: int,
    total_wealth_rappen: int,
    cashflow_projection_series_rappen: list[int],
    inflation_series_bps: list[int],
    expected_return_bps: int,
    reserve_needed_rappen: int,
    policy: OptimizerPolicy,
    expected_death_year_offset: int | None = None,
) -> list[dict]:
    """Sprint U-P5 Fix H12: expected_death_year_offset (Years from today)
    schneidet die contribution_series so dass keine Cashflows nach dem
    erwarteten Sterbejahr in den deterministischen projected_rappen einfliessen.
    Vorher: Goal-Analyse sah komplette Cashflow-Series ohne Mortality-Cutoff
    — AHV-Goal mit langer Laufzeit floss komplett in projected obwohl der
    Mandant statistisch in t=15 stirbt.
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import (
        _external_assets_inflation_value,
        _goal_reserve_for_goal,
        _goal_uses_total_scope,
        _norm_text,
    )

    analysis = []
    # #83 Gesamtvermoegen-Scope: externe Assets = Gesamt- minus Beratungsvermoegen.
    external_wealth_rappen = max(0, int(total_wealth_rappen or 0) - int(advisory_wealth_rappen or 0))
    for goal in sorted(goals, key=lambda g: (int(g.rank or 999), g.label or "")):
        years = _goal_projection_years(goal)
        # B4: Default werden Goals gegen advisory_wealth bewertet, weil die
        # Strategie nur das Beratungsvermoegen optimiert. External Assets
        # (Eigenheim etc.) werden mit Aktien-Renditen NICHT hochgerechnet, weil
        # diese Annahme fragil ist (PK-konsistent, ASIP §3.2). Bisheriger
        # Skalierungs-Pfad mit allow_other_assets_for_goals erzeugte Drift
        # zwischen deterministischer und MC-Bewertung.
        # #83 (opt-in): bei goal_scope='Gesamtvermoegen' werden externe Assets
        # ZUSAETZLICH beruecksichtigt — aber KONSERVATIV nur mit Teuerung (real
        # 0%, keine Vola), siehe Vermoegensziel-Zweig + _external_assets_inflation_value.
        investable_base = advisory_wealth_rappen
        projection_years = max(1, years or 1)
        contribution_series = list(cashflow_projection_series_rappen[:projection_years])
        if len(contribution_series) < projection_years:
            contribution_series.extend([0] * (projection_years - len(contribution_series)))
        # Sprint U-P5 Fix H12: Mortality-Cutoff
        if expected_death_year_offset is not None and expected_death_year_offset > 0:
            cutoff = min(projection_years, int(expected_death_year_offset))
            for idx in range(cutoff, len(contribution_series)):
                contribution_series[idx] = 0
        projected_rappen = future_value_with_cashflow_series(
            investable_base,
            contribution_series,
            expected_return_bps,
        )
        target_rappen = 0
        goal_type = _norm_text(goal.goal_type)
        hardness_key = _goal_hardness_key(goal)
        # B5: Score = alpha * success_rate_pct + (1-alpha) * funded_ratio_pct
        # Deterministisch ist success_rate binaer (entweder erreicht oder nicht).
        # MC liefert echte success_rate via _monte_carlo_goal_summary.
        if goal_type == "Renditeziel":
            target_rappen = projected_rappen
            target_return = max(1, int(goal.target_return_bps or 1))
            funded_ratio_pct = int(round(min(200, max(-100, expected_return_bps / target_return * 100))))
            success_rate_pct = 100 if expected_return_bps >= int(goal.target_return_bps or 0) else 0
            score = _compute_goal_score(
                success_rate_pct=success_rate_pct,
                funded_ratio_pct=funded_ratio_pct,
                hardness_key=hardness_key,
            )
        elif goal_type in ("Kapitalerhalt", "Vermoegensziel"):
            target_rappen = _goal_target_wealth_rappen(goal, years, inflation_series_bps)
            # #83: bei Gesamtvermoegen-Scope die externen Assets (nur Teuerung,
            # real 0%) zum projizierten Beratungsvermoegen addieren. Default-Scope
            # unveraendert. Wirkt auch im gespeicherten projected_value_rappen.
            if _goal_uses_total_scope(goal):
                projected_rappen += _external_assets_inflation_value(
                    external_wealth_rappen, projection_years, inflation_series_bps
                )
            denominator = max(1, target_rappen)
            funded_ratio_pct = int(round(min(200, max(-100, projected_rappen / denominator * 100))))
            success_rate_pct = 100 if projected_rappen >= target_rappen else 0
            score = _compute_goal_score(
                success_rate_pct=success_rate_pct,
                funded_ratio_pct=funded_ratio_pct,
                hardness_key=hardness_key,
            )
        else:
            target_rappen = _annualize_goal_amount(goal) if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe") else int(goal.target_amount_rappen or 0)
            # C5: zielbezogene Reserve statt globaler reserve_needed_rappen,
            # damit ein grosses Ziel kleinere Ziele nicht unbeabsichtigt
            # auf 'On Track' hebt.
            # Sprint U-P2 Fix H10: vorher wurde fuer years>3 ausschliesslich
            # `projected_rappen` als available genutzt. Folge: ein 5M-Goal in
            # 10J mit 500k advisory zeigte "On Track" weil projected_rappen
            # > 5M moeglich war — obwohl objektiv unterfinanziert. Jetzt:
            # min(projected, _goal_reserve_for_goal) — die kleinere Zahl wirkt,
            # damit eine grosse Lebenshaltungs-Annahme nicht zu falscher
            # Sicherheit fuehrt.
            if years <= 3:
                available = _goal_reserve_for_goal(goal)
            else:
                # Long-term: projected_rappen muss die zielbezogene Reserve
                # NICHT unterschreiten — sonst nimmt der konservativere Wert.
                reserve_for_goal = _goal_reserve_for_goal(goal)
                # _goal_reserve_for_goal liefert fuer years>3 die abgezinste
                # Reserve nach Time-Bucket-Logik; bei stufen-mode = 0 fuer >7J.
                # In dem Fall ignorieren wir die Reserve und nutzen nur projected.
                if reserve_for_goal > 0:
                    available = min(projected_rappen, reserve_for_goal + projected_rappen // 2)
                else:
                    available = projected_rappen
            denominator = max(1, target_rappen)
            funded_ratio_pct = int(round(min(200, max(-100, available / denominator * 100))))
            success_rate_pct = 100 if available >= target_rappen else 0
            score = _compute_goal_score(
                success_rate_pct=success_rate_pct,
                funded_ratio_pct=funded_ratio_pct,
                hardness_key=hardness_key,
            )
        status = "On Track" if score >= 70 else ("Pruefen" if score >= 45 else "Gefaehrdet")
        analysis.append(
            {
                "goal_id": goal.id,
                "label": goal.label,
                "goal_type": goal.goal_type,
                "goal_scope": goal.goal_scope,
                "value_mode": getattr(goal, "value_mode", "nominal") or "nominal",
                "hardness": getattr(goal, "hardness", None),
                "rank": int(goal.rank or 0),
                "weight_bps": _goal_weight(goal),
                "target_amount_rappen": target_rappen,
                "target_wealth_rappen": int(goal.target_wealth_rappen) if goal.target_wealth_rappen is not None else None,
                "target_return_bps": int(goal.target_return_bps) if goal.target_return_bps is not None else None,
                "projected_value_rappen": projected_rappen,
                "achievement_score": score,
                "status": status,
                "start_date": goal.start_date,
                "target_date": goal.target_date,
                "horizon_years": years,
                "is_ongoing": int(goal.is_ongoing or 0),
                "frequency": goal.frequency,
                "timing_label": _goal_timing_label(goal, years),
            }
        )
    return analysis


def _merge_goal_analysis_with_monte_carlo(
    goal_analysis: list[dict],
    monte_carlo: dict | None,
    *,
    summaries_key: str = "goal_summaries",
) -> list[dict]:
    if not monte_carlo:
        return goal_analysis
    summaries = {
        item["goal_id"]: item
        for item in (monte_carlo.get(summaries_key) or [])
        if item.get("goal_id")
    }
    merged = []
    for item in goal_analysis:
        summary = summaries.get(item.get("goal_id"))
        if not summary:
            merged.append(item)
            continue
        merged.append(
            {
                **item,
                "achievement_score": int(summary.get("score", item.get("achievement_score") or 0)),
                "status": "On Track" if int(summary.get("score", 0)) >= 70 else ("Pruefen" if int(summary.get("score", 0)) >= 45 else "Gefaehrdet"),
                "success_rate_pct": int(summary.get("success_rate_pct") or 0),
                "path_success_rate_pct": int(summary.get("success_rate_pct") or 0),
                "funded_ratio_p50": float(summary.get("funded_ratio_p50") or 0),
                "median_achievement_pct": int(summary.get("median_achievement_pct") or 0),
                "pessimistic_shortfall_rappen": max(0, int(summary.get("pessimistic_shortfall_rappen") or 0)),
                "projected_value_p10_rappen": int(summary.get("projected_value_p10_rappen") or 0),
                "projected_value_p50_rappen": int(summary.get("projected_value_p50_rappen") or 0),
                "projected_value_p90_rappen": int(summary.get("projected_value_p90_rappen") or 0),
                "projected_value_rappen": int(summary.get("projected_value_p50_rappen") or item.get("projected_value_rappen") or 0),
                "evaluation_note": summary.get("evaluation_note") or item.get("evaluation_note"),
            }
        )
    return merged


def _build_bucket_response(
    target_allocation: TargetAllocation,
    current_amounts: dict,
    advisory_wealth_rappen: int,
    target_total_rappen: int | None = None,
    target_base_rappen: int | None = None,  # alias from rp-ueberarbeitung
) -> list[dict]:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import BUCKET_FIELDS, BUCKET_LABELS, _bps

    if target_base_rappen is not None and target_total_rappen is None:
        target_total_rappen = target_base_rappen
    target_base_rappen = int(target_total_rappen if target_total_rappen is not None else advisory_wealth_rappen)
    label_map = {
        "equities": (BUCKET_LABELS["equities"], target_allocation.target_equities_bps, target_allocation.band_equities_min_bps, target_allocation.band_equities_max_bps),
        "bonds": (BUCKET_LABELS["bonds"], target_allocation.target_bonds_bps, target_allocation.band_bonds_min_bps, target_allocation.band_bonds_max_bps),
        "real_estate": (BUCKET_LABELS["real_estate"], target_allocation.target_real_estate_bps, target_allocation.band_real_estate_min_bps, target_allocation.band_real_estate_max_bps),
        "alternatives": (BUCKET_LABELS["alternatives"], target_allocation.target_alternatives_bps, target_allocation.band_alternatives_min_bps, target_allocation.band_alternatives_max_bps),
        "liquidity": (BUCKET_LABELS["liquidity"], target_allocation.target_liquidity_bps, target_allocation.band_liquidity_min_bps, target_allocation.band_liquidity_max_bps),
    }
    bucket_response = []
    for key in BUCKET_FIELDS:
        label, target_bps, min_bps, max_bps = label_map[key]
        current_amount = current_amounts[key]
        current_bps = _bps(current_amount, advisory_wealth_rappen)
        bucket_response.append(
            {
                "asset_class": label,
                "current_weight_bps": current_bps,
                "current_amount_rappen": current_amount,
                "target_weight_bps": int(target_bps),
                "target_amount_rappen": int(round(target_base_rappen * target_bps / 10000)) if target_base_rappen else 0,
                "delta_weight_bps": int(target_bps) - current_bps,
                "band_min_bps": int(min_bps),
                "band_max_bps": int(max_bps),
            }
        )
    return bucket_response


def _product_matches_constraints(
    product: Product,
    prefs: dict,
    score_bucket: int,
    *,
    ignore_suitability: bool = False,
    jurisdiction_ctx: dict | None = None,
) -> bool:
    """WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): jurisdiction_ctx (siehe
    _resolve_jurisdiction_context()) parametrisiert die chf_only-/Hedging-
    Pruefungen ueber home_currency statt hartcodiertem "CHF". Ohne
    jurisdiction_ctx (z.B. bestehende Aufrufer/Tests) wird
    _CH_JURISDICTION_CONTEXT verwendet -- home_currency="CHF", exakt das
    bisherige Verhalten (Constraint 1: CH-Pfad byte-identisch)."""
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _CH_JURISDICTION_CONTEXT, _norm_text

    ctx = jurisdiction_ctx or _CH_JURISDICTION_CONTEXT
    home_currency = ctx["home_currency"]
    product_prefs = prefs["product"]
    geo_prefs = prefs["geo"]
    policy_prefs = prefs["policy"]
    asset_class = _norm_text(product.asset_class)
    funds_only = product_prefs.get("fundsOnly") or policy_prefs.get("universe") == "funds_only"
    listed_only = product_prefs.get("listedOnly") or policy_prefs.get("universe") == "listed_only"
    chf_only = geo_prefs.get("chfOnly") or policy_prefs.get("hedging") == "chf_only"
    if funds_only and asset_class != "Liquiditaet" and product.product_type not in ("ETF", "Fonds", "Immobilienfonds"):
        return False
    if listed_only and asset_class != "Liquiditaet" and product.product_type not in ("ETF", "Einzeltitel", "Anleihe"):
        return False
    # Sprint U-P0 Fix H5: noStructured und noDerivatives sind semantisch
    # verschieden — vorher rief beides nur _product_is_structured. Jetzt
    # prueft noDerivatives zusaetzlich echte Derivate-Marker.
    if product_prefs.get("noStructured") and _product_is_structured(product):
        return False
    if product_prefs.get("noDerivatives") and (
        _product_is_structured(product) or _product_is_derivative(product)
    ):
        return False
    if product_prefs.get("noLeverage") and _product_is_leveraged(product):
        return False
    if chf_only and product.currency != home_currency:
        return False
    if geo_prefs.get("noUsd") and product.currency == "USD":
        return False
    if geo_prefs.get("hedgingRequired") and not _product_is_chf_or_fx_hedged(product, home_currency):
        return False
    if policy_prefs.get("esg") in ("best_in_class", "impact", "net_zero") and asset_class != "Liquiditaet":
        if str(product.sfdr_class or "") not in ("8", "9"):
            return False
    if product.suitability and not ignore_suitability:
        allowed = [
            rule for rule in product.suitability
            if int(rule.profile_from or 1) <= score_bucket <= int(rule.profile_to or 10) and int(rule.advisory_allowed or 0) == 1
        ]
        return bool(allowed)
    return True


def _product_descriptor_text(product: Product) -> str:
    fields = (
        product.product_name,
        product.product_type,
        product.asset_class,
        product.sub_asset_class,
        getattr(product, "security_type", None),
        getattr(product, "security_type2", None),
        getattr(product, "market_sector", None),
    )
    return " ".join(str(field or "") for field in fields).lower()


def _product_is_structured(product: Product) -> bool:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _norm_text

    text = _product_descriptor_text(product)
    product_type = _norm_text(product.product_type).strip().lower()
    return product_type == "strukturiertes produkt" or "structured" in text or "zertifikat" in text


def _product_is_leveraged(product: Product) -> bool:
    text = _product_descriptor_text(product)
    return any(marker in text for marker in ("leveraged", "gehebelt", "2x", "3x", "ultra", "short etf"))


def _product_is_derivative(product: Product) -> bool:
    """Sprint U-P0 Fix H5: erkennt echte Derivate (Futures, Optionen, Swaps,
    Forwards, Mini-Futures, Tracker-Zertifikate) — getrennt von strukturierten
    Produkten, damit `noDerivatives` semantisch korrekt filtert."""
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _norm_text

    text = _product_descriptor_text(product)
    product_type = _norm_text(product.product_type).strip().lower()
    derivative_markers = (
        "future", "option", "swap", "forward",
        "mini-future", "knock-out", "warrant", "optionsschein",
        "tracker", "discount-zertifikat", "bonus-zertifikat",
    )
    return product_type in ("future", "option", "derivat") or any(
        marker in text for marker in derivative_markers
    )


def _product_is_chf_or_fx_hedged(product: Product, home_currency: str = "CHF") -> bool:
    """WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): home_currency default
    "CHF" reproduziert exakt das bisherige CH-Verhalten (Constraint 1).
    Fuer Nicht-CH wird die aufgeloeste Heimwaehrung (siehe
    _resolve_jurisdiction_context()) durchgereicht, z.B. "EUR" -> Marker
    "eur-hedg"/"eur hedg" statt "chf-hedg"/"chf hedg"."""
    home = (home_currency or "CHF").upper()
    if str(product.currency or "").upper() == home:
        return True
    text = _product_descriptor_text(product)
    home_lower = home.lower()
    markers = ("hedged", f"{home_lower}-hedg", f"{home_lower} hedg", "abgesichert")
    return any(marker in text for marker in markers)


def _product_score(product: Product, sub_asset_class: str, prefs: dict, jurisdiction_ctx: dict | None = None) -> int:
    """WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): siehe
    _product_matches_constraints() -- ohne jurisdiction_ctx exakt das
    bisherige CH-Verhalten (home_currency="CHF", home_equity_label="Schweiz")."""
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _CH_JURISDICTION_CONTEXT, _norm_text

    ctx = jurisdiction_ctx or _CH_JURISDICTION_CONTEXT
    home_currency = ctx["home_currency"]
    home_equity_label = ctx["home_equity_label"]
    score = 1000
    score -= int(product.ter_bps or 0)
    if product.currency == home_currency:
        score += 40
    if product.sub_asset_class == sub_asset_class:
        score += 200
    elif _norm_text(product.asset_class) in ("Aktien", "Obligationen", "Immobilien", "Alternative", "Liquiditaet"):
        score += 50
    policy_prefs = prefs["policy"]
    geo_prefs = prefs["geo"]
    tilts = prefs["tilts"]
    if policy_prefs.get("homeBias") == "ch_focus" and (home_equity_label in (product.sub_asset_class or "") or product.currency == home_currency):
        score += 35
    if (geo_prefs.get("hedgingRequired") or policy_prefs.get("hedging") in ("hedged", "risk_budget")) and _product_is_chf_or_fx_hedged(product, home_currency):
        score += 20
    if str(product.sfdr_class or "") in ("8", "9"):
        score += 25
    thematic_map = {
        "Thema Fossile Energie": "fossil",
        "Thema Verteidigung": "defense",
        "Thema Tabak": "tobacco",
        "Thema Alkohol": "alcohol",
        "Thema Gluecksspiel": "gaming",
        "Thema Kernenergie": "nuclear",
    }
    thematic_key = thematic_map.get(sub_asset_class)
    if thematic_key:
        tilt_mode = tilts.get(thematic_key)
        if tilt_mode == "exclude":
            return -10000
        if tilt_mode == "underweight":
            score -= 150
        if tilt_mode == "overweight":
            score += 250
    return score


def _items_with_known_ter(items: list[dict]) -> list[dict]:
    return [item for item in items if item.get("ter_bps") is not None]


def _average_ter_bps(items: list[dict]) -> int:
    known = _items_with_known_ter(items)
    total_weight = sum(int(item.get("target_weight_bps") or 0) for item in known)
    if total_weight <= 0:
        return 0
    weighted_ter = sum(int(item.get("ter_bps") or 0) * int(item.get("target_weight_bps") or 0) for item in known)
    return int(round(weighted_ter / total_weight))


def _ter_coverage_bps(items: list[dict]) -> int:
    total_weight = sum(int(item.get("target_weight_bps") or 0) for item in items)
    if total_weight <= 0:
        return 0
    known_weight = sum(int(item.get("target_weight_bps") or 0) for item in _items_with_known_ter(items))
    return max(0, min(10000, int(round(known_weight / total_weight * 10000))))


def _missing_ter_positions_count(items: list[dict]) -> int:
    return sum(1 for item in items if item.get("ter_bps") is None)


def _implementation_steps(buckets: list[dict], target_total_rappen: int) -> list[str]:
    steps = []
    def amount_delta_rappen(item: dict) -> int:
        if item.get("target_amount_rappen") is not None and item.get("current_amount_rappen") is not None:
            return int(item.get("target_amount_rappen") or 0) - int(item.get("current_amount_rappen") or 0)
        return int(round(target_total_rappen * int(item.get("delta_weight_bps") or 0) / 10000))

    for bucket in sorted(buckets, key=lambda item: abs(amount_delta_rappen(item)), reverse=True):
        if abs(int(bucket["delta_weight_bps"])) < 100:
            continue
        delta_rappen = amount_delta_rappen(bucket)
        amount = int(round(abs(delta_rappen) / 100))
        direction = "aufbauen" if delta_rappen > 0 else "reduzieren"
        steps.append(f"{bucket['asset_class']} {direction}: ca. CHF {amount:,.0f}".replace(",", "'"))
    if not steps:
        steps.append("Aktuelle Allokation liegt bereits weitgehend in den Zielbandbreiten.")
    return steps


def _validate_recommendation_concentration_limits(aggregated_positions: dict[str, dict], prefs: dict) -> None:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _parse_bps_percent

    limits = prefs.get("limits") or {}
    max_single_bps = _parse_bps_percent(limits.get("singlePosition"))
    max_issuer_bps = _parse_bps_percent(limits.get("singleIssuer"))

    if max_single_bps is not None:
        breaches = [
            entry for entry in aggregated_positions.values()
            if int(entry.get("target_weight_bps") or 0) > max_single_bps
        ]
        if breaches:
            first = breaches[0]
            product = first["product"]
            raise ValueError(
                "Einzelpositionslimite kann mit dem aktuellen Produktuniversum nicht eingehalten werden: "
                f"{product.product_name} {int(first['target_weight_bps']) / 100:.2f}% > {max_single_bps / 100:.2f}%."
            )

    if max_issuer_bps is not None:
        by_provider: dict[str, int] = {}
        for entry in aggregated_positions.values():
            product = entry["product"]
            provider = str(product.provider or product.product_name or "Unbekannter Emittent")
            by_provider[provider] = by_provider.get(provider, 0) + int(entry.get("target_weight_bps") or 0)
        breaches = [(provider, weight) for provider, weight in by_provider.items() if weight > max_issuer_bps]
        if breaches:
            provider, weight = sorted(breaches, key=lambda item: item[1], reverse=True)[0]
            raise ValueError(
                "Einzelemittentenlimite kann mit dem aktuellen Produktuniversum nicht eingehalten werden: "
                f"{provider} {weight / 100:.2f}% > {max_issuer_bps / 100:.2f}%."
            )


def _filter_products_by_universe(db: Session, mandate: Mandate, products: list) -> list:
    """2026-07-27 (Laender-Skalierung, Fonds-Kuratierung): schraenkt den
    Produktkandidaten-Pool auf die ProductUniverseEntry-Positivliste des
    Tenants+Jurisdiktion ein, WENN mindestens ein Eintrag existiert.

    Rueckwaerts-kompatibel: existiert fuer (tenant_id, jurisdiction) KEIN
    Eintrag, wird NICHT einfach der komplette globale Katalog zurueckgegeben
    -- stattdessen (2026-08-01, Cross-Jurisdiktions-Leck-Fix) auf
    Product.jurisdiction in (None, mandate_jurisdiction) gefiltert. Grund:
    ein per Integrationstest gefundenes echtes Datenleck
    (tests/test_de_onboarding_integration.py::
    test_ch_mandate_unaffected_by_coexisting_de_fixtures_in_same_db) --
    OHNE diesen Filter sieht ein CH-Mandat ohne eigene Fonds-Kuratierung
    automatisch JEDES in der Installation angelegte Nicht-CH-Produkt, sobald
    eine zweite Jurisdiktion (z.B. Deutschland) eigene Produkte anlegt.
    Aendert NICHTS am CH-Verhalten, solange kein Produkt explizit mit
    jurisdiction != "CH"/NULL angelegt wird (Bestandskatalog ist komplett
    NULL -> Filter ist ein No-Op, Golden-Snapshot-Test bleibt gruen).

    mandate.tenant_id=NULL wird wie ueberall im Code (siehe
    services/auth.py::_resolve_tenant_id_for_user) auf DEFAULT_TENANT_ID
    ('main') aufgeloest statt die Filterung zu uebergehen -- Mandate/Users
    werden beim naechsten Boot ohnehin dorthin zurueckgeschrieben
    (database.py-Backfill, Single-Tenant-Modus).
    """
    from models.tenant import DEFAULT_TENANT_ID
    tenant_id = getattr(mandate, "tenant_id", None) or DEFAULT_TENANT_ID
    jurisdiction = getattr(mandate, "jurisdiction", None) or "CH"
    entries = db.query(ProductUniverseEntry).filter(
        ProductUniverseEntry.tenant_id == tenant_id,
        ProductUniverseEntry.jurisdiction == jurisdiction,
        ProductUniverseEntry.deleted_at.is_(None),
    ).all()
    if not entries:
        return [
            product for product in products
            if getattr(product, "jurisdiction", None) in (None, jurisdiction)
        ]
    allowed_product_ids = {entry.product_id for entry in entries}
    return [product for product in products if product.id in allowed_product_ids]
