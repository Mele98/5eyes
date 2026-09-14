"""DECUM-DEPLETION-001 / DECUM-READINESS-001 (Phase-0-Fix, 2026-09-10).

Zwei zusammenhaengende Funde im Retirement-/Verzehr-Reporting:

1. DECUM-DEPLETION-001: MonteCarloResponse deklarierte die vier vom Engine
   berechneten depletion-Felder nicht -> pydantic v2 verwarf sie lautlos
   (extra="ignore" Default). Das Frontend las das fehlende Feld dann per
   `Number(pct||0)` als echte 0% -- ein gefaehrlicher Falsch-Negativ fuer
   ein Verzehr-Risiko-Warnsignal. Fix: Schema deklariert die Felder jetzt
   (siehe tests/test_sequence_of_returns_depletion.py fuer den
   Backend-Schema-Vertrag), UND das Frontend unterscheidet "fehlend" von
   "berechnet 0".

2. DECUM-READINESS-001: Der Readiness-Checklist-Punkt "Reichweite bestaetigt"
   wurde nur aufgenommen, wenn allocation.decumulation.decumulation_mode
   vorhanden war -- ein Feld, das kein Produktionscode je befuellt (siehe
   Audit-Grep). Der Punkt fehlte also STILL, die Checkliste blieb bei 4
   Punkten, und "Meeting ist bereit fuer PDF und Signatur." konnte fuer ein
   Pensionierungsmandat erscheinen, dessen Reichweite nie geprueft wurde.
   Fix: fail-closed -- bei einem aktiven Pensionsausgabe-Ziel wird der Punkt
   IMMER aufgenommen, und zaehlt als offen, solange das Backend keine echte
   Decumulation-Auswertung liefert.

Dieser Test folgt dem in diesem Repo etablierten Muster fuer
Frontend-Monolith-Tests (siehe z.B. test_frontend_review_cockpit.py,
test_frontend_verzehr_liquidity.py): statische String-/Struktur-Assertions
gegen die HTML/JS-Quelle, keine JS-Ausfuehrung.
"""
from __future__ import annotations

import re
from pathlib import Path

HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


# ── DECUM-DEPLETION-001: fehlend != 0% ───────────────────────────────────────

def test_fmt_depletion_distinguishes_missing_from_zero():
    html = _html()
    match = re.search(
        r"var _fmtDepletion=function\(pct,year\)\{(.*?)\};",
        html,
        re.DOTALL,
    )
    assert match, "_fmtDepletion nicht gefunden -- wurde die Stelle umbenannt/verschoben?"
    body = match.group(1)
    # Muss explizit auf null/undefined pruefen, BEVOR es Number() aufruft --
    # sonst verschluckt Number(null)===0 den Unterschied wieder.
    assert "pct===null" in body or "pct == null" in body
    assert "'n/a'" in body
    # Die alte Bug-Signatur (Number(pct||0), keine Missing-Unterscheidung)
    # darf nicht mehr vorkommen.
    assert "Number(pct||0)" not in body


def test_old_conflating_zero_default_pattern_is_gone_for_depletion():
    html = _html()
    assert "var _fmtDepletion=function(pct,year){var p=Number(pct||0);" not in html


def test_depletion_color_coding_does_not_treat_missing_as_zero():
    html = _html()
    # DECUM-DEPLETION-001: der Farbvergleich SOLL-vs-IST darf ein fehlendes
    # (null) Feld nicht als 0 interpretieren und faelschlich einfaerben.
    assert "mc.target_depletion_probability_pct!=null&&mc.current_depletion_probability_pct!=null" in html


# ── DECUM-READINESS-001: fail-closed statt stiller Omission ────────────────

def test_decumulation_applicability_signal_exists():
    html = _html()
    assert "function _reviewHasDecumulationRelevantGoal()" in html
    assert "goal_type!=='Pensionsausgabe'" in html


