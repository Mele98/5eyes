"""Abnahmenetz G2: Risikofragebogen und Scoring je Jurisdiktion eingefroren.

Laenderpaket-Schritt X0 (nur Tests). Spaetere Schritte (X5: Fragebogen als
Daten, Scoring ueber das Laenderpaket) muessen diese Basiswerte unveraendert
lassen; jede Abweichung ist eine fachliche Verhaltensaenderung.

1. Definition: alle Fragen, Antwortoptionen, Punkte, Horizont-Kanonisierung,
   Matrix, Profilbaender und die davon abhaengigen Kopien (PDF-Fragenkatalog,
   Plausibilisierungsbaender, Strategie-Readiness) als kanonisches JSON plus
   Hash. Heute gibt es genau einen Fragebogen; er gilt fuer jede Jurisdiktion
   (Basiswert unter dem Schluessel ``CH``).
2. Exhaustive Scoring-Tabelle: ``compute_scores`` ueber den gesamten
   API-Definitionsbereich (Einkommen 0-4, Verpflichtungen 0-4, Sparen 0-12,
   Vermoegen 0-12, 13 Horizont-Labels, 3x Bereitschaft 1-4) und FZK an/aus =
   7'030'400 Faelle als ein Hash.
3. Frontend-erreichbare Teilmenge (240'000 Options-Kombinationen): Hash plus
   lesbare Punktetabelle (CSV) je (Faehigkeits-Summe, Horizont,
   Bereitschafts-Summe).
"""
from __future__ import annotations

import csv
import hashlib
import io
import itertools
import sys
import typing
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services import risk_capacity_plausibility as rcp  # noqa: E402
from services import risk_questionnaire_integrity as rqi  # noqa: E402
from services import risk_scoring as rs  # noqa: E402
from services.risk_scoring import compute_scores, profile_for_score_x10  # noqa: E402
from tests.acceptance_net_support import (  # noqa: E402
    assert_matches_baseline,
    baseline_path,
    digest,
    update_mode,
)

JURISDICTION = "CH"
POINTS_CSV = "risk_scoring_ch_points.csv"
FZK_CAP_X10 = 75

_POINT_RANGES = {
    "q_income_points": range(0, 5),
    "q_obligations_points": range(0, 5),
    "q_savings_points": range(0, 13),
    "q_wealth_points": range(0, 13),
    "q_investment_goal_points": range(1, 5),
    "q_risk_preference_points": range(1, 5),
    "q_risk_behavior_points": range(1, 5),
}


def _api_horizon_labels() -> list[str]:
    from schemas.profiling import RiskAssessmentCreate

    annotation = RiskAssessmentCreate.model_fields["investment_horizon_label"].annotation
    return list(typing.get_args(annotation))


def _bands(mapping: dict) -> list:
    return [[lo, hi, name] for (lo, hi), name in mapping.items()]


