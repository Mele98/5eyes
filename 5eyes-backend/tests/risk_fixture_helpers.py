from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from models.profiling import RiskAssessmentAnswer
from services.risk_scoring import HORIZON_YEARS, canonicalize_horizon_label, compute_scores


CURRENT_RISK_SCHEMA_MARKERS = {
    "knowledge_services_json": "{}",
    "knowledge_instruments_json": "{}",
    "income_sources_json": '["Berufliche Taetigkeit"]',
}


CURRENT_RISK_ANSWERS = [
    (1, "Finanzdienstleistungen: Beratung und Verwaltung", 0),
    (2, "Finanzinstrumente: Anlagefonds und ETFs", 0),
    (3, "CHF 12'000 bis 20'000", 3),
    (4, "Herkunft: Berufliche Taetigkeit", 0),
    (5, "CHF 3'000 bis 5'000", 3),
    (6, "CHF 1'000'000 bis 2'000'000", 9),
    (7, "25 bis 50 %", 9),
    (8, "Mehr als 12 Jahre - Matrix-Faktor", 0),
    (9, "Das investierte Kapital soll sich stetig vermehren.", 3),
    (10, "Ich strebe eine hoehere Rendite an und bin bereit, dafuer ein erhoehtes Risiko einzugehen.", 3),
    (11, "Ich kann den Verlust voruebergehend akzeptieren und halte an meinen Anlagen fest.", 3),
]


def derive_current_risk_fields(
    *,
    q_income_points: int,
    q_obligations_points: int,
    q_savings_points: int,
    q_wealth_points: int,
    investment_horizon_label: str,
    q_investment_goal_points: int,
    q_risk_preference_points: int,
    q_risk_behavior_points: int,
) -> dict[str, int | str]:
    """Build a self-consistent persisted risk fixture from source answers."""

    canonical_horizon = canonicalize_horizon_label(investment_horizon_label)
    if canonical_horizon not in HORIZON_YEARS:
        raise ValueError(
            f"Test-Fixture verwendet keinen kanonischen Horizon: {investment_horizon_label!r}"
        )
    source = {
        "q_income_points": q_income_points,
        "q_obligations_points": q_obligations_points,
        "q_savings_points": q_savings_points,
        "q_wealth_points": q_wealth_points,
        "investment_horizon_label": canonical_horizon,
        "q_investment_goal_points": q_investment_goal_points,
        "q_risk_preference_points": q_risk_preference_points,
        "q_risk_behavior_points": q_risk_behavior_points,
    }
    scores = compute_scores(**source)
    return {
        **source,
        "investment_horizon_years": HORIZON_YEARS[canonical_horizon],
        "risk_capacity_total": scores.risk_capacity_total,
        "risk_capacity_profile": scores.risk_capacity_profile,
        "risk_capacity_score_x10": scores.risk_capacity_score_x10,
        "risk_willingness_total": scores.risk_willingness_total,
        "risk_willingness_profile": scores.risk_willingness_profile,
        "risk_willingness_score_x10": scores.risk_willingness_score_x10,
        "final_score_x10": scores.final_score_x10,
        "final_profile": scores.final_profile,
    }


def add_current_risk_answers(session, assessment_id: str, created_at: str, *, section: str = "Risikoprofil") -> None:
    for question_number, label, points in CURRENT_RISK_ANSWERS:
        session.add(
            RiskAssessmentAnswer(
                id=str(uuid.uuid4()),
                assessment_id=assessment_id,
                question_number=question_number,
                question_section=section,
                answer_label=label,
                answer_points=points,
                created_at=created_at,
            )
        )


@asynccontextmanager
async def noop_lifespan(_app):
    yield


# ── Standard-Fragebogen aus der Desktop-Frontend-Quelle ────────────────────────
# Liest Optionstexte und Punkttabellen direkt aus dem Monolithen, damit Tests
# echte Fragebogen-Payloads bauen (wie buildRiskAssessmentPayloadFromUI) ohne
# den Server-Katalog zu spiegeln.

import html as _html
import json as _json
import re as _re
from pathlib import Path as _Path

MONOLITH_PATH = _Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"
_OPTION_GROUPS = ("rf-income", "rf-oblig", "rf-wealth", "rf-savings", "rf-horizon", "q9", "q10", "q11")


