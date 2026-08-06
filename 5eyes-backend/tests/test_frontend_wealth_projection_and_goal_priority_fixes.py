"""2026-08-06 (User-Direktive, Cashflow-/Ziele-Audit): zwei Live-Browser-Funde
beim Durchklicken der Cashflows-&-Ziele-Seite.

1. refreshBaselineChartFromClientDataForced() liess bei einem Mandanten OHNE
   jedes Vermoegen/Cashflow den hartcodierten Demo-Platzhalter aus
   initCharts() (TOTAL||2848000) unveraendert stehen, statt ihn zu leeren --
   ein frisch angelegter Mandant zeigte eine frei erfundene Wachstumskurve
   CHF 2.8 -> 5.1 Mio unter dem Titel "Aktueller Gesamtvermoegenspfad", ohne
   jede Demo-Kennzeichnung.
2. syncGoalModalState() setzte 'nz-prio' bei JEDEM Aufruf fuer ein neues
   Renditeziel unconditional auf '3' (Opportunistisch) zurueck -- auch NACH
   einer manuellen Wahl von '2' (Primaer, fuer Renditeziele ausdruecklich
   zulaessig). Ein neues Renditeziel liess sich dadurch nie mit 'Primaer'
   speichern.
"""
from __future__ import annotations

from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _function_body(text: str, signature_start: str) -> str:
    start = text.find(signature_start)
    assert start > 0, f"Funktion nicht gefunden: {signature_start}"
    end = text.find("\n}\n", start)
    assert end > start, f"Funktionsende nicht gefunden: {signature_start}"
    return text[start:end]


def test_baseline_chart_clears_demo_placeholder_when_no_real_data():
    body = _function_body(_html(), "function refreshBaselineChartFromClientDataForced(")
    flat = body.replace(" ", "")
    # Der fruehe Return-Zweig (keine Wealth-/Cashflow-Daten) muss die Charts
    # explizit leeren -- nicht nur `return;` ohne jede Aktion.
    assert "charts.ist.data.datasets=[];" in flat
    assert "charts.aaCurrent.data.datasets=[];" in flat
    assert "renderCurrentWealthOnlyProjectionSummary({labels:[],projectedRappen:0" in flat


def test_return_goal_priority_only_corrects_invalid_hart_not_user_choice():
    body = _function_body(_html(), "function syncGoalModalState(")
    flat = body.replace(" ", "")
    # Die alte, fehlerhafte Zeile ohne Bedingung auf den aktuellen Wert
    # darf nicht mehr vorkommen.
    assert "if(!currentGoalEditId)setSelectValue('nz-prio','3')" not in flat
    # Der Reset darf nur greifen, wenn die aktuelle Prioritaet der fachlich
    # unzulaessige Wert 'Hart' (1) ist.
    assert "if(!currentGoalEditId&&getInputValue('nz-prio')==='1')setSelectValue('nz-prio','3')" in flat
