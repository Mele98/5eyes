"""Kern-Integration H12+K1+K2: Querschnitt-Test Freshness (aus Pruefung H-164).

Uebernommen aus dem Pruefer-Test (N-912-01, N-912-04). Ein publizierter
SEALED+FRESH-Lauf muss nach IRRELEVANTEN Aenderungen unveraendert bleiben:

Teil A (H12-Siegel-Ausnahme): neuer FX-Kurs einer Waehrung, die das Mandat
nicht haelt (GBP, JPY), sowie Aenderungen an einem anderen Mandat (Ziel) und
einem anderen Kunden (Position) lassen Envelope, Siegel, FX-Ausnahme,
Wasserzeichen und Publikationsstatus (deep/shallow) unveraendert.
Positivkontrollen: das andere Mandat wird STALE; eine Aenderung am eigenen
Mandat nimmt Siegel und Ausnahme weg.

Teil B (K1 E2E-03, v5-Hash ueber effektive Kurse): nach einem neuen GBP/JPY-
Kurs liefern die gegateten Kunden-PDFs (u. a. Assetallocation und
Contract-Signoff) eines publizierten CHF-Mandats weiterhin 200 und final.
Gegenprobe: mit dem Snapshot-Default v4 (ohne core.fx_freshness) wird Teil B rot.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from tests.test_ccx_p1_snapshot_hash import session_factory  # noqa: F401
from tests.test_ccx_p2_invalidation import _envelope, _ids, _mutate_goal
from tests.test_ccx_p4_allocation_publish import _mandate, _published, _state


def _new_rate(db, currency, rate):
    from models.fx_rate import FXRate

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for row in db.query(FXRate).filter(FXRate.currency == currency, FXRate.is_current == 1).all():
        row.is_current, row.valid_until, row.updated_at = 0, now, now
    db.flush()
    db.add(FXRate(id=str(uuid.uuid4()), currency=currency, rate_x10000=int(rate * 10000),
                  valid_from=now[:10], is_current=1, source="Manual", notes="Pruefer",
                  created_at=now, updated_at=now))


def _snapshot(session_factory, mid, run_id, envelope_id, monkeypatch):
    import services.allocation_publication_gate as pub
    import services.print_fx_gate as fxgate

    with session_factory() as db:
        mandate = _mandate(db, mid)
        env = tuple(_envelope(db, envelope_id)[:2])
        sealed = fxgate.run_is_sealed(db, mandate, run_id)
        watermark = pub.customer_document_watermark(db, mandate)
        with monkeypatch.context() as m:
            m.setattr(fxgate, "mandate_amount_currencies", lambda _db, _m: {"CHF", "USD"})
            exempt = True
            try:
                fxgate.assert_print_fx_basis_current(db, mandate, run_id=run_id)
            except Exception:  # noqa: BLE001
                exempt = False
    deep = _state(session_factory, mid)
    shallow = _state(session_factory, mid, deep=False)
    return {"envelope": env, "sealed": sealed, "exempt": exempt, "watermark": watermark,
            "deep": (deep.status, deep.reason_code), "shallow": (shallow.status, shallow.reason_code)}


def test_irrelevant_changes_keep_sealed_fresh_run_exempt_and_published(session_factory, monkeypatch):
    advisor_id, _approver, mid, _aid, run_id, decision = _published(session_factory, "xc-a")
    envelope_id = decision.envelope_id
    before = _snapshot(session_factory, mid, run_id, envelope_id, monkeypatch)
    assert before["envelope"] == ("SEALED", "FRESH")
    assert before["sealed"] is True and before["exempt"] is True and before["watermark"] is None, before

    # 1. FX-Kurs einer Fremdwaehrung, die das Mandat nicht haelt
    with session_factory() as db:
        with db.no_autoflush:
            _new_rate(db, "GBP", 1.1234)
            _new_rate(db, "JPY", 0.0061)
        db.commit()
    after_fx = _snapshot(session_factory, mid, run_id, envelope_id, monkeypatch)
    assert after_fx == before, ("FX fremde Waehrung", before, after_fx)

    # 2. anderes Mandat (Ziel) und anderer Kunde (Position)
    other = _ids(session_factory, "xc-b")
    with session_factory() as db:
        db.info["ares_actor_user_id"] = other["advisor"]
        _mutate_goal(db, other)
        db.execute(text("SELECT 1"))
        from models.wealth import WealthPosition
        pos = db.query(WealthPosition).filter(WealthPosition.client_id == other["cid"]).first()
        pos.current_value_rappen = int(pos.current_value_rappen or 0) + 100_00
        db.commit()
    with session_factory() as db:
        assert _envelope(db, other["envelope"])[1] == "STALE"  # Positivkontrolle: Mutation wirkt
    after_other = _snapshot(session_factory, mid, run_id, envelope_id, monkeypatch)
    assert after_other == before, ("anderes Mandat", before, after_other)

    # Positivkontrolle: relevante Aenderung am eigenen Mandat -> STALE, keine Ausnahme
    with session_factory() as db:
        db.info["ares_actor_user_id"] = advisor_id
        _mutate_goal(db, {"mid": mid})
        db.commit()
    after_own = _snapshot(session_factory, mid, run_id, envelope_id, monkeypatch)
    assert after_own["envelope"] == ("SEALED", "STALE")
    assert after_own["sealed"] is False and after_own["exempt"] is False
    assert after_own["deep"][0] != "PUBLISHED" or after_own["watermark"] is not None


def test_irrelevant_fx_change_keeps_run_amount_pdfs_final(session_factory):
    """Kunden-PDF (run_amounts / gegatet) eines publizierten CHF-Mandats: nach
    neuem GBP/JPY-Kurs weiterhin 200 und final (kein Entwurf)."""
    from tests.test_h12_ccx_hygiene import _gated_calls, _text, _user

    advisor_id, _approver, mid, _aid, _run, _decision = _published(session_factory, "xc-pdf")
    calls = _gated_calls()
    results = {}
    for phase in ("before", "after"):
        if phase == "after":
            with session_factory() as db:
                with db.no_autoflush:
                    _new_rate(db, "GBP", 1.1234)
                    _new_rate(db, "JPY", 0.0061)
                db.commit()
        for name, call in calls.items():
            with session_factory() as db:
                try:
                    resp = call(mid, db, _user(db, advisor_id))
                    body = _text(resp.body)
                    results[(phase, name)] = (resp.status_code, "nicht publiziert" in body)
                except Exception as exc:  # noqa: BLE001
                    results[(phase, name)] = ("EXC", getattr(exc, "reason_code", None) or str(getattr(exc, "detail", exc))[:200])
    print("XC-RESULTS", results)
    for name in calls:
        assert results[("before", name)] == (200, False), (name, results)
        assert results[("after", name)] == results[("before", name)], (name, results)
