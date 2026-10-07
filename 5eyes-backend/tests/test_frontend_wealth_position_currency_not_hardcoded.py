"""CURRENCY-CLOBBER-001 (Audit-Finding, 2026-10-07): source-level contract for
buildWealthPositionPayload() in 5eyes_v2.html.

Befund: die Funktion verdrahtete `currency:'CHF'` fest in jedes Payload, egal
ob eine neue Position angelegt oder eine bestehende bearbeitet wurde -- jedes
Speichern (auch ein reines Edit) ueberschrieb damit die currency einer
Position, selbst wenn sie legitim in einer Fremdwaehrung lautete. Seit
BASE-CURRENCY-HARDCODED-001 (2026-09-27) kann mandate.base_currency frei
gewaehlt werden, wodurch Fremdwaehrungs-Positionen real vorkommen.

Es gibt noch kein UI-Feld zur Waehrungswahl in dieser Maske (kein Full-Fix) --
dieser Test deckt nur den Minimalfix ab: keine stille Clobber mehr, neue
Positionen defaulten auf die Mandats-Basiswaehrung statt hart CHF."""
from __future__ import annotations

from pathlib import Path


HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)


def _wealth_position_payload_builder() -> str:
    html = HTML_PATH.read_text(encoding="utf-8")
    return html.split(
        "function buildWealthPositionPayload(cat,typ,note){", 1
    )[1].split("async function saveWealthPosition()", 1)[0]


def test_wealth_position_payload_does_not_hardcode_chf_currency():
    builder = _wealth_position_payload_builder()
    assert "currency:'CHF'" not in builder, (
        "buildWealthPositionPayload() darf currency nicht mehr hart auf 'CHF' "
        "verdrahten -- das ueberschreibt bei JEDEM Speichern (auch Edit) die "
        "currency einer Position, siehe CURRENCY-CLOBBER-001."
    )


def test_wealth_position_payload_defaults_new_positions_to_mandate_base_currency():
    builder = _wealth_position_payload_builder()
    assert "currentMandateData" in builder and "base_currency" in builder, (
        "Neue Positionen muessen auf mandate.base_currency defaulten statt "
        "hart CHF, sobald keine bestehende Position zum Uebernehmen da ist."
    )


def test_wealth_position_payload_preserves_existing_currency_on_edit():
    builder = _wealth_position_payload_builder()
    assert "currentWealthEditId" in builder and "existingWealthPos" in builder, (
        "Beim Bearbeiten (currentWealthEditId gesetzt) muss die bestehende "
        "Position aus currentWealthPositions nachgeschlagen werden, damit ihre "
        "currency erhalten bleibt statt verworfen zu werden."
    )
    payload_line = builder.split("currency:payloadCurrency", 1)
    assert len(payload_line) == 2, (
        "payload.currency muss aus der hergeleiteten payloadCurrency kommen, "
        "nicht mehr aus einem Literal."
    )
