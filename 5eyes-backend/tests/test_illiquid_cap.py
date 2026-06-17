"""3eyes-Parität: maxIlliquid deckelt NUR den echt illiquiden Baustein (Private
Equity), nicht die ganze Alternatives-Quote.

Methodik (drei augen.pdf): Illiquidität ist eine Baustein-Eigenschaft.
Direktimmobilien laufen extern über das Gesamtvermögen; der einzige illiquide
Baustein in der handelbaren SAA ist Private Equity. Gold / Liquid Alts sind
liquide und dürfen vom Illiquiditäts-Limit NICHT getroffen werden.
"""
from services.portfolio_engine import _apply_illiquid_cap


def _targets(**over):
    base = {"equities": 4000, "bonds": 3000, "real_estate": 2000, "alternatives": 1000, "liquidity": 0}
    base.update(over)
    return base


def _sum_subs(subs):
    return sum(int(s["target_weight_bps"]) for s in subs)


def test_pe_capped_freed_goes_to_liquid_alt_quote_unchanged():
    subs = [
        {"asset_class": "Alternative", "sub_asset_class": "Gold / Rohstoffe", "target_weight_bps": 600, "rationale": ""},
        {"asset_class": "Alternative", "sub_asset_class": "Private Equity", "target_weight_bps": 400, "rationale": ""},
    ]
    targets = _targets(alternatives=1000)
    reasoning = []
    out_subs, out_targets = _apply_illiquid_cap(subs, targets, 200, reasoning)

    pe = next(s for s in out_subs if s["sub_asset_class"] == "Private Equity")
    gold = next(s for s in out_subs if s["sub_asset_class"] == "Gold / Rohstoffe")
    assert pe["target_weight_bps"] == 200          # auf das Limit gedeckelt
    assert gold["target_weight_bps"] == 800        # 200 bps zu liquidem Sleeve
    assert out_targets["alternatives"] == 1000     # Alternatives-Quote UNVERAENDERT
    assert _sum_subs(out_subs) == 1000             # nichts verloren (600+400 -> 800+200)
    assert reasoning and "liquiden" in reasoning[0]


def test_pe_only_freed_goes_to_liquidity_and_reduces_alternatives():
    subs = [
        {"asset_class": "Alternative", "sub_asset_class": "Private Equity", "target_weight_bps": 1000, "rationale": ""},
        {"asset_class": "Liquiditaet", "sub_asset_class": "Geldmarktfonds", "target_weight_bps": 500, "rationale": ""},
    ]
    targets = _targets(alternatives=1000, liquidity=500, equities=4000, bonds=3000, real_estate=1500)
    total_before = sum(targets.values())
    reasoning = []
    out_subs, out_targets = _apply_illiquid_cap(subs, targets, 300, reasoning)

    pe = next(s for s in out_subs if s["sub_asset_class"] == "Private Equity")
    liq = next(s for s in out_subs if s["asset_class"] == "Liquiditaet")
    assert pe["target_weight_bps"] == 300
    assert out_targets["alternatives"] == 300              # 700 bps raus aus Alternativen
    assert out_targets["liquidity"] == 1200                # 700 bps in die Liquiditaet
    assert liq["target_weight_bps"] == 1200
    assert sum(out_targets.values()) == total_before       # 100% erhalten
    assert reasoning and "Liquiditaet" in reasoning[0]


def test_pe_below_cap_is_untouched():
    subs = [
        {"asset_class": "Alternative", "sub_asset_class": "Gold / Rohstoffe", "target_weight_bps": 800, "rationale": ""},
        {"asset_class": "Alternative", "sub_asset_class": "Private Equity", "target_weight_bps": 200, "rationale": ""},
    ]
    targets = _targets(alternatives=1000)
    reasoning = []
    out_subs, out_targets = _apply_illiquid_cap(subs, targets, 500, reasoning)
    pe = next(s for s in out_subs if s["sub_asset_class"] == "Private Equity")
    assert pe["target_weight_bps"] == 200      # unter Limit -> unveraendert
    assert reasoning == []


def test_no_cap_means_no_change():
    subs = [
        {"asset_class": "Alternative", "sub_asset_class": "Private Equity", "target_weight_bps": 900, "rationale": ""},
    ]
    targets = _targets(alternatives=900)
    out_subs, out_targets = _apply_illiquid_cap(subs, targets, None, [])
    assert out_subs[0]["target_weight_bps"] == 900


def test_gold_liquidalts_not_treated_as_illiquid():
    """Reine liquide Alternatives (Gold + Liquid Alts) duerfen vom Illiquiditaets-
    Limit nie getroffen werden, auch bei sehr tiefem Limit."""
    subs = [
        {"asset_class": "Alternative", "sub_asset_class": "Gold / Rohstoffe", "target_weight_bps": 700, "rationale": ""},
        {"asset_class": "Alternative", "sub_asset_class": "Liquid Alternatives", "target_weight_bps": 300, "rationale": ""},
    ]
    targets = _targets(alternatives=1000)
    reasoning = []
    out_subs, out_targets = _apply_illiquid_cap(subs, targets, 100, reasoning)
    assert [s["target_weight_bps"] for s in out_subs] == [700, 300]   # nichts gedeckelt
    assert out_targets["alternatives"] == 1000
    assert reasoning == []
