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
      `_recurring_outflow_total_rappen`, `_goal_duration_years`) per Lazy-Import
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
`_recurring_outflow_total_rappen`, `_goal_duration_years`) per Lazy-Import aus
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

import json
import logging
from datetime import date

from sqlalchemy.orm import Session

from models.allocation import CapitalMarketAssumption, OptimizerPolicy, TargetAllocation
from models.mandates import Mandate
from models.review import Product, ProductUniverseEntry
from models.wealth import Goal
from services.calendar_horizon import calendar_years_until
from services.cashflow_timeline import future_value_with_cashflow_series, normalize_frequency
from services.goal_success_status import (
    SUCCESS_SOURCE_OPTIMIZER,
    SUCCESS_SOURCE_SIMULATION,
    canonical_success_by_goal,
    goal_status_from_success_pct,
)

logger = logging.getLogger(__name__)


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
    reasoning: list[str] | None = None,
) -> list[dict]:
    """Herkunft je Sub-Anlageklasse fuer den Nachweis.

    LIQUIDITY-INSTRUMENT-MODEL-001: ``"CMA Sub-Asset-Class"`` nur, wenn die
    CMA-Version die Kennzahl belegt. Ein nie freigegebener Code-Default wird
    als ``"unapproved_code_default"`` mit SHA-256 deklariert und -- wenn ein
    ``reasoning``-Kanal uebergeben wird -- dort sichtbar gemacht. Die Zahlen
    selbst bleiben unveraendert.
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import (
        _asset_class_expected_metrics,
        _sub_asset_class_assumption_map,
        _sub_asset_class_metrics,
    )
    from services.portfolio_engine_cma import (
        _sub_asset_class_code_default_evidence,
    )

    returns, vols = _asset_class_expected_metrics(cma)
    assumption_map = _sub_asset_class_assumption_map(cma)
    code_defaults = _sub_asset_class_code_default_evidence(cma)
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
        entry = {
            "asset_class": asset_class,
            "sub_asset_class": sub_asset_class,
            "expected_return_bps": expected_return_bps,
            "expected_volatility_bps": expected_volatility_bps,
            "source": "CMA Sub-Asset-Class" if sub_asset_class in assumption_map else "Asset-Class fallback",
        }
        code_default = code_defaults.get(sub_asset_class)
        if code_default is not None:
            entry["source"] = "unapproved_code_default"
            entry["approval_status"] = "not_approved"
            entry["evidence_sha256"] = code_default["sha256"]
            if reasoning is not None:
                reasoning.append(
                    f"Sub-Anlageklasse {sub_asset_class}: Rendite/Volatilitaet "
                    "stammen aus einem Code-Default, nicht aus der genehmigten "
                    "CMA-Version (nicht freigegeben, Evidenz-Hash "
                    f"{code_default['sha256'][:12]})."
                )
        items.append(entry)
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
      weight_bps. Strategie-Sicht. None wenn keine Goals.
    - weakest_hard_score: min(score) ueber Goals mit hardness=Hart.
      Compliance-Sicht. None wenn keine harten Goals.

    Methodisch: Mandate haben oft heterogene Goals (PK-Pflicht vs.
    ueberobligatorisch vs. Reisefonds). Pure Aggregation maskiert harte
    Verfehlungen; daher beide Sichten parallel.

    GOAL-SCORE-001 (Kontrollrunde 2026-09-28,
    docs/audits/2026-09-21-stochastic-optimizer-monte-carlo-asset-
    allocation-and-goal-integrity-audit.md, Kontrollrunde 33):
    `item["weight_bps"]` kommt aus `_goal_weight()`, das den Hardness-
    Multiplier bereits einmal einpreist (Hart=2x, Opportunistisch=0.4x).
    Diese Funktion darf den Multiplier deshalb NICHT ein zweites Mal
    anwenden -- sonst wirkt Hardness quadratisch statt linear (Repro:
    weighted_score=96 statt korrekt 83 bei einem Hart/Opportunistisch-Paar
    mit identischem Basisgewicht). `weight_bps` wird hier daher direkt als
    effektives Gewicht verwendet; dieselbe Interpretation nutzt bereits die
    unabhaengige Frontend-Berechnung in 5eyes_v2.html (`scoreWeightTotal`).
    """
    if not goal_analysis:
        return {
            "weighted_score": None,
            "weakest_hard_score": None,
            "weakest_hard_goal_id": None,
            "method": "weighted_avg + weakest_hard_min",
        }

    # weighted: weight_bps ist bereits hardness-adjustiert (_goal_weight()).
    weighted_sum = 0.0
    weight_sum = 0.0
    for item in goal_analysis:
        score = float(item.get("achievement_score") or 0)
        effective_weight = max(0, int(item.get("weight_bps") or 0))
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
    # GOAL-CALENDAR-HORIZON-PARITY-001 (Pflichttest 6): fuer Stroeme ist der
    # Anker der BEGINN (erste Faelligkeit), wie im Solver
    # (goal_liabilities._resolve_target_year_index). Vorher stand hier das
    # Enddatum zuerst: eine Rente ab in 2 Jahren mit Ende in 25 Jahren galt
    # der Reserve als "in 25 Jahren faellig" und bekam keine Reserve.
    if _norm_text(goal.goal_type) in ("Wiederkehrende_Ausgabe", "Pensionsausgabe"):
        anchor = start_date or target_date
    else:
        anchor = target_date
    if anchor:
        # ADR-1a (Owner-Entscheid 2026-10-11): dieselbe Tage-Ceiling-Formel wie
        # im Wealth-Router, mit derselben Verzerrung -- an exakten Jahrestagen
        # ein Jahr zu lang (gemessen 97 % der runden Jahrestage). Beide rufen
        # jetzt die kanonische Kalenderanniversar-Funktion.
        return max(1, calendar_years_until(anchor))
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
    Sterbe-Zeitpunkt als Years-from-reference ab. Delegiert an
    services.mortality.horizon.expected_death_year_offset_from_mandate, der
    SELBEN Quelle, die seit dem Fix vom 2026-09-19 (Kontrollrunde Mortalitaet)
    auch der Solver-Pfad nutzt -- verhindert eine Divergenz zwischen dem, was
    im Report als Sterbe-Marker gezeigt wird, und dem, was die Simulation
    tatsaechlich als Horizont-Cutoff verwendet.

    - Priorität 1: life_expectancy_year (manuell gepflegt im Mandate)
    - Priorität 2: BFS-Default basierend auf client_birth_year + client_sex
                   (median life expectancy aus BFS_2020_2022) -- NUR fuer
                   CH-Mandate (siehe Jurisdiktions-Gate im Modul).
    - Sonst None (kein Cutoff)

    Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): BFS_2020_2022 ist eine Schweizer
    Sterbetafel. Fuer ein DE/AT-Mandat (mandate.jurisdiction != CH) haette
    sie das Sterbealter systematisch falsch geschaetzt und damit das
    Verzehr-/Depletion-Risiko in der Monte-Carlo-Simulation verzerrt. "Kein
    Cutoff" (konservativ, unbefristeter Horizont) bleibt die richtige Wahl
    statt einer falschen Zahl.

    Diese Report-/Anzeige-Stelle faengt Fehler weiterhin ab und faellt auf
    "kein Cutoff" zurueck (konservativ fuer eine reine Chart-Markierung) --
    der Solver-Pfad tut das NICHT mehr (fail-closed fuer ein aktiviertes,
    bereits validiertes Feature), siehe horizon.py-Docstring.

    MORT-CHANNEL-001 (Codex-Review PR #644, Vertrag 2): bei ausgeschalteter
    Mortalitaets-Simulation hat der Solver KEINEN Cutoff -- hier wurde
    trotzdem der BFS-Median angewandt (zwei Modelle fuer denselben
    Mandatszustand). Jetzt entscheidet ``resolve_mortality_cutoff`` einmal
    fuer alle Consumer: ``disabled`` -> None.
    """
    from services.mortality.horizon import resolve_mortality_cutoff
    try:
        return resolve_mortality_cutoff(mandate)[1]
    except Exception:
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
    advisory_path_series_rappen: list[int] | None = None,
    total_path_series_rappen: list[int] | None = None,
    reserve_ledger=None,
) -> list[dict]:
    """Sprint U-P5 Fix H12: expected_death_year_offset (Years from today)
    schneidet die contribution_series so dass keine Cashflows nach dem
    erwarteten Sterbejahr in den deterministischen projected_rappen einfliessen.
    Vorher: Goal-Analyse sah komplette Cashflow-Series ohne Mortality-Cutoff
    — AHV-Goal mit langer Laufzeit floss komplett in projected obwohl der
    Mandant statistisch in t=15 stirbt.

    RESERVE-FUNDING-LEDGER-001: ``advisory_wealth_rappen`` ist der
    investierbare Teil A - E. Mit ``reserve_ledger`` fliesst die externe
    Reserve gemaess Ledger-Release (dieselbe Serie wie Solver/MC) in die
    Projektion zurueck; der nicht freigegebene Rest bleibt als Bargeld
    Kundenvermoegen. Ohne Ledger: Altverhalten (nur A - E).
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import (
        _external_assets_inflation_value,
        _goal_probability_factor,
        _goal_reserve_for_goal,
        _goal_uses_total_scope,
        _norm_text,
    )

    analysis = []
    # #83 Gesamtvermoegen-Scope: externe Assets = Gesamt- minus Beratungsvermoegen.
    reserve_external = int(reserve_ledger.total_external_rappen) if reserve_ledger is not None else 0
    external_wealth_rappen = max(
        0, int(total_wealth_rappen or 0) - int(advisory_wealth_rappen or 0) - reserve_external
    )
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
        reserve_release = (
            reserve_ledger.release_prefix(projection_years) if reserve_ledger is not None
            else [0] * projection_years
        )
        projected_rappen = future_value_with_cashflow_series(
            investable_base,
            [int(value) + released for value, released in zip(contribution_series, reserve_release)],
            expected_return_bps,
        ) + max(0, reserve_external - sum(reserve_release))
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
            probability_factor = _goal_probability_factor(goal)
            target_rappen = int(round(
                _goal_target_wealth_rappen(goal, years, inflation_series_bps)
                * probability_factor
            ))
            # Total-scope reporting consumes the exact deterministic total
            # path already used by the visible projection. Expected-funding
            # semantics remain advisory + p * external versus p * target.
            if _goal_uses_total_scope(goal):
                exact_path_available = (
                    advisory_path_series_rappen is not None
                    and total_path_series_rappen is not None
                    and projection_years < len(advisory_path_series_rappen)
                    and projection_years < len(total_path_series_rappen)
                )
                if exact_path_available:
                    advisory_projected = int(
                        advisory_path_series_rappen[projection_years]
                    )
                    total_projected = int(
                        total_path_series_rappen[projection_years]
                    )
                    projected_rappen = int(round(
                        advisory_projected
                        + probability_factor
                        * (total_projected - advisory_projected)
                    ))
                else:
                    # Legacy/direct-call fallback. Production always supplies
                    # both deterministic paths.
                    projected_rappen += int(round(
                        _external_assets_inflation_value(
                            external_wealth_rappen,
                            projection_years,
                            inflation_series_bps,
                        )
                        * probability_factor
                    ))
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
        # Vorlaeufig (ohne Simulation keine Erfolgs-Wkt.); in Produktion ersetzt
        # _merge_goal_analysis_with_monte_carlo ihn (GOAL-STATUS-BY-SUCCESS-001).
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
                # Gewicht der Erfolgs-Wkt. gesamt wie im Bericht (AR-2): roh.
                "success_weight_bps": int(goal.weight_bps or 0),
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
    achievability: list[dict] | None = None,
) -> list[dict]:
    """Simulationswerte je Ziel einmischen und die Erfolgswahrscheinlichkeit
    samt Status setzen (GOAL-STATUS-BY-SUCCESS-001, CIO-Entscheid #667):
    kanonisch die priorisierte Optimizer-Evidenz (``achievability``), sonst
    ``success_rate_pct`` der Simulation als Schaetzung. ``path_success_rate_pct``
    bleibt der Simulationswert (SOLL/IST-Vergleich auf gleicher Basis)."""
    summaries = {
        item["goal_id"]: item
        for item in ((monte_carlo or {}).get(summaries_key) or [])
        if item.get("goal_id")
    }
    canonical = canonical_success_by_goal(achievability)
    merged = []
    for item in goal_analysis:
        summary = summaries.get(item.get("goal_id"))
        row = dict(item)
        if summary:
            row.update({
                "achievement_score": int(summary.get("score", item.get("achievement_score") or 0)),
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
            })
        probability = canonical.get(str(item.get("goal_id") or ""))
        source = SUCCESS_SOURCE_OPTIMIZER
        if probability is None and summary:
            probability = max(0.0, min(1.0, float(summary.get("success_rate_pct") or 0) / 100.0))
            source = SUCCESS_SOURCE_SIMULATION
        if probability is not None:
            pct = int(round(probability * 100))
            row.update({
                "success_probability": probability,
                "success_probability_pct": pct,
                "success_probability_source": source,
                "status": goal_status_from_success_pct(pct),
            })
        merged.append(row)
    return merged


