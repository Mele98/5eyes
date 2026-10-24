"""Tests fuer services/optimizer/goal_liabilities.py.

Pro Goal-Typ einzelne Tests, plus Aggregation. Liability-Pfade muessen
konsistent zur Convention sein:
  liability_path_rappen[0] = Outflow im naechsten Jahr (Jahr 1)
  liability_path_rappen[T-1] = Outflow im Jahr T (= horizon_years)

Inflation greift nur wenn value_mode='real'. Hardness und Weight haben
sinnvolle Defaults.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.optimizer.goal_liabilities import (
    GoalLiability,
    aggregate_liability_path,
    goal_to_liability,
    goals_to_liabilities,
)


def _make_goal(
    *,
    goal_id: str = "g1",
    label: str = "Test",
    goal_type: str = "Vermoegensziel",
    target_amount_rappen: int | None = None,
    target_wealth_rappen: int | None = None,
    target_return_bps: int | None = None,
    horizon_years: int | None = None,
    target_date: str | None = None,
    start_date: str | None = None,
    is_ongoing: int = 0,
    frequency: str | None = None,
    hardness: str = "Primaer",
    rank: int = 2,
    weight_bps: int | None = None,
    value_mode: str = "nominal",
    goal_scope: str = "Beratungsvermoegen",
    pension_pillar: str | None = None,
):
    """Mock-Goal als SimpleNamespace (kein DB-Objekt noetig)."""
    return SimpleNamespace(
        id=goal_id,
        label=label,
        goal_type=goal_type,
        target_amount_rappen=target_amount_rappen,
        target_wealth_rappen=target_wealth_rappen,
        target_return_bps=target_return_bps,
        horizon_years=horizon_years,
        target_date=target_date,
        start_date=start_date,
        is_ongoing=is_ongoing,
        frequency=frequency,
        hardness=hardness,
        rank=rank,
        weight_bps=weight_bps,
        value_mode=value_mode,
        goal_scope=goal_scope,
        pension_pillar=pension_pillar,
    )


# ============================================================================
# Renditeziel: kein Outflow, target ist bps
# ============================================================================


def test_renditeziel_returns_zero_path_and_bps_target():
    goal = _make_goal(goal_type="Renditeziel", target_return_bps=450, horizon_years=10)
    liab = goal_to_liability(goal, horizon_years=10)
    assert liab.target_kind == "return_rate"
    assert liab.target_amount_rappen == 450  # ist bps in diesem Feld
    assert liab.liability_path_rappen == [0] * 10
    assert liab.target_year_index == 10


def test_renditeziel_with_zero_target_clamped():
    goal = _make_goal(goal_type="Renditeziel", target_return_bps=None, horizon_years=5)
    liab = goal_to_liability(goal, horizon_years=5)
    assert liab.target_amount_rappen == 0


# ============================================================================
# Vermoegensziel / Kapitalerhalt: Wealth-Schwelle in Zieljahr
# ============================================================================


def test_vermoegensziel_nominal_no_inflation_applied():
    goal = _make_goal(
        goal_type="Vermoegensziel",
        target_wealth_rappen=1_000_000_00,
        horizon_years=10,
        value_mode="nominal",
    )
    liab = goal_to_liability(goal, horizon_years=10, inflation_series_bps=[200] * 10)
    assert liab.target_kind == "wealth_at_t"
    assert liab.target_amount_rappen == 1_000_000_00


def test_total_wealth_goal_credits_inflation_projected_external_assets():
    goal = _make_goal(
        goal_type="Vermoegensziel",
        target_wealth_rappen=1_500_000_00,
        horizon_years=10,
        value_mode="nominal",
        goal_scope="Gesamtvermoegen",
    )

    liab = goal_to_liability(
        goal,
        horizon_years=10,
        inflation_series_bps=[200] * 10,
        external_wealth_rappen=800_000_00,
    )

    external_projected = int(round(800_000_00 * (1.02 ** 10)))
    assert liab.target_kind == "wealth_at_t"
    assert liab.target_amount_rappen == 1_500_000_00 - external_projected
    assert "Gesamtvermoegensziel" in str(liab.evaluation_note)


def test_total_wealth_goal_uses_exact_external_series_value_at_target_year():
    goal = _make_goal(
        goal_type="Vermoegensziel",
        target_wealth_rappen=150_000_000,
        horizon_years=3,
        value_mode="nominal",
        goal_scope="Gesamtvermoegen",
    )

    liability = goal_to_liability(
        goal,
        horizon_years=3,
        inflation_series_bps=[2500, 2500, 2500],
        external_wealth_rappen=60_000_000,
        external_wealth_series_rappen=[
            60_000_000,
            75_000_000,
            90_000_000,
            110_000_000,
        ],
    )

    # The exact year-3 value wins over the legacy CPI reconstruction
    # (60m * 1.25^3 = 117.1875m).
    assert liability.target_year_index == 3
    assert liability.target_amount_rappen == 40_000_000


def test_goals_to_liabilities_forwards_exact_external_series():
    goal = _make_goal(
        goal_type="Kapitalerhalt",
        target_wealth_rappen=100_000_000,
        horizon_years=2,
        value_mode="nominal",
        goal_scope="Gesamtvermoegen",
    )

    liabilities = goals_to_liabilities(
        [goal],
        horizon_years=2,
        external_wealth_rappen=10_000_000,
        external_wealth_series_rappen=[10_000_000, 25_000_000, 40_000_000],
    )

    assert len(liabilities) == 1
    assert liabilities[0].target_amount_rappen == 60_000_000


def test_direct_and_indirect_amortization_series_have_same_net_goal_credit():
    goal = _make_goal(
        goal_type="Vermoegensziel",
        target_wealth_rappen=150_000_000,
        horizon_years=2,
        value_mode="nominal",
        goal_scope="Gesamtvermoegen",
    )
    property_series = [100_000_000, 100_000_000, 100_000_000]

    # Direct amortization: debt falls by 10m per year.
    direct_liability = [40_000_000, 30_000_000, 20_000_000]
    direct_pledged = [0, 0, 0]
    direct_external = [
        property_series[i] + direct_pledged[i] - direct_liability[i]
        for i in range(3)
    ]

    # Indirect amortization: debt stays flat while the pledged asset receives
    # the same 10m transfers.  Net external wealth is therefore identical.
    indirect_liability = [40_000_000, 40_000_000, 40_000_000]
    indirect_pledged = [0, 10_000_000, 20_000_000]
    indirect_external = [
        property_series[i] + indirect_pledged[i] - indirect_liability[i]
        for i in range(3)
    ]

    assert direct_external == indirect_external == [60_000_000, 70_000_000, 80_000_000]

    direct = goal_to_liability(
        goal,
        horizon_years=2,
        external_wealth_series_rappen=direct_external,
    )
    indirect = goal_to_liability(
        goal,
        horizon_years=2,
        external_wealth_series_rappen=indirect_external,
    )

    assert direct.target_amount_rappen == indirect.target_amount_rappen == 70_000_000


def test_ahv_pension_is_a_normal_portfolio_liability_now():
    """PENSION-AHV-001 (Phase 0, 2026-09): vorher (siehe git history) wurde
    ein AHV-Pensionsausgabe-Goal hier zu target_kind='state_funded' mit
    target_amount_rappen=0 und success_probability_min_x100=10000 gebaut --
    eine Liability, die der Optimizer komplett ignorieren konnte, obwohl es
    keinerlei Beleg fuer eine tatsaechliche AHV-Rente gibt (kein
    Betragsfeld in schemas/wealth.py GoalCreate/-Update). Fix: pension_pillar
    aendert die Liability-Konstruktion nicht mehr -- ein AHV-Goal wird wie
    jedes andere Wiederkehrende_Ausgabe/Pensionsausgabe-Goal via
    _build_recurring_outflow() zu einem echten outflow_stream mit realem
    Betrag und Erfolgs-Schwelle."""
    goal = _make_goal(
        goal_type="Pensionsausgabe",
        target_amount_rappen=30_000_00,
        horizon_years=10,
        is_ongoing=1,
        frequency="jaehrlich",
        pension_pillar="AHV",
    )

    liab = goal_to_liability(goal, horizon_years=10)

    assert liab.target_kind == "outflow_stream"
    assert liab.target_amount_rappen == 3_000_000
    assert liab.liability_path_rappen == [0] * 9 + [3_000_000]
    assert liab.target_year_index == 10
    # Default-Erfolgsschwelle fuer outflow_stream-Goals (siehe
    # _build_recurring_outflow), NICHT mehr die kuenstliche 100%
    # (10000 x100) des fruehen state_funded-Sonderpfads.
    assert liab.success_probability_min_x100 == 8000

    # Regressionsschutz: identisch zu einem Goal OHNE pension_pillar --
    # das Label allein darf die Liability nicht mehr veraendern.
    goal_no_pillar = _make_goal(
        goal_type="Pensionsausgabe",
        target_amount_rappen=30_000_00,
        horizon_years=10,
        is_ongoing=1,
        frequency="jaehrlich",
        pension_pillar=None,
    )
    liab_no_pillar = goal_to_liability(goal_no_pillar, horizon_years=10)
    assert liab == liab_no_pillar


def test_vermoegensziel_real_applies_compound_inflation():
    """value_mode='real' -> target wird mit kumulativer Inflation hochgerechnet."""
    goal = _make_goal(
        goal_type="Vermoegensziel",
        target_wealth_rappen=1_000_000_00,
        horizon_years=5,
        value_mode="real",
    )
    liab = goal_to_liability(goal, horizon_years=5, inflation_series_bps=[200] * 5)
    # Ziel: 1M heute -> 1M * 1.02^5 = 1'104'080.80 in 5 Jahren
    expected = int(round(1_000_000_00 * (1.02 ** 5)))
    assert liab.target_amount_rappen == pytest.approx(expected, abs=10)


def test_kapitalerhalt_uses_wealth_target():
    goal = _make_goal(
        goal_type="Kapitalerhalt",
        target_wealth_rappen=500_000_00,
        horizon_years=3,
    )
    liab = goal_to_liability(goal, horizon_years=3)
    assert liab.target_kind == "wealth_at_t"
    assert liab.target_amount_rappen == 500_000_00


def test_vermoegensziel_target_year_clamped_to_horizon():
    """Wenn horizon_years=10 aber goal.horizon_years=20 -> auf 10 geclamped."""
    goal = _make_goal(
        goal_type="Vermoegensziel",
        target_wealth_rappen=1_000_000_00,
        horizon_years=20,
    )
    liab = goal_to_liability(goal, horizon_years=10)
    assert liab.target_year_index == 10


# ============================================================================
# Einmalige_Ausgabe: Outflow in Zieljahr
# ============================================================================


def test_einmalige_ausgabe_places_outflow_in_the_calendar_year_of_the_target_date():
    """Der Outflow liegt im KALENDERJAHR des Zieldatums.

    ADR-2 (2026-10-11): vorher kam der Index aus ``_resolve_target_year_index``
    und war ein Jahrestag-Bucket. Eine Ausgabe, deren Zieldatum im
    Kalenderjahr liegt, aber den Jahrestag des Stichtags noch nicht erreicht
    hat, wurde dem VORJAHR belastet. Da dieser Pfad in dasselbe
    ``liability_path_rappen`` schreibt wie die wiederkehrenden Stroeme und
    aggregate_liability_path() beide summiert, waeren das zwei Konventionen
    in einem Array gewesen.
    """
    today = date.today()
    target = (today + timedelta(days=365 * 4)).isoformat()
    goal = _make_goal(
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=100_000_00,
        target_date=target,
    )
    liab = goal_to_liability(goal, horizon_years=10)
    bucket = date.fromisoformat(target).year - today.year

    assert liab.target_kind == "cashflow_in_year"
    assert liab.target_amount_rappen == 100_000_00
    assert liab.target_year_index == bucket + 1
    expected_path = [0] * 10
    expected_path[bucket] = 100_000_00
    assert liab.liability_path_rappen == expected_path


def test_einmalige_ausgabe_real_value_mode_inflated():
    today = date.today()
    target = (today + timedelta(days=365 * 5)).isoformat()
    goal = _make_goal(
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=50_000_00,
        target_date=target,
        value_mode="real",
    )
    liab = goal_to_liability(goal, horizon_years=10, inflation_series_bps=[200] * 10)
    # ADR-2: Faktor 1.0 im laufenden Kalenderjahr, der Exponent ist also der
    # Bucket-Index. Der Betrag liegt jetzt im Bucket des Zielkalenderjahres
    # (vorher ein Jahrestag-Bucket frueher), der Exponent wandert mit.
    bucket = date.fromisoformat(target).year - today.year
    expected = int(round(50_000_00 * (1.02 ** bucket)))
    assert liab.liability_path_rappen[bucket] == pytest.approx(expected, abs=10)
    assert liab.target_amount_rappen == pytest.approx(expected, abs=10)


def test_einmalige_ausgabe_beyond_horizon_is_not_pulled_into_last_year():
    """Goal in 15J but horizon=10 has no in-horizon payment."""
    today = date.today()
    target = (today + timedelta(days=365 * 15)).isoformat()
    goal = _make_goal(
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=100_000_00,
        target_date=target,
    )
    liab = goal_to_liability(goal, horizon_years=10)
    # Der Index wird bewusst NICHT auf den Horizont geklemmt:
    # target_year_index > horizon_years ist das Signal "ausserhalb".
    bucket = date.fromisoformat(target).year - today.year
    assert liab.target_year_index == bucket + 1
    assert liab.target_year_index > 10
    assert liab.liability_path_rappen == [0] * 10
    assert "ausserhalb" in str(liab.evaluation_note).lower()


# ============================================================================
# Wiederkehrende_Ausgabe / Pensionsausgabe: jaehrlich Outflow ab Start
# ============================================================================


def test_pensionsausgabe_yearly_outflow_books_only_the_instalments_that_fall_due():
    """Pension CHF 3'000/Monat, Fenster today+5J bis today+9J, horizon=15.

    ADR-2 (Owner-Entscheid 2026-10-11) korrigiert hier zwei Dinge auf
    einmal, und der alte Testname nannte den Fehler selbst: "ab Jahr 5 fuer
    5 Jahre". Das Fenster ist VIER Jahre lang, nicht fuenf -- es beruehrt
    nur fuenf Kalenderjahr-Labels, weil es unterjaehrig beginnt und endet.

    * Betrag: 48 Monatsraten sind faellig (4 Jahre). Gebucht wurden 60,
      weil in jedes beruehrte Label ein voller Jahresbetrag ging: +25 %.
    * Platzierung: die Buckets sind jetzt Kalenderjahre, also beginnt der
      Strom im Jahr des Startdatums und nicht ein Jahrestag-Bucket frueher.

    Erstes und letztes Jahr sind Teiljahre und tragen entsprechend weniger:
    3 Raten im Startjahr (Okt-Dez), 9 im Endjahr (Jan-Sep, weil der
    Anker-Tag nach dem Enddatum liegt).
    """
    today = date.today()
    start = (today + timedelta(days=365 * 5)).isoformat()
    end = (today + timedelta(days=365 * 9)).isoformat()
    goal = _make_goal(
        goal_type="Pensionsausgabe",
        target_amount_rappen=3_000_00,  # monatlich 3000 CHF
        frequency="monatlich",
        start_date=start,
        target_date=end,
    )
    liab = goal_to_liability(goal, horizon_years=15)
    monthly = 3_000_00
    first_bucket = date.fromisoformat(start).year - today.year

    assert liab.target_kind == "outflow_stream"
    assert liab.target_year_index == first_bucket + 1

    path = liab.liability_path_rappen
    assert path[first_bucket] == 3 * monthly       # Teiljahr: Okt-Dez
    for offset in (1, 2, 3):
        assert path[first_bucket + offset] == 12 * monthly
    assert path[first_bucket + 4] == 9 * monthly   # Teiljahr: Jan-Sep

    # Insgesamt genau vier Jahre Monatsraten -- nicht fuenf.
    assert sum(path) == 48 * monthly
    assert liab.target_amount_rappen == 48 * monthly

    for i in range(first_bucket):
        assert path[i] == 0
    for i in range(first_bucket + 5, 15):
        assert path[i] == 0


def test_pensionsausgabe_real_compounds_inflation_per_year():
    """Pension mit value_mode='real' wird PRO JAHR mit kum. Inflation hochgerechnet."""
    today = date.today()
    start = (today + timedelta(days=365 * 3)).isoformat()
    end = (today + timedelta(days=365 * 5)).isoformat()
    goal = _make_goal(
        goal_type="Pensionsausgabe",
        target_amount_rappen=12_000_00,  # 12k jaehrlich
        frequency="jährlich",
        start_date=start,
        target_date=end,
        value_mode="real",
    )
    liab = goal_to_liability(goal, horizon_years=10, inflation_series_bps=[200] * 10)
    # ADR-2: die Buckets sind Kalenderjahre, Faktor 1.0 im laufenden Jahr
    # (User-Eingabe ist ein heutiger Wert, B1-Konvention wie bei Cashflows).
    # Der Exponent bleibt damit an den Bucket-Index gekoppelt: Bucket i
    # traegt 1.02^i. Die Zahlungen liegen in den Kalenderjahren
    # today+3 .. today+5, also in den Buckets 3..5 -- vorher 2..4, weil der
    # Startindex ein Jahrestag-Bucket war.
    first_bucket = date.fromisoformat(start).year - date.today().year
    for offset in range(3):
        bucket = first_bucket + offset
        expected = int(round(12_000_00 * (1.02 ** bucket)))
        assert liab.liability_path_rappen[bucket] == pytest.approx(expected, abs=10)


def test_pensionsausgabe_ongoing_runs_until_horizon():
    """is_ongoing=1 -> Outflow von Start bis horizon_years."""
    today = date.today()
    start = (today + timedelta(days=365 * 4)).isoformat()
    goal = _make_goal(
        goal_type="Pensionsausgabe",
        target_amount_rappen=24_000_00,
        frequency="jährlich",
        start_date=start,
        is_ongoing=1,
    )
    liab = goal_to_liability(goal, horizon_years=10)
    # ADR-2: Buckets sind Kalenderjahre. Der Strom beginnt im Kalenderjahr
    # des Startdatums (vorher ein Jahrestag-Bucket frueher) und laeuft bis
    # zum Horizont-Ende.
    first_bucket = date.fromisoformat(start).year - today.year
    for i in range(first_bucket, 10):
        assert liab.liability_path_rappen[i] == 24_000_00
    for i in range(first_bucket):
        assert liab.liability_path_rappen[i] == 0


def test_pensionsausgabe_truncated_horizon_adds_evaluation_note():
    """Goal laeuft 30 Jahre aber horizon=10 -> note erwaehnt Truncation."""
    today = date.today()
    start = (today + timedelta(days=365 * 5)).isoformat()
    end = (today + timedelta(days=365 * 35)).isoformat()
    goal = _make_goal(
        goal_type="Pensionsausgabe",
        target_amount_rappen=24_000_00,
        frequency="jährlich",
        start_date=start,
        target_date=end,
    )
    liab = goal_to_liability(goal, horizon_years=10)
    assert liab.evaluation_note is not None
    assert "Horizont" in liab.evaluation_note


def test_wiederkehrende_ausgabe_quarterly_books_four_instalments_only_in_full_years():
    """quartalsweise: vier Raten pro VOLLEM Jahr, weniger im Teiljahr.

    Der Test hiess einmal ``..._annualizes_to_4x`` und prueft jetzt genau
    die Einschraenkung, die im Namen fehlte: die Annualisierung auf 4x gilt
    nur fuer ein volles Kalenderjahr. Das Fenster today+1J bis today+3J ist
    zwei Jahre lang und beruehrt drei Kalenderjahre; faellig sind acht
    Quartalsraten, gebucht wurden zwoelf (drei Labels x 4).
    """
    today = date.today()
    start = (today + timedelta(days=365)).isoformat()
    end = (today + timedelta(days=365 * 3)).isoformat()
    goal = _make_goal(
        goal_type="Wiederkehrende_Ausgabe",
        target_amount_rappen=2_500_00,
        frequency="quartalsweise",
        start_date=start,
        target_date=end,
    )
    liab = goal_to_liability(goal, horizon_years=10)
    quarterly = 2_500_00
    first_bucket = date.fromisoformat(start).year - today.year

    assert liab.liability_path_rappen[first_bucket] == 1 * quarterly      # Teiljahr
    assert liab.liability_path_rappen[first_bucket + 1] == 4 * quarterly  # volles Jahr
    assert liab.liability_path_rappen[first_bucket + 2] == 3 * quarterly  # Teiljahr
    assert sum(liab.liability_path_rappen) == 8 * quarterly


# ============================================================================
# Maximierung
# ============================================================================


def test_maximierung_has_zero_path_and_zero_target():
    goal = _make_goal(goal_type="Maximierung", horizon_years=10)
    liab = goal_to_liability(goal, horizon_years=10)
    assert liab.target_kind == "maximize"
    assert liab.target_amount_rappen == 0
    assert all(v == 0 for v in liab.liability_path_rappen)


# ============================================================================
# Hardness + Weight
# ============================================================================


def test_hardness_hart_normalized():
    goal = _make_goal(hardness="Hart", horizon_years=5)
    liab = goal_to_liability(goal, horizon_years=5)
    assert liab.hardness_key == "hart"


def test_hardness_primaer_with_german_umlaut():
    goal = _make_goal(hardness="Primär", horizon_years=5)
    liab = goal_to_liability(goal, horizon_years=5)
    assert liab.hardness_key == "primaer"


def test_hardness_unknown_falls_back_to_primaer():
    goal = _make_goal(hardness="Quantum", horizon_years=5)
    liab = goal_to_liability(goal, horizon_years=5)
    assert liab.hardness_key == "primaer"


def test_weight_uses_explicit_when_set():
    goal = _make_goal(weight_bps=2500, horizon_years=5)
    liab = goal_to_liability(goal, horizon_years=5)
    assert liab.weight_bps == 2500


def test_weight_falls_back_to_rank_default():
    goal = _make_goal(weight_bps=None, rank=1, horizon_years=5)
    liab = goal_to_liability(goal, horizon_years=5)
    # Validierung 2026-06-11: Rank-Default an portfolio_engine.GOAL_WEIGHT_BY_RANK
    # angeglichen (war divergent 1875). Rank 1 = 10000 (weight_bps/10000 = 1.0).
    assert liab.weight_bps == 10000


def test_goal_rank_weight_parity_with_portfolio_engine():
    """Die Rank->Weight-Basistabelle der Optimizer-Liability MUSS mit der
    Mandate-Score-Aggregation uebereinstimmen (sonst divergente Gewichtung)."""
    from services.optimizer.goal_liabilities import _DEFAULT_WEIGHT_BY_RANK
    from services.portfolio_engine import GOAL_WEIGHT_BY_RANK
    assert _DEFAULT_WEIGHT_BY_RANK == GOAL_WEIGHT_BY_RANK


def test_conditional_goal_prorata_weights_liability():
    """engine-spec 4.4: bedingte Goals (probability_pct) werden pro-rata
    gewichtet — konsistent zur Reserve-Engine (portfolio_engine)."""
    td = (date.today() + timedelta(days=365 * 3)).isoformat()
    g50 = _make_goal(goal_type="Einmalige_Ausgabe", target_amount_rappen=10_000_000,
                     target_date=td, value_mode="nominal")
    g50.probability_pct = 50
    assert goal_to_liability(g50, horizon_years=5).target_amount_rappen == 5_000_000

    gnone = _make_goal(goal_type="Einmalige_Ausgabe", target_amount_rappen=10_000_000,
                       target_date=td, value_mode="nominal")
    gnone.probability_pct = None
    assert goal_to_liability(gnone, horizon_years=5).target_amount_rappen == 10_000_000


def test_conditional_total_wealth_applies_probability_after_external_assets():
    goal = _make_goal(
        goal_type="Vermoegensziel",
        target_wealth_rappen=150_000_000,
        horizon_years=1,
        value_mode="nominal",
        goal_scope="Gesamtvermoegen",
    )
    goal.probability_pct = 50

    liability = goal_to_liability(
        goal,
        horizon_years=1,
        external_wealth_rappen=80_000_000,
    )

    # Expected funding = 50% * (1.5m target - 0.8m external), not
    # max(0, 50% * 1.5m - 0.8m) == 0.
    assert liability.target_amount_rappen == 35_000_000


def test_recurring_spending_after_horizon_creates_no_last_year_outflow():
    start = (date.today() + timedelta(days=365 * 25)).isoformat()
    end = (date.today() + timedelta(days=365 * 30)).isoformat()
    goal = _make_goal(
        goal_type="Pensionsausgabe",
        target_amount_rappen=36_000_00,
        frequency="jaehrlich",
        start_date=start,
        target_date=end,
    )

    liability = goal_to_liability(goal, horizon_years=10)

    assert liability.target_year_index > 10
    assert liability.target_amount_rappen == 0
    assert liability.liability_path_rappen == [0] * 10
    assert "ausserhalb" in str(liability.evaluation_note).lower()


def test_one_off_spending_after_horizon_creates_no_last_year_outflow():
    target = (date.today() + timedelta(days=365 * 25)).isoformat()
    goal = _make_goal(
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=100_000_00,
        target_date=target,
    )

    liability = goal_to_liability(goal, horizon_years=10)

    assert liability.target_year_index > 10
    assert liability.liability_path_rappen == [0] * 10


# ============================================================================
# Aggregation
# ============================================================================


def test_aggregate_sums_outflows_per_year():
    today = date.today()
    target_a = (today + timedelta(days=365 * 3)).isoformat()
    target_b = (today + timedelta(days=365 * 3)).isoformat()
    goal_a = _make_goal(
        goal_id="a", goal_type="Einmalige_Ausgabe",
        target_amount_rappen=50_000_00, target_date=target_a,
    )
    goal_b = _make_goal(
        goal_id="b", goal_type="Einmalige_Ausgabe",
        target_amount_rappen=30_000_00, target_date=target_b,
    )
    liabs = goals_to_liabilities([goal_a, goal_b], horizon_years=10)
    aggregated = aggregate_liability_path(liabs, 10)
    # Beide Ziele fallen ins selbe Kalenderjahr -> ein Bucket mit 80'000.
    bucket = date.fromisoformat(target_a).year - today.year
    assert aggregated[bucket] == 80_000_00
    for i in range(10):
        if i != bucket:
            assert aggregated[i] == 0


def test_aggregate_combines_recurring_and_einmalig():
    today = date.today()
    pension_start = (today + timedelta(days=365 * 5)).isoformat()
    pension_end = (today + timedelta(days=365 * 9)).isoformat()
    bullet_target = (today + timedelta(days=365 * 7)).isoformat()
    pension = _make_goal(
        goal_id="p", goal_type="Pensionsausgabe",
        target_amount_rappen=24_000_00, frequency="jährlich",
        start_date=pension_start, target_date=pension_end,
    )
    bullet = _make_goal(
        goal_id="b", goal_type="Einmalige_Ausgabe",
        target_amount_rappen=100_000_00, target_date=bullet_target,
    )
    liabs = goals_to_liabilities([pension, bullet], horizon_years=12)
    aggregated = aggregate_liability_path(liabs, 12)

    # ADR-2: wiederkehrende UND einmalige Outflows liegen jetzt beide auf
    # der Kalenderjahr-Achse. Dieser Test ist die Stelle, an der das
    # zaehlt: aggregate_liability_path() summiert sie in EIN Array, das vom
    # Vermoegen auf demselben Index abgezogen wird. Lagen die beiden auf
    # verschiedenen Achsen, war die Summe nicht nur verschoben, sondern
    # inkonsistent verschoben.
    pension_first = date.fromisoformat(pension_start).year - today.year
    bullet_bucket = date.fromisoformat(bullet_target).year - today.year

    # Das Pensionsfenster ist vier Jahre lang (today+5J bis today+9J) und
    # jaehrlich, also vier Raten -- vorher fuenf, eine pro beruehrtem Label.
    pension_buckets = [
        i for i, value in enumerate(aggregated)
        if value in (24_000_00, 24_000_00 + 100_000_00)
    ]
    assert pension_buckets == [pension_first + o for o in range(4)]
    assert aggregated[bullet_bucket] == 24_000_00 + 100_000_00
    assert aggregated[pension_first - 1] == 0
    assert aggregated[pension_first + 4] == 0
    assert sum(aggregated) == 4 * 24_000_00 + 100_000_00


def test_goals_to_liabilities_empty_list_returns_empty():
    assert goals_to_liabilities([], horizon_years=10) == []
    assert aggregate_liability_path([], 10) == [0] * 10
