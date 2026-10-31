"""PROPERTY-GOAL-BASIS-001 (Audit 2026-09-14, User-Entscheid 2026-09-16):
`_build_external_goal_funding_series()` verwendete fuer die GESAMTE externe
Bruttobasis (inkl. einer darin enthaltenen Direktimmobilie) einheitlich CPI-
Wachstum, obwohl `property_series_rappen` dieselbe Immobilie bereits korrekt
mit der vom Kunden eingegebenen `asset_expected_return_bps` fortschreibt.
Zielentscheidung (dieser Pfad) und Gesamtvermoegens-Projektion (die
`property_series_rappen` direkt konsumiert) konnten dadurch fuer denselben
Jahrgang unterschiedliche Werte fuer dieselbe Immobilie zeigen.

Fix: der Immobilienanteil der Startbasis wird herausgerechnet und mit der
kanonischen property_series_rappen fortgeschrieben (Kundenwunsch: 0% bleibt
0%, 2% bleibt 2%); nur der verbleibende, nicht-immobilien-basierte externe
Anteil waechst weiterhin konservativ mit CPI (#83, User-Entscheid 2026-06-19).
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine import _build_external_goal_funding_series


def _foundation(property_series, liability_series=None, pledged_series=None):
    n = len(property_series)
    return {
        "property_series_rappen": property_series,
        "liability_series_rappen": liability_series or [0] * n,
        "pledged_asset_series_rappen": pledged_series or [0] * n,
    }


def test_audit_repro_zero_percent_property_return_stays_flat_not_cpi():
    """Exakter Audit-Repro: Immobilie 1'000'000, Immobilienrendite 0%, CPI 2%.
    Vorher wuchs die externe Basis trotz 0%-Immobilienrendite auf 1'020'000
    im Jahr 1 (CPI). Jetzt muss sie bei 1'000'000 bleiben (Kundenwunsch: 0%
    heisst 0%)."""
    series = _build_external_goal_funding_series(
        external_gross_assets_rappen=1_000_000,
        external_foundation_projection=_foundation([1_000_000, 1_000_000]),
        inflation_series_bps=[200, 200],
        horizon_years=1,
    )
    assert series == [1_000_000, 1_000_000]


def test_property_return_above_cpi_grows_at_property_rate_not_cpi():
    """Immobilienrendite 4% > CPI 2%: die Basis muss mit 4% wachsen (Kunden-
    eingabe), nicht mit den konservativeren 2% CPI."""
    series = _build_external_goal_funding_series(
        external_gross_assets_rappen=1_000_000,
        external_foundation_projection=_foundation([1_000_000, 1_040_000]),
        inflation_series_bps=[200],
        horizon_years=1,
    )
    assert series == [1_000_000, 1_040_000]


def test_negative_property_return_is_honored():
    """Eine vom Kunden eingegebene negative Immobilienrendite darf die
    Zielbasis auch tatsaechlich sinken lassen, nicht auf CPI-Wachstum
    zurueckfallen."""
    series = _build_external_goal_funding_series(
        external_gross_assets_rappen=1_000_000,
        external_foundation_projection=_foundation([1_000_000, 950_000]),
        inflation_series_bps=[200],
        horizon_years=1,
    )
    assert series == [1_000_000, 950_000]


def test_non_property_external_assets_still_grow_with_cpi():
    """Regressionsschutz (#83, User-Entscheid 2026-06-19): externe Assets
    OHNE Immobilienanteil (property_series bleibt 0) wachsen weiterhin
    konservativ nur mit CPI -- unveraendertes Verhalten fuer z.B. eine
    Beteiligung ohne eigene Renditeserie."""
    series = _build_external_goal_funding_series(
        external_gross_assets_rappen=1_000_000,
        external_foundation_projection=_foundation([0, 0]),
        inflation_series_bps=[200],
        horizon_years=1,
    )
    assert series == [1_000_000, 1_020_000]


def test_mixed_property_and_non_property_external_assets_split_correctly():
    """Gemischter Fall: externe Gesamtbasis enthaelt eine Immobilie (600'000,
    0% Rendite) UND eine andere externe Position (400'000, kein eigener
    Renditepfad). Die Immobilie bleibt flach, der Rest waechst mit CPI --
    beide Anteile werden korrekt getrennt fortgeschrieben."""
    series = _build_external_goal_funding_series(
        external_gross_assets_rappen=1_000_000,  # 600k Immobilie + 400k Rest
        external_foundation_projection=_foundation([600_000, 600_000]),
        inflation_series_bps=[200],
        horizon_years=1,
    )
    # Jahr 1: 400'000 * 1.02 (CPI) + 600'000 (Immobilie, 0%) = 1'008'000
    assert series == [1_000_000, 1_008_000]


def test_liability_and_pledged_series_still_applied_on_top():
    """Regressionsschutz: Liability-Abzug und Pledged-Zuschlag bleiben nach
    dem Property/CPI-Split unveraendert additiv wirksam."""
    series = _build_external_goal_funding_series(
        external_gross_assets_rappen=1_000_000,
        external_foundation_projection=_foundation(
            property_series=[1_000_000, 1_000_000],
            liability_series=[300_000, 250_000],
            pledged_series=[0, 50_000],
        ),
        inflation_series_bps=[200],
        horizon_years=1,
    )
    # Jahr 0: 1'000'000 (Immobilie, kein Rest) - 300'000 Liability = 700'000
    # Jahr 1: 1'000'000 (Immobilie, 0%) + 50'000 Pledged - 250'000 Liability = 800'000
    assert series == [700_000, 800_000]


def test_property_series_length_mismatch_raises():
    """Regressionsschutz: eine zu kurze property_series wird jetzt genauso
    fail-closed abgewiesen wie liability/pledged (dieselbe Symmetrie wie die
    bestehende Laengenpruefung fuer die anderen beiden Serien)."""
    from services.optimizer.constraints import OptimizerInputError

    try:
        _build_external_goal_funding_series(
            external_gross_assets_rappen=1_000_000,
            external_foundation_projection={
                "property_series_rappen": [1_000_000],
                "liability_series_rappen": [0, 0],
                "pledged_asset_series_rappen": [0, 0],
            },
            inflation_series_bps=[200],
            horizon_years=1,
        )
        assert False, "expected OptimizerInputError"
    except OptimizerInputError:
        pass