def _stored_goal_achievability(allocation, *, log_invalid: bool = True) -> list[dict]:
    """Persistierte Optimizer-Evidenz (``goal_achievability_json``) als Liste."""
    raw = getattr(allocation, "goal_achievability_json", None)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        if log_invalid:
            logger.warning(
                "Stored goal_achievability_json invalid for allocation %s: %s",
                getattr(allocation, "id", "?"), exc,
            )
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


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


# ESG-THEME-EXCLUSION-EFFECTIVE-001 (Audit 2026-10-14): Klassifikation der
# sechs "Kontroverse Exposures"-Themen. Einzige Quelle fuer Filter
# (_product_matches_constraints), Score (_product_score), Run-Warnung und
# PDF-Text -- die Labels sind dieselben, die
# portfolio_engine_house_matrix._build_sub_allocations() fuer Overweight-
# Themenbausteine verwendet.
THEME_SUB_ASSET_CLASSES: dict[str, str] = {
    "fossil": "Thema Fossile Energie",
    "defense": "Thema Verteidigung",
    "tobacco": "Thema Tabak",
    "alcohol": "Thema Alkohol",
    "gaming": "Thema Gluecksspiel",
    "nuclear": "Thema Kernenergie",
}
THEME_DISPLAY_NAMES: dict[str, str] = {
    "fossil": "Fossile Energie",
    "defense": "Verteidigung",
    "tobacco": "Tabak",
    "alcohol": "Alkohol",
    "gaming": "Gluecksspiel",
    "nuclear": "Kernenergie",
}
_THEME_KEY_BY_SUB_ASSET_CLASS = {label: key for key, label in THEME_SUB_ASSET_CLASSES.items()}
SCREENING_TILT_MODES = frozenset({"exclude", "underweight"})
# ESG-PREMIUM-CRITERIA-001 (Owner-Entscheid 2026-10-14): vierter Zustand
# "allow" = "bewusst zulassen". Uebersteuert das Negativ-Screening fuer
# dieses Thema; Pflicht-Begruendung in prefs["tiltReasons"][theme] (siehe
# schemas/allocation.py::AllocationPreferencesPayload) und im
# Anlagestrategie-PDF als dokumentierte Abweichung ausgewiesen.
THEME_TILT_ALLOW = "allow"