def monolith_risk_questionnaire() -> dict:
    src = MONOLITH_PATH.read_text(encoding="utf-8")
    options = {}
    for group in _OPTION_GROUPS:
        found = _re.findall(
            r"<div class=\"qopt\" onclick=\"sq\(this,'" + _re.escape(group)
            + r"'\)\"><div class=\"qrad\"></div><span class=\"qtxt\">(.*?)</span></div>",
            src,
        )
        assert found, group
        options[group] = [_html.unescape(text).strip() for text in found]
    sources = [
        _html.unescape(text).strip()
        for text in _re.findall(r"<div class=\"qcb\" onclick=\"[^\"]*\"><div class=\"qbox\"></div>(.*?)</div>", src)
    ]
    points = {}
    for name in ("RISK_INCOME_POINTS", "RISK_OBLIGATIONS_POINTS", "RISK_WEALTH_POINTS", "RISK_SAVINGS_POINTS"):
        match = _re.search(r"^var " + name + r" = \[([^\]]*)\];", src, _re.M)
        assert match, name
        points[name] = [int(v) for v in match.group(1).split(",")]
    horizon_years = [
        int(v) for v in _re.findall(r"\{label:'[^']*',\s*years:(\d+)\}", src.split("var RISK_HORIZON_OPTIONS = [", 1)[1].split("];", 1)[0])
    ]
    return {"options": options, "sources": sources, "points": points, "horizon_years": horizon_years}


def standard_risk_payload(
    *, income=3, oblig=1, wealth=3, savings=3, horizon=5, goal=2, pref=2, behav=2,
    sources=(0,), knowledge=None,
) -> dict:
    """Payload wie buildRiskAssessmentPayloadFromUI fuer die gewaehlten Indizes."""
    q = monolith_risk_questionnaire()
    o, p = q["options"], q["points"]
    knowledge = knowledge if knowledge is not None else {"Anlageberatung": {"known": 1, "informed": 1}}
    instruments = {"Anlagefonds": {"known": 1, "informed": 0}}
    src_labels = [q["sources"][i] for i in sources]
    horizon_label = o["rf-horizon"][horizon]
    points = {
        "q_income_points": p["RISK_INCOME_POINTS"][income],
        "q_obligations_points": p["RISK_OBLIGATIONS_POINTS"][oblig],
        "q_wealth_points": p["RISK_WEALTH_POINTS"][wealth],
        "q_savings_points": p["RISK_SAVINGS_POINTS"][savings],
        "q_investment_goal_points": goal + 1,
        "q_risk_preference_points": pref + 1,
        "q_risk_behavior_points": behav + 1,
    }
    return {
        **points,
        "investment_horizon_label": horizon_label,
        "investment_horizon_years": q["horizon_years"][horizon],
        "knowledge_services_json": _json.dumps(knowledge),
        "knowledge_instruments_json": _json.dumps(instruments),
        "income_sources_json": _json.dumps(src_labels),
        "answers": [
            {"question_number": 1, "question_section": "Kenntnisse & Erfahrungen", "answer_label": "Finanzdienstleistungen: " + _json.dumps(knowledge, separators=(",", ":")), "answer_points": 0},
            {"question_number": 2, "question_section": "Kenntnisse & Erfahrungen", "answer_label": "Finanzinstrumente: " + _json.dumps(instruments, separators=(",", ":")), "answer_points": 0},
            {"question_number": 3, "question_section": "Risikofähigkeit", "answer_label": o["rf-income"][income], "answer_points": points["q_income_points"]},
            {"question_number": 4, "question_section": "Risikofähigkeit", "answer_label": "Herkunft: " + (", ".join(src_labels) or "Keine Angabe"), "answer_points": 0},
            {"question_number": 5, "question_section": "Risikofähigkeit", "answer_label": o["rf-oblig"][oblig], "answer_points": points["q_obligations_points"]},
            {"question_number": 6, "question_section": "Risikofähigkeit", "answer_label": o["rf-wealth"][wealth], "answer_points": points["q_wealth_points"]},
            {"question_number": 7, "question_section": "Risikofähigkeit", "answer_label": o["rf-savings"][savings], "answer_points": points["q_savings_points"]},
            {"question_number": 8, "question_section": "Risikofähigkeit", "answer_label": horizon_label + " · Matrix-Faktor", "answer_points": 0},
            {"question_number": 9, "question_section": "Risikobereitschaft", "answer_label": o["q9"][goal], "answer_points": goal + 1},
            {"question_number": 10, "question_section": "Risikobereitschaft", "answer_label": o["q10"][pref], "answer_points": pref + 1},
            {"question_number": 11, "question_section": "Risikobereitschaft", "answer_label": o["q11"][behav], "answer_points": behav + 1},
        ],
    }
