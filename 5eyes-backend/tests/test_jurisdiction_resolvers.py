"""WP-Resolver (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
Regressionstests fuer die freistehenden Jurisdiktions-Resolver in
services/jurisdiction/.

Deckt ab:
1. resolve_mandate_jurisdiction: NULL/fehlend -> "CH", explizit gesetzt -> Wert.
2. resolve_cma_for_jurisdiction: CH-Fallback (NULL und "CH") liefert
   identisches Ergebnis zur heutigen direkten Query aus
   services/portfolio_engine.py::ensure_runtime_reference_data.
3. resolve_cma_for_jurisdiction: unbekannte Jurisdiktion ohne Daten ->
   JurisdictionReferenceDataMissingError.
4. resolve_cma_for_jurisdiction: status="data_derived" +
   require_committee_approved=True -> JurisdictionNotApprovedError;
   require_committee_approved=False -> liefert die Zeile trotzdem.
5. resolve_building_blocks_for_jurisdiction: CH-Fallback (inkl. leeres
   Ergebnis, KEIN Fehler) vs. Nicht-CH (leeres Ergebnis -> Fehler).
6. assert_jurisdiction_ready: CH immer ok; Nicht-CH ohne Freigabe -> Fehler,
   mit allow_provisional_preview=True -> True (Provisorik-Signal), bereits
   committee_approved -> False (kein Fehler).

Diese Tests rufen NUR services/jurisdiction/* auf -- KEIN Wiring in
services/portfolio_engine.py oder services/cost_disclosure.py (das ist
bewusst nicht Teil dieses Arbeitspakets, siehe WP2).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
# Alle Models importieren, damit SQLAlchemy alle FK-Beziehungen aufloesen
# kann (Vorbild: tests/test_jurisdiction_schema_migration.py).
import models.allocation  # noqa: E402,F401
import models.clients  # noqa: E402,F401
import models.client_login  # noqa: E402,F401
import models.fx_rate  # noqa: E402,F401
import models.jurisdiction  # noqa: E402,F401
import models.mandates  # noqa: E402,F401
import models.profiling  # noqa: E402,F401
import models.review  # noqa: E402,F401
import models.snapshots  # noqa: E402,F401
import models.tenant  # noqa: E402,F401
import models.users  # noqa: E402,F401
import models.wealth  # noqa: E402,F401

from models.allocation import BuildingBlock, CapitalMarketAssumption, OptimizerPolicy  # noqa: E402
from services.jurisdiction.exceptions import (  # noqa: E402
    JurisdictionNotApprovedError,
    JurisdictionReferenceDataConflictError,
    JurisdictionReferenceDataMissingError,
)
from services.jurisdiction.provisional_gate import assert_jurisdiction_ready  # noqa: E402
from services.jurisdiction.resolve import (  # noqa: E402
    resolve_building_blocks_for_jurisdiction,
    resolve_cma_for_jurisdiction,
    resolve_mandate_jurisdiction,
)

NOW = "2026-07-30T00:00:00.000Z"


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'resolver_test.db'}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_cma(
    row_id: str,
    *,
    jurisdiction: str | None = None,
    tenant_id: str | None = None,
    status: str | None = "committee_approved",
    is_current: int = 1,
) -> CapitalMarketAssumption:
    return CapitalMarketAssumption(
        id=row_id,
        assumption_set_name=f"Standard-{row_id}",
        version=1,
        valid_from="2026-01-01",
        is_current=is_current,
        jurisdiction=jurisdiction,
        tenant_id=tenant_id,
        status=status,
        created_by="tester",
        created_at=NOW,
        updated_at=NOW,
    )


def _make_policy(policy_id: str) -> OptimizerPolicy:
    return OptimizerPolicy(
        id=policy_id,
        policy_name=f"Policy-{policy_id}",
        version=1,
        is_current=1,
        valid_from="2026-01-01",
        created_by="tester",
        created_at=NOW,
        updated_at=NOW,
    )


def _make_building_block(
    row_id: str,
    policy_id: str,
    *,
    jurisdiction: str | None = None,
    sub_asset_class: str = "Aktien Schweiz",
    universe: str = "Standard",
    is_active: int = 1,
) -> BuildingBlock:
    return BuildingBlock(
        id=row_id,
        policy_id=policy_id,
        asset_class="Aktien",
        sub_asset_class=sub_asset_class,
        universe=universe,
        risky_fraction_bps=10000,
        is_active=is_active,
        created_at=NOW,
        updated_at=NOW,
        jurisdiction=jurisdiction,
    )


# ===========================================================================
# 1. resolve_mandate_jurisdiction
# ===========================================================================


def test_resolve_mandate_jurisdiction_null_falls_back_to_ch():
    mandate = SimpleNamespace(jurisdiction=None)
    assert resolve_mandate_jurisdiction(mandate) == "CH"


def test_resolve_mandate_jurisdiction_missing_attribute_falls_back_to_ch():
    mandate = SimpleNamespace()  # kein jurisdiction-Attribut ueberhaupt
    assert resolve_mandate_jurisdiction(mandate) == "CH"


def test_resolve_mandate_jurisdiction_explicit_value_passed_through():
    mandate = SimpleNamespace(jurisdiction="DE")
    assert resolve_mandate_jurisdiction(mandate) == "DE"


def test_resolve_mandate_jurisdiction_explicit_ch_passed_through():
    mandate = SimpleNamespace(jurisdiction="CH")
    assert resolve_mandate_jurisdiction(mandate) == "CH"


# ===========================================================================
# 2 + 3. resolve_cma_for_jurisdiction: CH-Fallback vs. fehlende Daten
# ===========================================================================


def test_resolve_cma_ch_none_matches_direct_query(db_session):
    """NULL-jurisdiction (Bestandszeile) muss ueber jurisdiction=None UND
    jurisdiction="CH" gefunden werden -- identisch zur heutigen direkten
    Query in services/portfolio_engine.py::ensure_runtime_reference_data."""
    cma = _make_cma("cma-ch-1", jurisdiction=None, status="committee_approved")
    db_session.add(cma)
    db_session.commit()

    direct = db_session.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.is_current == 1,
        CapitalMarketAssumption.deleted_at.is_(None),
    ).first()

    resolved_none = resolve_cma_for_jurisdiction(db_session, None)
    resolved_ch = resolve_cma_for_jurisdiction(db_session, "CH")

    assert direct is not None
    assert resolved_none.id == direct.id == "cma-ch-1"
    assert resolved_ch.id == direct.id


@pytest.mark.parametrize("requested_jurisdiction", [None, "CH"])
def test_resolve_cma_ch_scope_never_leaks_de_or_tenant_de(
    db_session,
    requested_jurisdiction,
):
    """Der CH-Resolver muss auch in einem realistisch gemischten Bestand
    ausschliesslich firmenweite CH-Zeilen beruecksichtigen. Insbesondere
    duerfen weder die firmenweite noch eine Tenant-DE-Zeile durch die
    historische CH(NULL)-Kompatibilitaet in den CH-Pfad gelangen."""
    db_session.add_all([
        _make_cma("cma-ch-legacy", jurisdiction=None),
        _make_cma("cma-de-firmwide", jurisdiction="DE"),
        _make_cma("cma-de-tenant", jurisdiction="DE", tenant_id="tenant-de"),
    ])
    db_session.commit()

    resolved = resolve_cma_for_jurisdiction(
        db_session,
        requested_jurisdiction,
        tenant_id="tenant-de",
    )

    assert resolved.id == "cma-ch-legacy"
    assert resolved.jurisdiction in (None, "CH")
    assert resolved.tenant_id is None


@pytest.mark.parametrize("requested_jurisdiction", [None, "CH"])
def test_resolve_cma_ch_duplicate_current_rows_fail_closed(
    db_session,
    requested_jurisdiction,
):
    """Zwei aktuelle CH-Reihen (Legacy-NULL plus explizites CH) sind ein
    mehrdeutiger Modellzustand. Der Resolver darf hier nicht per ungeordnetem
    ``first()`` zufaellig eine Annahmenbasis waehlen, sondern muss fail-closed
    abbrechen. Der konkrete Exception-Typ bleibt der Produktionsimplementierung
    ueberlassen; die Meldung muss die Mehrdeutigkeit jedoch klar benennen."""
    db_session.add_all([
        _make_cma("cma-ch-legacy-duplicate", jurisdiction=None),
        _make_cma("cma-ch-explicit-duplicate", jurisdiction="CH"),
        _make_cma("cma-de-unrelated", jurisdiction="DE"),
    ])
    db_session.commit()

    with pytest.raises(
        JurisdictionReferenceDataConflictError,
        match=r"(?i)(mehrdeutig|mehrere|multiple|ambig|eindeutig)",
    ):
        resolve_cma_for_jurisdiction(db_session, requested_jurisdiction)


def test_resolve_cma_unknown_jurisdiction_without_data_raises(db_session):
    cma = _make_cma("cma-ch-2", jurisdiction=None, status="committee_approved")
    db_session.add(cma)
    db_session.commit()

    with pytest.raises(JurisdictionReferenceDataMissingError):
        resolve_cma_for_jurisdiction(db_session, "FR")


def test_resolve_cma_ch_without_any_row_raises_not_none(db_session):
    """Auch der CH-Pfad gibt NIEMALS None zurueck -- fehlende Daten sind
    ein Fehler, keine stille Rueckgabe von None."""
    with pytest.raises(JurisdictionReferenceDataMissingError):
        resolve_cma_for_jurisdiction(db_session, None)


# ===========================================================================
# 4. require_committee_approved Gate
# ===========================================================================


def test_resolve_cma_data_derived_with_require_approved_raises(db_session):
    cma = _make_cma("cma-de-1", jurisdiction="DE", status="data_derived")
    db_session.add(cma)
    db_session.commit()

    with pytest.raises(JurisdictionNotApprovedError):
        resolve_cma_for_jurisdiction(db_session, "DE", require_committee_approved=True)


def test_resolve_cma_data_derived_without_require_approved_returns_row(db_session):
    cma = _make_cma("cma-de-2", jurisdiction="DE", status="data_derived")
    db_session.add(cma)
    db_session.commit()

    resolved = resolve_cma_for_jurisdiction(db_session, "DE", require_committee_approved=False)
    assert resolved.id == "cma-de-2"
    assert resolved.status == "data_derived"


def test_resolve_cma_committee_approved_with_require_approved_returns_row(db_session):
    cma = _make_cma("cma-de-3", jurisdiction="DE", status="committee_approved")
    db_session.add(cma)
    db_session.commit()

    resolved = resolve_cma_for_jurisdiction(db_session, "DE", require_committee_approved=True)
    assert resolved.id == "cma-de-3"


def test_resolve_cma_non_current_row_ignored(db_session):
    """is_current=0 darf nie gefunden werden -- selbst wenn es die einzige
    Zeile fuer diese Jurisdiktion ist (kein erfundener Treffer)."""
    stale = _make_cma("cma-de-stale", jurisdiction="DE", status="committee_approved", is_current=0)
    db_session.add(stale)
    db_session.commit()

    with pytest.raises(JurisdictionReferenceDataMissingError):
        resolve_cma_for_jurisdiction(db_session, "DE")


# ===========================================================================
# 5. resolve_building_blocks_for_jurisdiction
# ===========================================================================


def test_resolve_building_blocks_ch_none_and_ch_identical(db_session):
    policy = _make_policy("policy-1")
    db_session.add(policy)
    db_session.add(_make_building_block("bb-ch-1", "policy-1", jurisdiction=None))
    db_session.commit()

    rows_none = resolve_building_blocks_for_jurisdiction(db_session, "policy-1", None)
    rows_ch = resolve_building_blocks_for_jurisdiction(db_session, "policy-1", "CH")

    assert [r.id for r in rows_none] == ["bb-ch-1"]
    assert [r.id for r in rows_ch] == ["bb-ch-1"]


def test_resolve_building_blocks_ch_empty_result_does_not_raise(db_session):
    """CH-Pfad: leeres Ergebnis ist heute ein gueltiger Fall (keine Bausteine
    fuer diese Policy) -- KEIN Fehler, byte-identisch zum heutigen Verhalten
    von services/portfolio_engine.py::_building_block_rows_for_policy."""
    policy = _make_policy("policy-empty")
    db_session.add(policy)
    db_session.commit()

    rows = resolve_building_blocks_for_jurisdiction(db_session, "policy-empty", None)
    assert rows == []


def test_resolve_building_blocks_unknown_jurisdiction_empty_raises(db_session):
    policy = _make_policy("policy-2")
    db_session.add(policy)
    db_session.add(_make_building_block("bb-ch-2", "policy-2", jurisdiction=None))
    db_session.commit()

    with pytest.raises(JurisdictionReferenceDataMissingError):
        resolve_building_blocks_for_jurisdiction(db_session, "policy-2", "DE")


def test_resolve_building_blocks_jurisdiction_filter_matches_only_that_jurisdiction(db_session):
    policy = _make_policy("policy-3")
    db_session.add(policy)
    db_session.add(_make_building_block("bb-ch-3", "policy-3", jurisdiction=None))
    db_session.add(_make_building_block("bb-de-1", "policy-3", jurisdiction="DE"))
    db_session.commit()

    rows_de = resolve_building_blocks_for_jurisdiction(db_session, "policy-3", "DE")
    assert [r.id for r in rows_de] == ["bb-de-1"]


@pytest.mark.parametrize("requested_jurisdiction", [None, "CH"])
def test_resolve_building_blocks_ch_scope_excludes_de_rows(
    db_session,
    requested_jurisdiction,
):
    policy = _make_policy(f"policy-ch-scope-{requested_jurisdiction or 'none'}")
    db_session.add(policy)
    db_session.add_all([
        _make_building_block(
            f"bb-ch-legacy-{requested_jurisdiction or 'none'}",
            policy.id,
            jurisdiction=None,
            sub_asset_class="Aktien Global Shared",
        ),
        _make_building_block(
            f"bb-ch-explicit-{requested_jurisdiction or 'none'}",
            policy.id,
            jurisdiction="CH",
            sub_asset_class="Aktien Schweiz Exact",
        ),
        _make_building_block(
            f"bb-de-out-of-scope-{requested_jurisdiction or 'none'}",
            policy.id,
            jurisdiction="DE",
            sub_asset_class="Aktien Deutschland Out",
        ),
    ])
    db_session.commit()

    rows = resolve_building_blocks_for_jurisdiction(
        db_session,
        policy.id,
        requested_jurisdiction,
    )

    assert {row.jurisdiction for row in rows} == {None, "CH"}
    assert all(row.id.startswith("bb-ch-") for row in rows)


def test_resolve_building_blocks_inactive_row_ignored(db_session):
    policy = _make_policy("policy-4")
    db_session.add(policy)
    db_session.add(_make_building_block("bb-de-inactive", "policy-4", jurisdiction="DE", is_active=0))
    db_session.commit()

    with pytest.raises(JurisdictionReferenceDataMissingError):
        resolve_building_blocks_for_jurisdiction(db_session, "policy-4", "DE")


# ===========================================================================
# 6. assert_jurisdiction_ready (provisional_gate)
# ===========================================================================


def test_assert_jurisdiction_ready_ch_none_always_ok_even_with_non_approved_status():
    cma = SimpleNamespace(status="data_derived")
    assert assert_jurisdiction_ready(None, cma) is False
    assert assert_jurisdiction_ready("CH", cma) is False


def test_assert_jurisdiction_ready_non_ch_not_approved_without_preview_raises():
    cma = SimpleNamespace(status="data_derived")
    with pytest.raises(JurisdictionNotApprovedError):
        assert_jurisdiction_ready("DE", cma, allow_provisional_preview=False)


def test_assert_jurisdiction_ready_non_ch_not_approved_with_preview_returns_true():
    cma = SimpleNamespace(status="provisional")
    assert assert_jurisdiction_ready("DE", cma, allow_provisional_preview=True) is True


def test_assert_jurisdiction_ready_non_ch_already_approved_returns_false():
    cma = SimpleNamespace(status="committee_approved")
    assert assert_jurisdiction_ready("DE", cma, allow_provisional_preview=False) is False
    # allow_provisional_preview darf hier egal sein -- schon freigegeben.
    assert assert_jurisdiction_ready("DE", cma, allow_provisional_preview=True) is False