# ESG-PREMIUM-CRITERIA-001, Stufe 3b: Look-through NUR fuer Fossile Energie.
# Fossile Energie ist (naeherungsweise) ein ganzer GICS-Sektor ("Energy",
# Schluesselschreibweise wie in services/product_exposures.py und in
# Product.sector_exposure_json). Tabak, Alkohol, Gluecksspiel, Verteidigung
# und Kernenergie sind Sub-Industrien innerhalb breiterer Sektoren (Consumer
# Staples, Consumer Discretionary, Industrials, Utilities) und aus der
# Sektor-Aufschluesselung NICHT ableitbar -- dafuer gibt es bewusst keinen
# Look-through (er waere erfunden). Schwelle 10 % (1000 bps, strikt groesser):
# breite Kernindizes liegen deutlich darunter (Welt ~4.5 %, Europa/EM ~6 %,
# Schweiz ~0.5 %), ein Energie-Sektor- oder Rohstoff-ETF deutlich
# darueber. Nur GEPFLEGTE Produktdaten zaehlen, nie der Sub-Klassen-Proxy aus
# services/product_exposures.py (das ist eine Schaetzung, keine Produktdaten).
FOSSIL_LOOK_THROUGH_SECTOR = "Energy"
FOSSIL_LOOK_THROUGH_THRESHOLD_BPS = 1000

# ESG-PREMIUM-CRITERIA-001, Stufe 2: unterscheidbare, datengetriebene
# Kriterien je ESG-Policy. Fehlende Daten -> Produkt fuer diese Policy NICHT
# zulaessig (fail-closed). Die GESAMTE Anlageklasse Liquiditaet bleibt
# ausgenommen (ESG_POLICY_EXEMPT_ASSET_CLASS) -- inkl. Geldmarktfonds, auch
# solche mit SFDR-Klassifikation.
# - best_in_class (CIO-Entscheid 2026-10-18, konservativ gegen
#   Greenwashing): nur die LEADER-Klasse der siebenstufigen Rating-Skala
#   AAA-CCC (Product.esg_rating). Die Skala teilt sich in Leader (AAA, AA),
#   Durchschnitt (A, BBB, BB) und Nachzuegler (B, CCC); "A" ist damit
#   Durchschnitt und KEIN Best-in-Class. Alternativ der numerische Score
#   Product.esg_score_x10 (Skala 0-1000 = 0.0-100.0, siehe models/review.py)
#   ab der Untergrenze der Leader-Klasse: auf der 0-10-Skala der
#   Rating-Systematik liegt AA ab 7.143 (= 10 * 5/7), also hier >= 714.
# - net_zero (CIO-Entscheide 2026-10-18): SFDR Art. 8 oder 9 UND
#   EU-Klima-Benchmark nach Verordnung (EU) 2019/2089 -- Paris-aligned
#   Benchmark (PAB) / Climate Transition Benchmark (CTB), Katalogfeld
#   Product.climate_benchmark. Beides PFLICHT: SFDR Art. 9 allein belegt
#   kein Netto-Null-Ziel, und ein Benchmark-Produkt nach SFDR Art. 6 (oder
#   ohne Klassifikation) ist keine Klima-Anlage im Sinne dieser Policy.
ESG_BEST_IN_CLASS_RATINGS: tuple[str, ...] = ("AAA", "AA")
ESG_BEST_IN_CLASS_MIN_SCORE_X10 = 714
CLIMATE_BENCHMARKS: tuple[str, ...] = ("PAB", "CTB")
ESG_POLICY_NAMES: dict[str, str] = {
    "esg_integration": "ESG-Integration",
    "best_in_class": "Best-in-Class",
    "impact": "Impact Investing",
    "net_zero": "Paris-aligned / Net Zero",
}
ESG_POLICY_CRITERIA: dict[str, str] = {
    "esg_integration": "nur Produkte nach SFDR Art. 8 oder 9",
    "best_in_class": (
        "nur Produkte nach SFDR Art. 8 oder 9 mit ESG-Rating AAA oder AA "
        "(Leader-Klasse der Rating-Skala AAA-CCC) oder ESG-Score von "
        "mindestens 71.4/100; Produkte ohne Rating/Score sind nicht zulaessig"
    ),
    "impact": "nur Produkte nach SFDR Art. 9",
    "net_zero": (
        "nur Produkte nach SFDR Art. 8 oder 9 mit EU-Klima-Benchmark PAB oder "
        "CTB (beides Pflicht); SFDR Art. 9 allein genuegt nicht"
    ),
}


