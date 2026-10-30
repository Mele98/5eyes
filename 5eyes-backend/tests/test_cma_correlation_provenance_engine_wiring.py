"""CMA-CORRELATION-JURISDICTION-PROVENANCE-001 -- Verdrahtung in der Engine.

Die Modul-Suite (``tests/test_cma_correlation_jurisdiction_provenance.py``)
prueft die Herkunftsbestimmung isoliert. Hier wird der Weg durch die echte
Engine geprueft: ein DE-Mandat mit eigener Korrelationsmatrix weist sie im
Modell-Basis-Block aus; ohne eigene Matrix wird der Lauf seit CMA-001 /
CMA-CORR-001 verweigert statt auf der SCHWEIZER Struktur zu rechnen.

Isoliert geprueft waere die Funktion korrekt und trotzdem wirkungslos -- wenn
der Modell-Basis-Block sie nicht aufruft oder ``cma`` nicht durchgereicht
bekommt, erfaehrt niemand davon. Genau das war der Zustand vorher.

Geprueft wird am PERSISTIERTEN Nachweis
(``TargetAllocation.effective_constraints_json -> optimization_model_basis``),
nicht an einem Live-Rueckgabewert: das ist der unveraenderliche Datensatz, der
die Wahrscheinlichkeiten dieser Allokation begleitet, und genau dort muss
nachlesbar sein, unter welcher Korrelationsannahme sie entstanden ist. Beide
Kanaele -- Entscheidung und Reporting -- lesen dieselbe CMA-Spalte und fuehren
den Block deshalb beide.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _path in (BACKEND_ROOT, TESTS_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import json

from models.allocation import TargetAllocation
from models.mandates import Mandate
import pytest

from services.cma_correlation_provenance import EXPLICIT_CMA_SOURCE
from services.portfolio_engine import generate_recommendation_run

# Wiederverwendete DE-Seed-Fixture (WP2 Engine-Wiring), wie in
# tests/test_provisional_warning_json_and_client_portal.py.
from test_engine_de_jurisdiction_wiring import (  # noqa: F401 (Fixture)
    _seed_de_mandate,
    session_factory,
)


def _persisted_bucket_correlation(session_factory, mandate_id: str) -> dict:
    """Herkunftsblock aus dem persistierten Nachweis der Allokation."""
    with session_factory() as session:
        allocation = (
            session.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == mandate_id)
            .order_by(TargetAllocation.created_at.desc())
            .first()
        )
        assert allocation is not None, "Keine TargetAllocation persistiert"
        raw = allocation.effective_constraints_json
    assert raw, "effective_constraints_json ist leer"
    basis = (json.loads(raw) or {}).get("optimization_model_basis") or {}
    provenance = basis.get("bucket_correlation")
    assert provenance, (
        "optimization_model_basis fuehrt keinen bucket_correlation-Block -- "
        "die Herkunft der Korrelationsmatrix ist im persistierten Nachweis "
        "nicht nachlesbar"
    )
    return provenance


def test_de_run_without_own_matrix_is_refused(session_factory) -> None:
    """CMA-001 / CMA-CORR-001: ein DE-Lauf ohne eigene Korrelationsmatrix
    rechnet nicht mehr auf der Schweizer Struktur, sondern wird verweigert;
    es wird keine Allokation persistiert.

    Vorher (CMA-CORRELATION-JURISDICTION-PROVENANCE-001) lief er und wies nur
    ``jurisdiction_matched=False`` aus.
    """
    from models.allocation import CapitalMarketAssumption

    advisor_id, mandate_id, _tenant_id = _seed_de_mandate(
        session_factory,
        suffix="corr-prov-de",
        cma_status="committee_approved",
    )
    with session_factory() as session:
        row = (
            session.query(CapitalMarketAssumption)
            .filter(CapitalMarketAssumption.jurisdiction == "DE")
            .first()
        )
        row.correlation_matrix_json = None
        session.commit()

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).first()
        with pytest.raises(Exception) as exc_info:
            generate_recommendation_run(session, mandate, advisor_id, preferences=None)
        session.rollback()
    assert "CMA-CORR-001" in str(exc_info.value)
    with session_factory() as session:
        assert session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count() == 0


def test_de_run_with_own_matrix_is_matched(session_factory) -> None:
    """Gegenprobe: traegt die DE-CMA eine eigene Matrix, ist nichts zu melden.

    Positivfall: mit eigener Matrix laeuft der DE-Pfad und ist ``matched``.
    """
    from models.allocation import CapitalMarketAssumption

    advisor_id, mandate_id, _tenant_id = _seed_de_mandate(
        session_factory,
        suffix="corr-prov-de-own",
        cma_status="committee_approved",
    )
    # Eine zulaessige (PSD) Matrix auf die DE-CMA-Zeile legen. Die Zahlen sind
    # hier reine Testdaten -- sie stehen fuer "das IC hat eine DE-Matrix
    # geliefert", nicht fuer eine fachliche Annahme.
    own_matrix = [[1.0 if i == j else 0.3 for j in range(5)] for i in range(5)]
    with session_factory() as session:
        row = (
            session.query(CapitalMarketAssumption)
            .filter(CapitalMarketAssumption.jurisdiction == "DE")
            .first()
        )
        assert row is not None
        row.correlation_matrix_json = json.dumps(own_matrix)
        session.commit()

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).first()
        generate_recommendation_run(session, mandate, advisor_id, preferences=None)
        session.commit()

    provenance = _persisted_bucket_correlation(session_factory, mandate_id)
    assert provenance["source"] == EXPLICIT_CMA_SOURCE
    assert provenance["jurisdiction_matched"] is True
