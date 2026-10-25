"""CMA-CORRELATION-JURISDICTION-PROVENANCE-001 -- Verdrahtung in der Engine.

Die Modul-Suite (``tests/test_cma_correlation_jurisdiction_provenance.py``)
prueft die Herkunftsbestimmung isoliert. Hier wird der Weg durch die echte
Engine geprueft: ein DE-Mandat mit einer CMA-Zeile ohne eigene
Korrelationsmatrix muss im Modell-Basis-Block ausweisen, dass es auf der
SCHWEIZER Korrelationsstruktur rechnet.

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
from services.cma_correlation_provenance import (
    EXPLICIT_CMA_SOURCE,
    SWISS_MARKET_DEFAULT_SOURCE,
)
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


def test_de_run_discloses_the_swiss_correlation_structure(session_factory) -> None:
    """Der eigentliche Nachweis: DE-Lauf weist Fremdmarkt-Korrelation aus.

    Die DE-CMA-Fixture setzt jurisdiktionsspezifische Returns und
    Volatilitaeten, aber KEINE Korrelationsmatrix -- genau der Zustand, der in
    Produktion entsteht, weil die Jurisdiktions-Seeds gar keine
    Korrelationsdaten enthalten. Der Lauf rechnet deshalb auf der Schweizer
    Struktur, und das muss im Nachweis stehen.
    """
    advisor_id, mandate_id, _tenant_id = _seed_de_mandate(
        session_factory,
        suffix="corr-prov-de",
        cma_status="committee_approved",
    )
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).first()
        generate_recommendation_run(session, mandate, advisor_id, preferences=None)
        session.commit()

    provenance = _persisted_bucket_correlation(session_factory, mandate_id)
    assert provenance["jurisdiction"] == "DE"
    assert provenance["source"] == SWISS_MARKET_DEFAULT_SOURCE
    assert provenance["jurisdiction_matched"] is False, (
        "Ein DE-Mandat rechnet auf schweizerischen Korrelationen, ohne dass "
        "der Nachweis das ausweist -- genau die Luecke, die dieser Befund "
        "schliesst."
    )
    assert provenance["matrix_digest"], "Digest der verwendeten Matrix fehlt"
    assert provenance["dimension"] == 5


def test_de_run_with_own_matrix_is_matched(session_factory) -> None:
    """Gegenprobe: traegt die DE-CMA eine eigene Matrix, ist nichts zu melden.

    Ohne diese Gegenprobe koennte ``jurisdiction_matched`` konstant False sein
    und der Test oben trotzdem gruen.
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