def _questionnaire_definition() -> dict:
    from services import portfolio_engine as pe
    from services.pdf.components import eignungspruefung as ep

    return {
        "questions_required": list(rqi.REQUIRED_QUESTIONS),
        "options": {str(q): list(v) for q, v in rqi.STANDARD_OPTIONS.items()},
        "points": {str(q): list(v) for q, v in rqi.STANDARD_POINTS.items()},
        "point_fields": {str(q): v for q, v in rqi.POINT_FIELD_BY_QUESTION.items()},
        "horizon_options": list(rqi.HORIZON_OPTIONS),
        "income_source_options": list(rqi.INCOME_SOURCE_OPTIONS),
        "no_income_source": rqi.NO_INCOME_SOURCE,
        "unscored_prefix": {str(q): v for q, v in rqi.UNSCORED_PREFIX.items()},
        "nonstandard_placeholder_labels": list(rqi.NONSTANDARD_PLACEHOLDER_LABELS),
        "nonstandard_source_markers": sorted(rqi.NONSTANDARD_SOURCE_MARKERS),
        "api_horizon_labels": _api_horizon_labels(),
        "horizon_years": dict(rs.HORIZON_YEARS),
        "canonical_horizon_labels": dict(rs.CANONICAL_HORIZON_LABELS),
        "capacity_total_to_profile": _bands(rs.CAPACITY_TOTAL_TO_PROFILE),
        "capacity_band": dict(rs.CAPACITY_BAND),
        "horizon_capacity_matrix": [[h, c, v] for (h, c), v in rs.HORIZON_CAPACITY_MATRIX.items()],
        "willingness_score_to_profile": _bands(rs.WILLINGNESS_SCORE_TO_PROFILE),
        "score_to_profile": _bands(rs.SCORE_TO_PROFILE),
        "pdf_section_order": list(ep.SECTION_ORDER),
        "pdf_question_catalog": {str(q): list(v) for q, v in ep.QUESTION_CATALOG.items()},
        "plausibility": {
            "income_bands_chf_month": [list(b) for b in rcp.INCOME_BANDS_CHF_MONTH],
            "obligation_bands_chf_month": [list(b) for b in rcp.OBLIGATION_BANDS_CHF_MONTH],
            "free_wealth_bands_chf": [list(b) for b in rcp.FREE_WEALTH_BANDS_CHF],
            "savings_rate_bands_pct": [list(b) for b in rcp.SAVINGS_RATE_BANDS_PCT],
            "income_points": list(rcp.INCOME_POINTS),
            "obligation_points": list(rcp.OBLIGATION_POINTS),
            "wealth_points": list(rcp.WEALTH_POINTS),
            "savings_points": list(rcp.SAVINGS_POINTS),
        },
        "readiness": {
            "required_questions": sorted(pe._REQUIRED_RISK_QUESTION_NUMBERS_FOR_STRATEGY),
            "answer_points": {str(q): sorted(v) for q, v in pe._CURRENT_RISK_ANSWER_POINTS.items()},
            "horizon_labels": list(pe._CURRENT_RISK_HORIZON_LABELS),
        },
    }


def _validation_domain() -> dict:
    """Wertebereich, den ``compute_scores`` akzeptiert (aus dem Verhalten
    ermittelt, nicht abgeschrieben)."""
    base = {name: rng.start for name, rng in _POINT_RANGES.items()}
    domain = {}
    for name in _POINT_RANGES:
        accepted = []
        for value in range(-2, 16):
            try:
                compute_scores(**{**base, name: value}, investment_horizon_label="Bis 2 Jahre")
            except ValueError:
                continue
            accepted.append(value)
        domain[name] = [min(accepted), max(accepted), len(accepted)]
    return domain


def _row(result) -> str:
    return (
        f"{result.risk_capacity_total},{result.risk_capacity_profile},{result.risk_capacity_score_x10},"
        f"{result.risk_willingness_total},{result.risk_willingness_profile},{result.risk_willingness_score_x10},"
        f"{result.final_score_x10},{result.final_profile}"
    )


def _fzk(result) -> str:
    # Wie routers/profiling.py::create_risk_assessment fuer mandate_type FZK.
    final = result.final_score_x10
    if final > FZK_CAP_X10:
        return f"{FZK_CAP_X10},{profile_for_score_x10(FZK_CAP_X10)}"
    return f"{final},{result.final_profile}"


def test_questionnaire_definition_matches_baseline():
    definition = _questionnaire_definition()
    definition["compute_scores_domain"] = _validation_domain()
    assert_matches_baseline(f"risk_questionnaire_{JURISDICTION.lower()}.json", {
        "jurisdiction": JURISDICTION,
        "definition": definition,
        "definition_sha256": digest(definition),
    })


def test_exhaustive_scoring_table_matches_baseline():
    labels = sorted(_api_horizon_labels())
    assert sorted(rs.HORIZON_YEARS) == labels, "API-Horizont-Labels und Scoring-Tabelle laufen auseinander"
    table_hash = hashlib.sha256()
    cases = 0
    for inc, obl, sav, wea in itertools.product(
        _POINT_RANGES["q_income_points"], _POINT_RANGES["q_obligations_points"],
        _POINT_RANGES["q_savings_points"], _POINT_RANGES["q_wealth_points"],
    ):
        lines = []
        for label in labels:
            for goal, pref, beh in itertools.product(range(1, 5), repeat=3):
                result = compute_scores(
                    q_income_points=inc, q_obligations_points=obl, q_savings_points=sav,
                    q_wealth_points=wea, investment_horizon_label=label,
                    q_investment_goal_points=goal, q_risk_preference_points=pref,
                    q_risk_behavior_points=beh,
                )
                key = f"{inc},{obl},{sav},{wea},{label},{goal},{pref},{beh}"
                lines.append(f"{key},0|{_row(result)}\n{key},1|{_fzk(result)}\n")
                cases += 2
        table_hash.update("".join(lines).encode("utf-8"))
    assert cases == 7_030_400
    assert_matches_baseline(f"risk_scoring_{JURISDICTION.lower()}.json", {
        "jurisdiction": JURISDICTION,
        "exhaustive_cases": cases,
        "exhaustive_sha256": table_hash.hexdigest(),
        "frontend_reachable": _frontend_reachable_summary(),
    })


