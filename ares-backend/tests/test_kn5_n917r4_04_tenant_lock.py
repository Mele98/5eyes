"""KN5 / N-917R4-04: Mandantensperre auch bei nicht geladenem Attribut und fuer
Core-DML.

Befund (H-176-Pruefung): ``models/snapshots._guard_tenant_reassignment`` prueft
``history.deleted``. Nach ``db.expire(obj)`` (oder ``refresh`` mit Teilmenge)
ist der alte Wert nicht geladen, ``deleted`` leer -> die Sperre griff nicht.
Core-DML ueber ``connection.execute(update(...))`` umging sie ganz.

Erlaubt bleiben: Anlegen mit tenant_id, NULL -> Default-Mandant, gleicher Wert.
Gegenproben: alter Waechter (nur ``history.deleted``, kein Core-Pruefpunkt) -> rot.
"""
from __future__ import annotations

import pytest
from sqlalchemy import update

from tests.test_ccx_p1_snapshot_hash import session_factory  # noqa: F401


def _published_ids(session_factory, suffix):
    from tests.test_ccx_p4_allocation_publish import _published
    from models.mandates import Mandate

    _a, _b, mid, _aid, _run, _decision = _published(session_factory, suffix)
    with session_factory() as db:
        mandate = db.get(Mandate, mid)
        client_id = mandate.client_id
    with session_factory() as db:  # gesetzte tenant_id (NULL -> Default ist erlaubt)
        from models.clients import Client

        for obj in (db.get(Mandate, mid), db.get(Client, client_id)):
            obj.tenant_id = obj.tenant_id or "main"
        db.commit()
    return mid, client_id


def test_expired_attribute_cannot_be_reassigned(session_factory):
    from models.clients import Client
    from models.mandates import Mandate

    mid, client_id = _published_ids(session_factory, "kn5-expire")
    for model, oid in ((Client, client_id), (Mandate, mid)):
        with session_factory() as db:
            obj = db.get(model, oid)
            db.expire(obj)              # alter Wert nicht mehr geladen
            obj.tenant_id = "firma-b"
            assert not obj.__class__.tenant_id.impl.get_history(
                obj._sa_instance_state, obj._sa_instance_state.dict).deleted  # Befund-Voraussetzung
            with pytest.raises(RuntimeError, match="TENANT_REASSIGNMENT_FORBIDDEN"):
                db.commit()
            db.rollback()
        with session_factory() as db:
            assert db.get(model, oid).tenant_id == "main"


def test_expired_attribute_same_value_is_allowed(session_factory):
    from models.clients import Client

    _mid, client_id = _published_ids(session_factory, "kn5-same")
    with session_factory() as db:
        obj = db.get(Client, client_id)
        db.expire(obj)
        obj.tenant_id = "main"         # unveraendert
        db.commit()


def test_core_update_of_tenant_id_is_forbidden(session_factory):
    from models.clients import Client
    from models.mandates import Mandate
    from models.wealth import WealthPosition

    mid, client_id = _published_ids(session_factory, "kn5-core")
    with session_factory() as db:
        conn = db.connection()
        for statement in (
            update(Client.__table__).where(Client.__table__.c.id == client_id).values(tenant_id="firma-b"),
            update(Mandate.__table__).where(Mandate.__table__.c.id == mid).values(tenant_id="firma-b"),
            update(WealthPosition.__table__).values(tenant_id="firma-b"),
        ):
            with pytest.raises(RuntimeError, match="TENANT_REASSIGNMENT_FORBIDDEN"):
                conn.execute(statement)
        # Wert erst in den Ausfuehrungsparametern.
        with pytest.raises(RuntimeError, match="TENANT_REASSIGNMENT_FORBIDDEN"):
            conn.execute(update(Client.__table__).where(Client.__table__.c.id == client_id), {"tenant_id": "firma-b"})
        db.rollback()
    with session_factory() as db:
        assert db.get(Client, client_id).tenant_id == "main"
        assert db.get(Mandate, mid).tenant_id == "main"


