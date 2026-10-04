"""Red test for GOAL-PAST-DATE-LIFECYCLE-001 (round 38 audit), Pflichttest 5.

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md,
section "Finding GOAL-PAST-DATE-LIFECYCLE-001", Pflichttest 5: a goal marked
as fulfilled/cancelled must remain visible/queryable (not deleted) but must
contribute ZERO to the optimizer's liability calculation.

Schema-Check (Stand develop d1fe2e8, verifiziert gegen models/wealth.py::Goal):
es gibt KEIN typisiertes Lifecycle-/Status-Feld (kein `fulfilled`, kein
`cancelled`, kein `status`). Die einzigen vorhandenen Felder sind `is_active`
(Integer, default 1) und das generische Soft-Delete-Feld `deleted_at`. Dieser
Test benutzt `is_active=0` als naechstliegenden Proxy fuer "storniert /
erfuellt" -- das ist die beste heute verfuegbare Annaeherung an den
Soll-Vertrag (Audit-Reparaturvertrag Punkt 1: "Ein Goal besitzt einen
typisierten Lifecycle").

Zwei getrennte Eigenschaften werden hier geprueft:

1. Sichtbarkeit (NICHT xfail -- dieser Teil ist heute bereits korrekt):
   ein Goal mit is_active=0 wird nicht geloescht (deleted_at bleibt None)
   und bleibt ueber eine normale Query auffindbar.

2. Wirtschaftliche Null-Wirkung auf die Optimizer-Liability (xfail strict):
   `goal_to_liability()` in services/optimizer/goal_liabilities.py liest
   `is_active` an KEINER Stelle (verifiziert: keine is_active-Referenz im
   gesamten Modul). Die einzige heute existierende Absicherung liegt
   AUSSERHALB dieses Moduls, in
   services/portfolio_engine.py::_strictly_active_rows(), die inaktive
   Goals VOR dem Aufruf von goals_to_liabilities() aus der Liste entfernt.
   Ruft man goal_to_liability() direkt auf (oder ein Aufrufer, der diesen
   Upstream-Filter umgeht/vergisst), berechnet es fuer ein is_active=0-Goal
   exakt dieselbe volle Liability wie fuer ein aktives Ziel. Das Modul
   selbst hat also keine eigene Lifecycle-Absicherung -- genau die Luecke,
   die dieser Red-Test dokumentiert.
"""
from __future__ import annotations

import datetime
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from main import app  # noqa: F401 -- imports the full model graph for metadata.create_all()
from models.wealth import Goal
from services.optimizer.goal_liabilities import goal_to_liability

_FUTURE_TARGET_DATE = (date.today() + timedelta(days=3 * 365)).isoformat()


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_fulfilled_cancelled_visible_but_null.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_cancelled_goal_row(goal_id: str = "cancelled-goal-1") -> Goal:
    """Goal-ORM-Zeile mit `is_active=0` als Proxy fuer storniert/erfuellt.

    target_date liegt bewusst 3 Jahre in der Zukunft (nicht in der
    Vergangenheit) -- dieser Test soll ausschliesslich die is_active-Luecke
    pruefen, nicht das separat dokumentierte Past-Date-Clamping-Problem
    (siehe die anderen Pflichttest-Dateien zu GOAL-PAST-DATE-LIFECYCLE-001).
    """
    now = _utc_now_iso()
    return Goal(
        id=goal_id,
        mandate_id="mandate-1",
        client_id="client-1",
        goal_family="Ausgaben",
        goal_type="Einmalige_Ausgabe",
        label="Stornierte/erfuellte Einmalausgabe",
        rank=1,
        goal_scope="Beratungsvermoegen",
        value_mode="nominal",
        target_amount_rappen=50_000_00,
        is_ongoing=0,
        hardness="Primaer",
        target_date=_FUTURE_TARGET_DATE,
        is_active=0,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


def _make_cancelled_goal_namespace(goal_id: str = "cancelled-goal-1") -> SimpleNamespace:
    """Minimal mock-Goal (SimpleNamespace), mirrors tests/test_optimizer_goal_liabilities.py::_make_goal.

    Same economic shape as `_make_cancelled_goal_row()` above, but as the
    plain attribute-bag goal_to_liability() actually consumes.
    """
    return SimpleNamespace(
        id=goal_id,
        label="Stornierte/erfuellte Einmalausgabe",
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=50_000_00,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=10,
        target_date=_FUTURE_TARGET_DATE,
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=None,
        success_probability_min_x100=None,
        # Proxy fuer "storniert/erfuellt" -- siehe Modul-Docstring. Dieses
        # Feld existiert nur zur Dokumentation des Inputs; goal_to_liability()
        # liest es nicht (das ist genau die gepruefte Luecke).
        is_active=0,
        deleted_at=None,
    )


def test_inactive_goal_remains_visible_and_not_deleted(session_factory):
    """Proxy-Verhalten, das HEUTE schon korrekt ist (kein xfail).

    is_active=0 darf nicht mit Loeschung verwechselt werden: die Zeile bleibt
    in der DB, `deleted_at` bleibt None, und eine normale Query (ohne
    is_active-Filter) findet sie weiterhin. Faellt dieser Teil jemals aus,
    waere das eine Regression der Sichtbarkeits-Garantie, nicht nur eine
    fehlende Lifecycle-Verfeinerung.
    """
    session = session_factory()
    try:
        goal = _make_cancelled_goal_row()
        session.add(goal)
        session.commit()

        reloaded = session.query(Goal).filter(Goal.id == goal.id).one_or_none()
        assert reloaded is not None, (
            "Ein auf is_active=0 gesetztes Goal darf nicht aus der Datenbank "
            "verschwinden -- es muss weiterhin sichtbar/abrufbar bleiben."
        )
        assert reloaded.deleted_at is None, (
            "is_active=0 (storniert/erfuellt-Proxy) darf kein Soft-Delete "
            "(deleted_at) ausloesen."
        )
        assert int(reloaded.is_active) == 0
    finally:
        session.close()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-PAST-DATE-LIFECYCLE-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md "
        "(Pflichttest 5): goal_liabilities.py kennt is_active ueberhaupt nicht "
        "und berechnet fuer ein storniertes/erfuelltes Ziel dieselbe volle "
        "Liability wie fuer ein aktives."
    ),
)
def test_inactive_goal_contributes_zero_to_optimizer_liability():
    """Soll-Vertrag: ein storniertes/erfuelltes Ziel darf wirtschaftlich
    NICHTS mehr zur Optimizer-Liability beitragen -- auch dann nicht, wenn
    `goal_to_liability()` (oder ein Aufrufer, der den Upstream-Filter in
    services/portfolio_engine.py::_strictly_active_rows umgeht oder
    vergisst) direkt mit einem solchen Goal aufgerufen wird.

    Ist-Verhalten: goal_to_liability() liest `is_active` an keiner Stelle;
    das Resultat ist byte-identisch zu einem aktiven Ziel mit denselben
    Feldern -- volle CHF 50'000 Liability statt null.
    """
    goal = _make_cancelled_goal_namespace()

    liab = goal_to_liability(goal, horizon_years=10)

    assert liab.target_amount_rappen == 0, (
        "Ein storniertes/erfuelltes Ziel (is_active=0) darf keinen "
        f"wirtschaftlichen Zielbetrag mehr erzeugen, bekam aber "
        f"{liab.target_amount_rappen} Rappen."
    )
    assert not any(liab.liability_path_rappen), (
        "Der Liability-Pfad eines stornierten/erfuellten Ziels muss komplett "
        f"null sein, ist aber {liab.liability_path_rappen}."
    )
