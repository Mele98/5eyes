"""KN4-B / E2E4-02: Review-Ist und -Soll auf derselben Basis, Reserve getrennt.

Befund (Dok. 119): Persona C (Kapitalschutz, Liquiditaetsreserve ausserhalb der
Strategie: Beratungsvermoegen 399'000, Strategiebasis 230'970, Reserve 168'030).
Der Review empfahl «Obligationen aufstocken 63.4 % -> 92.0 %» und «Liquiditaet
reduzieren 8.8 % -> 5.2 %». In Franken ist es umgekehrt (Soll Obligationen
212'492 < Ist 253'000; Soll Liquiditaet 11'987 + Reserve 168'030 > Ist 35'000).
Ursache: Ist auf dem Beratungsvermoegen, Soll auf der Strategiebasis.

Jetzt (services/portfolio_engine_payload._bucket_rows, eine Quelle fuer
Generate, Reload und Review-Trigger): Ist auf der Strategiebasis, die Reserve
wird vom Liquiditaets-Ist abgezogen und getrennt ausgewiesen. Richtung in
Franken = Richtung in %. Ohne Reserve ist alles unveraendert.

Gegenprobe: Ist wieder auf dem Beratungsvermoegen -> rot.
"""
from __future__ import annotations

from types import SimpleNamespace

ADVISORY = 399_000_00
BASE = 230_970_00
RESERVE = ADVISORY - BASE
HOLDINGS = {"equities": 0, "bonds": 253_000_00, "real_estate": 0, "alternatives": 111_000_00,
            "liquidity": 35_000_00}
TARGETS = {"equities": (0, 0, 0), "bonds": (9200, 8000, 10000), "real_estate": (0, 0, 0),
           "alternatives": (280, 0, 500), "liquidity": (520, 0, 1000)}


def _label_map(targets=TARGETS):
    names = {"equities": "Aktien", "bonds": "Obligationen", "real_estate": "Immobilien",
             "alternatives": "Alternative", "liquidity": "Liquiditaet"}
    return {key: (names[key], *targets[key]) for key in names}


def _rows(base=BASE, holdings=HOLDINGS):
    from services.portfolio_engine import _bps
    from services.portfolio_engine_payload import _bucket_rows

    return {row["asset_class"]: row for row in _bucket_rows(_label_map(), holdings, ADVISORY, base, bps=_bps)}


def test_direction_in_francs_matches_direction_in_percent_with_reserve():
    rows = _rows()
    for row in rows.values():
        amount_delta = (row["target_amount_rappen"] + row.get("reserve_rappen", 0)
                        - row["current_amount_rappen"])
        if row["delta_weight_bps"]:
            assert (amount_delta > 0) == (row["delta_weight_bps"] > 0), row
    bonds, liq = rows["Obligationen"], rows["Liquiditaet"]
    # Obligationen: reduzieren (212'492 Soll < 253'000 Ist).
    assert bonds["delta_weight_bps"] < 0 and bonds["current_weight_bps"] > 10000 - 1 and bonds["current_weight_bps"] > 9200
    # Liquiditaet: Reserve 168'030 + Soll 11'987 gegen Ist 35'000 -> aufstocken.
    assert liq["delta_weight_bps"] > 0
    # Strategieanteil des Bestands: 35'000 Liquiditaet abzueglich Reserve; der
    # ausgewiesene Bestand bleibt der tatsaechliche (externe Abnahme g).
    assert liq["current_strategy_amount_rappen"] == 35_000_00 - RESERVE
    assert liq["current_amount_rappen"] == 35_000_00
    # Summen-Konsistenz: Ist-Summe = Soll-Summe + Reserve = Beratungsvermoegen.
    assert abs(sum(r["current_amount_rappen"] for r in rows.values())
               - sum(r["target_amount_rappen"] for r in rows.values()) - RESERVE) <= 500
    # Reserve getrennt ausgewiesen, tatsaechlicher Bestand erhalten.
    assert liq["reserve_rappen"] == RESERVE and liq["reserve_funded_rappen"] == 35_000_00
    assert liq["reserve_gap_rappen"] == RESERVE - 35_000_00
    assert liq["current_amount_total_rappen"] == 35_000_00
    assert all(row["comparison_basis"] == "strategy" for row in rows.values())
    # Ist summiert auf der Strategiebasis zu 100 %.
    assert abs(sum(row["current_weight_bps"] for row in rows.values()) - 10000) <= 2


def test_implementation_steps_follow_the_franc_direction():
    from services.portfolio_engine_payload import _implementation_steps

    steps = _implementation_steps(list(_rows().values()), BASE)
    assert any(step.startswith("Obligationen reduzieren") for step in steps), steps
    assert any(step.startswith("Liquiditaet aufbauen") for step in steps), steps


def test_without_reserve_nothing_changes():
    from services.portfolio_engine import _bps

    rows = _rows(base=ADVISORY)
    for key, row in zip(HOLDINGS, rows.values()):
        assert row["current_weight_bps"] == _bps(HOLDINGS[key], ADVISORY)
        assert row["current_amount_rappen"] == HOLDINGS[key]
        assert row["comparison_basis"] == "advisory_wealth"
    assert rows["Liquiditaet"]["reserve_rappen"] == 0


def test_bucket_response_and_review_drift_use_the_same_basis():
    from services.portfolio_engine_payload import _build_bucket_response

    allocation = SimpleNamespace(**{f"target_{k}_bps": v[0] for k, v in TARGETS.items()},
                                 **{f"band_{k}_min_bps": v[1] for k, v in TARGETS.items()},
                                 **{f"band_{k}_max_bps": v[2] for k, v in TARGETS.items()})
    rows = {r["asset_class"]: r for r in _build_bucket_response(allocation, HOLDINGS, ADVISORY,
                                                                 target_total_rappen=BASE)}
    assert rows["Obligationen"]["delta_weight_bps"] < 0 and rows["Liquiditaet"]["delta_weight_bps"] > 0
