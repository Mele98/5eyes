"""NS-BOND-SLEEVE-COLLAPSE-001 (GEFIXT) und NS-YIELD-RETURN-HORIZON-001 (offen).

Ursprung: docs/audits/2026-10-04-bond-curve-quotation-sleeve-and-return-semantics-integrity-audit.md
(Kontrollrunde 49 nach der Zaehlung des Audits).

NS-BOND-SLEEVE-COLLAPSE-001 -- gefixt am 2026-10-11
---------------------------------------------------
Der Befund war in services/portfolio_engine_cma.py:

    ns_bonds = _compute_bonds_return_from_nelson_siegel(cma)
    if ns_bonds is not None:
        adjusted["bonds"] = int(round(ns_bonds))   # <-- volles ERSETZEN

Das lief NACH `_weighted_bucket_metrics()`, das den Obligationen-Return
bereits korrekt aus dem echten CHF-IG/Global-Hedged/High-Yield/Emerging-Mix
gewichtet hatte. Bemerkenswert war die Asymmetrie zu Aktien, die schon immer
ADDITIV angepasst wurden (`adjusted["equities"] + kgv_adj`) und ihre
Sub-Allokations-Differenzierung dadurch behielten -- nur Obligationen bekamen
ein volles Overwrite.

Zwei Schaeden gleichzeitig:

1. **Kreditaufschlag vernichtet.** Die NS-Kurve ist eine Swap-/Staatskurve
   (hinterlegte CHF-Kalibrierung per 2024-12-31: 50 bps bei 5 Jahren), die
   CMA-Bond-Returns sind Basis-plus-Spread (CHF IG 180, Global Hedged 220,
   High Yield 420 bps). Ein gewichteter Obligationen-Return von 228 bps wurde
   damit zu 50 bps.
2. **Sleeve-Kollaps.** 100 % IG, 100 % HY und ein 80/20-Mix kollabierten auf
   denselben Wert, obwohl ihre Werte vor der Anpassung 180, 420 und 228 bps
   waren.

Fix: die Kurve setzt nicht mehr das NIVEAU, sondern liefert nur die
TERMSTRUKTUR als additiven Tilt gegen eine Referenzlaufzeit
(services/rates/bond_duration.py, `_compute_bonds_duration_tilt_bps()`).
Kreditaufschlag und Sleeve-Rangfolge bleiben vollstaendig erhalten, und bei
Referenzlaufzeit ist der Tilt exakt 0.

NS-YIELD-RETURN-HORIZON-001 -- weiter offen
-------------------------------------------
Die Kurvenabfrage nimmt jetzt eine Laufzeit (`maturity_years`), und der Tilt
differenziert nachweislich (Fixture-Kurve: -39 bps bei 2 Jahren, +17 bps bei
10). Was fehlt, ist die Verdrahtung der `bondsDuration`-Praeferenz bis dorthin:
KEINE Produktions-Aufrufstelle fuellt den Parameter.

Die Praeferenz wirkt heute ausschliesslich ueber den Sleeve-MIX (Kurzfristig
70 % CHF IG vs. Langfristig 55 %), also als Kredit-/Geografie-Verschiebung --
die Sleeve-Labels tragen gar keine Laufzeit. Die Termstruktur-Dimension
erreicht sie nicht.

Die Verdrahtung ist breit: sechs Aufrufstellen von
`_weighted_bucket_metrics()` ueber sechs verschiedene Funktionen, UND der
Szenario-Cache-Key muss die Laufzeit mitnehmen (sonst liefert der Cache Pfade
aus der alten Laufzeit -- derselbe Befund wie bei den effektiven
ScenarioInputs). Halb verdrahtet waere schlechter als gar nicht: bekaeme der
Solver-Kanal den Tilt und der Reporting-Kanal nicht, waere die gerade
geschlossene Solver/Reporting-Paritaet wieder offen.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from models.allocation import CapitalMarketAssumption


def _make_cma_with_ns(**overrides):
    """Same bond sub-allocation values as the audit's own reproduction and
    as the existing tests/test_audit_z4_weighted_metrics.py fixture (CHF
    IG=180, Global Hedged=220, High Yield=420 bps), plus active
    Nelson-Siegel curve parameters (beta0=400, beta1=-150, beta2=50,
    lambda=0.6 -- the audit's own reproduction values)."""
    sub_assumptions = {
        "Obligationen CHF IG": {"asset_class": "Obligationen", "expected_return_bps": 180, "expected_volatility_bps": 350},
        "Obligationen Global Hedged": {"asset_class": "Obligationen", "expected_return_bps": 220, "expected_volatility_bps": 450},
        "Obligationen High Yield": {"asset_class": "Obligationen", "expected_return_bps": 420, "expected_volatility_bps": 950},
    }
    base = dict(
        id="cma-r50-ns", assumption_set_name="Test", version=1, valid_from="2026-01-01",
        is_current=1,
        bonds_chf_ig_return_bps=180, bonds_chf_ig_vol_bps=350,
        bonds_fx_hedged_return_bps=220, bonds_fx_hedged_vol_bps=450,
        equity_ch_return_bps=500, equity_ch_vol_bps=1450,
        equity_intl_return_bps=700, equity_intl_vol_bps=1500,
        real_estate_ch_return_bps=330, real_estate_ch_vol_bps=820,
        alternatives_gold_return_bps=300, alternatives_gold_vol_bps=1200,
        liquidity_return_bps=80, liquidity_vol_bps=15,
        sub_asset_class_assumptions_json=json.dumps(sub_assumptions),
        bonds_ns_beta0_bps=400, bonds_ns_beta1_bps=-150,
        bonds_ns_beta2_bps=50, bonds_ns_lambda_x100=60,
        created_by="advisor-1",
        created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
    )
    base.update(overrides)
    return CapitalMarketAssumption(**base)


_SUBS_100_IG = [
    {"asset_class": "Obligationen", "sub_asset_class": "Obligationen CHF IG", "target_weight_bps": 10000, "rationale": ""},
]
_SUBS_100_HY = [
    {"asset_class": "Obligationen", "sub_asset_class": "Obligationen High Yield", "target_weight_bps": 10000, "rationale": ""},
]
_SUBS_80_20 = [
    {"asset_class": "Obligationen", "sub_asset_class": "Obligationen CHF IG", "target_weight_bps": 8000, "rationale": ""},
    {"asset_class": "Obligationen", "sub_asset_class": "Obligationen High Yield", "target_weight_bps": 2000, "rationale": ""},
]


def test_active_nelson_siegel_preserves_bond_sleeve_differentiation():
    """100 % CHF IG, 100 % High Yield und ein 80/20-Mix bleiben differenziert.

    Vorher kollabierten alle drei auf den identischen NS-5-Jahres-Wert.
    """
    from services.portfolio_engine import _weighted_bucket_metrics

    cma = _make_cma_with_ns()
    bonds_ig = _weighted_bucket_metrics(cma, _SUBS_100_IG)[0]["bonds"]
    bonds_hy = _weighted_bucket_metrics(cma, _SUBS_100_HY)[0]["bonds"]
    bonds_mix = _weighted_bucket_metrics(cma, _SUBS_80_20)[0]["bonds"]

    assert bonds_ig != bonds_hy, (
        f"100% IG ({bonds_ig} bps) und 100% HY ({bonds_hy} bps) muessen bei "
        "aktivem Nelson-Siegel wirtschaftlich verschieden bleiben"
    )
    assert bonds_ig < bonds_mix < bonds_hy, (
        f"der 80/20-Mix ({bonds_mix} bps) muss strikt zwischen reinem IG "
        f"({bonds_ig} bps) und reinem HY ({bonds_hy} bps) liegen"
    )


def test_active_nelson_siegel_does_not_change_the_bond_level_at_all():
    """Der eigentliche Vertrag: eine aktive Kurve setzt KEIN Niveau.

    Staerker als "differenziert bleiben" -- ohne Laufzeitpraeferenz muss der
    Obligationen-Return bei aktivem NS EXAKT demselben Wert entsprechen wie
    bei inaktivem NS. Die Kurve darf ausschliesslich die Termstruktur
    beitragen, und die ist bei Referenzlaufzeit null.

    Dieser Test faengt auch den Rueckfall in ein teilweises Overwrite, das die
    Rangfolge zufaellig erhalten koennte (etwa ein gewichteter Mischwert aus
    Kurve und CMA) -- so ein Fix haette den Kreditaufschlag immer noch
    anteilig vernichtet.
    """
    from services.portfolio_engine import _weighted_bucket_metrics

    active = _make_cma_with_ns()
    inactive = _make_cma_with_ns(
        bonds_ns_beta0_bps=None, bonds_ns_beta1_bps=None,
        bonds_ns_beta2_bps=None, bonds_ns_lambda_x100=None,
    )
    for label, subs in (
        ("100% IG", _SUBS_100_IG),
        ("100% HY", _SUBS_100_HY),
        ("80/20", _SUBS_80_20),
    ):
        with_ns = _weighted_bucket_metrics(active, subs)[0]["bonds"]
        without_ns = _weighted_bucket_metrics(inactive, subs)[0]["bonds"]
        assert with_ns == without_ns, (
            f"{label}: aktives Nelson-Siegel veraendert das Niveau "
            f"({without_ns} -> {with_ns} bps), obwohl keine "
            "Laufzeitpraeferenz vorliegt"
        )


def test_credit_spread_survives_an_active_curve():
    """Der Kreditaufschlag zwischen IG und HY bleibt in voller Hoehe erhalten.

    Die Fixture-Sleeves sind 180 (IG) und 420 (HY) bps, der Aufschlag also
    240 bps. Vor dem Fix wurde beides auf den Kurvenwert gesetzt und der
    Aufschlag war 0.
    """
    from services.portfolio_engine import _weighted_bucket_metrics

    cma = _make_cma_with_ns()
    bonds_ig = _weighted_bucket_metrics(cma, _SUBS_100_IG)[0]["bonds"]
    bonds_hy = _weighted_bucket_metrics(cma, _SUBS_100_HY)[0]["bonds"]
    assert bonds_hy - bonds_ig == pytest.approx(240, abs=1), (
        f"Kreditaufschlag IG->HY ist {bonds_hy - bonds_ig} bps statt 240"
    )


def test_tilt_is_uniform_across_sleeves_and_preserves_ordering():
    """Wird eine Laufzeit gesetzt, verschiebt der Tilt alle Sleeves gleich.

    Das ist die Eigenschaft, die die Differenzierung mathematisch garantiert:
    ein additiver Betrag, der fuer jedes Sleeve derselbe ist, kann eine
    Rangfolge nicht aendern und einen Aufschlag nicht verkleinern.
    """
    from services.optimizer.scenario_engine import _compute_bonds_duration_tilt_bps
    from services.portfolio_engine_cma import _apply_cma_market_adjustments

    cma = _make_cma_with_ns()
    tilt = _compute_bonds_duration_tilt_bps(cma, maturity_years=10.0)
    assert tilt is not None and tilt != 0.0

    for base in (180, 228, 420):
        adjusted = _apply_cma_market_adjustments(
            {
                "equities": 600, "bonds": base, "real_estate": 330,
                "alternatives": 300, "liquidity": 80,
            },
            cma,
            bonds_maturity_years=10.0,
        )
        assert adjusted["bonds"] == int(round(base + tilt)), (
            f"Tilt wirkt nicht uniform: {base} -> {adjusted['bonds']}, "
            f"erwartet {int(round(base + tilt))}"
        )


def test_tilt_is_exactly_zero_at_the_reference_maturity():
    """Bei Referenzlaufzeit ist der Tilt exakt 0, nicht nur klein."""
    from services.optimizer.scenario_engine import _compute_bonds_duration_tilt_bps
    from services.rates.bond_duration import CMA_REFERENCE_MATURITY_YEARS

    cma = _make_cma_with_ns()
    assert _compute_bonds_duration_tilt_bps(
        cma, maturity_years=CMA_REFERENCE_MATURITY_YEARS
    ) == 0.0
    # Und ohne Angabe ebenfalls -- der Default IS die Referenz.
    assert _compute_bonds_duration_tilt_bps(cma) == 0.0


def test_tilt_is_none_when_the_curve_is_inactive():
    """Ohne vollstaendige NS-Gruppe gibt es keinen Tilt (nicht 0, sondern None).

    Die Unterscheidung ist bedeutsam: ``None`` heisst "kein Modell aktiv",
    ``0.0`` heisst "Modell aktiv, Termstruktur neutral". Der Nachweis muss
    beides auseinanderhalten koennen.
    """
    from services.optimizer.scenario_engine import _compute_bonds_duration_tilt_bps

    inactive = _make_cma_with_ns(
        bonds_ns_beta0_bps=None, bonds_ns_beta1_bps=None,
        bonds_ns_beta2_bps=None, bonds_ns_lambda_x100=None,
    )
    assert _compute_bonds_duration_tilt_bps(inactive, maturity_years=10.0) is None


def test_tilt_direction_follows_the_curve_shape():
    """Kurz unter, lang ueber der Referenz -- bei normal steigender Kurve.

    Pinnt das Vorzeichen, nicht nur den Betrag. Ein invertiertes Vorzeichen
    waere ein Rechenfehler, der betragsmaessig unauffaellig bleibt.
    """
    from services.optimizer.scenario_engine import _compute_bonds_duration_tilt_bps

    cma = _make_cma_with_ns()  # beta1 = -150 -> steigende Kurve
    short = _compute_bonds_duration_tilt_bps(cma, maturity_years=2.0)
    long = _compute_bonds_duration_tilt_bps(cma, maturity_years=10.0)
    assert short < 0.0 < long, f"kurz={short}, lang={long}"


def test_inverted_curve_produces_an_inverted_tilt():
    """Bei inverser Kurve kehrt sich der Tilt um.

    Belegt, dass der Tilt tatsaechlich die Kurvenform liest und nicht eine
    fest verdrahtete Annahme "lang = mehr Rendite" enthaelt.
    """
    from services.optimizer.scenario_engine import _compute_bonds_duration_tilt_bps

    inverted = _make_cma_with_ns(bonds_ns_beta1_bps=150)  # kurzes Ende hoeher
    short = _compute_bonds_duration_tilt_bps(inverted, maturity_years=2.0)
    long = _compute_bonds_duration_tilt_bps(inverted, maturity_years=10.0)
    assert long < 0.0 < short, f"kurz={short}, lang={long}"


def test_positive_control_sleeve_differentiation_without_active_ns():
    """Positive control: without NS parameters set (inactive model), the
    existing, already-correct weighted bucket logic keeps IG/HY sleeves
    differentiated (180 / 420 / 228 bps) -- this must be preserved by any
    future fix."""
    from services.portfolio_engine import _weighted_bucket_metrics

    cma = _make_cma_with_ns(
        bonds_ns_beta0_bps=None, bonds_ns_beta1_bps=None,
        bonds_ns_beta2_bps=None, bonds_ns_lambda_x100=None,
    )
    subs_100_ig = [
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen CHF IG", "target_weight_bps": 10000, "rationale": ""},
    ]
    subs_100_hy = [
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen High Yield", "target_weight_bps": 10000, "rationale": ""},
    ]
    subs_80_20 = [
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen CHF IG", "target_weight_bps": 8000, "rationale": ""},
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen High Yield", "target_weight_bps": 2000, "rationale": ""},
    ]
    returns_ig, _ = _weighted_bucket_metrics(cma, subs_100_ig)
    returns_hy, _ = _weighted_bucket_metrics(cma, subs_100_hy)
    returns_mix, _ = _weighted_bucket_metrics(cma, subs_80_20)

    assert returns_ig["bonds"] == pytest.approx(180, abs=1)
    assert returns_hy["bonds"] == pytest.approx(420, abs=1)
    assert returns_mix["bonds"] == pytest.approx(228, abs=1)


def test_the_maturity_mechanism_itself_is_capable() -> None:
    """Die Kurve IST laufzeitsensitiv und die Abfrage nimmt die Laufzeit.

    Positive Kontrolle zum Reproducer darunter: die Faehigkeit ist vorhanden,
    es fehlt nur die Verdrahtung der Praeferenz. Ohne diesen Test koennte der
    Reproducer auch gruen werden, indem die Kurve ihre
    Laufzeitsensitivitaet verliert -- das waere kein Fix.
    """
    from services.optimizer.scenario_engine import (
        _compute_bonds_return_from_nelson_siegel,
    )
    from services.rates.bond_duration import (
        BOND_DURATION_MATURITY_YEARS,
        resolve_bond_maturity_years,
    )

    cma = _make_cma_with_ns()
    yields = {
        preference: _compute_bonds_return_from_nelson_siegel(
            cma, maturity_years=resolve_bond_maturity_years(preference)
        )
        for preference in BOND_DURATION_MATURITY_YEARS
    }
    assert len(set(yields.values())) == len(yields), (
        f"Die drei Laufzeitpraeferenzen liefern nicht drei verschiedene "
        f"Kurvenwerte: {yields}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "NS-YIELD-RETURN-HORIZON-001 (weiter offen): die Kurvenabfrage nimmt "
        "jetzt eine Laufzeit und der Tilt differenziert nachweislich "
        "(Fixture-Kurve -39 bps bei 2J, +17 bps bei 10J) -- aber KEINE "
        "Produktions-Aufrufstelle fuellt den Parameter. Die "
        "bondsDuration-Praeferenz wirkt ausschliesslich ueber den Sleeve-MIX "
        "(Kurzfristig 70 % CHF IG vs. Langfristig 55 %), also als Kredit-/"
        "Geografie-Verschiebung; die Sleeve-Labels tragen gar keine Laufzeit, "
        "die Termstruktur-Dimension erreicht die Praeferenz nicht. Die "
        "Verdrahtung ist breit: sechs Aufrufstellen von "
        "_weighted_bucket_metrics() ueber sechs Funktionen, UND der "
        "Szenario-Cache-Key muss die Laufzeit mitnehmen (sonst stale Pfade "
        "aus der alten Laufzeit). Halb verdrahtet waere schlechter als gar "
        "nicht -- bekaeme der Solver-Kanal den Tilt und der Reporting-Kanal "
        "nicht, waere die Solver/Reporting-Paritaet wieder offen."
    ),
)
def test_bonds_duration_preference_reaches_the_curve() -> None:
    """Reproducer: mindestens eine Produktionsstelle muss die Laufzeit setzen.

    Geprueft am Quelltext statt am Verhalten, und zwar aus einem Grund: ueber
    die Produktions-Signaturen ist die Praeferenz heute gar nicht
    ausdrueckbar, ein Verhaltenstest koennte sie also nirgends einspeisen. Was
    fehlt, ist strukturell -- ein Aufruf, der ``bonds_maturity_years``
    tatsaechlich fuellt.

    Ein Verhaltenstest waere hier ausserdem irrefuehrend: zwei Mandate mit
    verschiedener Laufzeitpraeferenz haben BEREITS verschiedene
    Obligationen-Returns, weil die Praeferenz den Sleeve-Mix verschiebt. Er
    waere also gruen, ohne dass die Termstruktur beteiligt ist.
    """
    services_dir = BACKEND_ROOT / "services"
    callers: list[str] = []
    for path in services_dir.rglob("*.py"):
        if path.name in ("portfolio_engine_cma.py", "bond_duration.py"):
            continue  # Definition bzw. Zuordnung, keine Aufrufstelle
        text = path.read_text(encoding="utf-8", errors="replace")
        if "bonds_maturity_years=" in text:
            callers.append(str(path.relative_to(BACKEND_ROOT)))

    assert callers, (
        "Keine Produktionsstelle uebergibt bonds_maturity_years -- die "
        "bondsDuration-Praeferenz kann die Nelson-Siegel-Laufzeit nicht "
        "erreichen, obwohl der Mechanismus dafuer bereitsteht."
    )