# Self-Review 2026-10-18: die Liquiditaets-Ausnahme (siehe
# _product_matches_constraints) gehoert in jedes Kundendokument, das ein
# Kriterium nennt -- sonst behauptet "nur Produkte nach SFDR Art. 9" mehr, als
# die Engine umsetzt.
# CIO-Entscheid 2026-10-18 (Review C3, Dokument != Engine): der Text
# beschreibt EXAKT die Code-Bedingung -- ausgenommen ist die gesamte
# Anlageklasse (Product.asset_class, normalisiert), also auch Geldmarktfonds
# mit eigener SFDR-Klasse, nicht nur Konto/Festgeld ohne Klassifikation.
# Text und Bedingung teilen sich ESG_POLICY_EXEMPT_ASSET_CLASS.
ESG_POLICY_EXEMPT_ASSET_CLASS = "Liquiditaet"
ESG_POLICY_LIQUIDITY_EXEMPTION = (
    f"die gesamte Anlageklasse {ESG_POLICY_EXEMPT_ASSET_CLASS} (Konto, Festgeld "
    "und Geldmarktfonds, unabhaengig von deren SFDR-Klassifikation) ist vom "
    "Kriterium ausgenommen"
)


def esg_policy_criterion_label(policy: str | None) -> str | None:
    """BERATER-Label '<Name> (<exaktes Kriterium>)' fuer SFDR-gebundene
    Policies, sonst None. Nie in Kundendokumenten verwenden -- dort
    esg_policy_customer_label()."""
    if policy not in ESG_POLICY_CRITERIA:
        return None
    return f"{ESG_POLICY_NAMES[policy]} ({ESG_POLICY_CRITERIA[policy]})"


# CIO-Entscheid 2026-10-18 (ESG-Architektur-Review C3/H1): Kundendokumente
# nennen nur das technisch gepruefte KRITERIUM, nie einen Claim-Namen. Die
# Policy-Namen (ESG_POLICY_NAMES) behaupten mehr, als die Daten belegen
# ("Impact" = Wirkungsabsicht/-messung, "Best-in-Class" = Peer-Group-
# Vergleich, "Net Zero" = Netto-Null-Ziel, "ESG-Integration" = institutsseitige
# Risikointegration) -- geprueft wird jeweils nur ein Katalogfeld. Die
# Berater-UI darf Name + Kriterium zeigen. Diese Liste ist der Waechter fuer
# alle Kundentexte (Test: test_customer_documents_contain_no_esg_claim_labels).
ESG_CUSTOMER_CLAIM_LABELS: tuple[str, ...] = (
    "Impact",
    "Net Zero",
    "Net-Zero",
    "Netto-Null",
    "Paris-aligned",
    "Best-in-Class",
    "Best in Class",
    "ESG-Integration",
    "Nachhaltig",
)


def esg_policy_customer_label(policy: str | None) -> str | None:
    """KUNDEN-Label: nur das gepruefte Kriterium, ohne Policy-Namen."""
    if policy not in ESG_POLICY_CRITERIA:
        return None
    return f"Kriterium der Produktauswahl: {ESG_POLICY_CRITERIA[policy]}"


def product_meets_esg_policy(product, policy: str | None) -> bool:
    """ESG-PREMIUM-CRITERIA-001: prueft das Produkt gegen das Kriterium der
    ESG-Policy (ohne Liquiditaets-Ausnahme -- die liegt beim Aufrufer).
    Policies ohne Produktkriterium ("none", "negative_screening", None)
    lassen jedes Produkt zu."""
    if policy not in ESG_POLICY_CRITERIA:
        return True
    sfdr = str(getattr(product, "sfdr_class", None) or "").strip()
    if policy == "esg_integration":
        return sfdr in ("8", "9")
    if policy == "best_in_class":
        if sfdr not in ("8", "9"):
            return False
        rating = str(getattr(product, "esg_rating", None) or "").strip().upper()
        if rating in ESG_BEST_IN_CLASS_RATINGS:
            return True
        score = getattr(product, "esg_score_x10", None)
        return (
            isinstance(score, int)
            and not isinstance(score, bool)
            and score >= ESG_BEST_IN_CLASS_MIN_SCORE_X10
        )
    if policy == "impact":
        return sfdr == "9"
    if policy == "net_zero":
        benchmark = str(getattr(product, "climate_benchmark", None) or "").strip().upper()
        return sfdr in ("8", "9") and benchmark in CLIMATE_BENCHMARKS
    return False  # pragma: no cover -- alle Keys oben abgedeckt


def parse_theme_tags(raw) -> frozenset[str]:
    """Liest Product.theme_tags (JSON-Liste von Themen-Keys). Unbekannte Keys
    und kaputte Legacy-Werte klassifizieren nichts (neue Daten werden am
    Schema-Rand validiert, siehe schemas/review.py)."""
    if raw is None or raw == "":
        return frozenset()
    if isinstance(raw, (list, tuple, set, frozenset)):
        values = list(raw)
    else:
        try:
            values = json.loads(str(raw))
        except (TypeError, ValueError):
            logger.warning("Product.theme_tags ist kein gueltiges JSON: %r", raw)
            return frozenset()
        if not isinstance(values, list):
            return frozenset()
    return frozenset(
        str(value).strip() for value in values
        if str(value).strip() in THEME_SUB_ASSET_CLASSES
    )


