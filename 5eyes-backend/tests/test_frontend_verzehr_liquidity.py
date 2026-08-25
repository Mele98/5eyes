"""User-Fachentscheid 2026-06-17: Liquidität wertet NICHT auf (Cash = 0%).
Die FE-Vermögensverzehr-Projektion (wealthProjectionInputs / consumableReturnBps)
darf die Liquidität NICHT mit der CMA-Default-Rendite (0.8%) wachsen lassen —
sonst steigt die IST-Kurve eines reinen 0%-Konto-Kunden fälschlich.
Echte Konto-Zinsen laufen über den abgeleiteten Zinsertrag-Cashflow (kein Doppelzählen).
"""
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_verzehr_liquidity_does_not_default_to_cma():
    html = _html()
    # Alte Phantom-Wachstum-Quelle (Liquidität -> CMA/80bps) MUSS weg sein.
    assert "ADMIN_CMA_DEFAULTS.liquidity_return_bps||80" not in html
    # Begruendung/Marker des Fixes vorhanden.
    assert "Liquidität wertet NICHT auf (Cash = 0%" in html
