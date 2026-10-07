"""CURRENCY-CLOBBER-001 fuer Cashflows (Audit-Finding, 2026-10-07): source-level
contract for saveCashflow() in 5eyes_v2.html.

Befund: identisches Bugmuster wie die bereits gefixte Vermoegens-Variante
(buildWealthPositionPayload/CURRENCY-CLOBBER-001, PR #553) -- saveCashflow()
verdrahtete `currency:'CHF'` fest in jedes Payload, egal ob ein neuer Cashflow
angelegt oder ein bestehender bearbeitet wurde. Jedes Speichern (auch ein
reines Edit) ueberschrieb damit die currency eines bestehenden Cashflows.
Seit BASE-CURRENCY-HARDCODED-001 (2026-09-27) kann mandate.base_currency frei
gewaehlt werden, wodurch Fremdwaehrungs-Cashflows real vorkommen."""
from __future__ import annotations

from pathlib import Path


HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)


def _save_cashflow_fn() -> str:
    html = HTML_PATH.read_text(encoding="utf-8")
    return html.split(
        "async function saveCashflow(){", 1
    )[1].split("function inflowSourceLabel(", 1)[0]


def test_save_cashflow_does_not_hardcode_chf_currency():
    fn = _save_cashflow_fn()
    assert "currency:'CHF'" not in fn, (
        "saveCashflow() darf currency nicht mehr hart auf 'CHF' verdrahten -- "
        "das ueberschreibt bei JEDEM Speichern (auch Edit) die currency eines "
        "Cashflows, siehe CURRENCY-CLOBBER-001."
    )


def test_save_cashflow_defaults_new_entries_to_mandate_base_currency():
    fn = _save_cashflow_fn()
    assert "currentMandateData" in fn and "base_currency" in fn, (
        "Neue Cashflows muessen auf mandate.base_currency defaulten statt "
        "hart CHF, sobald kein bestehender Cashflow zum Uebernehmen da ist."
    )


def test_save_cashflow_preserves_existing_currency_on_edit():
    fn = _save_cashflow_fn()
    assert "currentCashflowEditId" in fn and "existingCashflow" in fn, (
        "Beim Bearbeiten (currentCashflowEditId gesetzt) muss der bestehende "
        "Cashflow aus currentCashflows nachgeschlagen werden, damit seine "
        "currency erhalten bleibt statt verworfen zu werden."
    )
    assert "currency:cashflowCurrency" in fn, (
        "payload.currency muss aus der hergeleiteten cashflowCurrency kommen, "
        "nicht mehr aus einem Literal."
    )
