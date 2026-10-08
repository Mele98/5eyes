"""DATE-GROUP-001 (Audit-Feedback, 2026-10-08): source-level contract for the
Jahr/Monat/Tag date-picker that replaces native <input type="date"> for the
four Ziele/Cashflow date fields in 5eyes_v2.html.

Hintergrund: Nutzer-Feedback meldete (a) unkomfortable native Kalender-
Popup-Navigation fuer weit entfernte Daten und (b) ein gelegentliches
Verschwinden der Maske beim Tippen -- plausibelster Grund ist eine
Interaktion zwischen dem vom Betriebssystem gerenderten nativen Datums-
Popup und dem Overlay-Click-Outside-Schliessen-Handler. Browser-native
<select>-Elemente ersetzen das native Popup vollstaendig (kein von der
Seite entkoppeltes Popup mehr) und sind per Browser-Standard-Type-Ahead
direkt eintippbar.

Zusaetzlich: GOAL-HORIZON-REDUNDANCY-001 -- "Zeithorizont (Jahre)" wird bei
gesetztem Zieldatum zu einem reinen Anzeigefeld (aus dem Datum abgeleitet),
nicht mehr unabhaengig editierbar -- schliesst die Ursache von
GOAL-HORIZON-STALE-001 strukturell."""
from __future__ import annotations

from pathlib import Path


HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_all_four_date_fields_no_longer_use_native_date_input():
    html = _html()
    for field_id in ("nz-target-date", "nz-start-date", "acf-valid-from", "acf-valid-until"):
        assert f'id="{field_id}" type="date"' not in html, (
            f"{field_id} darf kein natives <input type=\"date\"> mehr sein -- "
            "DATE-GROUP-001 ersetzt es durch Jahr/Monat/Tag-<select>-Dropdowns."
        )
        assert f'id="{field_id}" value=""' in html, (
            f"{field_id} muss als Hidden-Input mit demselben id weiterleben, "
            "damit getInputValue()/setInputValue() unveraendert funktionieren."
        )


def test_date_group_selects_are_ordered_year_month_day():
    html = _html()
    for field_id in ("nz-target-date", "nz-start-date", "acf-valid-from", "acf-valid-until"):
        block = html.split(f"onDateGroupChange('{field_id}')", 1)
        assert len(block) == 2, f"onDateGroupChange('{field_id}') nicht gefunden"
        # Der Jahr-Select muss im Markup vor dem Monat-Select stehen, und
        # dieser vor dem Tag-Select -- exakt die vom Nutzer gewuenschte
        # Reihenfolge ("zuerst Jahre waehlen, danach der Monat, am Schluss
        # der Tag").
        wrap_start = html.rfind('<div class="date-group">', 0, html.index(f"onDateGroupChange('{field_id}')"))
        assert wrap_start != -1
        wrap_html = html[wrap_start:html.index(f'id="{field_id}" value=""') + 40]
        year_pos = wrap_html.find('dg-year')
        month_pos = wrap_html.find('dg-month')
        day_pos = wrap_html.find('dg-day')
        assert year_pos != -1 and month_pos != -1 and day_pos != -1
        assert year_pos < month_pos < day_pos, (
            f"Reihenfolge fuer {field_id} muss Jahr -> Monat -> Tag sein."
        )


def test_days_in_month_uses_leap_year_safe_js_idiom():
    html = _html()
    assert "function dateGroupDaysInMonth(year,month){" in html
    assert "return new Date(year,month,0).getDate();" in html, (
        "new Date(year, month, 0) ist der JS-Standardidiom fuer 'letzter Tag "
        "des Vormonats' (0-indiziert) -- korrekt schaltjahr-sicher (Feb "
        "liefert 28 oder 29 je nach Jahr), ohne eigene Schaltjahr-Formel."
    )


def test_set_input_value_routes_date_group_fields_through_select_sync():
    html = _html()
    fn = html.split("function setInputValue(id,value){", 1)[1].split(
        "function setSelectValue(", 1
    )[0]
    assert "DATE_GROUP_FIELDS" in fn and "setDateGroupValue(id,value)" in fn, (
        "setInputValue() muss die vier Datumsfeld-ids weiterhin transparent "
        "unterstuetzen (bestehende Aufrufer wie resetGoalModal/openGoalEditor/"
        "resetCashflowModal/openCashflowEditor duerfen nicht angepasst werden "
        "muessen), indem es fuer diese ids auf setDateGroupValue() umleitet, "
        "statt nur das Hidden-Feld zu setzen."
    )


def test_goal_horizon_becomes_computed_readonly_when_target_date_set():
    html = _html()
    fn = html.split("function onGoalDateGroupChange(){", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "goalEditorHorizonYears()" in fn, (
        "Der berechnete Horizont muss ueber dieselbe Funktion kommen, die "
        "auch die Live-Diagnose (updateGoalDerivedDiagnostics) verwendet -- "
        "Single Source of Truth, schliesst GOAL-HORIZON-STALE-001 strukturell."
    )
    assert "horizonInput.readOnly=true" in fn
    assert "horizonInput.readOnly=false" in fn, (
        "Ohne Zieldatum muss das Feld wieder editierbar werden (Fallback-"
        "Pfad fuer Zieltypen, die auch ohne Datum einen reinen Jahres-"
        "Horizont akzeptieren)."
    )


def test_save_goal_calls_the_date_group_horizon_sync_on_open_and_edit():
    html = _html()
    reset_fn = html.split("function resetGoalModal(){", 1)[1].split(
        "\nfunction openGoalEditor", 1
    )[0]
    edit_fn = html.split("function openGoalEditor(goalId){", 1)[1].split(
        "\nfunction renderGoalList", 1
    )[0]
    assert "onGoalDateGroupChange();" in reset_fn, (
        "Neues Ziel: der Horizont-Readonly-Zustand muss schon beim Oeffnen "
        "korrekt gesetzt sein (Default kein Zieldatum -> editierbar)."
    )
    assert "onGoalDateGroupChange();" in edit_fn, (
        "Bestehendes Ziel bearbeiten: wenn bereits ein Zieldatum gespeichert "
        "ist, muss der Horizont sofort als berechnet/readonly angezeigt "
        "werden, nicht erst nach der ersten manuellen Dropdown-Interaktion."
    )
