"""Regressions-Lock: Liquiditaet wertet in der Projektion NICHT auf (Cash = 0 %).

User-Fachentscheid 2026-06-17 ("solche Sachen sind verdammt gefaehrlich"): ein 0%-Konto
muss in der Vermoegensprojektion flach bleiben. Echte Kontozinsen laufen ausschliesslich
ueber den abgeleiteten Zinsertrag-Cashflow (kein Doppelzaehlen). Die Engine setzt daher
returns["liquidity"]=0 und vols["liquidity"]=0 in BEIDEN Pfaden (deterministisch +
Monte-Carlo). Dieser Lock verhindert, dass die CMA-liquidity_return_bps versehentlich
wieder ins Bucket-Wachstum einfliesst.
"""
from pathlib import Path

# ADR-014 (Engine-God-Modul-Split, ab 2026-08-02): der Engine-Code lebt nicht
# mehr nur in portfolio_engine.py, sondern zunehmend in per-Cluster
# Submodulen (services/portfolio_engine_<cluster>.py, z.B. beide hier
# gesperrten Vorkommen -- deterministischer UND Monte-Carlo-Pfad -- liegen
# nach Schritt 5 beide in portfolio_engine_mc_simulation.py). Damit dieser
# Lock unabhaengig davon greift, WELCHE Datei den Code aktuell haelt, wird
# ueber portfolio_engine.py + alle portfolio_engine_*.py Submodule gescannt.
_SERVICES_DIR = Path(__file__).resolve().parents[1] / "services"
ENGINE = "\n".join(
    p.read_text(encoding="utf-8")
    for p in sorted(_SERVICES_DIR.glob("portfolio_engine*.py"))
)


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
