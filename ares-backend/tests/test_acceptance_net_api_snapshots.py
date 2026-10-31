"""Abnahmenetz G5: zentrale API-Antworten eingefroren.

Laenderpaket-Schritt X0 (nur Tests). Profiling, Jurisdiktionen, Tax,
Referenzdaten, Fehlerpfade Allocation/Review und Datenexport laufen gegen eine
frische Installation ueber die echte App. Je Aufruf wird festgehalten:
HTTP-Status, Typ-Skelett der Antwort (Feldmenge und Typen) und ein Digest der
normalisierten Antwort (UUIDs, Zeitstempel, Datumswerte und Hex-Hashes
maskiert, Floats auf 12 signifikante Stellen). Klartexte liegen nicht im
Repo; lokal ausgeben mit ``ACCEPTANCE_NET_DUMP_DIR``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.acceptance_net_install import advisory_scenario  # noqa: E402
from tests.acceptance_net_support import (  # noqa: E402
    assert_matches_baseline,
    canonical,
    canonical_json,
    digest,
    dump_actual,
    shape,
)
from tests.risk_fixture_helpers import standard_risk_payload  # noqa: E402


_SCORE_FIELDS = (
    "risk_capacity_score_x10", "risk_willingness_score_x10", "final_score_x10", "final_profile",
)


def _sorted_lists(value):
    """Listen ohne fachliche Reihenfolge (Gleichstand bei Zeitstempel/UUID)
    kanonisch sortieren."""
    if isinstance(value, dict):
        return {k: _sorted_lists(v) for k, v in value.items()}
    if isinstance(value, list):
        items = [_sorted_lists(v) for v in value]
        return sorted(items, key=canonical_json)
    return value


def _snapshot(name: str, response, snapshots: dict, dumps: dict, *, unordered: bool = False) -> None:
    try:
        body = response.json()
    except ValueError:
        body = {"<non-json>": response.headers.get("content-type", "")}
    normalized = canonical(body)
    if unordered:
        normalized = _sorted_lists(normalized)
    entry = {"status": response.status_code, "shape": shape(body), "sha256": digest(normalized)}
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict) and isinstance(detail.get("reason_code"), str):
        entry["reason_code"] = detail["reason_code"]
    if isinstance(body, dict) and "final_score_x10" in body:
        entry["scores"] = {key: body.get(key) for key in _SCORE_FIELDS}
    snapshots[name] = entry
    dumps[name] = normalized


@pytest.fixture(scope="module")
def api_snapshots(tmp_path_factory) -> dict:
    snapshots: dict = {}
    dumps: dict = {}
    db_file = tmp_path_factory.mktemp("acceptance-api") / "fresh.db"
    with advisory_scenario(db_file) as (client, _factory, ids):
        advisory, aggressive, empty = ids["advisory"], ids["aggressive"], ids["empty"]

        def snap(name, response, **kwargs):
            _snapshot(name, response, snapshots, dumps, **kwargs)

        # Jurisdiktionen und Tax
        snap("jurisdictions.list", client.get("/jurisdictions"))
        snap("jurisdictions.ch", client.get("/jurisdictions/CH"))
        snap("jurisdictions.ch.home_bias", client.get("/jurisdictions/CH/home-bias-defaults"))
        snap("jurisdictions.unknown", client.get("/jurisdictions/XX"))
        snap("tax.jurisdictions", client.get("/tax/jurisdictions"))
        snap("tax.estimate.ch_zh", client.post("/tax/estimate", json={
            "country_code": "CH", "region": "ZH", "year": 2026,
            "taxable_income_rappen": 12_000_000, "taxable_wealth_rappen": 150_000_000,
        }))
        snap("tax.estimate.unknown", client.post("/tax/estimate", json={"country_code": "XX"}))

        # Referenzdaten
        for score in range(1, 11):
            snap(f"house_matrix.{score}", client.get(f"/house-matrix/{score}"))
        snap("building_blocks.current", client.get("/building-blocks/current"))
        snap("cma.current", client.get("/capital-market-assumptions/current"))
        snap("optimizer_policy.current", client.get("/optimizer-policies/current"))

        # Profiling (Standard-Fragebogen)
        snap("profiling.create.advisory", client.post(
            f"/mandates/{advisory}/risk-assessments", json=standard_risk_payload()))
        snap("profiling.current.advisory", client.get(f"/mandates/{advisory}/risk-assessments/current"))
        # Bereitschafts-Summe 11 statt 12: Summen 3-6 und 12 scheitern in einer
        # frischen Installation am CHECK auf risk_willingness_profile (eigener
        # Befund, hier bewusst nicht als Basiswert eingefroren).
        top = standard_risk_payload(income=4, oblig=0, wealth=4, savings=4, horizon=5, goal=3, pref=3, behav=2)
        snap("profiling.create.top_score", client.post(f"/mandates/{aggressive}/risk-assessments", json=top))
        mismatch = standard_risk_payload()
        mismatch["q_income_points"] = (mismatch["q_income_points"] + 1) % 5
        snap("profiling.create.points_mismatch", client.post(f"/mandates/{empty}/risk-assessments", json=mismatch))
        snap("profiling.current.missing", client.get(f"/mandates/{empty}/risk-assessments/current"))

        # Fehlerpfade Allocation / Review
        snap("allocation.generate.no_profile", client.post(f"/mandates/{empty}/target-allocation/generate", json={}))
        snap("allocation.generate.no_wealth", client.post(f"/mandates/{advisory}/target-allocation/generate", json={}))
        snap("allocation.current.missing", client.get(f"/mandates/{advisory}/target-allocation/current"))
        snap("review.recommendation.generate.no_allocation",
             client.post(f"/mandates/{advisory}/recommendations/generate", json={}))
        snap("review.cost_disclosure_pdf.no_recommendation",
             client.get(f"/mandates/{advisory}/reports/cost-disclosure.pdf"))
        snap("review.unknown_mandate", client.get("/mandates/00000000-0000-0000-0000-000000000000/documents"))

        # Datenexport (Reihenfolge der Mandate/Antworten folgt Zeitstempel- bzw.
        # UUID-Gleichstand und ist deshalb nicht Teil des Basiswerts)
        snap("clients.data_export", client.get(f"/clients/{ids['client']}/data-export"), unordered=True)

    dump_actual("api_snapshots.json", json.dumps(dumps, sort_keys=True, ensure_ascii=False, indent=1))
    return snapshots


def test_api_snapshots_match_baseline(api_snapshots):
    assert_matches_baseline("api_snapshots_ch.json", api_snapshots)


def test_profiling_scores_are_readable_anchors(api_snapshots):
    # Lesbare Anker zum Hash (dieselben Werte wie die Punktetabelle aus G2).
    scores = {
        name: entry.get("scores")
        for name, entry in api_snapshots.items() if name.startswith("profiling.create.")
    }
    assert api_snapshots["profiling.create.advisory"]["status"] == 201
    assert api_snapshots["profiling.create.top_score"]["status"] == 201
    assert scores["profiling.create.advisory"]["final_score_x10"] == 70, scores
    assert scores["profiling.create.top_score"]["final_score_x10"] == 90, scores