def _frontend_reachable_rows() -> tuple[int, str, dict]:
    pts = rqi.STANDARD_POINTS
    rows_hash = hashlib.sha256()
    table: dict[tuple, tuple] = {}
    count = 0
    for idx in itertools.product(
        range(len(pts[3])), range(len(pts[5])), range(len(pts[6])), range(len(pts[7])),
        range(len(rqi.HORIZON_OPTIONS)), range(len(pts[9])), range(len(pts[10])), range(len(pts[11])),
    ):
        inc, obl, wea, sav = pts[3][idx[0]], pts[5][idx[1]], pts[6][idx[2]], pts[7][idx[3]]
        label = rqi.HORIZON_OPTIONS[idx[4]]
        goal, pref, beh = pts[9][idx[5]], pts[10][idx[6]], pts[11][idx[7]]
        result = compute_scores(
            q_income_points=inc, q_obligations_points=obl, q_savings_points=sav,
            q_wealth_points=wea, investment_horizon_label=label,
            q_investment_goal_points=goal, q_risk_preference_points=pref,
            q_risk_behavior_points=beh,
        )
        row = (
            result.risk_capacity_profile, result.risk_capacity_score_x10,
            result.risk_willingness_profile, result.risk_willingness_score_x10,
            result.final_score_x10, result.final_profile, _fzk(result),
        )
        rows_hash.update((",".join(map(str, idx)) + "|" + _row(result) + "|" + _fzk(result) + "\n").encode("utf-8"))
        key = (result.risk_capacity_total, label, result.risk_willingness_total)
        assert table.setdefault(key, row) == row, f"Punktetabelle nicht eindeutig fuer {key}"
        count += 1
    return count, rows_hash.hexdigest(), table


def _points_csv(table: dict) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([
        "capacity_total", "horizon_label", "willingness_total", "capacity_profile",
        "capacity_score_x10", "willingness_profile", "willingness_score_x10",
        "final_score_x10", "final_profile", "fzk_final_score_x10", "fzk_final_profile",
    ])
    order = {label: i for i, label in enumerate(rqi.HORIZON_OPTIONS)}
    for (cap, label, will), row in sorted(table.items(), key=lambda kv: (kv[0][0], order[kv[0][1]], kv[0][2])):
        fzk_score, fzk_profile = row[6].split(",")
        writer.writerow([cap, label, will, *row[:6], fzk_score, fzk_profile])
    return out.getvalue()


_FE_CACHE: dict = {}


def _frontend_reachable_summary() -> dict:
    if not _FE_CACHE:
        count, sha, table = _frontend_reachable_rows()
        _FE_CACHE.update(count=count, sha=sha, csv=_points_csv(table))
    csv_text = _FE_CACHE["csv"]
    return {
        "cases": _FE_CACHE["count"],
        "sha256": _FE_CACHE["sha"],
        "points_table_rows": csv_text.count("\n") - 1,
        "points_table_sha256": hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
    }


def test_frontend_reachable_points_table_matches_csv_baseline():
    summary = _frontend_reachable_summary()
    assert summary["cases"] == 240_000
    path = baseline_path(POINTS_CSV)
    csv_text = _FE_CACHE["csv"]
    if update_mode():
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(csv_text)
        return
    expected = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if expected != csv_text:
        exp_lines, act_lines = expected.splitlines(), csv_text.splitlines()
        changed = [
            f"Zeile {i + 1}: {e!r} -> {a!r}"
            for i, (e, a) in enumerate(zip(exp_lines, act_lines)) if e != a
        ]
        raise AssertionError(
            f"Punktetabelle weicht ab ({len(exp_lines)} -> {len(act_lines)} Zeilen): " + "; ".join(changed[:20])
        )
