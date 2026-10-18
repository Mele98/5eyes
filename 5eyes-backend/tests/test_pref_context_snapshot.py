"""PREF-CONTEXT-001 (CIO-Entscheid 2026-10-18, ESG-Architektur-Review §I/D 1-3).

Bei vorhandener aktueller Soll-Allokation ist deren verifizierter
Praeferenz-Snapshot (``preferences_json``) die EINZIGE Quelle fuer Matcher,
Score, ESG-Gap-Hinweis, Themen-Offenlegung und Konzentrationslimits der
Produktselektion (services/preference_snapshot.py):

* ``preferences=None`` -> Snapshot (vorher: Defaults -> ESG-Filter verschwand).
* Request kanonisch != Snapshot -> 409 ``PREFERENCE_SNAPSHOT_MISMATCH``,
  kein Run, keine Position.
* Inhaltsgleicher, anders sortierter Request -> akzeptiert.
* Legacy-TA ohne Snapshot -> bisheriges Verhalten + Warnung
  ``PREFERENCE_SNAPSHOT_LEGACY``.
* TA-Neuberechnung mit ``preferences=None`` (React ``generateAllocation``)
  uebernimmt die Praeferenzen der aktuellen TA statt Defaults.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _path in (BACKEND_ROOT, TESTS_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from database import Base  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.tenant  # noqa: E402,F401
import models.client_login  # noqa: E402,F401
import models.protocol_bausteine  # noqa: E402,F401

configure_mappers()

import services.portfolio_engine as pe  # noqa: E402
from models.allocation import TargetAllocation  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import Product, RecommendationPosition, RecommendationRun  # noqa: E402
from services.preference_snapshot import (  # noqa: E402
    INHERITED_PREFERENCES_NOTE,
    PREFERENCE_SNAPSHOT_LEGACY,
    PREFERENCE_SNAPSHOT_MISMATCH,
    PreferenceSnapshotMismatchError,
)
from test_optimizer_integration import _seed_realistic_mandate  # noqa: E402


@pytest.fixture()
def SF(tmp_path, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pref_context.db'}", connect_args={"check_same_thread": False},
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
        s.commit()
    return advisor_id, mandate_id


def _generate_ta(SF, mandate_id, advisor_id, prefs) -> str:
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = pe.generate_target_allocation(s, mandate, advisor_id, prefs)
        s.commit()
        return result["target_allocation"].id


def _recommend(SF, mandate_id, advisor_id, prefs, *, commit=False):
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = pe.generate_recommendation_run(s, mandate, advisor_id, prefs)
        positions = []
        for item in result["positions"]:
            product = s.get(Product, item["product_id"])
            positions.append({
                "id": product.id,
                "name": product.product_name,
                "asset_class": pe._norm_text(product.asset_class),
                "sfdr": product.sfdr_class,
                "weight": item["target_weight_bps"],
            })
        warnings = list(result.get("warnings") or [])
        if commit:
            s.commit()
        else:
            s.rollback()
        return positions, warnings


def _run_count(SF, mandate_id) -> int:
    with SF() as s:
        return s.query(RecommendationRun).filter(RecommendationRun.mandate_id == mandate_id).count()


# ---------------------------------------------------------------------------
# D1: impact-Snapshot + preferences=None -> nur Art.-9-Produkte
# ---------------------------------------------------------------------------


def test_impact_snapshot_with_none_request_selects_only_art9_products(SF):
    advisor_id, mandate_id = _seed(SF, "pc-impact")
    _generate_ta(SF, mandate_id, advisor_id, {})
    baseline, _ = _recommend(SF, mandate_id, advisor_id, None)
    lure = max((p for p in baseline if p["asset_class"] != "Liquiditaet"), key=lambda p: p["weight"])
    # Katalog: alles Art. 9, nur das sonst gewaehlte Top-Produkt ist Art. 8.
    with SF() as s:
        for product in s.query(Product).all():
            if pe._norm_text(product.asset_class) != "Liquiditaet":
                product.sfdr_class = "8" if product.id == lure["id"] else "9"
        s.commit()
    # Positivkontrolle: ohne ESG-Policy bleibt das Art.-8-Produkt gewaehlt
    # (der Test unterscheidet also wirklich gefiltert/ungefiltert).
    control, _ = _recommend(SF, mandate_id, advisor_id, None)
    assert lure["id"] in {p["id"] for p in control}

    _generate_ta(SF, mandate_id, advisor_id, {"policy": {"esg": "impact"}})
    positions, _ = _recommend(SF, mandate_id, advisor_id, None)
    assert positions
    assert lure["id"] not in {p["id"] for p in positions}
    assert {p["sfdr"] for p in positions if p["asset_class"] != "Liquiditaet"} == {"9"}


def test_impact_snapshot_with_none_request_fails_closed_on_seed_catalog(SF):
    """Seed-Katalog hat kein Art.-9-Produkt -> fail-closed statt still ungefiltert."""
    advisor_id, mandate_id = _seed(SF, "pc-impact-fc")
    _generate_ta(SF, mandate_id, advisor_id, {"policy": {"esg": "impact"}})
    with pytest.raises(ValueError, match="Produktselektion unvollstaendig"):
        _recommend(SF, mandate_id, advisor_id, None)


# ---------------------------------------------------------------------------
# D2: negative_screening-Snapshot + Request esg=none -> 409, kein Run
# ---------------------------------------------------------------------------


def test_divergent_request_raises_mismatch_without_run(SF):
    advisor_id, mandate_id = _seed(SF, "pc-mismatch")
    _generate_ta(SF, mandate_id, advisor_id, {"policy": {"esg": "negative_screening"}})
    with pytest.raises(PreferenceSnapshotMismatchError) as excinfo:
        _recommend(SF, mandate_id, advisor_id, {"policy": {"esg": "none"}}, commit=True)
    assert excinfo.value.reason_code == PREFERENCE_SNAPSHOT_MISMATCH
    assert excinfo.value.differing_sections == ["policy"]
    assert str(excinfo.value).startswith(PREFERENCE_SNAPSHOT_MISMATCH)
    assert _run_count(SF, mandate_id) == 0


def test_router_maps_mismatch_to_409_with_reason_code_and_persists_nothing(SF):
    from routers.review import generate_recommendation_run_endpoint
    from schemas.review import RecommendationGenerateRequest
    from models.users import User

    advisor_id, mandate_id = _seed(SF, "pc-router")
    ta_id = _generate_ta(SF, mandate_id, advisor_id, {"policy": {"esg": "negative_screening"}})
    body = RecommendationGenerateRequest(
        target_allocation_id=ta_id, preferences={"policy": {"esg": "none"}},
    )
    with SF() as s:
        user = s.get(User, advisor_id)
        user.role = "admin"  # globaler Mandatszugriff fuer den direkten Router-Aufruf
        with pytest.raises(HTTPException) as excinfo:
            generate_recommendation_run_endpoint(mandate_id, body, None, db=s, current_user=user)
        s.commit()
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["reason_code"] == PREFERENCE_SNAPSHOT_MISMATCH
    assert "policy" in excinfo.value.detail["differing_sections"]
    assert _run_count(SF, mandate_id) == 0
    with SF() as s:
        assert s.query(RecommendationPosition).count() == 0


# ---------------------------------------------------------------------------
# Konzentrationslimit aus dem Snapshot greift auch mit preferences=None
# ---------------------------------------------------------------------------


def test_single_position_limit_from_snapshot_applies_with_none_request(SF):
    advisor_id, mandate_id = _seed(SF, "pc-limit")
    _generate_ta(SF, mandate_id, advisor_id, {"limits": {"singlePosition": "1"}})
    with pytest.raises(ValueError, match="Einzelpositionslimite"):
        _recommend(SF, mandate_id, advisor_id, None)


# ---------------------------------------------------------------------------
# Kanonischer Vergleich: Reihenfolge egal, Mandats-Defaults beidseitig
# ---------------------------------------------------------------------------


def test_same_content_different_key_order_is_accepted(SF):
    advisor_id, mandate_id = _seed(SF, "pc-order")
    prefs = {
        "policy": {"esg": "negative_screening", "homeBias": "ch_focus"},
        "tilts": {"fossil": "exclude", "tobacco": "neutral"},
        "limits": {"singlePosition": "60"},
    }
    _generate_ta(SF, mandate_id, advisor_id, prefs)
    reordered = {
        "limits": {"singlePosition": "60"},
        "tilts": {"tobacco": "neutral", "fossil": "exclude"},
        "policy": {"homeBias": "ch_focus", "esg": "negative_screening"},
    }
    positions, warnings = _recommend(SF, mandate_id, advisor_id, reordered)
    assert positions
    assert not any(PREFERENCE_SNAPSHOT_LEGACY in w for w in warnings)


def test_request_without_merged_mandate_defaults_matches_snapshot(SF):
    """Classic sendet dieselben UI-Praeferenzen an TA- und Empfehlungs-
    Generate; der Snapshot enthaelt zusaetzlich die gemergten Mandats-
    Building-Block-Defaults -- das ist KEINE Abweichung."""
    advisor_id, mandate_id = _seed(SF, "pc-defaults")
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).one()
        mandate.default_building_blocks_json = json.dumps({"bondsHighYield": False})
        s.commit()
    prefs = {"policy": {"esg": "negative_screening"}}
    ta_id = _generate_ta(SF, mandate_id, advisor_id, prefs)
    with SF() as s:
        snapshot = json.loads(s.get(TargetAllocation, ta_id).preferences_json)
    assert snapshot["assetClasses"]["bondsHighYield"] is False
    positions, _ = _recommend(SF, mandate_id, advisor_id, prefs)
    assert positions


# ---------------------------------------------------------------------------
# D3: React-Null-Pfad -- TA-Neuberechnung mit None behaelt ESG
# ---------------------------------------------------------------------------


def test_regenerate_with_none_keeps_stored_esg_preferences(SF):
    advisor_id, mandate_id = _seed(SF, "pc-react-null")
    prefs = {"policy": {"esg": "negative_screening"}, "tilts": {"fossil": "exclude"}}
    first_id = _generate_ta(SF, mandate_id, advisor_id, prefs)
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = pe.generate_target_allocation(s, mandate, advisor_id, None)
        s.commit()
        second = result["target_allocation"]
        first = s.get(TargetAllocation, first_id)
        # Gleiche Praeferenzen + gleiche Inputs -> REGENERATE-IDEMPOTENT-001
        # behaelt die bestehende TA (vorher: neue TA mit Default-Praeferenzen).
        assert second.id == first_id
        assert second.preferences_json == first.preferences_json
        stored = json.loads(second.preferences_json)
    assert stored["policy"]["esg"] == "negative_screening"
    assert stored["tilts"]["fossil"] == "exclude"
    assert INHERITED_PREFERENCES_NOTE in result["reasoning"]


def test_regenerate_with_explicit_empty_object_resets_to_defaults(SF):
    advisor_id, mandate_id = _seed(SF, "pc-react-empty")
    _generate_ta(SF, mandate_id, advisor_id, {"policy": {"esg": "impact"}})
    second_id = _generate_ta(SF, mandate_id, advisor_id, {})
    with SF() as s:
        stored = json.loads(s.get(TargetAllocation, second_id).preferences_json)
    assert stored.get("policy", {}).get("esg") in (None, "none")


def test_router_regenerate_with_null_preferences_keeps_esg(SF):
    """HTTP-Pfad exakt wie React: POST /target-allocation/generate {preferences:null}."""
    from routers.allocation import generate_target_allocation_endpoint
    from schemas.allocation import TargetAllocationGenerateRequest
    from models.users import User

    advisor_id, mandate_id = _seed(SF, "pc-react-router")
    _generate_ta(SF, mandate_id, advisor_id, {"policy": {"esg": "net_zero"}})
    body = TargetAllocationGenerateRequest.model_validate({"preferences": None})
    with SF() as s:
        user = s.get(User, advisor_id)
        user.role = "admin"
        try:
            generate_target_allocation_endpoint(mandate_id, body, None, db=s, current_user=user)
        except AttributeError:
            pass  # request=None: Audit-IP-Extraktion nach dem Generate
        s.commit()
    with SF() as s:
        current = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id, TargetAllocation.is_current == 1,
        ).one()
        assert json.loads(current.preferences_json)["policy"]["esg"] == "net_zero"


# ---------------------------------------------------------------------------
# Legacy-TA ohne Snapshot: bisheriges Verhalten, aber gekennzeichnet
# ---------------------------------------------------------------------------


def _strip_snapshot(SF, ta_id):
    with SF() as s:
        # Legacy-Zeile vor C8/Context-Artefakten: weder Snapshot noch Hash.
        row = s.get(TargetAllocation, ta_id)
        row.preferences_json = None
        row.allocation_context_hash = None
        row.sub_allocations_json = None
        row.effective_constraints_json = None
        row.context_artifacts_required = 0
        s.commit()


def test_legacy_allocation_without_snapshot_is_flagged(SF):
    advisor_id, mandate_id = _seed(SF, "pc-legacy")
    ta_id = _generate_ta(SF, mandate_id, advisor_id, {})
    _strip_snapshot(SF, ta_id)
    positions, warnings = _recommend(SF, mandate_id, advisor_id, None)
    assert positions
    assert any(w.startswith(PREFERENCE_SNAPSHOT_LEGACY) for w in warnings)


def test_legacy_allocation_still_uses_request_preferences(SF):
    advisor_id, mandate_id = _seed(SF, "pc-legacy-req")
    ta_id = _generate_ta(SF, mandate_id, advisor_id, {})
    _strip_snapshot(SF, ta_id)
    with pytest.raises(ValueError, match="Produktselektion unvollstaendig"):
        _recommend(SF, mandate_id, advisor_id, {"policy": {"esg": "impact"}})


def test_modern_allocation_has_no_legacy_warning(SF):
    advisor_id, mandate_id = _seed(SF, "pc-modern")
    _generate_ta(SF, mandate_id, advisor_id, {})
    _positions, warnings = _recommend(SF, mandate_id, advisor_id, None)
    assert not any(PREFERENCE_SNAPSHOT_LEGACY in w for w in warnings)


# ---------------------------------------------------------------------------
# Classic-Recovery-Pfade senden bei vorhandenem Snapshot null (PREF-REFRESH-001)
# ---------------------------------------------------------------------------


def test_classic_recovery_paths_defer_to_server_snapshot():
    import re

    html = (BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html").read_text(encoding="utf-8")
    helper = re.search(
        r"function recommendationPreferencesForStoredAllocation\(result\)\{(.*?)\n\}", html, re.S,
    ).group(1)
    assert "preferences_json)return null;" in helper
    calls = re.findall(r"API\.post\('/mandates/'\+mid\+'/recommendations/generate',\{preferences:(\w+)", html)
    assert calls == ["recommendationPrefs", "currentPrefs", "prefs"], calls
    assert "var recommendationPrefs=recommendationPreferencesForStoredAllocation(allocation);" in html
    assert "var currentPrefs=recommendationPreferencesForStoredAllocation(currentAllocation);" in html
