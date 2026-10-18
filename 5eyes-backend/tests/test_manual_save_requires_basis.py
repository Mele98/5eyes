"""MANUAL-SAVE-BASIS-001 (Owner-Entscheid 2026-10-14).

Generate (und die Sensitivitaetsanalyse) verweigern eine Soll-Allokation fuer
ein Mandat ganz ohne Datenbasis (weder Beratungsvermoegen noch Cashflows) mit
"Keine Vermögensbasis" (``_assert_allocation_has_basis``, 409). Der manuelle
Speicherpfad (``POST /mandates/{id}/target-allocation``) kannte diese Regel
nicht: der Berater konnte fuer ein leeres Mandat eine "aktuelle" Strategie
speichern, deren SOLL-%-Torte ein nicht existierendes Vermoegen vorzeigt.

Vertrag:
A) Manuelles Speichern ohne Vermoegensbasis -> 409 mit derselben deutschen
   Meldung wie Generate; nichts aendert sich (die vorherige Allokation bleibt
   aktuell, keine neue Zeile).
B) Nur Cashflows (Vermoegensaufbau, Beratungsvermoegen 0) -> erlaubt, wie
   bei Generate.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from tests.test_manual_allocation_save_contract import (  # noqa: F401
    SF,
    _assessment,
    _body_from,
    _current,
    _request,
    _seed,
)
import routers.allocation as allocation_router
from models.allocation import TargetAllocation
from models.wealth import Cashflow, WealthPosition

NOW = "2026-10-14T12:00:00.000Z"


def _remove_advisory_wealth(s, client_id) -> None:
    for pos in s.query(WealthPosition).filter(
        WealthPosition.client_id == client_id,
        WealthPosition.deleted_at.is_(None),
    ).all():
        pos.deleted_at = NOW
    s.commit()


def _exclude_cashflows(s, client_id) -> int:
    rows = s.query(Cashflow).filter(Cashflow.client_id == client_id).all()
    for cf in rows:
        cf.is_included = 0
    s.commit()
    return len(rows)


def test_manual_save_without_any_basis_is_rejected_like_generate(SF):
    with SF() as s:
        mandate, adv = _seed(s)
        engine_ta = _current(s, mandate.id)
        engine_id = engine_ta.id
        aid = _assessment(s, mandate.id).id
        count_before = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate.id
        ).count()
        _remove_advisory_wealth(s, mandate.client_id)
        _exclude_cashflows(s, mandate.client_id)

        with pytest.raises(HTTPException) as exc:
            allocation_router.create_target_allocation(
                mandate.id, _body_from(engine_ta, aid), _request(),
                db=s, current_user=adv,
            )
        assert exc.value.status_code == 409
        detail = str(exc.value.detail)
        assert detail.startswith("Keine Vermögensbasis"), detail
        assert "weder Beratungsvermögen noch Cashflows" in detail

        s.rollback()
        assert _current(s, mandate.id).id == engine_id
        assert s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate.id
        ).count() == count_before


def test_manual_save_with_cashflows_only_is_allowed(SF):
    """Vermoegensaufbau: Beratungsvermoegen 0, aber Cashflows -> erlaubt."""
    with SF() as s:
        mandate, adv = _seed(s)
        engine_ta = _current(s, mandate.id)
        aid = _assessment(s, mandate.id).id
        assert s.query(Cashflow).filter(
            Cashflow.client_id == mandate.client_id,
            Cashflow.is_included == 1,
            Cashflow.deleted_at.is_(None),
        ).count() > 0, "Fixture braucht eingeschlossene Cashflows"
        _remove_advisory_wealth(s, mandate.client_id)

        manual = allocation_router.create_target_allocation(
            mandate.id, _body_from(engine_ta, aid), _request(),
            db=s, current_user=adv,
        )
        assert manual.is_current == 1
