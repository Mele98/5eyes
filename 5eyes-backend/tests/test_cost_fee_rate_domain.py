"""COST-DOMAIN-001: Gebuehrensaetze typisiert annehmen, nicht klemmen.

CERT-COST-CONFLICT-001. Befund 2026-10-12: jeder Gebuehrensatz lief durch
`max(0, _safe_int(value))` -- zwei Stillschweige-Mechanismen uebereinander:

    "not-a-rate"  -> _safe_int faengt den ValueError        -> 0
    -75           -> max(0, ...) verschluckt das Vorzeichen  -> 0

Beide ergaben einen Kostenposten mit 0 bps, der als "konfiguriert" galt. Das
FIDLEG-Dokument wies damit eine KOSTENLOSE Dienstleistung aus, wo in
Wahrheit ein unverwertbarer Wert hinterlegt war. Eine Null ist hier nicht
die konservative Annahme, sondern die guenstigste -- die falsche Richtung
fuer einen Pflichtausweis.

Geprueft werden beide Grenzen getrennt:
- die reine Funktion lehnt ab (kaputtes ARGUMENT),
- `build_cost_disclosure()` degradiert zu `_pending_payload` (persistierte
  Altdaten duerfen das Dokument nicht mit HTTP 500 abreissen).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.cost_disclosure import (  # noqa: E402
    REASON_RATE_NEGATIVE,
    REASON_RATE_NOT_A_NUMBER,
    REASON_RATE_NOT_INTEGRAL,
    CostDisclosureDomainError,
    _require_rate_bps,
    calculate_cost_disclosure,
)

_POSITIONS = [{"amount_rappen": 100_000_000, "weight_bps": 10000, "ter_bps": 20}]


def _calc(fee_model, **kwargs):
    return calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000,
        positions=_POSITIONS,
        fee_model=fee_model,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Der Validator selbst
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, reason",
    [
        ("not-a-rate", REASON_RATE_NOT_A_NUMBER),
        ("75", REASON_RATE_NOT_A_NUMBER),      # Ziffernstring ist keine Zahl
        ("", REASON_RATE_NOT_A_NUMBER),
        (True, REASON_RATE_NOT_A_NUMBER),      # bool: True waere 1 bps
        (False, REASON_RATE_NOT_A_NUMBER),
        ([75], REASON_RATE_NOT_A_NUMBER),
        ({"bps": 75}, REASON_RATE_NOT_A_NUMBER),
        (float("nan"), REASON_RATE_NOT_A_NUMBER),
        (float("inf"), REASON_RATE_NOT_A_NUMBER),
        (75.5, REASON_RATE_NOT_INTEGRAL),
        (-1, REASON_RATE_NEGATIVE),
        (-75, REASON_RATE_NEGATIVE),
    ],
)
def test_malformed_rate_is_rejected_with_stable_reason(value, reason):
    with pytest.raises(CostDisclosureDomainError) as excinfo:
        _require_rate_bps(value, location="fee_model['x']")
    assert excinfo.value.reason_code == reason
    assert excinfo.value.location == "fee_model['x']"


@pytest.mark.parametrize("value, expected", [(0, 0), (75, 75), (75.0, 75), (10000, 10000)])
def test_valid_rate_passes_through_unchanged(value, expected):
    """Gegenprobe: gueltige Saetze duerfen NICHT abgelehnt werden.

    Ohne diese Zeile waere ein Validator, der alles ablehnt, von den Tests
    oben nicht zu unterscheiden. `0` ist ausdruecklich gueltig -- eine
    bewusst erfasste Nullgebuehr ist eine Aussage, eine stillschweigend
    erzeugte Null war der Defekt.
    """
    assert _require_rate_bps(value, location="fee_model['x']") == expected


def test_domain_error_is_a_value_error():
    """Bestehende Aufrufer, die breit auf ValueError pruefen, bleiben heil."""
    assert issubclass(CostDisclosureDomainError, ValueError)


def test_no_upper_bound_is_invented():
    """Ein absurd HOHER Satz wird NICHT abgelehnt -- bewusst.

    Fuer Gebuehrensaetze existiert in diesem Repo kein Praezedenzfall fuer
    eine Obergrenze (anders als `_INDUCEMENT_SANITY_CEILING_RAPPEN` fuer
    Betraege, der aus einem Audit stammt). Einen Deckel zu erfinden koennte
    legitime Konfigurationen ablehnen; ein hoher Satz ist im Dokument
    ausserdem sichtbar, waehrend die stille Null es nicht war.

    Dieser Test haelt die ENTSCHEIDUNG fest, nicht eine Eigenschaft, die
    gut waere: wer eine Grenze einfuehrt, soll hier bewusst vorbeikommen.
    """
    assert _require_rate_bps(1_000_000, location="fee_model['x']") == 1_000_000


# ---------------------------------------------------------------------------
# Die reine Funktion lehnt ab, an jedem Eintrittspunkt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "default_advisory_fee_bps",
        "advisory_fee_bps",
        "management_fee_bps",
        "custody_fee_bps",
        "platform_fee_bps",
        "onboarding_fee_bps",
        "entry_fee_bps",
    ],
)
def test_every_fee_key_is_validated_not_only_the_first(key):
    """Jeder Gebuehrenschluessel, nicht nur der aus dem Reproducer.

    Der Reproducer trifft `default_advisory_fee_bps`. Waere nur dieser
    verdrahtet, blieben die uebrigen Saetze stillschweigend geklemmt -- ein
    Fix, der genau den gemessenen Fall schliesst und die gleiche Luecke
    daneben offen laesst.
    """
    with pytest.raises(CostDisclosureDomainError):
        _calc({key: "not-a-rate"})


def test_transaction_cost_rate_is_validated_too():
    with pytest.raises(CostDisclosureDomainError):
        _calc({"default_advisory_fee_bps": 75}, transaction_cost_bps="not-a-rate")


def test_absent_key_is_not_a_domain_error():
    """ABWESENHEIT bleibt ein eigener, bereits behandelter Zustand.

    Ein fehlender Gebuehrenschluessel ist keine kaputte Angabe, sondern eine
    fehlende -- dafuer gibt es `service_fee_known=False` samt Warnung. Die
    Ablehnung darf diesen Pfad nicht verschlucken, sonst waere jedes
    unvollstaendig erfasste Mandat blockiert.
    """
    payload = _calc({})
    assert payload["is_complete"] is False
    assert any("nicht hinterlegt" in w for w in payload["warnings"])


def test_explicit_none_is_treated_as_absent_not_malformed():
    payload = _calc({"default_advisory_fee_bps": None})
    assert payload["is_complete"] is False
    assert any("nicht hinterlegt" in w for w in payload["warnings"])


def test_valid_fee_model_still_produces_a_complete_payload():
    """Gegenprobe auf Ebene des Payloads: der gute Fall bleibt gut."""
    payload = _calc({"default_advisory_fee_bps": 75})
    assert payload["is_complete"] is True
    keys = {item["key"] for item in payload["cost_items"]}
    assert "default_advisory_fee_bps" in keys
