"""UX-1 (UX-Audit Befunde 8 + 14): eine Erfolgskennzahl, klientenfaehiges Deutsch.

Befund 8: Zielerreichung erschien unter vier Massen (Median-Erreichung,
"P", "Pfaderfolg", Score) ohne Definition. Jetzt traegt die
Erfolgswahrscheinlichkeit die Ampel, der Median-Erreichungsgrad ist korrekt
als Median benannt (das Payload hat KEIN P25-Erreichungsfeld; P25 betrifft nur
den Fehlbetrag) und die Ampel-Schwellen sind sichtbar erklaert.

Befund 14: Engine-Jargon/Englisch ("Reasoning-Trace", "Sensitivity-Analyse",
"Shadow", "Constraint", "Slack", "Goal-Driver", "Risky Fraction", "Headroom",
"Advisory-Basis", "Event(s)", hart codiert "7J-Projektion", "Mulvey/Ziemba")
ist durch deutsche Begriffe ersetzt; Audit-Fusszeile und Vergleichsmethode
liegen in details.tech und sind im Consulting-Modus ausgeblendet.

Reine Anzeige-Vertraege -- keine Rechenlogik.
"""
import json
import re
import subprocess
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "ares.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _function_source(html: str, name: str) -> str:
    match = re.search(r"function " + re.escape(name) + r"\(", html)
    assert match, name
    i = html.index("{", match.end())
    depth, j = 1, i + 1
    while depth:
        if html[j] == "{":
            depth += 1
        elif html[j] == "}":
            depth -= 1
        j += 1
    return html[match.start():j]


def test_old_engine_jargon_is_gone_from_visible_labels():
    html = _html()
    for old in (
        ">Reasoning-Trace</summary>",
        ">Sensitivity-Analyse</summary>",
        ">Goal-Driver (Shortfall-Beitrag, gemeinsamer Pfad)</summary>",
        "<th>Shadow</th>",
        "<th>Constraint</th>",
        "<th>Slack</th>",
        "<th>Beitrag (milli)</th>",
        "{label:'Risk Budget'",
        "{label:'Risky Fraction'",
        "'Headroom '",
        "7J-Projektion",
        "Advisory-Basis",
        "' Event(s)'",
        "Mulvey",
        "'Shadow konvergiert'",
        "L(w*)",
        "Zielerreichung (Entscheidungsmodell)",
        "Pfaderfolg ",
    ):
        assert old not in html, old


def test_new_plain_german_labels_are_present():
    html = _html()
    for new in (
        ">Herleitung</summary>",
        ">Was-w&auml;re-wenn</summary>",
        ">Treiber der Zielabweichung</summary>",
        "<th>Vergleichsmethode</th>",
        "<th>Grenze</th>",
        ">Spielraum</th>",
        "{label:'Risikobudget'",
        "{label:'Risikobehafteter Anteil'",
        "mit tausenden simulierten Marktverläufen",
    ):
        assert new in html, new


def test_success_probability_is_the_single_defined_primary_measure():
    html = _html()
    assert (
        "var GOAL_SUCCESS_PROBABILITY_TOOLTIP='Anteil der simulierten Verl\\u00e4ufe, "
        "in denen das Ziel vollst\\u00e4ndig erreicht wird';"
    ) in html
    assert "\\u2265 70 % gut \\u00b7 45\\u201369 % knapp \\u00b7 < 45 % kritisch" in html
    soll_ist = _function_source(html, "renderGoalAchievementSollIst")
    assert "Erfolgs-Wkt. SOLL" in soll_ist
    assert "path_success_rate_pct" in soll_ist
    # Median ist Median, nicht P25: der Erreichungsgrad wird so benannt; P25
    # gehoert nur zum Fehlbetrag (pessimistic_shortfall_rappen, P25-Pfad).
    assert "Erreichungsgrad (Median)" in soll_ist
    assert "(P25)" in soll_ist
    assert "Erreichungsgrad im ung" not in soll_ist
    assert "goalAmpelLegendHtml()" in soll_ist
    mc_goals = _function_source(html, "buildMonteCarloGoalsHtml")
    assert "var tone=success>=70" in mc_goals
    assert "goalAmpelLegendHtml()" in mc_goals


def test_technical_details_are_collapsed_and_hidden_in_consulting():
    html = _html()
    assert '<details class="tech" id="opt-tech-details"' in html
    assert '<details class="tech" id="method-comparison-tech">' in html
    assert "<summary>Technische Details</summary>" in html
    assert 'html[data-presentation-mode="consulting"] details.tech,' in html
    assert 'html[data-presentation-mode="consulting"] #al-method-comparison-panel{display:none!important;}' in html
    # Audit-Fusszeile liegt im details-Element.
    tech = html[html.index('id="opt-tech-details"'):]
    tech = tech[: tech.index("</details>")]
    assert 'id="opt-audit-footer"' in tech


def _run_horizon(result: dict, sim) -> str:
    fn = _function_source(_html(), "engineProjectionHorizonSub")
    script = fn + "\nprocess.stdout.write(engineProjectionHorizonSub(" + json.dumps(result) + "," + json.dumps(sim) + "));"
    out = subprocess.run(["node", "-e", script], capture_output=True, timeout=10, check=False)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    return out.stdout.decode("utf-8")


def test_projection_horizon_comes_from_payload_not_hardcoded():
    assert "Prognosehorizont 23 Jahre" in _run_horizon({"projection_horizon": {"years": 23}}, None)
    assert "Prognosehorizont 12 Jahre" in _run_horizon({}, {"horizon_years": 12})
    neutral = _run_horizon({}, None)
    assert "Jahre" not in neutral and "Erwartung p.a." in neutral


def test_review_cockpit_ampel_uses_70_45_and_keeps_strategy_level_separate():
    html = _html()
    badge = _function_source(html, "rvGoalProbBadge")
    assert "p>=0.70" in badge and "p>=0.45" in badge
    review = _function_source(html, "renderReviewGoalAchievability")
    assert "goalAmpelLegendHtml()" in review
    assert "GOAL_STRATEGY_LEVEL_TOOLTIP" in review
    assert "goalAchievabilityStatusLabel(row.status)" in review
    assert "var GOAL_STRATEGY_LEVEL_TOOLTIP='Zielniveau der Strategie:" in html
    assert 'class="goal-ampel-legend"' in html