def _maintained_energy_share_bps(product) -> int | None:
    """Gepflegter GICS-'Energy'-Anteil aus Product.sector_exposure_json, None
    wenn keine (gueltigen) Sektordaten gepflegt sind. Bewusst KEIN Proxy."""
    raw = getattr(product, "sector_exposure_json", None)
    if not raw:
        return None
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or not parsed:
        return None
    total = 0
    for key, value in parsed.items():
        if str(key).strip().lower() == FOSSIL_LOOK_THROUGH_SECTOR.lower():
            try:
                total += int(value)
            except (TypeError, ValueError):
                return None
    return total


def product_theme_keys(product) -> frozenset[str]:
    """ESG-PREMIUM-CRITERIA-001: alle Themen, denen das Produkt zugeordnet ist.

    1. eigene Sub-Anlageklasse "Thema X" (nicht der angefragte Slot),
    2. Katalogfeld theme_tags,
    3. Look-through Fossile Energie: gepflegter GICS-Sektoranteil "Energy"
       > FOSSIL_LOOK_THROUGH_THRESHOLD_BPS.
    """
    keys = set(parse_theme_tags(getattr(product, "theme_tags", None)))
    by_sub = product_theme_key(product)
    if by_sub:
        keys.add(by_sub)
    energy = _maintained_energy_share_bps(product)
    if energy is not None and energy > FOSSIL_LOOK_THROUGH_THRESHOLD_BPS:
        keys.add("fossil")
    return frozenset(keys)


def product_theme_key(product) -> str | None:
    """Themen-Key aus der eigenen Sub-Anlageklasse des Produkts (nicht aus dem
    angefragten Slot)."""
    return _THEME_KEY_BY_SUB_ASSET_CLASS.get(str(getattr(product, "sub_asset_class", None) or "").strip())


# THEME-MISSINGNESS-001 (CIO-Entscheid 2026-10-18, ESG-Review C4/F P0-5):
# fehlende Themenklassifikation gilt bei einem Themen-Ausschluss NICHT mehr
# als "nicht betroffen" (fail-closed). Ausgenommen: die Anlageklasse
# Liquiditaet (ESG_POLICY_EXEMPT_ASSET_CLASS) und kollektive Anlagen --
# dieselben Produkttypen, die "nur Fonds/ETFs" (fundsOnly) zulaesst. Fuer sie
# gilt die woertliche Offenlegung "breit diversifizierte Index- und
# Fondsprodukte werden nicht durchleuchtet" (theme_look_through_disclosure).
THEME_SCREENING_COLLECTIVE_PRODUCT_TYPES: tuple[str, ...] = ("ETF", "Fonds", "Immobilienfonds")


def _theme_tags_maintained(product) -> bool:
    """True, wenn theme_tags eine gueltige JSON-Liste ist (auch ``[]`` =
    bewusst "keinem Thema zugeordnet"). NULL/kaputt = nicht gepflegt."""
    raw = getattr(product, "theme_tags", None)
    if raw is None:
        return False
    if isinstance(raw, (list, tuple, set, frozenset)):
        return True
    try:
        return isinstance(json.loads(str(raw)), list)
    except (TypeError, ValueError):
        return False


def product_theme_classification_missing(product, screened_keys) -> bool:
    """THEME-MISSINGNESS-001: True, wenn das Produkt fuer mindestens ein
    gescreentes Thema NICHT klassifiziert ist und keine Ausnahme greift.

    Klassifiziert ist ein Produkt fuer Thema T, wenn
    - theme_tags gepflegt ist (gueltige Liste, auch leer), oder
    - seine Sub-Anlageklasse ein Themenbaustein "Thema X" ist, oder
    - T == fossil und gepflegte Sektordaten vorliegen (Look-through).
    """
    from services.portfolio_engine import _norm_text

    keys = set(screened_keys or ())
    if not keys:
        return False
    if _norm_text(getattr(product, "asset_class", None)) == ESG_POLICY_EXEMPT_ASSET_CLASS:
        return False
    if str(getattr(product, "product_type", None) or "").strip() in THEME_SCREENING_COLLECTIVE_PRODUCT_TYPES:
        return False
    if _theme_tags_maintained(product) or product_theme_key(product):
        return False
    if keys == {"fossil"} and _maintained_energy_share_bps(product) is not None:
        return False
    return True


def theme_classification_gap_hint(
    products: list, sub_asset_class: str, asset_class: str, prefs: dict, score_bucket: int,
    *, jurisdiction_ctx: dict | None = None,
) -> str | None:
    """Benennt, wenn ein Baustein NUR wegen fehlender Themenklassifikation
    unumsetzbar ist (gleicher Matcher, nur die Missingness-Regel aus)."""
    from services.portfolio_engine import _norm_text

    if not effective_theme_screening(prefs):
        return None
    blocked = [
        product for product in products
        if (
            str(product.sub_asset_class or "") == str(sub_asset_class)
            or _norm_text(product.asset_class) == _norm_text(asset_class)
        )
        and not _product_matches_constraints(product, prefs, score_bucket, jurisdiction_ctx=jurisdiction_ctx)
        and _product_matches_constraints(
            product, prefs, score_bucket, jurisdiction_ctx=jurisdiction_ctx,
            enforce_theme_classification=False,
        )
    ]
    if not blocked:
        return None
    names = ", ".join(sorted({str(p.product_name) for p in blocked})[:5])
    return (
        f"{len(blocked)} sonst zulaessige(s) Produkt(e) ohne Themen-Zuordnung "
        f"bei aktivem Themen-Ausschluss nicht verwendbar ({names})"
    )


def default_catalog_theme_tags(sub_asset_class: str | None) -> str | None:
    """ESG-PREMIUM-CRITERIA-001: Themenprodukte des Seed-Katalogs tragen ihren
    Themen-Tag explizit (gleiche Regel wie der Backfill in database.py /
    Alembic d7c3e9a2f5b1). Andere Produkte: NULL (= nicht gepflegt)."""
    key = _THEME_KEY_BY_SUB_ASSET_CLASS.get(str(sub_asset_class or "").strip())
    return json.dumps([key]) if key else None


