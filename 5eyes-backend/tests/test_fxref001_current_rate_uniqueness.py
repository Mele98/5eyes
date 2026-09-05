"""FX-REF-001 (2026-08-27, Marktpreis-/FX-Referenzintegritaetsaudit):
current-FX-row uniqueness/quantization was not strictly validated pre/post
integer conversion.

Ausgangslage (siehe docs/audits/2026-08-27-market-price-and-fx-reference-
integrity-audit.md):

* `PUT /fx-rates` prueft ``rate`` nur VOR der Integer-Quantisierung
  (``rate_x10000 = round(rate * 10000)``). Ein Wert wie ``0.00001`` besteht
  ``> 0`` und ``<= 1000`` auf dem Float, quantisiert aber zu ``0`` -- HTTP
  200, neue globale Current-Zeile mit ``rate_x10000=0``. Der strikte
  Solver-Loader (``FXRateSource.from_db_for_model``) blockiert danach
  global; der aeltere Reporting-Loader (``FXRateSource.from_db``) ueberliest
  dieselbe Nullzeile still und rechnet mit Defaults weiter.
* ``rate: true`` wird von Pydantics laxer float-Koerzion unbemerkt zu
  ``1.0``.
* ``rate: NaN`` besteht den reinen ``<= 0``-Vergleich (Vergleiche mit NaN
  sind immer False) und liess ``round()`` bislang mit HTTP 500 crashen.
* Die Tabelle hatte weder Range-/Bool-CHECK noch einen Partial-Unique-Index
  fuer ``(currency) WHERE is_current=1 AND valid_until IS NULL``. Die
  Current-Eindeutigkeit war ausschliesslich applikationsseitig
  (``with_for_update()``) geschuetzt -- kein Schutz fuer zwei echte
  parallele Erstwrites einer Waehrung ohne bestehende Current-Zeile (dort
  gibt es fuer FOR UPDATE nichts zu sperren).

Dieser Test beweist die Rot->Gruen-Reproduktion der drei Luecken und dass
der normale Berater-Workflow (Upsert, Rollover, Mehrfach-Waehrungen in einem
Batch) unveraendert funktioniert.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, ensure_current_anchor_unique_indexes, get_db
from main import app  # noqa: F401 -- import registers the full ORM model set
from models.fx_rate import FXRate
from models.users import User
from services.auth import get_current_user


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fxref001.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="advisor-fxref001", username="advisor-fxref001", password_hash="h",
        full_name="FX-REF-001 Advisor", role="advisor", is_active=1,
        created_at=_now_iso(), updated_at=_now_iso(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _fx_row(row_id: str, *, currency: str, rate_x10000: int, is_current: int = 1,
            valid_until: str | None = None):
    now = _now_iso()
    return {
        "id": row_id,
        "currency": currency,
        "rate_x10000": rate_x10000,
        "valid_from": now,
        "valid_until": valid_until,
        "is_current": is_current,
        "source": "Manual",
        "notes": None,
        "created_at": now,
        "updated_at": now,
        "created_by": "advisor-fxref001",
    }


# ── Rot->Gruen: positiver Float quantisiert zu einer ungueltigen Nullzeile ──

def test_rate_that_quantizes_to_zero_is_rejected_not_persisted(auth_client, session_factory):
    """Kernreproduktion des Audits: rate=0.00001 ist > 0 und <= 1000, aber
    round(0.00001 * 10000) == 0. Muss VOR der Persistenz scheitern, nicht als
    HTTP 200 mit einer rate_x10000=0-Zeile enden."""
    resp = auth_client.put("/fx-rates", json={"rates": [{"currency": "jpy", "rate": 0.00001}]})
    assert resp.status_code == 422, resp.text

    with session_factory() as s:
        assert s.query(FXRate).filter(FXRate.currency == "JPY").count() == 0


def test_smallest_valid_quantized_rate_is_accepted(auth_client, session_factory):
    """Regressionsgrenze: rate_x10000=1 (kleinstmoeglicher gueltiger Wert)
    darf weiterhin durchgehen -- die neue Pruefung darf nicht ueberschiessen."""
    resp = auth_client.put("/fx-rates", json={"rates": [{"currency": "jpy", "rate": 0.0001}]})
    assert resp.status_code == 200, resp.text

    with session_factory() as s:
        row = s.query(FXRate).filter(FXRate.currency == "JPY", FXRate.is_current == 1).one()
        assert row.rate_x10000 == 1


# ── Rot->Gruen: Bool wird von Pydantic zu 1.0 koerziert ────────────────────

def test_boolean_rate_is_rejected(auth_client, session_factory):
    resp = auth_client.put("/fx-rates", json={"rates": [{"currency": "usd", "rate": True}]})
    assert resp.status_code == 422, resp.text
    with session_factory() as s:
        assert s.query(FXRate).filter(FXRate.currency == "USD").count() == 0


# ── Rot->Gruen: NaN bestand den <=0 Vergleich und crashte round() mit 500 ──

def test_nan_rate_yields_stable_422_not_500(auth_client, session_factory):
    resp = auth_client.put(
        "/fx-rates",
        content=b'{"rates": [{"currency": "jpy", "rate": NaN}]}',
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.status_code != 500
    with session_factory() as s:
        assert s.query(FXRate).filter(FXRate.currency == "JPY").count() == 0


def test_infinity_rate_is_rejected(auth_client, session_factory):
    resp = auth_client.put(
        "/fx-rates",
        content=b'{"rates": [{"currency": "jpy", "rate": Infinity}]}',
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 422, resp.text
    with session_factory() as s:
        assert s.query(FXRate).filter(FXRate.currency == "JPY").count() == 0


# ── Batch-Prevalidation: doppelte Waehrung im selben Request ───────────────

def test_duplicate_currency_in_batch_is_rejected_atomically(auth_client, session_factory):
    # Bestehende Current-Zeile fuer USD anlegen, um zu beweisen, dass ein
    # abgelehnter Batch sie unveraendert laesst (Fix-Vertrag Punkt 3).
    resp = auth_client.put("/fx-rates", json={"rates": [{"currency": "usd", "rate": 0.9}]})
    assert resp.status_code == 200, resp.text

    resp = auth_client.put(
        "/fx-rates",
        json={"rates": [
            {"currency": "usd", "rate": 0.91},
            {"currency": "usd", "rate": 0.92},
        ]},
    )
    assert resp.status_code == 422, resp.text

    with session_factory() as s:
        rows = s.query(FXRate).filter(FXRate.currency == "USD").all()
        assert len(rows) == 1
        assert rows[0].is_current == 1
        assert rows[0].rate_x10000 == 9000  # unveraendert vom ersten Upsert


# ── CHF-Identitaet bleibt nach Quantisierung exakt 10000 ───────────────────

def test_chf_rate_must_quantize_to_exactly_10000(auth_client, session_factory):
    resp = auth_client.put("/fx-rates", json={"rates": [{"currency": "chf", "rate": 1.0}]})
    assert resp.status_code == 200, resp.text
    with session_factory() as s:
        row = s.query(FXRate).filter(FXRate.currency == "CHF", FXRate.is_current == 1).one()
        assert row.rate_x10000 == 10000


# ── Normaler Berater-Workflow bleibt unveraendert (Regression) ─────────────

def test_normal_rollover_still_produces_exactly_one_current_row(auth_client, session_factory):
    auth_client.put("/fx-rates", json={"rates": [{"currency": "eur", "rate": 0.95}]})
    resp = auth_client.put("/fx-rates", json={"rates": [{"currency": "eur", "rate": 0.97}]})
    assert resp.status_code == 200, resp.text

    with session_factory() as s:
        current = s.query(FXRate).filter(
            FXRate.currency == "EUR", FXRate.is_current == 1
        ).all()
        assert len(current) == 1
        assert current[0].rate_x10000 == 9700
        historical = s.query(FXRate).filter(
            FXRate.currency == "EUR", FXRate.is_current == 0
        ).all()
        assert len(historical) == 1
        assert historical[0].valid_until is not None


def test_multiple_distinct_currencies_in_one_batch_still_accepted(auth_client, session_factory):
    resp = auth_client.put(
        "/fx-rates",
        json={"rates": [
            {"currency": "usd", "rate": 0.9},
            {"currency": "gbp", "rate": 1.12},
        ]},
    )
    assert resp.status_code == 200, resp.text
    with session_factory() as s:
        assert {r.currency for r in s.query(FXRate).filter(FXRate.is_current == 1)} == {
            "USD", "GBP",
        }


# ── DB-Ebene: Partial-Unique-Index faengt echte parallele Erstwrites ───────

def test_db_level_unique_index_rejects_two_true_concurrent_first_writes(session_factory):
    """with_for_update() sperrt beim ersten Insert einer Waehrung keine
    existierende Zeile -- fuer FOR UPDATE gibt es dort nichts zu sperren.
    Zwei echte parallele Erstwrites (zwei Sessions, keine bestehende
    AUD-Zeile) muessen deshalb auf DB-Ebene ueber den neuen Partial-Unique-
    Index abgefangen werden."""
    session_a = session_factory()
    session_b = session_factory()
    try:
        session_a.add(FXRate(**_fx_row("aud-writer-a", currency="AUD", rate_x10000=6500)))
        session_b.add(FXRate(**_fx_row("aud-writer-b", currency="AUD", rate_x10000=6600)))

        session_a.commit()
        with pytest.raises(IntegrityError):
            session_b.commit()
        session_b.rollback()

        with session_factory() as s:
            current = s.query(FXRate).filter(
                FXRate.currency == "AUD", FXRate.is_current == 1
            ).all()
            assert len(current) == 1
            assert current[0].id == "aud-writer-a"
    finally:
        session_a.close()
        session_b.close()


def test_soft_replaced_historical_fx_rows_do_not_block_new_current(session_factory):
    """Regression: das Partial-Unique-Index-Praedikat (``is_current = 1 AND
    valid_until IS NULL``) darf normale Versionierung nicht blockieren --
    historische Zeilen (is_current=0, valid_until gesetzt) fuer dieselbe
    Waehrung sind erlaubt und beliebig viele."""
    with session_factory() as s:
        s.add_all([
            FXRate(**_fx_row(
                "usd-hist-1", currency="USD", rate_x10000=8800, is_current=0,
                valid_until=_now_iso(),
            )),
            FXRate(**_fx_row(
                "usd-hist-2", currency="USD", rate_x10000=8900, is_current=0,
                valid_until=_now_iso(),
            )),
            FXRate(**_fx_row("usd-current", currency="USD", rate_x10000=9000)),
        ])
        s.commit()

    with session_factory() as s:
        assert s.query(FXRate).filter(FXRate.currency == "USD").count() == 3
        assert s.query(FXRate).filter(
            FXRate.currency == "USD", FXRate.is_current == 1
        ).count() == 1


# ── Desktop-Repair-Pfad: bestehende SQLite-DBs ohne den neuen Index ────────

def test_legacy_sqlite_db_without_index_is_repaired_and_then_fails_closed(tmp_path):
    """``ensure_current_anchor_unique_indexes`` (database.py) laeuft bei
    jedem Start gegen bestehende Tier-1-Desktop-DBs (Holger). Eine DB, die
    vor diesem Fix erstellt wurde, hat fx_rates ohne den Partial-Unique-
    Index. Der Reparaturpfad muss ihn nachziehen -- idempotent, und
    anschliessend muss ein doppelter direkter Insert (der vorher moeglich
    war) fehlschlagen."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-fx-rates.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE fx_rates ("
                "id TEXT PRIMARY KEY, currency TEXT NOT NULL, "
                "rate_x10000 INTEGER NOT NULL, valid_from TEXT NOT NULL, "
                "valid_until TEXT, is_current INTEGER NOT NULL, "
                "source TEXT, notes TEXT, created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL, created_by TEXT)"
            )
            connection.execute(
                FXRate.__table__.insert(),
                _fx_row("legacy-usd", currency="USD", rate_x10000=8800),
            )

        assert "ux_fx_rate_one_current" not in {
            item["name"] for item in inspect(engine).get_indexes("fx_rates")
        }

        ensure_current_anchor_unique_indexes(engine)
        ensure_current_anchor_unique_indexes(engine)  # idempotent

        migrated = {
            item["name"]: item for item in inspect(engine).get_indexes("fx_rates")
        }["ux_fx_rate_one_current"]
        assert migrated["unique"] == 1
        assert migrated["column_names"] == ["currency"]

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    FXRate.__table__.insert(),
                    _fx_row("legacy-usd-2", currency="USD", rate_x10000=8900),
                )
    finally:
        engine.dispose()
