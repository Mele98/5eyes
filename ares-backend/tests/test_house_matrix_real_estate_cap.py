from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import migrate_house_matrix_real_estate_cap_20  # noqa: E402
from services.house_matrix_loader import (  # noqa: E402
    _HARDCODED_FALLBACK,
    load_house_matrix_default_tuples,
)
from services.portfolio_engine import _baseline_target_bands  # noqa: E402


def test_all_default_profiles_allow_up_to_twenty_percent_real_estate():
    """Owner-Entscheid 2026-06-14 gilt fuer jedes Profil, fuer das
    ueberhaupt ein suitability-geeignetes Immobilien-Produkt existieren
    kann. CERT-PRODUCT-ELIGIBILITY-001 (2026-10-10, Befund B) stellte fest,
    dass Immobilien (wie Aktien) erst ab Score 4 geeignet ist (siehe
    services/product_eligibility.py::default_product_risk_band()) --
    Kapitalschutz (Score 1-2) und die Defensiv-Zeile fuer Score 3 bekommen
    deshalb bewusst real_estate_max_bps=0 statt 2000: ein 20%-Band, das nie
    mit einem eligible Produkt gefuellt werden kann, ist keine echte
    Flexibilitaet, sondern eine garantierte Produktselektions-Luecke."""
    yaml_defaults = load_house_matrix_default_tuples()
    no_eligible_re_product = {(1, 2), (3, 3)}  # score_from, score_to
    for profile in yaml_defaults:
        score_range = (profile[0], profile[1])
        if score_range in no_eligible_re_product:
            assert profile[14] == 0, (
                f"{profile[2]} (Score {score_range}) sollte real_estate_max_bps=0 haben "
                f"(kein eligible Immobilien-Produkt unterhalb Score 4)."
            )
        else:
            assert profile[14] == 2000, (
                f"{profile[2]} (Score {score_range}) sollte real_estate_max_bps=2000 haben."
            )
    for profile in _HARDCODED_FALLBACK:
        score_range = (profile[0], profile[1])
        expected = 0 if score_range in no_eligible_re_product else 2000
        assert profile[14] == expected


def test_twenty_percent_is_a_band_cap_not_a_forced_target():
    house_matrix = SimpleNamespace(
        equity_target_bps=4800,
        bonds_target_bps=3500,
        real_estate_target_bps=1000,
        alt_target_bps=500,
        liq_target_bps=200,
        equity_min_bps=4000,
        equity_minimum_bps=0,
        bonds_min_bps=2500,
        real_estate_min_bps=500,
        alt_min_bps=300,
        liq_min_bps=0,
        equity_max_bps=5500,
        bonds_max_bps=4500,
        real_estate_max_bps=2000,
        alt_max_bps=800,
        liq_max_bps=300,
    )
    policy = SimpleNamespace(
        max_real_estate_bps=2000,
        max_alternatives_bps=1000,
        min_liquidity_bps=0,
    )

    targets, _minimums, maximums = _baseline_target_bands(house_matrix, policy)

    assert targets["real_estate"] == 1000
    assert maximums["real_estate"] == 2000


def test_migration_updates_only_legacy_defaults_on_current_policy(tmp_path):
    db_engine = create_engine(f"sqlite:///{tmp_path / 'house-matrix.db'}")
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE optimizer_policies (
                    id INTEGER PRIMARY KEY,
                    is_current INTEGER NOT NULL,
                    max_real_estate_bps INTEGER
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE house_matrix (
                    id INTEGER PRIMARY KEY,
                    policy_id INTEGER NOT NULL,
                    profile_name TEXT NOT NULL,
                    real_estate_max_bps INTEGER NOT NULL,
                    is_active INTEGER NOT NULL,
                    updated_at TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO optimizer_policies (id, is_current, max_real_estate_bps)
                VALUES (1, 1, 2000), (2, 0, 2000)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO house_matrix
                    (id, policy_id, profile_name, real_estate_max_bps, is_active)
                VALUES
                    (1, 1, 'Ausgewogen', 1500, 1),
                    (2, 1, 'Wachstum', 1200, 1),
                    (3, 1, 'Defensiv', 1700, 1),
                    (4, 2, 'Aktien', 800, 1),
                    (5, 1, 'Dynamisch', 1000, 0)
                """
            )
        )

    assert migrate_house_matrix_real_estate_cap_20(db_engine) == 2
    assert migrate_house_matrix_real_estate_cap_20(db_engine) == 0

    with db_engine.connect() as conn:
        rows = dict(
            conn.execute(
                text(
                    "SELECT id, real_estate_max_bps FROM house_matrix ORDER BY id"
                )
            ).all()
        )

    assert rows == {1: 2000, 2: 2000, 3: 1700, 4: 800, 5: 1000}