def effective_theme_screening(prefs: dict | None) -> dict[str, str]:
    """ESG-THEME-EXCLUSION-EFFECTIVE-001: liefert {theme_key: mode} fuer alle
    Themen, deren Produkte NICHT empfohlen werden duerfen (mode "exclude"
    oder "underweight").

    Semantik:
    - "exclude": Themenprodukte werden nie ausgewaehlt -- weder in einem
      Themenbaustein noch als Ersatz/Fallback fuer einen anderen Slot.
    - "underweight": kein eigener Themenbaustein (ein solcher entsteht ohnehin
      nur bei "overweight") UND Themenprodukte werden nie als Ersatz/Fallback
      fuer einen anderen Slot ausgewaehlt. Produktwirkung damit identisch zu
      "exclude"; das abweichende Label bleibt im Dokument erhalten.
    - "neutral" (UI-Default) und "Key fehlt" sind gleichbedeutend: das Thema
      folgt der ESG-Policy, bei policy.esg == "negative_screening" also
      "exclude" (die Monolith-UI sendet immer alle sechs Tilts).
    - "allow" (ESG-PREMIUM-CRITERIA-001): bewusst zugelassen, uebersteuert
      das Negativ-Screening (dokumentierte Begruendung Pflicht, siehe
      theme_policy_deviations()). Ohne Negativ-Screening wie "neutral".
    - "overweight" uebersteuert das Negativ-Screening ebenfalls (bestehender
      Vertrag) und wird im PDF als Abweichung ausgewiesen.
    """
    prefs = prefs if isinstance(prefs, dict) else {}
    tilts = prefs.get("tilts") if isinstance(prefs.get("tilts"), dict) else {}
    policy = prefs.get("policy") if isinstance(prefs.get("policy"), dict) else {}
    negative_screening = policy.get("esg") == "negative_screening"
    screened: dict[str, str] = {}
    for key in THEME_SUB_ASSET_CLASSES:
        mode = tilts.get(key)
        if mode in (None, "neutral") and negative_screening:
            mode = "exclude"
        if mode in SCREENING_TILT_MODES:
            screened[key] = mode
    return screened


def theme_policy_deviations(prefs: dict | None) -> dict[str, dict]:
    """ESG-PREMIUM-CRITERIA-001: {theme_key: {"mode", "reason"}} fuer alle
    bewusst getroffenen Abweichungen vom Themen-Ausschluss:
    - "allow" immer (Begruendung ist Pflicht, Schema-validiert),
    - "overweight" nur, wenn die ESG-Policy Negativ-Screening ist (dann
      weicht der Tilt vom Policy-Ausschluss ab). Eine Begruendung ist hier
      optional, damit bereits persistierte Praeferenzen gueltig bleiben."""
    prefs = prefs if isinstance(prefs, dict) else {}
    tilts = prefs.get("tilts") if isinstance(prefs.get("tilts"), dict) else {}
    policy = prefs.get("policy") if isinstance(prefs.get("policy"), dict) else {}
    reasons = prefs.get("tiltReasons") if isinstance(prefs.get("tiltReasons"), dict) else {}
    negative_screening = policy.get("esg") == "negative_screening"
    deviations: dict[str, dict] = {}
    for key in THEME_SUB_ASSET_CLASSES:
        mode = tilts.get(key)
        if mode == THEME_TILT_ALLOW or (mode == "overweight" and negative_screening):
            reason = reasons.get(key)
            deviations[key] = {
                "mode": mode,
                "reason": reason.strip() if isinstance(reason, str) and reason.strip() else None,
            }
    return deviations


def theme_look_through_disclosure(theme_keys) -> str:
    """Themenspezifische Offenlegung, was der Themenfilter erfasst."""
    selected = set(theme_keys or ())
    keys = [key for key in THEME_SUB_ASSET_CLASSES if key in selected]
    parts = []
    if "fossil" in keys:
        parts.append(
            "Fossile Energie: Themenprodukte sowie Fonds mit Energie-Sektoranteil > 10 % "
            "(GICS 'Energy' gemaess gepflegter Sektor-Aufschluesselung) ausgeschlossen "
            "(Look-through); Produkte ohne gepflegte Sektordaten werden nicht durchleuchtet."
        )
    others = [THEME_DISPLAY_NAMES[key] for key in keys if key != "fossil"]
    if others:
        parts.append(
            ", ".join(others) + ": nur als Themenprodukt klassifizierte Produkte "
            "(Sub-Anlageklasse 'Thema ...' oder Themen-Tag im Produktkatalog); kein "
            "Look-through, da diese Themen Sub-Industrien und aus Sektordaten nicht "
            "ableitbar sind -- breit diversifizierte Index- und Fondsprodukte werden "
            "nicht durchleuchtet und koennen Titel dieser Themen enthalten."
        )
    if parts:
        # THEME-MISSINGNESS-001: die fail-closed-Regel gehoert in den Text.
        parts.append(
            "Andere Produkte (z.B. Einzeltitel) ohne Themen-Zuordnung im "
            "Produktkatalog werden nicht ausgewaehlt."
        )
    return " ".join(parts)


def theme_screening_disclosure(prefs: dict | None) -> str | None:
    """Run-Warnung/Offenlegung, sobald mindestens ein Thema gescreent wird
    oder bewusst vom Themen-Ausschluss abgewichen wurde."""
    screened = effective_theme_screening(prefs)
    deviations = theme_policy_deviations(prefs)
    if not screened and not deviations:
        return None
    sentences = []
    if screened:
        parts = [
            f"{THEME_DISPLAY_NAMES[key]} ({'ausgeschlossen' if mode == 'exclude' else 'untergewichtet'})"
            for key, mode in screened.items()
        ]
        sentences.append(
            "Themen-Screening aktiv: " + ", ".join(parts) + ". Ausgeschlossene und "
            "untergewichtete Themen werden weder als Themenbaustein noch als Ersatz "
            "fuer einen anderen Baustein umgesetzt. " + theme_look_through_disclosure(screened)
        )
    if deviations:
        labels = [
            THEME_DISPLAY_NAMES[key]
            + (" bewusst zugelassen" if item["mode"] == THEME_TILT_ALLOW else " uebergewichtet")
            for key, item in deviations.items()
        ]
        sentences.append(
            "Dokumentierte Abweichung vom Themen-Ausschluss: " + ", ".join(labels) + "."
        )
    return " ".join(sentences)


