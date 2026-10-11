"""CMA-CORRELATION-JURISDICTION-PROVENANCE-001.

Returns und Volatilitaeten einer CMA-Zeile sind jurisdiktionsbewusst und
fail-closed -- fehlt ein Wert, gibt es einen ``CMAValidationError``. Die
5x5-Bucket-Korrelationsmatrix bekam diese Behandlung nie: fehlt ihr Payload,
wird der "canonical Swiss-market default" eingesetzt, **unabhaengig von
``cma.jurisdiction``**. Ein DE-Mandat rechnet seine Risikozahlen damit auf
schweizerischen Abhaengigkeiten.

Diese Suite trennt streng zwei Dinge:

* **Gefixt** -- die Herkunft ist jetzt im Nachweis benannt. Der
  Modell-Basis-Block sagt, welche Korrelationsstruktur gerechnet wurde und ob
  sie zur Jurisdiktion passt.
* **Offen (strict xfail)** -- ob eine Nicht-CH-Jurisdiktion ohne eigene Matrix
  ueberhaupt noch live rechnen darf. Das ist fail-closed die konsequente
  Antwort, hat aber echte Bruchflaeche (der DE-Pfad ruht heute tragend auf dem
  Fallback) und verlangt eine freigegebene Matrix, die NICHT erfunden wird.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from sqlalchemy.orm import configure_mappers

from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation,
    clients,
    mandates,
    profiling,
    review,
    snapshots,
    users,
    wealth,
)

configure_mappers()

from models.allocation import CapitalMarketAssumption
from services.cma_correlation_provenance import (
    EXPLICIT_CMA_SOURCE,
    JURISDICTION_DEFAULT_CORRELATION_SOURCES,
    SWISS_MARKET_DEFAULT_SOURCE,
    UNKNOWN_SOURCE,
    UNRESOLVED_SOURCE,
    bucket_correlation_provenance,
    correlation_matrix_digest,
    normalized_jurisdiction,
)


def _cma(*, jurisdiction: str | None, correlation_matrix_json: str | None = None):
    return CapitalMarketAssumption(
        id=f"cma-prov-{jurisdiction or 'none'}",
        assumption_set_name="PROV",
        version=1,
        valid_from="2026-01-01",
        is_current=1,
        jurisdiction=jurisdiction,
        correlation_matrix_json=correlation_matrix_json,
    )


def _valid_matrix(off_diagonal: float) -> list[list[float]]:
    """PSD-Matrix mit einheitlicher Nebendiagonale (0 <= rho < 1 ist immer PSD)."""
    size = 5
    return [
        [1.0 if i == j else off_diagonal for j in range(size)] for i in range(size)
    ]


# ── Gefixt: die Herkunft steht im Nachweis ───────────────────────────────────


def test_ch_without_payload_is_a_matched_default() -> None:
    """CH ohne eigene Matrix: Schweizer Default, und das passt zur Jurisdiktion."""
    provenance = bucket_correlation_provenance(_cma(jurisdiction="CH"))
    assert provenance["source"] == SWISS_MARKET_DEFAULT_SOURCE
    assert provenance["jurisdiction"] == "CH"
    assert provenance["jurisdiction_matched"] is True
    assert provenance["matrix_digest"]


def test_missing_jurisdiction_is_treated_as_ch() -> None:
    """Gleiche Normalform wie validate_runtime_cma_completeness().

    Laufen Nachweis und Validierung hier auseinander, beschreibt der Nachweis
    einen anderen Lauf als den, der validiert wurde.
    """
    assert normalized_jurisdiction(_cma(jurisdiction=None)) == "CH"
    assert normalized_jurisdiction(_cma(jurisdiction="  de ")) == "DE"
    provenance = bucket_correlation_provenance(_cma(jurisdiction=None))
    assert provenance["jurisdiction"] == "CH"
    assert provenance["jurisdiction_matched"] is True


@pytest.mark.parametrize("jurisdiction", ["DE", "US", "AT", "FR"])
def test_non_ch_without_payload_is_flagged_as_foreign_market(jurisdiction: str) -> None:
    """DER Kernbefund: Nicht-CH ohne eigene Matrix rechnet auf Fremdmarkt-Korrelationen.

    Vorher war das im Nachweis nicht erkennbar. Jetzt weist
    ``jurisdiction_matched = False`` es ausdruecklich aus -- die Zahl wird nicht
    ersetzt, aber sie ist nicht mehr stumm.
    """
    provenance = bucket_correlation_provenance(_cma(jurisdiction=jurisdiction))
    assert provenance["jurisdiction"] == jurisdiction
    assert provenance["source"] == SWISS_MARKET_DEFAULT_SOURCE
    assert provenance["jurisdiction_matched"] is False, (
        f"{jurisdiction} rechnet auf der Schweizer Matrix, ohne dass der "
        "Nachweis das ausweist"
    )


def test_explicit_payload_is_always_matched() -> None:
    """Eine CMA-Zeile mit eigener Matrix ist per Definition passend.

    Die Zeile traegt ihre Jurisdiktion UND ihre Matrix -- da gibt es keinen
    Fremdmarkt-Fallback mehr, auch nicht fuer DE.
    """
    payload = json.dumps(_valid_matrix(0.3))
    provenance = bucket_correlation_provenance(
        _cma(jurisdiction="DE", correlation_matrix_json=payload)
    )
    assert provenance["source"] == EXPLICIT_CMA_SOURCE
    assert provenance["jurisdiction"] == "DE"
    assert provenance["jurisdiction_matched"] is True


def test_different_matrices_yield_different_digests() -> None:
    """Der Digest unterscheidet Laeufe mit verschiedenen Korrelationsannahmen."""
    first = bucket_correlation_provenance(
        _cma(jurisdiction="CH", correlation_matrix_json=json.dumps(_valid_matrix(0.2)))
    )
    second = bucket_correlation_provenance(
        _cma(jurisdiction="CH", correlation_matrix_json=json.dumps(_valid_matrix(0.4)))
    )
    assert first["matrix_digest"] != second["matrix_digest"]


def test_digest_ignores_formatting_but_not_content() -> None:
    """Der Digest laeuft ueber die validierten Zahlen, nicht ueber den Rohtext.

    Sonst waere er ein Formatierungs-Hash: dieselbe Matrix mit anderer
    JSON-Formatierung oder als Integer notiert haette einen anderen Digest und
    zwei identische Laeufe erschienen verschieden.
    """
    compact = json.dumps(_valid_matrix(0.25), separators=(",", ":"))
    spaced = json.dumps(_valid_matrix(0.25), indent=2)
    integers = json.dumps([[1 if i == j else 0 for j in range(5)] for i in range(5)])

    assert bucket_correlation_provenance(
        _cma(jurisdiction="CH", correlation_matrix_json=compact)
    )["matrix_digest"] == bucket_correlation_provenance(
        _cma(jurisdiction="CH", correlation_matrix_json=spaced)
    )["matrix_digest"]

    assert correlation_matrix_digest(
        [[1 if i == j else 0 for j in range(5)] for i in range(5)]
    ) == correlation_matrix_digest(
        [[1.0 if i == j else 0.0 for j in range(5)] for i in range(5)]
    )
    assert (
        bucket_correlation_provenance(
            _cma(jurisdiction="CH", correlation_matrix_json=integers)
        )["matrix_digest"]
        != bucket_correlation_provenance(
            _cma(jurisdiction="CH", correlation_matrix_json=compact)
        )["matrix_digest"]
    )


def test_invalid_payload_is_reported_not_swallowed() -> None:
    """Eine ungueltige Matrix wird als unaufgeloest ausgewiesen.

    Der Nachweis darf nicht an seiner eigenen Beschreibung scheitern (er wird
    auch fuer Legacy-/Fallback-Laeufe gebaut), aber er darf auch nicht
    "Schweizer Default" behaupten, wo in Wahrheit Muell steht.
    """
    provenance = bucket_correlation_provenance(
        _cma(jurisdiction="CH", correlation_matrix_json='[[1,2],[3,4]]')
    )
    assert provenance["source"] == UNRESOLVED_SOURCE
    assert provenance["jurisdiction_matched"] is False
    assert provenance["matrix_digest"] is None


def test_absent_cma_is_unknown_not_guessed() -> None:
    """Ohne CMA im Scope wird "unbekannt" ausgewiesen, nicht "CH-Default" geraten."""
    provenance = bucket_correlation_provenance(None)
    assert provenance["source"] == UNKNOWN_SOURCE
    assert provenance["jurisdiction"] is None
    assert provenance["jurisdiction_matched"] is False


def test_registry_holds_only_committee_backed_jurisdictions() -> None:
    """Die Registry enthaelt genau CH -- keine erfundene Fremdmarkt-Matrix.

    Dieser Test ist die Bremse gegen die naheliegende "Verbesserung", eine
    plausibel aussehende DE-/US-Matrix zu hinterlegen. Aus einem benennbaren
    Fremdmarkt-Fallback wuerde damit eine Zahl ohne Quelle, die niemand mehr
    als Luecke erkennt. Ein Eintrag hier gehoert zusammen mit einer
    IC-freigegebenen Matrix und einer Aktualisierung dieses Tests.
    """
    assert set(JURISDICTION_DEFAULT_CORRELATION_SOURCES) == {"CH"}


# ── Offen: Fail-Closed fuer Nicht-CH ohne eigene Matrix ──────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CMA-CORRELATION-JURISDICTION-PROVENANCE-001 (offen, Produktentscheid): "
        "Returns und Volatilitaeten sind pro Jurisdiktion fail-closed, die "
        "Korrelationsmatrix nicht -- eine Nicht-CH-CMA ohne eigene Matrix "
        "rechnet weiter auf der Schweizer Struktur, statt den Lauf zu "
        "verweigern. Die Herkunft ist jetzt im Nachweis benannt "
        "(jurisdiction_matched=False), der Lauf wird aber nicht blockiert. "
        "Fail-closed waere die konsequente Antwort, hat aber echte "
        "Bruchflaeche: der gesamte DE-Pfad ruht heute tragend auf dem Fallback "
        "(28 Aufrufstellen von _seed_de_mandate ueber 7 Testdateien, die DE-CMA "
        "setzt jurisdiktionsspezifische Returns/Vols, aber keine Matrix). Der "
        "Fix verlangt eine IC-freigegebene Matrix pro Jurisdiktion -- die wird "
        "bewusst NICHT erfunden, gleiche Linie wie HEDGED-ALKOHOL-GAP-001."
    ),
)
def test_non_ch_without_own_correlation_matrix_is_refused() -> None:
    """Reproducer: fehlende jurisdiktionsgerechte Korrelationen muessen den Lauf stoppen.

    Gruen wird dieser Test, sobald die Validierung die Korrelationsmatrix
    genauso behandelt wie die Returns und Volatilitaeten: fuer eine
    Nicht-CH-Jurisdiktion ist eine fehlende Matrix ein Domaenenfehler, kein
    Fallback.
    """
    from services.cma_validation import CMAValidationError
    from services.cma_validation import validate_runtime_cma_completeness

    de_cma = _cma(jurisdiction="DE")
    # Returns/Vols vollstaendig, damit der Test genau die Korrelation prueft
    # und nicht an einem anderen fehlenden Feld vorbei gruen/rot wird.
    de_cma.equity_home_return_bps = 650
    de_cma.equity_home_vol_bps = 1500
    de_cma.bonds_home_ig_return_bps = 200
    de_cma.bonds_home_ig_vol_bps = 380
    de_cma.real_estate_home_return_bps = 420
    de_cma.real_estate_home_vol_bps = 800
    de_cma.alternatives_gold_return_bps = 300
    de_cma.alternatives_gold_vol_bps = 1400
    de_cma.liquidity_return_bps = 50
    de_cma.liquidity_vol_bps = 30

    with pytest.raises(CMAValidationError):
        validate_runtime_cma_completeness(de_cma)
