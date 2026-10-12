"""INDUCEMENT-EVIDENCE-001: der Verzicht-Claim nur gegen echten Nachweis.

CERT-COST-CONFLICT-001. Befund 2026-10-12: `calculate_cost_disclosure()`
schrieb fuer JEDE einbehaltene Retrozession die Quelle
"Interessenkonflikt-Offenlegung (Retrozession, Verzicht dokumentiert)" und die
Warnung "gemaess dokumentiertem Kundenverzicht" ins FIDLEG-Dokument -- auch
wenn nie offengelegt und kein Verzichts-Dokument abgelegt war. Die Aussage war
damit nicht bloss unbelegt, sondern das Gegenteil der Datenlage, und zwar in
genau der Konstellation, die BGE 132 III 460 ohne gueltigen Verzicht
unzulaessig macht.

Dieses Modul prueft die vollstaendige Nachweismatrix und -- wichtiger -- dass
JEDE Bedingung tragend ist. Ein Test, der nur den Negativfall pinnt, koennte
auch gegen eine Konstante gruen bleiben; deshalb wird jede Bedingung einzeln
umgeschaltet und das Umschlagen beobachtet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.cost_disclosure import (  # noqa: E402
    _has_documented_waiver,
    calculate_cost_disclosure,
)

_POSITIONS = [{"amount_rappen": 50_000_000, "ter_bps": 20}]
_FEE = {"default_advisory_fee_bps": 75}

_WAIVER_CLAIM_FRAGMENTS = (
    "Verzicht dokumentiert",
    "dokumentiertem Kundenverzicht",
)


def _run(**inducement_overrides):
    inducement = {
        "amount_rappen": 50_000,
        "frequency": "jährlich",
        "reimbursed_to_client": False,
        "provider": "Fonds AG",
    }
    inducement.update(inducement_overrides)
    return calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000,
        positions=_POSITIONS,
        fee_model=_FEE,
        inducements=[inducement],
    )


def _retro_items(data):
    return [i for i in data["cost_items"] if i["category"] == "Vergütungen von Dritten"]


def _claims_waiver(data) -> bool:
    """Behauptet IRGENDEIN Textfeld des Payloads einen dokumentierten Verzicht?

    Prueft Items UND Warnungen, weil beide unveraendert ins PDF fliessen
    (services/pdf/components/kostenausweis.py rendert `source` in der Tabelle
    und `warnings` im Annahmen-Panel). Eine Pruefung nur auf den Key wuerde
    einen Fix durchlassen, der den Key aendert, aber den Prosatext behaelt.
    """
    haystack = [str(i.get("source") or "") for i in _retro_items(data)]
    haystack += [str(i.get("label") or "") for i in _retro_items(data)]
    haystack += [str(w) for w in data.get("warnings") or []]
    return any(
        fragment in text
        for text in haystack
        for fragment in _WAIVER_CLAIM_FRAGMENTS
    )


# ---------------------------------------------------------------------------
# Die Nachweismatrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "disclosed, waiver_doc, waiver_allowed",
    [
        (False, None, False),              # nichts erfasst -- der Befund
        (False, "doc-1", False),           # Dokument ohne Offenlegung
        (True, None, False),               # offengelegt, nichts abgelegt
        (True, "doc-1", True),             # vollstaendig belegt
    ],
)
def test_waiver_claim_requires_disclosure_and_document(disclosed, waiver_doc, waiver_allowed):
    data = _run(disclosed_to_client=disclosed, waiver_document_id=waiver_doc)
    items = _retro_items(data)
    assert len(items) == 1, "Die Retrozession muss in jedem Fall sichtbar bleiben"

    if waiver_allowed:
        assert items[0]["key"] == "retrocession_disclosed"
        assert items[0]["requires_resolution"] is False
        assert _claims_waiver(data), (
            "Bei vollstaendigem Nachweis DARF der Verzicht benannt werden -- "
            "sonst wird eine korrekt dokumentierte Lage verschwiegen"
        )
    else:
        assert items[0]["key"] == "retrocession_retained_unwaived"
        assert items[0]["requires_resolution"] is True
        assert not _claims_waiver(data), (
            "Verzicht-Claim ohne Nachweis: "
            f"disclosed={disclosed} waiver_doc={waiver_doc!r}"
        )


def test_each_evidence_condition_is_load_bearing():
    """Gegenprobe: beide Bedingungen muessen EINZELN das Ergebnis drehen.

    Haette ich nur den Vollnachweis-Fall und den Nichts-Fall getestet, waere
    eine Implementierung, die nur EINE der beiden Bedingungen prueft, unbemerkt
    gruen geblieben. Hier wird vom belegten Zustand aus jede Bedingung einzeln
    entfernt und das Umschlagen verlangt.
    """
    full = {"disclosed_to_client": True, "waiver_document_id": "doc-1"}
    assert _has_documented_waiver(full) is True

    for condition in ("disclosed_to_client", "waiver_document_id"):
        weakened = dict(full)
        weakened[condition] = False if condition == "disclosed_to_client" else None
        assert _has_documented_waiver(weakened) is False, (
            f"Bedingung '{condition}' ist nicht tragend -- sie liesse sich "
            "entfernen, ohne dass ein Test rot wird"
        )


@pytest.mark.parametrize("blank", ["", "   ", "\t", None])
def test_blank_waiver_document_id_is_no_evidence(blank):
    """Ein leerer String ist kein abgelegtes Dokument.

    Ohne diese Pruefung haette `waiver_document_id=""` -- der Normalfall eines
    leer abgeschickten Formularfelds -- als Nachweis gegolten.
    """
    assert _has_documented_waiver(
        {"disclosed_to_client": True, "waiver_document_id": blank}
    ) is False

    data = _run(disclosed_to_client=True, waiver_document_id=blank)
    assert _retro_items(data)[0]["key"] == "retrocession_retained_unwaived"
    assert not _claims_waiver(data)


def test_missing_evidence_keys_default_to_no_waiver():
    """Fail-closed bei fehlenden SCHLUESSELN, nicht nur bei falschen Werten.

    Aufrufer, die die Nachweisfelder (noch) nicht mitreichen, duerfen keinen
    Verzicht erhalten -- genau diese Luecke war der Befund: die Projektion in
    `build_cost_disclosure()` liess die Felder weg, und der Default war
    "Verzicht dokumentiert".
    """
    assert _has_documented_waiver({}) is False
    data = _run()  # keine Nachweisfelder im Dict
    assert _retro_items(data)[0]["key"] == "retrocession_retained_unwaived"
    assert not _claims_waiver(data)


# ---------------------------------------------------------------------------
# Wirtschaftliche Invarianten
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "disclosed, waiver_doc",
    [(False, None), (True, None), (True, "doc-1")],
)
def test_retained_retrocession_never_moves_the_total(disclosed, waiver_doc):
    """Der unbelegte Fall aendert die Totale NICHT.

    Bewusst so: ihn als Minusposten zu fuehren wuerde eine Rueckerstattung
    behaupten, die nicht stattgefunden hat; ihn zu addieren waere
    Doppelzaehlung (er steckt in den Produktkosten). Die Kennzeichnung
    geschieht ueber `requires_resolution`, nicht ueber eine erfundene Zahl.
    """
    baseline = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
    )
    data = _run(disclosed_to_client=disclosed, waiver_document_id=waiver_doc)
    assert data["totals"] == baseline["totals"]
    assert _retro_items(data)[0]["amount_rappen"] == 50_000
    assert _retro_items(data)[0]["included_in_total"] is False


def test_reimbursed_retrocession_needs_no_waiver_evidence():
    """Eine tatsaechlich zurueckerstattete Retrozession braucht keinen Verzicht.

    Der Herausgabeanspruch aus BGE 132 III 460 ist erfuellt. Die
    Nachweispruefung darf diesen Pfad nicht beruehren -- sonst wuerde der
    korrekte Fall als klaerungsbedueftig gemeldet.
    """
    data = _run(reimbursed_to_client=True)  # ohne jeden Nachweis
    items = _retro_items(data)
    assert len(items) == 1
    assert items[0]["key"] == "retrocession_reimbursed"
    assert items[0]["requires_resolution"] is False
    assert items[0]["amount_rappen"] == -50_000
    assert items[0]["included_in_total"] is True


def test_unwaived_warning_names_what_is_missing():
    """Die Warnung muss handlungsfaehig sein, nicht bloss "unvollstaendig"."""
    data = _run(disclosed_to_client=False, waiver_document_id=None)
    warning = next(w for w in data["warnings"] if "BGE 132 III 460" in w)
    assert "keine Offenlegung an den Kunden erfasst" in warning
    assert "kein Verzichts-Dokument abgelegt" in warning

    partial = _run(disclosed_to_client=True, waiver_document_id=None)
    warning = next(w for w in partial["warnings"] if "BGE 132 III 460" in w)
    assert "keine Offenlegung an den Kunden erfasst" not in warning, (
        "Die Warnung darf nur die TATSAECHLICH fehlenden Nachweise nennen"
    )
    assert "kein Verzichts-Dokument abgelegt" in warning