def test_orm_bulk_update_with_tenant_in_parameters_is_forbidden(session_factory):
    from models.clients import Client

    _mid, client_id = _published_ids(session_factory, "kn5-bulk")
    with session_factory() as db:
        with pytest.raises(RuntimeError, match="TENANT_REASSIGNMENT_FORBIDDEN"):
            db.execute(update(Client), [{"id": client_id, "tenant_id": "firma-b"}])
        db.rollback()


def test_other_core_updates_on_locked_tables_stay_allowed(session_factory):
    """Positivkontrolle: Core-UPDATE ohne tenant_id bleibt erlaubt."""
    from models.clients import Client

    _mid, client_id = _published_ids(session_factory, "kn5-ok")
    with session_factory() as db:
        db.connection().execute(update(Client.__table__).where(Client.__table__.c.id == client_id)
                                .values(notes="Notiz (fiktiv)"))
        db.commit()


# -- Querschnitt Freshness (irrelevant -> FRESH, relevant -> STALE) ----------


def test_cross_freshness_kn5_paths(session_factory):
    """KN5: abgewiesene Umhaengung (expired + Core), Aenderung eines nicht
    beratungsrelevanten Felds (ORM) und die Lauf-/Holdings-Auswahl lassen einen
    publizierten SEALED+FRESH-Stand unveraendert; eine relevante Aenderung (Ziel)
    macht ihn STALE (Positivkontrolle). Ein erlaubtes Core-UPDATE invalidiert
    weiterhin konservativ (N-908-02, neue Fassung unbekannt) -- bewusst nicht Teil
    der irrelevanten Menge."""
    from models.clients import Client
    from models.mandates import Mandate
    from services.depot_check import _select_latest_run_with_holdings
    from services.portfolio_engine import _current_recommendation_run
    from tests.test_ccx_p2_invalidation import _envelope, _mutate_goal
    from tests.test_ccx_p4_allocation_publish import _published, _state

    _a, _b, mid, _aid, _run, decision = _published(session_factory, "kn5-xfresh")
    with session_factory() as db:
        client_id = db.get(Mandate, mid).client_id
        client = db.get(Client, client_id)
        client.tenant_id = client.tenant_id or "main"  # NULL -> Default (erlaubt, nicht projiziert)
        db.commit()

    def snap():
        with session_factory() as db:
            env = tuple(_envelope(db, decision.envelope_id)[:2])
        deep = _state(session_factory, mid)
        return env, (deep.status, deep.reason_code)

    before = snap()
    assert before[0] == ("SEALED", "FRESH"), before
    with session_factory() as db:  # abgewiesene Umhaengung, expired
        obj = db.get(Client, client_id)
        db.expire(obj)
        obj.tenant_id = "firma-b"
        with pytest.raises(RuntimeError, match="TENANT_REASSIGNMENT_FORBIDDEN"):
            db.commit()
        db.rollback()
    with session_factory() as db:  # abgewiesenes Core-UPDATE
        with pytest.raises(RuntimeError, match="TENANT_REASSIGNMENT_FORBIDDEN"):
            db.connection().execute(update(Client.__table__).where(Client.__table__.c.id == client_id)
                                    .values(tenant_id="firma-b"))
        db.rollback()
    with session_factory() as db:  # erlaubt, nicht beratungsrelevant (ORM: echte Projektion)
        db.get(Client, client_id).notes = "Notiz (fiktiv)"
        db.commit()
    with session_factory() as db:  # Lauf-/Holdings-Auswahl (nur lesend)
        mandate = db.get(Mandate, mid)
        assert _current_recommendation_run(db, mid).id == _select_latest_run_with_holdings(db, mandate)[0].id
        db.commit()
    assert snap() == before, (before, snap())

    with session_factory() as db:  # relevant: Ziel des Mandats
        _mutate_goal(db, {"mid": mid})
        db.commit()
    after = snap()
    assert after[0] == ("SEALED", "STALE"), after
