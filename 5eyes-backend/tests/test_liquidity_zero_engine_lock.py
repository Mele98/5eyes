"""Regressions-Lock: Liquiditaet wertet in der Projektion NICHT auf (Cash = 0 %).

User-Fachentscheid 2026-06-17 ("solche Sachen sind verdammt gefaehrlich"): ein 0%-Konto
muss in der Vermoegensprojektion flach bleiben. Echte Kontozinsen laufen ausschliesslich
ueber den abgeleiteten Zinsertrag-Cashflow (kein Doppelzaehlen). Die Engine setzt daher
returns["liquidity"]=0 und vols["liquidity"]=0 in BEIDEN Pfaden (deterministisch +
Monte-Carlo). Dieser Lock verhindert, dass die CMA-liquidity_return_bps versehentlich
wieder ins Bucket-Wachstum einfliesst.
"""
from pathlib import Path

ENGINE = (Path(__file__).resolve().parents[1] / "services" / "portfolio_engine.py").read_text(encoding="utf-8")


def test_liquidity_returns_zeroed_in_both_paths():
    # Beide Engine-Pfade (deterministisch _build_simulation_payload + MC
    # _run_allocation_monte_carlo) muessen die Liquiditaets-Rendite nullen.
    assert ENGINE.count('returns = {**returns, "liquidity": 0}') >= 2, (
        "Liquiditaets-Rendite wird nicht in beiden Pfaden genullt (Cash-0%-Invariante)"
    )
    assert ENGINE.count('vols = {**vols, "liquidity": 0}') >= 2, (
        "Liquiditaets-Vola wird nicht in beiden Pfaden genullt"
    )


def test_rationale_documented_in_code():
    # Begruendung muss im Code stehen, damit der Entscheid nicht versehentlich
    # zurueckgedreht wird.
    assert "Cash = 0%" in ENGINE or "Cash = 0 %" in ENGINE or "Liquidität wertet" in ENGINE
    assert "Zinsertrag" in ENGINE  # echte Zinsen laufen ueber den abgeleiteten Cashflow
