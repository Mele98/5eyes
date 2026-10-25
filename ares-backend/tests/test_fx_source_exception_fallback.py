"""2026-07-24 (Generalaudit): FXRateSource.from_db() faengt intern bereits
JEDEN Fehler ab und faellt selbst auf Default-Kurse zurueck (services/
currency/fx_rates.py::from_db). Trotzdem gab es an 5 Aufrufstellen
(routers/clients.py x2, services/portfolio_engine.py x2,
services/advisory_report.py x1) einen AEUSSEREN `except Exception:
fx_source = None` -- praktisch unerreichbar, aber falls doch (z.B. ein
Import-Fehler), war der Fallback SCHLECHTER als der von from_db() selbst:
fx_source=None bedeutet fuer totals_for_year() "Waehrung ignorieren"
(Fremdwaehrungs-Betraege im Rohwert), statt wenigstens eine Naeherung
(Default-Kurse) zu zeigen.

Dieser Test beweist den Fix an der am einfachsten end-to-end testbaren
Stelle (cashflow-summary-Endpoint, CF-2-Nachbarschaft): wenn
FXRateSource.from_db() SELBST (simuliert) fehlschlaegt, konvertiert der
Endpoint weiterhin (mit Default-Kursen) statt die Konvertierung komplett
zu deaktivieren.
"""
from __future__ import annotations
import datetime

import pytest

from services.currency.fx_rates import FXRateSource
from test_cf2_cashflow_summary_fx import (  # noqa: F401
    _add_cashflow,
    _make_client,
    advisor_user,
    auth_client,
    session_factory,
)


def test_summary_still_converts_when_from_db_raises(auth_client, session_factory, advisor_user, monkeypatch):
    """Simuliert einen Fehler INNERHALB von FXRateSource.from_db() (z.B. ein
    DB-Problem, das from_db()'s eigenes internes try/except nicht mehr
    schuetzen kann, weil der Fehler beim Methodenaufruf selbst passiert) --
    der aeussere except-Fallback muss WEITERHIN konvertieren, nicht auf
    Rohbetrag zurueckfallen."""
    def _raise(*args, **kwargs):
        raise RuntimeError("simulierter FX-Ladefehler")
    monkeypatch.setattr(FXRateSource, "from_db", classmethod(_raise))

    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    _add_cashflow(
        session_factory, cid,
        label="US-Lohn", cashflow_type="Income",
        amount_rappen=1_000_000, currency="USD", frequency="jährlich",
        valid_from=f"{this_year}-01-01",
    )
    resp = auth_client.get(f"/clients/{cid}/cashflow-summary")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Muss WEITERHIN konvertiert sein (Default-Kurs 0.88), NICHT der USD-
    # Rohbetrag 1_000_000 -- das war der Bug (fx_source=None -> keine Konvertierung).
    assert body["recurring_income_rappen"] == pytest.approx(880_000, abs=1)
    assert body["recurring_income_rappen"] != 1_000_000


def test_no_five_bare_none_fallbacks_remain_in_codebase():
    """Drift-Wache: keine der 5 heute gefundenen Stellen darf zu
    `fx_source = None` im except-Zweig zurueckfallen."""
    import re
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[1]
    files = [
        backend_root / "routers" / "clients.py",
        backend_root / "services" / "portfolio_engine.py",
        backend_root / "services" / "advisory_report.py",
    ]
    pattern = re.compile(r"except Exception[^\n]*:\s*\n\s*fx_source\s*=\s*None")
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), (
            f"{path}: except-Zweig faellt noch auf fx_source=None zurueck "
            "(sollte FXRateSource() sein)"
        )
