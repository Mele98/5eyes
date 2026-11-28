"""EXE-P (H-187): Gebuehrenvereinbarung fuer Livetests ueber den Produktweg.

Die Vorlage-Policy traegt kein Gebuehrenmodell mehr (kein erfundener Satz).
Livetests, deren Kunden-PDFs final (nicht Entwurf) sein muessen, hinterlegen
ein ausdrueckliches TEST-Gebuehrenmodell so, wie eine Firma es tut: Admin
aendert die Policy (neue Entwurfsversion) und aktiviert sie.
"""
from __future__ import annotations

import json

# TESTWERT (byte-gleich zum frueheren Default, damit Texte/Zahlen gleich bleiben).
TEST_FEE_MODEL_JSON = json.dumps({"default_advisory_fee_bps": 75})


def set_test_fee_agreement(api) -> str:
    """``api(method, path, body=None) -> (status, json)``; liefert die aktive Policy-ID."""
    status, current = api("GET", "/optimizer-policies/current")
    assert status == 200, current
    status, updated = api("PUT", f"/admin/optimizer-policies/{current['id']}", {"fee_model_json": TEST_FEE_MODEL_JSON})
    assert status == 200, updated
    if updated["id"] != current["id"]:
        status, body = api("POST", f"/admin/optimizer-policies/{updated['id']}/activate", {})
        assert status in (200, 201), body
    status, active = api("GET", "/optimizer-policies/current")
    assert status == 200 and active["fee_model_json"] == TEST_FEE_MODEL_JSON, active
    return active["id"]