def test_applicability_signal_fails_closed_before_goals_are_loaded():
    """Code-Review-Nachtrag: refreshGoalsUI() und refreshReviewUI() laufen bei
    Mandatswechsel unawaited nebeneinander (siehe z.B. loadClientDetail()).
    currentGoals ist immer ein Array (nie null/undefined) -- "noch nicht
    geladen" und "wirklich leer" waren daher am Wert allein nicht
    unterscheidbar. Ein Render zwischen Mandatswechsel und dem ersten
    erfolgreichen refreshGoalsUI() haette den Reichweiten-Punkt sonst genau
    fuer den Fall auslassen koennen, den DECUM-READINESS-001 absichern soll."""
    html = _html()
    match = re.search(
        r"function _reviewHasDecumulationRelevantGoal\(\)\{(.*?)\n\}",
        html,
        re.DOTALL,
    )
    assert match, "_reviewHasDecumulationRelevantGoal nicht gefunden -- wurde die Stelle umbenannt/verschoben?"
    body = match.group(1)
    assert "_currentGoalsLoadedOnce" in body
    # Unbekannter/noch-nicht-geladener Zustand muss "koennte zutreffen" (true)
    # zurueckgeben, nicht "nicht anwendbar" (false) -- das ist der Kern des
    # Fail-closed-Vertrags.
    assert re.search(r"if\(typeof _currentGoalsLoadedOnce!=='undefined'&&!_currentGoalsLoadedOnce\)return true;", body)
    # Das Flag muss beim ersten erfolgreichen Laden auf true gesetzt werden,
    # sonst bliebe der fail-closed-Zustand fuer immer aktiv.
    assert "_currentGoalsLoadedOnce=true;" in html
    # Und bei jedem Mandats-/Kundenwechsel zurueckgesetzt werden, sonst
    # zeigte ein Wechsel auf ein anderes Mandat die STALE Anwendbarkeit des
    # vorherigen Mandats.
    reset_count = len(re.findall(r"_currentGoalsLoadedOnce\s*=\s*false;", html))
    assert reset_count >= 4


def test_readiness_checklist_always_adds_item_when_applicable():
    html = _html()
    match = re.search(
        r"function renderReadinessChecklist\(state\)\{(.*?)\n\}\nfunction renderReviewSummaryGrid",
        html,
        re.DOTALL,
    )
    assert match, "renderReadinessChecklist nicht gefunden -- wurde die Stelle umbenannt/verschoben?"
    body = match.group(1)
    # Die Anwendbarkeits-Pruefung muss VOR jeder Fallunterscheidung stehen --
    # der alte Bug war, dass der Punkt nur bei vorhandenem
    # allocation.decumulation.decumulation_mode ueberhaupt existierte.
    assert "if(_reviewHasDecumulationRelevantGoal()){" in body
    # Der Fail-closed-Zweig: fehlt die Datenbasis, MUSS der Punkt trotzdem
    # auftauchen -- als offener (done:false), blockierender Punkt.
    assert "nicht geprueft (Datenbasis fehlt)" in body
    assert "done:false" in body


def test_readiness_checklist_non_applicable_case_unaffected():
    """Regressions-Guard: ohne Pensionsausgabe-relevantes Ziel bleibt die
    Checkliste bei den urspruenglichen 4 Punkten (kein Verzehr-Punkt),
    exakt wie vor diesem Fix."""
    html = _html()
    match = re.search(
        r"function renderReadinessChecklist\(state\)\{(.*?)\n\}\nfunction renderReviewSummaryGrid",
        html,
        re.DOTALL,
    )
    assert match
    body = match.group(1)
    # Die urspruenglichen 4 Basis-Punkte sind noch unveraendert vorhanden.
    for label in (
        "Strategievergleich geprueft",
        "Eignungspruefung erfasst",
        "Entscheidung protokolliert",
        "Interessenkonflikte geprueft",
    ):
        assert label in body
    # Der 5. Punkt haengt strikt an der Anwendbarkeits-Pruefung, nicht an
    # einer unbedingten Push-Anweisung.
    push_calls = re.findall(r"items\.push\(", body)
    assert len(push_calls) == 2  # ein Zweig fuer erfuellt, einer fuer fail-closed
