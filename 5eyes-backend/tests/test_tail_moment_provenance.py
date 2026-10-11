"""CMA-TAIL-MISSINGNESS-SEMANTICS-001 -- Nachweis der Tail-Moment-Herkunft.

Beide Engines lesen die Skew-/Kurtosis-Felder als
``getattr(cma, name, 0) or 0``. Damit erzeugen ``None`` (nie geschaetzt) und
eine ausdrueckliche ``0`` denselben Laufzeitwert -- fuer die RECHNUNG richtig
(beides heisst normalverteilt), aber die Information, ob ueberhaupt jemand das
Moment angefasst hat, ging dabei verloren.

Der Befund nennt drei Orte ohne unterscheidenden Zustand: ``ScenarioInputs``,
die Log-Parameter der Haupt-MC und das CMA-Objekt selbst. Die ersten zwei sind
hiermit geschlossen -- ``ScenarioInputs`` traegt den Zustand pro Bucket, und
der Nachweis-Block in der Modellbasis deckt BEIDE Kanaele ab. Der dritte (ein
Review-/Freigabe-Attribut am CMA) bleibt bewusst offen: das ist eine
Schema- und Governance-Entscheidung, keine Engineering-Frage.

Deshalb die zentrale Benennung: **"explicit" heisst gesetzt, nicht
freigegeben.** Es gibt im System kein Freigabe-Flag pro Tail-Moment. Eine 0 in
der Datenbank als "von einem Modellverantwortlichen geprueft" auszuweisen
waere eine Governance-Behauptung, die die Daten nicht tragen.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.scenario_engine import (
    BUCKET_ORDER,
    TAIL_MOMENT_DEFAULTED,
    TAIL_MOMENT_EXPLICIT,
    tail_moment_provenance,
    tail_moment_state,
)


def _cma(**overrides) -> SimpleNamespace:
    base: dict[str, object] = {}
    for bucket in BUCKET_ORDER:
        base[f"{bucket}_skewness_bps"] = None
        base[f"{bucket}_excess_kurt_bps"] = None
    base.update(overrides)
    return SimpleNamespace(**base)


def test_explicit_zero_is_not_the_same_state_as_null() -> None:
    """Der Kern des Befundes: 0 und NULL sind verschiedene Zustaende.

    Die ZAHL bleibt in beiden Faellen 0 -- das ist richtig und wird nicht
    angetastet. Unterscheidbar ist jetzt der Zustand.
    """
    assert tail_moment_state(
        _cma(equities_skewness_bps=0), "equities_skewness_bps"
    ) == TAIL_MOMENT_EXPLICIT
    assert tail_moment_state(
        _cma(equities_skewness_bps=None), "equities_skewness_bps"
    ) == TAIL_MOMENT_DEFAULTED


def test_a_nonzero_moment_is_explicit() -> None:
    assert tail_moment_state(
        _cma(equities_skewness_bps=-5000), "equities_skewness_bps"
    ) == TAIL_MOMENT_EXPLICIT


def test_a_missing_attribute_counts_as_defaulted() -> None:
    """Eine Zeile ohne das Feld (Altbestand, Fixture) ist nicht "explizit"."""
    assert tail_moment_state(
        SimpleNamespace(), "equities_skewness_bps"
    ) == TAIL_MOMENT_DEFAULTED


def test_provenance_lists_the_defaulted_buckets() -> None:
    """Ausgewiesen wird die handlungsrelevante Seite: wo fehlt eine Schaetzung."""
    cma = _cma(
        equities_skewness_bps=-5000,
        equities_excess_kurt_bps=25000,
        bonds_skewness_bps=0,
    )
    provenance = tail_moment_provenance(cma)

    assert provenance["basis"] == "explicit_vs_defaulted_per_bucket_v1"
    assert "equities" not in provenance["skew_defaulted_buckets"]
    assert "bonds" not in provenance["skew_defaulted_buckets"], (
        "eine explizite 0 darf nicht als fehlende Schaetzung erscheinen"
    )
    assert "real_estate" in provenance["skew_defaulted_buckets"]
    # Kurtosis ist nur fuer equities gesetzt.
    assert "equities" not in provenance["excess_kurt_defaulted_buckets"]
    assert "bonds" in provenance["excess_kurt_defaulted_buckets"]
    assert provenance["all_tail_moments_defaulted"] is False


def test_provenance_flags_a_cma_without_any_estimated_tail_moment() -> None:
    """Der haeufigste Fall bekommt eine eigene, einfach auswertbare Angabe.

    Laut Audit passiert eine CMA mit durchgaengig NULL-Tail-Momenten die
    Laufzeit-Vollstaendigkeitspruefung heute -- der Lauf rechnet dann
    vollstaendig normalverteilt, ohne dass das irgendwo stand.
    """
    provenance = tail_moment_provenance(_cma())
    assert provenance["all_tail_moments_defaulted"] is True
    assert set(provenance["skew_defaulted_buckets"]) == set(BUCKET_ORDER)
    assert set(provenance["excess_kurt_defaulted_buckets"]) == set(BUCKET_ORDER)


def test_provenance_never_claims_an_approval_that_does_not_exist() -> None:
    """"explicit" darf nicht als "freigegeben" gelesen werden koennen.

    Es gibt kein Review-Attribut pro Tail-Moment. Ohne diese Angabe im
    Nachweis koennte "explicit" als Freigabe durch einen
    Modellverantwortlichen missverstanden werden -- eine
    Governance-Behauptung, die die Daten nicht tragen. Derselbe Grund, aus dem
    die Bootstrap-Katalog-Regeln ein ehrliches System-Label tragen statt eines
    erfundenen Pruefers.
    """
    provenance = tail_moment_provenance(_cma(equities_skewness_bps=0))
    assert provenance["approval_flag_exists"] is False


def test_absent_cma_is_unknown_not_all_defaulted() -> None:
    """Ohne CMA im Scope wird "unbekannt" ausgewiesen, nicht "alles defaultet".

    Der Modell-Basis-Block wird auch fuer Legacy- und Fallback-Laeufe gebaut,
    in denen keine CMA-Zeile vorliegt. "alles defaultet" waere dort ein
    Befund, den niemand geprueft hat.
    """
    provenance = tail_moment_provenance(None)
    assert provenance["basis"] == "unknown_no_cma_in_scope"
    assert provenance["all_tail_moments_defaulted"] is None
    assert provenance["skew_defaulted_buckets"] is None


def test_scenario_inputs_carry_the_per_bucket_state() -> None:
    """Der Solver-Kanal traegt den Zustand pro Bucket, in BUCKET_ORDER."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    full = SimpleNamespace(
        equity_ch_return_bps=600, equity_ch_vol_bps=1600,
        equity_intl_return_bps=600, equity_intl_vol_bps=1600,
        bonds_chf_ig_return_bps=170, bonds_chf_ig_vol_bps=350,
        bonds_fx_hedged_return_bps=200, bonds_fx_hedged_vol_bps=400,
        real_estate_ch_return_bps=330, real_estate_ch_vol_bps=820,
        alternatives_gold_return_bps=300, alternatives_gold_vol_bps=1200,
        liquidity_return_bps=80, liquidity_vol_bps=15,
        correlation_matrix_json="", sub_asset_class_assumptions_json="",
        jurisdiction="CH",
    )
    for bucket in BUCKET_ORDER:
        setattr(full, f"{bucket}_skewness_bps", None)
        setattr(full, f"{bucket}_excess_kurt_bps", None)
    full.equities_skewness_bps = 0

    inputs = scenario_inputs_from_cma(full)
    equities_index = BUCKET_ORDER.index("equities")
    bonds_index = BUCKET_ORDER.index("bonds")

    assert len(inputs.skew_state) == len(BUCKET_ORDER)
    assert inputs.skew_state[equities_index] == TAIL_MOMENT_EXPLICIT
    assert inputs.skew_state[bonds_index] == TAIL_MOMENT_DEFAULTED
    # Und die ZAHL bleibt in beiden Faellen 0 -- der Kollaps der Rechnung ist
    # korrekt und wird nicht angetastet.
    assert float(inputs.skew_bps[equities_index]) == 0.0
    assert float(inputs.skew_bps[bonds_index]) == 0.0


def test_the_model_basis_carries_the_provenance_in_both_channels() -> None:
    """Der Nachweis deckt BEIDE Kanaele ab, nicht nur den Solver.

    Die Luecke bestand in beiden Engines -- die Haupt-MC liest dieselben
    Felder mit demselben Ausdruck. Waere der Block nur im
    Entscheidungskanal, waere die Haelfte des Befundes offen geblieben.
    """
    source = (
        BACKEND_ROOT / "services" / "portfolio_engine_model_basis.py"
    ).read_text(encoding="utf-8")
    assert source.count('"tail_moment_provenance": tail_moments') == 2, (
        "tail_moment_provenance fehlt in einem der beiden Modell-Basis-Kanaele"
    )
