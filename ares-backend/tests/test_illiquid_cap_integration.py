"""End-to-End-Lock fuer den Illiquiditaets-Cap (#102/SOLL-Seite, 2026-06-17).

Differentiell ueber generate_target_allocation: mit altsPe+altsGold aktiv senkt ein
enges maxIlliquid-Limit den Private-Equity-Anteil, OHNE den liquiden Gold-Baustein zu
entfernen. Ergaenzt die Unit-Tests (test_illiquid_cap) um den echten Engine-Pfad.
"""
from __future__ import annotations

import pytest

from main import app  # noqa: F401
from models.mandates import Mandate
import services.portfolio_engine as pe
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401


def _gen(session_factory, mid, advisor_id, max_illiquid=None):
    prefs = {
        "policy": {}, "tilts": {}, "product": {}, "geo": {},
        "assetClasses": {"altsPe": True, "altsGold": True},
        "limits": ({"maxIlliquid": max_illiquid} if max_illiquid else {}),
        "simulation": {"monteCarloRuns": 200},
    }
    with session_factory() as s:
        m = s.query(Mandate).filter(Mandate.id == mid).one()
        return pe.generate_target_allocation(s, m, advisor_id, preferences=prefs)


def _sub_bps(result, sub_name):
    subs = result.get("sub_allocations") or []
    return sum(int(x.get("target_weight_bps") or 0)
               for x in subs if str(x.get("sub_asset_class")) == sub_name)


def test_maxilliquid_senkt_pe_laesst_gold_stehen(session_factory):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="illiq-int")
    uncapped = _gen(session_factory, mid, advisor_id, max_illiquid=None)
    pe_unc = _sub_bps(uncapped, "Private Equity")
    if pe_unc <= 100:
        pytest.skip(f"PE-Anteil ohne Cap nur {pe_unc} bps — Cap wuerde nicht greifen (Profil-abhaengig)")

    capped = _gen(session_factory, mid, advisor_id, max_illiquid="1")  # 1 % Limit
    pe_cap = _sub_bps(capped, "Private Equity")
    gold_cap = _sub_bps(capped, "Gold / Rohstoffe")

    assert pe_cap < pe_unc, f"Cap hat PE nicht gesenkt ({pe_unc} -> {pe_cap})"
    assert pe_cap <= 130, f"PE nach 1%-Cap zu hoch: {pe_cap} bps"
    assert gold_cap > 0, "liquider Gold-Baustein faelschlich entfernt"