def esg_policy_gap_hint(
    products: list,
    sub_asset_class: str,
    asset_class: str,
    prefs: dict,
    score_bucket: int,
    *,
    jurisdiction_ctx: dict | None = None,
) -> str | None:
    """ESG-PREMIUM-CRITERIA-001: erklaert, wenn das ESG-Policy-Kriterium der
    Grund ist, dass ein Slot leer bleibt -- nennt das exakte Kriterium und
    wie viele sonst zulaessige Produkte der Sub-Anlage- bzw. Anlageklasse es
    erfuellen. None, wenn keine SFDR-gebundene Policy aktiv ist oder es
    ohnehin keine sonst zulaessigen Produkte gibt (reine Katalogluecke)."""
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _norm_text

    prefs = prefs if isinstance(prefs, dict) else {}
    policy_prefs = prefs.get("policy") if isinstance(prefs.get("policy"), dict) else {}
    policy = policy_prefs.get("esg")
    if policy not in ESG_POLICY_CRITERIA:
        return None
    relaxed = {**prefs, "policy": {**policy_prefs, "esg": "none"}}
    otherwise_ok = [
        product for product in products
        if _product_matches_constraints(product, relaxed, score_bucket, jurisdiction_ctx=jurisdiction_ctx)
    ]
    in_sub = [p for p in otherwise_ok if str(p.sub_asset_class or "") == str(sub_asset_class)]
    in_class = [p for p in otherwise_ok if _norm_text(p.asset_class) == _norm_text(asset_class)]
    sub_ok = sum(1 for p in in_sub if product_meets_esg_policy(p, policy))
    class_ok = sum(1 for p in in_class if product_meets_esg_policy(p, policy))
    # Das Kriterium ist nur dann DER Grund, wenn es sonst zulaessige Produkte
    # der exakten Sub-Anlageklasse ausschliesst -- oder, falls es dort gar
    # keine gibt, den Anlageklassen-Ersatz vollstaendig verhindert.
    blocks_exact = bool(in_sub) and sub_ok == 0
    blocks_fallback = not in_sub and bool(in_class) and class_ok == 0
    if not (blocks_exact or blocks_fallback):
        return None
    return (
        f"ESG-Kriterium {esg_policy_criterion_label(policy)} erfuellt von "
        f"{sub_ok} von {len(in_sub)} Produkten der Sub-Anlageklasse {sub_asset_class}, "
        f"die alle uebrigen Mandatsrestriktionen erfuellen, und {class_ok} von "
        f"{len(in_class)} der Anlageklasse {asset_class}"
    )


def _product_matches_constraints(
    product: Product,
    prefs: dict,
    score_bucket: int,
    *,
    jurisdiction_ctx: dict | None = None,
    enforce_theme_classification: bool = True,
) -> bool:
    """WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): jurisdiction_ctx (siehe
    _resolve_jurisdiction_context()) parametrisiert die chf_only-/Hedging-
    Pruefungen ueber home_currency statt hartcodiertem "CHF". Ohne
    jurisdiction_ctx (z.B. bestehende Aufrufer/Tests) wird
    _CH_JURISDICTION_CONTEXT verwendet -- home_currency="CHF", exakt das
    bisherige Verhalten (Constraint 1: CH-Pfad byte-identisch).

    CERT-PRODUCT-ELIGIBILITY-001 (2026-10-09, Schritt 6/7): dieser Filter
    deckt ausschliesslich Anlagepraeferenzen ab (Universum, ESG, Hedging,
    Leverage/Derivate/Struktur, CHF-only) -- NIE Eignung/Suitability. Die
    fruehere score_bucket-/ProductSuitability-Pruefung und der
    ignore_suitability-Relaxation-Pfad (Produktionsentscheid komplett ohne
    Eignungspruefung) wurden entfernt und durch den zentralen, fail-closed
    services.product_eligibility.evaluate_product_eligibility()-Kern
    ersetzt -- siehe _eligible_candidates_for_generate() in
    services/portfolio_engine.py, der diese Funktion UND den governed-rule-
    Kern kombiniert aufruft. Ein hier "True" zurueckgegebenes Produkt ist
    NICHT automatisch empfehlbar -- es hat lediglich die Praeferenzfilter
    bestanden."""
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
    # ESG-POLICY-PARTIAL-NOOP-001 (Kontrollrunde 2026-09-27): "esg_integration"
    # war im Schema (schemas/allocation.py _VALID_POLICY_VALUES["esg"]) ein
    # gueltiger, im PDF sichtbarer Wert, hatte hier aber KEINE Wirkung -- ein
    # Berater, der ihn waehlte, bekam ein Dokument, das eine Umsetzung
    # behauptet, die die Engine nicht vornahm. "ESG-Integration" (Beruecks-
    # ichtigung von E/S-Merkmalen ohne volles Impact-Mandat) ist inhaltlich
    # am naechsten an SFDR Art. 8 -- behandelt wie die bestehenden drei Werte,
    # die bereits identisch auf denselben SFDR-8/9-Gate abgebildet sind.
    # ESG-THEME-EXCLUSION-EFFECTIVE-001 (Audit 2026-10-14): harter Filter auf
    # der Produkt-Klassifikation. Vorher nur ein Score-Malus, der am
    # angefragten SLOT hing -- ein ausgeschlossenes Themenprodukt wurde als
    # Anlageklassen-Fallback fuer z.B. "Aktien Global" normal ausgewaehlt
    # (live reproduziert: fossil=exclude -> 60% "Energy Select Sector ETF").
    # Weil dieser Filter VOR exact- und Fallback-Kandidatenbildung in
    # generate_recommendation_run() greift, gilt er fuer jeden Slot; ein Slot
    # ohne verbleibendes Produkt laeuft in den bestehenden fail-closed-Pfad
    # (missing_sub_classes -> ValueError "Produktselektion unvollstaendig").
    # ESG-PREMIUM-CRITERIA-001: Themen-Zuordnung zweistufig (Sub-Anlageklasse
    # / theme_tags + Fossil-Look-through ueber gepflegte Sektordaten), siehe
    # product_theme_keys().
    screened = effective_theme_screening(prefs)
    if screened and not screened.keys().isdisjoint(product_theme_keys(product)):
        return False
    # THEME-MISSINGNESS-001: fehlende Klassifikation != "nicht betroffen".
    # enforce_theme_classification=False nur fuer den Diagnose-Hinweis.
    if enforce_theme_classification and screened and product_theme_classification_missing(product, screened):
        return False
    # ESG-PREMIUM-CRITERIA-001 (Owner-Entscheid 2026-10-14): jede SFDR-
    # gebundene Policy hat jetzt ihr EIGENES, datengetriebenes Kriterium
    # (vorher bildeten alle vier identisch auf SFDR 8/9 ab -- "Impact" und
    # "Net Zero" versprachen damit mehr, als die Engine pruefte). Siehe
    # ESG_POLICY_CRITERIA / product_meets_esg_policy().
    if asset_class != ESG_POLICY_EXEMPT_ASSET_CLASS and not product_meets_esg_policy(product, policy_prefs.get("esg")):
        return False
    return True


