"""ESG-P0-3/4/5 (CTO/CIO-Review ESG-Architektur 18.10.2026, F P0-3..P0-5, D 4-6).

P0-3 PREF-MANUAL-001 / PREF-FINAL-001: manuelles Hinzufuegen einer Position
und die Finalisierung eines RecommendationRun pruefen mit DEMSELBEN Matcher
(``_product_matches_constraints``) gegen den Praeferenz-Snapshot der TA.
Verstoss -> 409 ``PREFERENCE_CONSTRAINT_VIOLATION`` + betroffene Positionen.
Legacy-TA ohne Snapshot -> Verhalten wie bisher + Warnung.

P0-4 ESG-SEED-PROVENANCE-001: ESG-Werte des Seed-Katalogs sind unbelegt
(``seed_unverified``); Berater sieht den Status, Kundendokumente machen auf
dieser Basis keine positive ESG-Aussage.

P0-5 THEME-MISSINGNESS-001: fehlende Themenklassifikation gilt bei einem
Themen-Ausschluss nicht als "nicht betroffen" -- ausser Liquiditaet und
kollektive Anlagen (Fonds/ETF, offengelegt "nicht durchleuchtet").
Unumsetzbarer Baustein -> 409 ``THEME_CLASSIFICATION_MISSING``.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _path in (BACKEND_ROOT, TESTS_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from database import Base, new_uuid  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.tenant  # noqa: E402,F401
import models.client_login  # noqa: E402,F401
import models.protocol_bausteine  # noqa: E402,F401

configure_mappers()

import services.portfolio_engine as pe  # noqa: E402
import services.portfolio_engine_payload as payload  # noqa: E402
from models.allocation import TargetAllocation  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import Product, RecommendationPosition, RecommendationRun  # noqa: E402
from models.users import User  # noqa: E402
from test_optimizer_integration import _seed_realistic_mandate  # noqa: E402

ROOT = BACKEND_ROOT.parent
MONOLITH = ROOT / "ares-desktop" / "frontend" / "ares.html"


class _FakeClient:
    host = "127.0.0.1"


class _FakeRequest:
    headers: dict = {}
    client = _FakeClient()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@pytest.fixture()
def SF(tmp_path, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'esg_p0b.db'}", connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        engine.dispose()


def _seed(SF, suffix: str):
    advisor_id, _cid, mandate_id, _aid = _seed_realistic_mandate(SF, suffix)
    with SF() as s:
        pe.ensure_default_products(s, jurisdiction="CH")
        pe.ensure_hedged_product_variants(s)
        user = s.get(User, advisor_id)
        user.role = "admin"  # globaler Mandatszugriff fuer direkte Router-Aufrufe
        s.commit()
    return advisor_id, mandate_id


def _generate_ta(SF, mandate_id, advisor_id, prefs) -> str:
    with SF() as s:
        mandate = s.get(Mandate, mandate_id)
        result = pe.generate_target_allocation(s, mandate, advisor_id, prefs)
        s.commit()
        return result["target_allocation"].id


def _generate_run(SF, mandate_id, advisor_id) -> tuple[str, list[str], list[str]]:
    with SF() as s:
        mandate = s.get(Mandate, mandate_id)
        result = pe.generate_recommendation_run(s, mandate, advisor_id, None)
        s.commit()
        return (
            result["run"].id,
            [item["product_id"] for item in result["positions"]],
            list(result.get("warnings") or []),
        )


def _draft_run(SF, mandate_id, advisor_id) -> str:
    """Leerer Draft-Run auf der aktuellen TA (wie POST /recommendations)."""
    with SF() as s:
        mandate = s.get(Mandate, mandate_id)
        ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id, TargetAllocation.is_current == 1,
        ).one()
        run_id = new_uuid()
        s.add(RecommendationRun(
            id=run_id, mandate_id=mandate_id, client_id=mandate.client_id,
            assessment_id=ta.based_on_assessment_id, target_allocation_id=ta.id,
            policy_id=ta.policy_id, capital_market_assumptions_id=ta.capital_market_assumptions_id,
            run_type="Manual", result_status="Draft", created_by=advisor_id,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()
        return run_id


def _product_id(SF, name: str) -> str:
    with SF() as s:
        return s.query(Product).filter(Product.product_name == name).one().id


def _add_product(SF, **fields) -> str:
    pid = new_uuid()
    defaults = dict(
        product_name=f"Testprodukt {pid[:6]}", provider="Test", product_type="ETF",
        asset_class="Aktien", sub_asset_class="Aktien Global", currency="CHF", ter_bps=20,
        is_active=1, created_at=_now(), updated_at=_now(),
    )
    defaults.update(fields)
    with SF() as s:
        s.add(Product(id=pid, **defaults))
        s.commit()
    return pid


def _add_position(SF, mandate_id, run_id, advisor_id, product_id, weight=500):
    from routers.review import add_position
    from schemas.review import RecommendationPositionCreate

    body = RecommendationPositionCreate(product_id=product_id, target_weight_bps=weight)
    with SF() as s:
        user = s.get(User, advisor_id)
        try:
            pos = add_position(mandate_id, run_id, body, db=s, current_user=user)
            return SimpleNamespace(
                product_id=pos.product_id, warnings=list(getattr(pos, "warnings", None) or []),
            )
        finally:
            s.rollback()


def _finalize(SF, mandate_id, run_id, advisor_id):
    from routers.review import finalize_recommendation

    with SF() as s:
        user = s.get(User, advisor_id)
        try:
            return finalize_recommendation(
                mandate_id=mandate_id, run_id=run_id, request=_FakeRequest(), db=s, current_user=user,
            )
        finally:
            s.rollback()


def _positions_of(SF, run_id) -> list[str]:
    with SF() as s:
        return [p.product_id for p in s.query(RecommendationPosition).filter(RecommendationPosition.run_id == run_id)]


def _status_of(SF, run_id) -> str:
    with SF() as s:
        return s.get(RecommendationRun, run_id).result_status


def _strip_snapshot(SF, ta_id):
    with SF() as s:
        row = s.get(TargetAllocation, ta_id)
        row.preferences_json = None
        row.allocation_context_hash = None
        row.sub_allocations_json = None
        row.effective_constraints_json = None
        row.context_artifacts_required = 0
        s.commit()


def _strip_preference_snapshot_keep_ledger(SF, ta_id):
    """Legacy-Praeferenz-TA (``preferences_json IS NULL``), deren uebriger
    Allocation-Context inkl. Reserve-Ledger-Snapshot gueltig gehasht bleibt.

    RESERVE-LEDGER-SNAPSHOT-001: eine TA ganz ohne gehashten Context ist
    ledger-``unverifiable`` und wird (gewollt) nicht finalisiert. Fuer den
    ESG-Legacy-Vertrag zaehlt nur der fehlende Praeferenz-Snapshot; der Hash
    wird deshalb ueber exakt dieselbe kanonische Form neu gebildet.
    """
    import json

    from services.portfolio_engine import BUCKET_FIELDS
    from services.goal_analysis_snapshot import bound_analysis_result_hash
    from services.portfolio_engine_allocation_integrity import allocation_context_hash_for

    with SF() as s:
        row = s.get(TargetAllocation, ta_id)
        constraints = json.loads(row.effective_constraints_json)
        row.preferences_json = None
        row.allocation_context_hash = allocation_context_hash_for(
            engine_version=constraints["engine_version"],
            policy_id=row.policy_id,
            cma_id=row.capital_market_assumptions_id,
            assessment_id=row.based_on_assessment_id,
            input_snapshot_hash=row.input_snapshot_hash,
            preferences_json=None,
            targets={b: int(getattr(row, f"target_{b}_bps")) for b in BUCKET_FIELDS},
            sub_allocations=json.loads(row.sub_allocations_json),
            effective_constraints=constraints,
            optimization_seed=row.optimization_seed,
            analysis_result_hash=bound_analysis_result_hash(constraints),
        )
        assert row.reserve_funding_ledger_hash  # gueltiger Ledger-Snapshot bleibt
        s.commit()


# ===========================================================================
# P0-3a PREF-MANUAL-001: manuelles Hinzufuegen
# ===========================================================================


def test_manual_add_of_art6_product_under_impact_snapshot_is_409(SF):
    from services.preference_snapshot import PREFERENCE_CONSTRAINT_VIOLATION

    advisor_id, mandate_id = _seed(SF, "man-impact")
    _generate_ta(SF, mandate_id, advisor_id, {"policy": {"esg": "impact"}})
    run_id = _draft_run(SF, mandate_id, advisor_id)
    art6 = _add_product(SF, product_name="Art6 Aktien", sfdr_class="6")

    with pytest.raises(HTTPException) as excinfo:
        _add_position(SF, mandate_id, run_id, advisor_id, art6)
    assert excinfo.value.status_code == 409
    detail = excinfo.value.detail
    assert detail["reason_code"] == PREFERENCE_CONSTRAINT_VIOLATION
    assert [item["product_id"] for item in detail["positions"]] == [art6]
    assert detail["positions"][0]["product_name"] == "Art6 Aktien"
    assert _positions_of(SF, run_id) == []


def test_manual_add_of_matching_product_under_impact_is_accepted(SF):
    """Positivkontrolle: dasselbe Setup mit Art.-9-Produkt wird angenommen
    (sonst waere der 409 oben nicht vom Kriterium verursacht)."""
    advisor_id, mandate_id = _seed(SF, "man-impact-ok")
    _generate_ta(SF, mandate_id, advisor_id, {"policy": {"esg": "impact"}})
    run_id = _draft_run(SF, mandate_id, advisor_id)
    art9 = _add_product(SF, product_name="Art9 Aktien", sfdr_class="9")

    pos = _add_position(SF, mandate_id, run_id, advisor_id, art9)
    assert pos.product_id == art9
    assert not list(getattr(pos, "warnings", []) or [])
    assert _positions_of(SF, run_id) == [art9]


def test_manual_add_of_liquidity_under_impact_follows_exemption(SF):
    advisor_id, mandate_id = _seed(SF, "man-liq")
    _generate_ta(SF, mandate_id, advisor_id, {"policy": {"esg": "impact"}})
    run_id = _draft_run(SF, mandate_id, advisor_id)
    cash = _product_id(SF, "Kontoguthaben CHF")
    pos = _add_position(SF, mandate_id, run_id, advisor_id, cash)
    assert pos.product_id == cash


def test_manual_add_of_excluded_theme_product_is_409(SF):
    from services.preference_snapshot import PREFERENCE_CONSTRAINT_VIOLATION

    advisor_id, mandate_id = _seed(SF, "man-theme")
    _generate_ta(SF, mandate_id, advisor_id, {"policy": {"esg": "negative_screening"}})
    run_id = _draft_run(SF, mandate_id, advisor_id)
    energy = _product_id(SF, "Energy Select Sector ETF")
    with pytest.raises(HTTPException) as excinfo:
        _add_position(SF, mandate_id, run_id, advisor_id, energy)
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["reason_code"] == PREFERENCE_CONSTRAINT_VIOLATION
    hints = " ".join(excinfo.value.detail["positions"][0]["hints"])
    assert "Fossile Energie" in hints


def test_manual_add_uses_the_same_matcher(SF, monkeypatch):
    """Kein zweiter Matcher: die Pruefung ruft _product_matches_constraints."""
    advisor_id, mandate_id = _seed(SF, "man-same")
    _generate_ta(SF, mandate_id, advisor_id, {})
    run_id = _draft_run(SF, mandate_id, advisor_id)
    pid = _add_product(SF, sfdr_class="9")
    calls = []

    def _never(product, prefs, score_bucket, **kwargs):
        calls.append(product.id)
        return False

    monkeypatch.setattr(payload, "_product_matches_constraints", _never)
    with pytest.raises(HTTPException) as excinfo:
        _add_position(SF, mandate_id, run_id, advisor_id, pid)
    assert excinfo.value.status_code == 409
    assert calls == [pid]


def test_manual_add_on_legacy_allocation_is_allowed_with_warning(SF):
    from services.preference_snapshot import PREFERENCE_SNAPSHOT_LEGACY

    advisor_id, mandate_id = _seed(SF, "man-legacy")
    ta_id = _generate_ta(SF, mandate_id, advisor_id, {"policy": {"esg": "impact"}})
    _strip_snapshot(SF, ta_id)
    run_id = _draft_run(SF, mandate_id, advisor_id)
    art6 = _add_product(SF, sfdr_class="6")
    pos = _add_position(SF, mandate_id, run_id, advisor_id, art6)
    assert pos.product_id == art6
    assert any(w.startswith(PREFERENCE_SNAPSHOT_LEGACY) for w in pos.warnings)


# ===========================================================================
# P0-3b PREF-FINAL-001: Finalisierung
# ===========================================================================


def test_finalize_clean_generated_run_succeeds(SF):
    """Positivkontrolle fuer die Finalisierungs-Tests unten."""
    advisor_id, mandate_id = _seed(SF, "fin-ok")
    _generate_ta(SF, mandate_id, advisor_id, {"tilts": {"fossil": "exclude"}})
    run_id, _pids, _w = _generate_run(SF, mandate_id, advisor_id)
    _finalize(SF, mandate_id, run_id, advisor_id)
    assert _status_of(SF, run_id) == "Final"


def test_finalize_blocks_run_with_manipulated_excluded_theme_position(SF):
    from services.preference_snapshot import PREFERENCE_CONSTRAINT_VIOLATION

    advisor_id, mandate_id = _seed(SF, "fin-theme")
    _generate_ta(SF, mandate_id, advisor_id, {"tilts": {"fossil": "exclude"}})
    run_id, pids, _w = _generate_run(SF, mandate_id, advisor_id)
    energy = _product_id(SF, "Energy Select Sector ETF")
    with SF() as s:
        pos = s.query(RecommendationPosition).filter(
            RecommendationPosition.run_id == run_id,
        ).order_by(RecommendationPosition.target_weight_bps.desc()).first()
        manipulated_id = pos.id
        pos.product_id = energy
        s.commit()

    with pytest.raises(HTTPException) as excinfo:
        _finalize(SF, mandate_id, run_id, advisor_id)
    assert excinfo.value.status_code == 409
    detail = excinfo.value.detail
    assert detail["reason_code"] == PREFERENCE_CONSTRAINT_VIOLATION
    assert [item["position_id"] for item in detail["positions"]] == [manipulated_id]
    assert detail["positions"][0]["product_id"] == energy
    assert _status_of(SF, run_id) == "Draft"


def test_finalize_blocks_when_product_esg_field_removed_after_generation(SF):
    advisor_id, mandate_id = _seed(SF, "fin-stale")
    _generate_ta(SF, mandate_id, advisor_id, {"policy": {"esg": "esg_integration"}})
    run_id, pids, _w = _generate_run(SF, mandate_id, advisor_id)
    with SF() as s:
        victim = next(
            s.get(Product, pid) for pid in pids
            if pe._norm_text(s.get(Product, pid).asset_class) != "Liquiditaet"
        )
        victim_id = victim.id
        victim.sfdr_class = None
        s.commit()
    with pytest.raises(HTTPException) as excinfo:
        _finalize(SF, mandate_id, run_id, advisor_id)
    assert excinfo.value.status_code == 409
    assert [item["product_id"] for item in excinfo.value.detail["positions"]] == [victim_id]
    assert _status_of(SF, run_id) == "Draft"


def test_finalize_legacy_allocation_keeps_behaviour_with_warning(SF):
    from models.review import AuditLog  # noqa: F401  (Existenz)
    from services.preference_snapshot import PREFERENCE_SNAPSHOT_LEGACY

    advisor_id, mandate_id = _seed(SF, "fin-legacy")
    ta_id = _generate_ta(SF, mandate_id, advisor_id, {})
    _strip_preference_snapshot_keep_ledger(SF, ta_id)
    run_id, _pids, _w = _generate_run(SF, mandate_id, advisor_id)
    _finalize(SF, mandate_id, run_id, advisor_id)
    assert _status_of(SF, run_id) == "Final"
    with SF() as s:
        from models.review import AuditLog as _AL

        entries = s.query(_AL).filter(_AL.record_id == run_id, _AL.field_name == "result_status").all()
        assert any(PREFERENCE_SNAPSHOT_LEGACY in str(e.new_value or "") for e in entries)


# ===========================================================================
# P0-4 ESG-SEED-PROVENANCE-001
# ===========================================================================


def test_seed_catalog_esg_data_is_marked_seed_unverified(SF):
    from services.esg_data_provenance import (
        ESG_DATA_STATUS_MAINTAINED_NO_SOURCE,
        ESG_DATA_STATUS_NOT_MAINTAINED,
        ESG_DATA_STATUS_SEED_UNVERIFIED,
        product_esg_data_status,
        seed_unverified_esg_fields,
    )

    _seed(SF, "seed-status")
    with SF() as s:
        spi = s.query(Product).filter(Product.product_name == "iShares Core SPI ETF").one()
        assert product_esg_data_status(spi) == ESG_DATA_STATUS_SEED_UNVERIFIED
        assert set(seed_unverified_esg_fields(spi)) == {"sfdr_class", "esg_rating"}
        energy = s.query(Product).filter(Product.product_name == "Energy Select Sector ETF").one()
        assert "theme_tags" in seed_unverified_esg_fields(energy)
        cash = s.query(Product).filter(Product.product_name == "Kontoguthaben CHF").one()
        assert product_esg_data_status(cash) == ESG_DATA_STATUS_NOT_MAINTAINED
        # Teilweise ueberschrieben: Rest bleibt Seed -> weiterhin unbelegt.
        spi.sfdr_class = "9"
        assert product_esg_data_status(spi) == ESG_DATA_STATUS_SEED_UNVERIFIED
        assert seed_unverified_esg_fields(spi) == ("esg_rating",)
        # Vollstaendig neu gepflegt: kein Seed-Wert mehr, aber ohne Quelle.
        spi.esg_rating = "AA"
        assert product_esg_data_status(spi) == ESG_DATA_STATUS_MAINTAINED_NO_SOURCE
        s.rollback()
    custom = _add_product(SF, product_name="iShares Core SPI ETF", tenant_id=None, sfdr_class="8", esg_rating="A")
    with SF() as s:
        # Gleichnamig, gleiche Werte: von der Seed-Zeile nicht unterscheidbar
        # -> konservativ unbelegt.
        assert product_esg_data_status(s.get(Product, custom)) == ESG_DATA_STATUS_SEED_UNVERIFIED
    own = _add_product(SF, product_name="Eigener Fonds", sfdr_class="8")
    with SF() as s:
        assert product_esg_data_status(s.get(Product, own)) == ESG_DATA_STATUS_MAINTAINED_NO_SOURCE


def test_product_response_exposes_esg_data_status(SF):
    from schemas.review import ProductResponse

    _seed(SF, "seed-resp")
    with SF() as s:
        spi = s.query(Product).filter(Product.product_name == "iShares Core SPI ETF").one()
        dumped = ProductResponse.model_validate(spi).model_dump()
    assert dumped["esg_data_status"] == "seed_unverified"
    assert set(dumped["esg_data_seed_fields"]) == {"sfdr_class", "esg_rating"}


def test_run_warns_advisor_when_esg_criterion_rests_on_seed_data(SF):
    from services.esg_data_provenance import ESG_DATA_SEED_UNVERIFIED

    advisor_id, mandate_id = _seed(SF, "seed-warn")
    _generate_ta(SF, mandate_id, advisor_id, {"policy": {"esg": "esg_integration"}})
    _run_id, _pids, warnings = _generate_run(SF, mandate_id, advisor_id)
    assert any(w.startswith(ESG_DATA_SEED_UNVERIFIED) for w in warnings), warnings
    # Ohne ESG-Kriterium kein Hinweis (es wird nichts behauptet).
    advisor_id, mandate_id = _seed(SF, "seed-nowarn")
    _generate_ta(SF, mandate_id, advisor_id, {})
    _run_id, _pids, warnings = _generate_run(SF, mandate_id, advisor_id)
    assert not any(w.startswith(ESG_DATA_SEED_UNVERIFIED) for w in warnings)


def _pdf_text(preferences, products=None) -> str:
    from reportlab.platypus import Paragraph, Table

    from services.pdf.documents.anlagestrategie import _make_preferences_section
    from services.pdf.styles import make_paragraph_styles

    chunks = []
    for flowable in _make_preferences_section(preferences, make_paragraph_styles(), products=products):
        if isinstance(flowable, Paragraph):
            chunks.append(flowable.getPlainText())
        elif isinstance(flowable, Table):
            for row in flowable._cellvalues:
                chunks.extend(cell.getPlainText() for cell in row if isinstance(cell, Paragraph))
    return "\n".join(chunks)


_SEED_PRODUCTS = [
    {"name": "iShares Core SPI ETF", "asset_class": "equities", "esg_data_status": "seed_unverified"},
    {"name": "Kontoguthaben CHF", "asset_class": "liquidity", "esg_data_status": "not_maintained"},
]


@pytest.mark.parametrize("policy", ["esg_integration", "best_in_class", "impact", "net_zero"])
def test_customer_pdf_states_seed_esg_data_as_unconfirmed(policy):
    from services.portfolio_engine_payload import ESG_CUSTOMER_CLAIM_LABELS

    text_ = _pdf_text({"policy": {"esg": policy}}, _SEED_PRODUCTS)
    lines = text_.splitlines()
    assert "ESG-Datenstand" in lines
    row = lines[lines.index("ESG-Datenstand") + 1]
    assert "nicht bestaetigt" in row
    assert "iShares Core SPI ETF" in row
    assert "Kontoguthaben" not in row  # ausgenommene Liquiditaet
    assert not [c for c in ESG_CUSTOMER_CLAIM_LABELS if c.lower() in text_.lower()]


def test_customer_pdf_without_criterion_or_products_has_no_data_row():
    assert "ESG-Datenstand" not in _pdf_text({"policy": {"esg": "none"}}, _SEED_PRODUCTS)
    assert "ESG-Datenstand" not in _pdf_text({"policy": {"esg": "impact"}}, None)
    verified = [{"name": "X", "asset_class": "equities", "esg_data_status": "maintained_no_source"}]
    assert "ESG-Datenstand" not in _pdf_text({"policy": {"esg": "impact"}}, verified)


@pytest.mark.parametrize("policy", ["negative_screening", "esg_integration", "best_in_class", "impact", "net_zero"])
def test_contract_signoff_orientation_contains_no_claim_label(policy):
    """Beratungsentscheid (Kundendokument) druckte die Rohwerte der
    Praeferenzen ("esg: impact") -- ein Claim-Name im Kundendokument."""
    from routers.pdf_reports import _format_portfolio_orientation
    from services.portfolio_engine_payload import ESG_CUSTOMER_CLAIM_LABELS

    text_ = _format_portfolio_orientation({"policy": {"esg": policy, "universe": "standard"}})
    assert not [c for c in ESG_CUSTOMER_CLAIM_LABELS if c.lower() in text_.lower()], text_
    assert "esg:" not in text_


def test_advisor_fund_table_shows_esg_data_status():
    html = MONOLITH.read_text(encoding="utf-8")
    start = html.index("function adminRenderFundSearchTable(")
    body = html[start:html.index("async function adminSearchFunds(", start)]
    assert "esg_data_status" in body
    assert "ESG-Daten unbelegt" in body


# ===========================================================================
# P0-5 THEME-MISSINGNESS-001
# ===========================================================================


def _stub(**fields):
    class _P:
        pass

    p = _P()
    defaults = dict(
        id="x", product_name="P", product_type="Aktie", asset_class="Aktien",
        sub_asset_class="Aktien Global", currency="CHF", sfdr_class=None, esg_rating=None,
        esg_score_x10=None, climate_benchmark=None, theme_tags=None, sector_exposure_json=None,
        product_descriptor=None, isin=None, symbol=None, provider=None,
    )
    defaults.update(fields)
    for key, value in defaults.items():
        setattr(p, key, value)
    return p


def _matches(product, prefs) -> bool:
    return payload._product_matches_constraints(product, pe._normalize_preferences(prefs), 5)


FOSSIL = {"tilts": {"fossil": "exclude"}}
TOBACCO = {"tilts": {"tobacco": "exclude"}}


def test_unclassified_single_security_is_excluded_under_theme_exclusion():
    assert not _matches(_stub(), FOSSIL)
    assert not _matches(_stub(), {"tilts": {"alcohol": "underweight"}})
    assert not _matches(_stub(), {"policy": {"esg": "negative_screening"}})


def test_unclassified_single_security_without_theme_screening_is_unchanged():
    assert _matches(_stub(), {})
    assert _matches(_stub(), {"tilts": {"fossil": "overweight"}})


def test_explicit_empty_theme_classification_counts_as_classified():
    assert _matches(_stub(theme_tags="[]"), FOSSIL)
    assert not _matches(_stub(theme_tags='["fossil"]'), FOSSIL)
    assert _matches(_stub(theme_tags='["fossil"]'), TOBACCO)


def test_broken_theme_tags_count_as_missing():
    assert not _matches(_stub(theme_tags="kaputt"), FOSSIL)


def test_maintained_sector_data_classifies_only_fossil():
    low_energy = json.dumps({"Energy": 300, "Tech": 9700})
    assert _matches(_stub(sector_exposure_json=low_energy), FOSSIL)
    assert not _matches(_stub(sector_exposure_json=low_energy), TOBACCO)
    assert not _matches(_stub(sector_exposure_json=json.dumps({"Energy": 4000, "Tech": 6000})), FOSSIL)


@pytest.mark.parametrize("product_type", ["ETF", "Fonds", "Immobilienfonds"])
def test_collective_products_stay_admissible_with_disclosure(product_type):
    assert _matches(_stub(product_type=product_type), FOSSIL)
    assert _matches(_stub(product_type=product_type), TOBACCO)
    text_ = payload.theme_screening_disclosure(pe._normalize_preferences(TOBACCO))
    assert "nicht durchleuchtet" in text_
    assert "ohne Themen-Zuordnung" in text_


def test_liquidity_is_exempt_from_missingness():
    cash = _stub(product_type="Cash", asset_class="Liquidität", sub_asset_class="Kontoguthaben")
    assert _matches(cash, FOSSIL)


def test_unimplementable_building_block_is_409_with_reason_code(SF):
    from services.preference_snapshot import THEME_CLASSIFICATION_MISSING

    advisor_id, mandate_id = _seed(SF, "miss-409")
    # Alle Immobilien-Produkte sind Einzeltitel ohne Themen-Zuordnung.
    with SF() as s:
        for product in s.query(Product).all():
            if pe._norm_text(product.asset_class) == "Immobilien":
                product.product_type = "Aktie"
                product.theme_tags = None
        s.commit()
    # Positivkontrolle ohne Themen-Ausschluss: der Katalog ist umsetzbar.
    _generate_ta(SF, mandate_id, advisor_id, {})
    with SF() as s:
        mandate = s.get(Mandate, mandate_id)
        result = pe.generate_recommendation_run(s, mandate, advisor_id, None)
        assert any(
            pe._norm_text(s.get(Product, p["product_id"]).asset_class) == "Immobilien"
            for p in result["positions"]
        )
        s.rollback()

    ta_id = _generate_ta(SF, mandate_id, advisor_id, FOSSIL)
    from routers.review import generate_recommendation_run_endpoint
    from schemas.review import RecommendationGenerateRequest

    body = RecommendationGenerateRequest(target_allocation_id=ta_id)
    with SF() as s:
        user = s.get(User, advisor_id)
        with pytest.raises(HTTPException) as excinfo:
            generate_recommendation_run_endpoint(mandate_id, body, None, db=s, current_user=user)
        s.rollback()
    assert excinfo.value.status_code == 409
    detail = excinfo.value.detail
    assert detail["reason_code"] == THEME_CLASSIFICATION_MISSING
    assert detail["building_blocks"]
    assert all("Immobilien" in item["sub_asset_class"] for item in detail["building_blocks"])
    with SF() as s:
        assert s.query(RecommendationRun).filter(RecommendationRun.mandate_id == mandate_id).count() == 0