def _suitability_block_hint(
    products: list[Product],
    sub_asset_class: str,
    prefs: dict,
    score_bucket: int,
    *,
    jurisdiction_ctx: dict | None = None,
) -> str | None:
    """Erklaert dem Berater, WARUM eine exakte Sub-Anlageklasse nicht umgesetzt
    wurde, wenn der Grund die Eignungspruefung ist (statt einer echten
    Katalogluecke): existiert ein Produkt fuer diese Sub-Anlageklasse, das nur
    an score_bucket scheitert, wird das dafuer benoetigte Mindest-Risikoprofil
    (Bucket + Score) genannt, damit gezielt ein dokumentierter
    Risikoprofil-Override (siehe _risk_assessment_has_documented_override)
    erwogen werden kann -- statt einer nichtssagenden "kein Produkt
    verfuegbar"-Meldung. Reine Katalogluecken (kein Produkt existiert
    ueberhaupt fuer diese Sub-Anlageklasse) liefern None."""
    candidates = [
        product for product in products
        if str(product.sub_asset_class or "") == str(sub_asset_class)
        and _product_matches_constraints(
            product, prefs, score_bucket, jurisdiction_ctx=jurisdiction_ctx,
        )
    ]
    required_buckets = [
        min(
            int(rule.profile_from or 1)
            for rule in product.suitability
            if int(rule.advisory_allowed or 0) == 1
        )
        for product in candidates
        if any(int(rule.advisory_allowed or 0) == 1 for rule in product.suitability)
    ]
    required_buckets = [bucket for bucket in required_buckets if bucket > score_bucket]
    if not required_buckets:
        return None
    required_bucket = min(required_buckets)
    required_score = max(0, required_bucket * 10 - 5)
    return (
        f"Passendes Produkt im Katalog vorhanden, aber ausserhalb des zugelassenen "
        f"Risikoprofil-Bands (aktuell Bucket {score_bucket}, benoetigt mind. Bucket "
        f"{required_bucket}). Nur mit dokumentiertem Risikoprofil-Override "
        f"(Score >= {required_score}) umsetzbar."
    )


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
    # ESG-THEME-EXCLUSION-EFFECTIVE-001 (Audit 2026-10-14): Ausschluss /
    # Untergewichtung haengt an der EIGENEN Sub-Anlageklasse des Produkts
    # (gleiche Regel wie der harte Filter in _product_matches_constraints;
    # hier nur Defense in Depth fuer Aufrufer, die den Filter umgehen).
    # Vorher hing er am angefragten Slot und war damit unerreichbar, weil ein
    # Slot "Thema X" nur bei "overweight" existiert. Siehe
    # effective_theme_screening() fuer die negative_screening-Semantik.
    screened = effective_theme_screening(prefs)
    if screened and not screened.keys().isdisjoint(product_theme_keys(product)):
        return -10000
    # Der Overweight-Bonus bleibt bewusst SLOT-gebunden: nur im eigenen
    # Themenbaustein "Thema X" bevorzugt, nie als Ersatz fuer einen
    # Kernbaustein hochgestuft.
    slot_theme = _THEME_KEY_BY_SUB_ASSET_CLASS.get(str(sub_asset_class or ""))
    if slot_theme and tilts.get(slot_theme) == "overweight":
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


def _tenant_visible_products_query(db: Session, mandate: Mandate):
    """REC-001 (Codex-Audit, Empfehlungsgenerator ohne Tenant-Filter): der
    Produktkandidaten-Pool fuer generate_recommendation_run() wurde bisher
    OHNE jeden Tenant-Filter geladen (`db.query(Product).filter(deleted_at,
    is_active)`) -- ein privates Produkt eines FREMDEN Tenants (Product.
    tenant_id gesetzt, siehe models/review.py::Product.tenant_id-Docstring:
    NULL=globaler/geteilter Katalog, gesetzt=privat fuer GENAU diesen
    Tenant) konnte dadurch in die Empfehlung eines Mandats einfliessen, das
    gar nicht zu diesem Tenant gehoert. _filter_products_by_universe()
    direkt darunter schuetzt davor NICHT zuverlaessig: ohne kuratierte
    ProductUniverseEntry-Positivliste (der Normalfall, u.a. Tier-1) filtert
    sie nur nach Jurisdiktion, nicht nach Tenant.

    Dies ist dieselbe Filterlogik wie routers/review.py::
    _active_products_query() (dort der kanonische Produktresolver fuer
    Listen-/Such-Endpunkte) -- services/*.py importiert bewusst NICHT aus
    routers/*.py (Layering-Konvention dieser Codebase), daher hier dupliziert
    statt importiert. tenant_id wird -- wie in _filter_products_by_universe()
    -- vom MANDAT aufgeloest (nicht vom aufrufenden User: ein
    Empfehlungslauf ist an ein Mandat/einen Kunden gebunden, nicht an den
    Tenant des ausfuehrenden Beraters), mit demselben DEFAULT_TENANT_ID-
    Fallback bei NULL.

    Tier-1 (Bestand hat durchweg Product.tenant_id NULL) bleibt dadurch
    BYTE-IDENTISCH: ein NULL-Produkt matcht `Product.tenant_id.is_(None)`
    unabhaengig davon, worauf tenant_id aufgeloest wird."""
    from models.tenant import DEFAULT_TENANT_ID
    tenant_id = getattr(mandate, "tenant_id", None) or DEFAULT_TENANT_ID
    return db.query(Product).filter(
        Product.deleted_at.is_(None),
        Product.is_active == 1,
        (Product.tenant_id.is_(None)) | (Product.tenant_id == tenant_id),
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
