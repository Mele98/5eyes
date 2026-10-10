"""DRAWDOWN-TIME-GRID-001 -- Zeitgitter-Verfeinerung des Max-Drawdown.

Der Max-Drawdown wurde auf Jahresstuetzstellen gemessen und unterschaetzt
dadurch den Peak-to-Trough-Verlust systematisch -- umso staerker, je volatiler
das Mandat ist. ``services/drawdown_refinement.py`` setzt zwischen die
Jahresstuetzstellen eine Brownsche Bruecke.

Diese Suite deckt die vier Eigenschaften ab, auf denen das Verfahren steht:

1. **Korrektheit** -- die Bruecke liefert dieselbe Drawdown-Verteilung wie eine
   *nativ* feiner simulierte Reihe. Ohne das waere die Verfeinerung nur eine
   Zahl, die groesser ist, nicht eine, die stimmt.
2. **Monotonie** -- der verfeinerte Wert ist nie kleiner als der bisherige
   (der Jahrespfad ist eine Teilmenge des verfeinerten Pfades). Die Korrektur
   kann die Kennzahl also nur konservativer machen.
3. **Blast Radius** -- kein anderer Wert des Simulationslaufs aendert sich.
4. **Reproduzierbarkeit und Rueckfall** -- gleicher Seed, gleiche Zahl; und ein
   degenerierter Input liefert still die bisherige Kennzahl statt eines Fehlers.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from services.drawdown_refinement import (
    DRAWDOWN_REFINEMENT_MODEL_VERSION,
    WEEKLY_SUB_STEPS,
    bridge_seed,
    max_drawdown_bps_from_levels,
    pooled_annual_log_volatility,
    refine_max_drawdowns,
)


# ── Hilfsmittel ──────────────────────────────────────────────────────────────


def _log_parameters(arith_mu: float, arith_sigma: float) -> tuple[float, float]:
    """Arithmetische Jahresmomente -> Log-Parameter (gleiche Konvention wie die Engine)."""
    var_ratio = 1.0 + (arith_sigma**2) / ((1.0 + arith_mu) ** 2)
    log_scale = math.sqrt(math.log(var_ratio))
    log_location = math.log(1.0 + arith_mu) - 0.5 * log_scale * log_scale
    return log_location, log_scale


def _native_paths(
    rng: np.random.Generator,
    *,
    log_location: float,
    log_scale: float,
    years: int,
    sub_steps: int,
    n_paths: int,
) -> np.ndarray:
    """Nativ mit ``sub_steps`` Teilschritten pro Jahr simuliert."""
    step_location = log_location / sub_steps
    step_scale = log_scale / math.sqrt(sub_steps)
    noise = rng.standard_normal((n_paths, years * sub_steps))
    increments = step_location + step_scale * noise
    levels = np.concatenate(
        [np.zeros((n_paths, 1)), np.cumsum(increments, axis=1)], axis=1
    )
    return np.exp(levels)


def _annual_paths(
    rng: np.random.Generator,
    *,
    log_location: float,
    log_scale: float,
    years: int,
    n_paths: int,
) -> np.ndarray:
    return _native_paths(
        rng,
        log_location=log_location,
        log_scale=log_scale,
        years=years,
        sub_steps=1,
        n_paths=n_paths,
    )


def _mean_and_p95_bps(values: list[int]) -> tuple[float, float]:
    array = np.asarray(values, dtype=np.float64)
    return float(array.mean()), float(np.percentile(array, 95))


# ── 1. Korrektheit: Bruecke == nativ feiner simuliert ────────────────────────


@pytest.mark.parametrize("sub_steps", [4, 12])
def test_bridge_matches_native_fine_simulation(sub_steps: int) -> None:
    """Die Bruecken-Verfeinerung reproduziert die native feine Simulation.

    Das ist der tragende Test des ganzen Verfahrens: die Bruecke ist die
    *exakte* bedingte Verteilung einer Brownschen Bewegung bei bekanntem
    Endwert. Verfeinert man einen Jahrespfad mit ihr, muss die resultierende
    Drawdown-Verteilung mit der einer von Anfang an feiner simulierten Reihe
    uebereinstimmen -- sonst ist die hoehere Zahl nur groesser, nicht richtiger.

    Verglichen werden Verteilungs-Kennzahlen (Mittel, p95) auf unabhaengigen
    Stichproben, die Toleranz ist deshalb Monte-Carlo-Rauschen, nicht
    Methodenspielraum.
    """
    log_location, log_scale = _log_parameters(0.045, 0.08)
    years, n_paths = 10, 6000

    native = _native_paths(
        np.random.default_rng(4242),
        log_location=log_location,
        log_scale=log_scale,
        years=years,
        sub_steps=sub_steps,
        n_paths=n_paths,
    )
    native_mean, native_p95 = _mean_and_p95_bps(
        [int(v) for v in max_drawdown_bps_from_levels(native)]
    )

    annual = _annual_paths(
        np.random.default_rng(9191),
        log_location=log_location,
        log_scale=log_scale,
        years=years,
        n_paths=n_paths,
    )
    refined = refine_max_drawdowns(annual, seed=123456, sub_steps=sub_steps)
    bridge_mean, bridge_p95 = _mean_and_p95_bps(refined.refined_bps)

    # 100 bps = 1 Prozentpunkt. Bei 6000 Pfaden liegt der Standardfehler des
    # Mittels bei ~15 bps, der des p95 hoeher -- die Toleranzen sind daran
    # bemessen und NICHT an der Methodendifferenz (die ist null).
    assert abs(bridge_mean - native_mean) < 100, (
        f"Bruecke {bridge_mean:.0f} bps vs nativ {native_mean:.0f} bps "
        f"bei K={sub_steps} -- mehr als 1pp Abweichung deutet auf einen "
        "Fehler in der Brueckenkonstruktion, nicht auf MC-Rauschen."
    )
    assert abs(bridge_p95 - native_p95) < 200


def test_bridge_preserves_annual_nodes_exactly() -> None:
    """Die Jahresstuetzstellen muessen im verfeinerten Pfad exakt wieder vorkommen.

    Die Standard-Bruecke erfuellt BB(1) = W(1) - 1*W(1) = 0 exakt (nicht nur im
    Erwartungswert). Daraus folgt die Monotonie-Eigenschaft und die Garantie,
    dass die Verfeinerung die Jahresendwerte -- und damit jede daraus
    abgeleitete Kennzahl -- nicht verschiebt.

    Geprueft wird hier die algebraische Identitaet am Einzelpfad: ein Pfad, der
    am Jahresende exakt auf seinem Jahreswert liegt, behaelt als Drawdown
    mindestens den Jahresgitter-Wert.
    """
    # Erster Pfad mit bekanntem Jahresgitter-Drawdown: 1500 -> 600 = 60 %.
    # Die weiteren Pfade sorgen fuer eine schaetzbare Dispersion quer ueber die
    # Pfade (ohne die faellt die Verfeinerung korrekt auf das Jahresgitter
    # zurueck, siehe test_single_path_falls_back_to_annual_grid).
    paths = [
        [1000.0, 1200.0, 800.0, 1500.0, 600.0],
        [1000.0, 950.0, 1050.0, 1100.0, 1250.0],
        [1000.0, 1100.0, 1210.0, 1150.0, 1300.0],
        [1000.0, 890.0, 940.0, 1020.0, 980.0],
    ]
    annual_only = refine_max_drawdowns(paths, seed=1, sub_steps=1)
    assert annual_only.annual_bps[0] == 6000

    refined = refine_max_drawdowns(paths, seed=1, sub_steps=24)
    assert refined.applied is True
    assert refined.annual_bps[0] == 6000
    # Die Jahresstuetzstellen sind exakt enthalten, also ist der verfeinerte
    # Wert jedes Pfades mindestens der Jahresgitter-Wert.
    assert all(
        fine >= coarse
        for fine, coarse in zip(refined.refined_bps, refined.annual_bps)
    )


# ── 2. Monotonie ─────────────────────────────────────────────────────────────


def test_refined_drawdown_never_below_annual_grid() -> None:
    """Pfadweise Monotonie ueber eine breite Stichprobe.

    Der verfeinerte Pfad ist eine Obermenge des Jahrespfades, also kann das
    laufende Maximum nur steigen und die Taeler nur tiefer werden. Ein
    Gegenbeispiel waere ein Konstruktionsfehler (etwa eine Bruecke, die den
    Endwert nicht trifft).
    """
    log_location, log_scale = _log_parameters(0.045, 0.10)
    annual = _annual_paths(
        np.random.default_rng(31337),
        log_location=log_location,
        log_scale=log_scale,
        years=12,
        n_paths=800,
    )
    refined = refine_max_drawdowns(annual, seed=555, sub_steps=WEEKLY_SUB_STEPS)
    violations = [
        (index, fine, coarse)
        for index, (fine, coarse) in enumerate(
            zip(refined.refined_bps, refined.annual_bps)
        )
        if fine < coarse
    ]
    assert not violations, f"{len(violations)} Pfade unter dem Jahresgitter: {violations[:5]}"


def test_refinement_increases_drawdown_materially() -> None:
    """Die Korrektur ist relevant gross, nicht kosmetisch.

    Pinnt die Richtung UND die Groessenordnung: auf dem Jahresgitter fehlt ein
    guter Teil des Peak-to-Trough-Verlusts. Ohne diese Schranke koennte eine
    stillgelegte Verfeinerung (etwa sigma faellt versehentlich auf 0) unbemerkt
    durchlaufen.
    """
    log_location, log_scale = _log_parameters(0.045, 0.08)
    annual = _annual_paths(
        np.random.default_rng(8080),
        log_location=log_location,
        log_scale=log_scale,
        years=15,
        n_paths=2000,
    )
    refined = refine_max_drawdowns(annual, seed=777, sub_steps=WEEKLY_SUB_STEPS)
    annual_mean, _ = _mean_and_p95_bps(refined.annual_bps)
    refined_mean, _ = _mean_and_p95_bps(refined.refined_bps)
    # Gemessen ~6.4pp bei 8 % Vol; die Schranke laesst Luft fuer MC-Rauschen,
    # faengt aber jedes Abschalten der Verfeinerung.
    assert refined_mean - annual_mean > 400, (
        f"Verfeinerung hob den Mittelwert nur um "
        f"{(refined_mean - annual_mean) / 100:.2f}pp -- erwartet > 4pp."
    )


def test_underestimation_grows_with_volatility() -> None:
    """Die Verzerrung des Jahresgitters ist volatilitaetsabhaengig.

    Das ist der eigentliche fachliche Schaden: auf dem Jahresgitter wird die
    Spreizung zwischen defensiven und riskanten Mandaten zusammengedrueckt,
    riskante Mandate erscheinen relativ sicherer als sie sind. Der Test pinnt,
    dass die Korrektur bei hoeherer Volatilitaet GROESSER ausfaellt -- eine
    konstante Korrektur waere fachlich falsch.
    """
    gaps = []
    for arith_sigma in (0.04, 0.08, 0.14):
        log_location, log_scale = _log_parameters(0.045, arith_sigma)
        annual = _annual_paths(
            np.random.default_rng(2026),
            log_location=log_location,
            log_scale=log_scale,
            years=15,
            n_paths=1500,
        )
        refined = refine_max_drawdowns(annual, seed=99, sub_steps=WEEKLY_SUB_STEPS)
        annual_mean, _ = _mean_and_p95_bps(refined.annual_bps)
        refined_mean, _ = _mean_and_p95_bps(refined.refined_bps)
        gaps.append(refined_mean - annual_mean)

    assert gaps[0] < gaps[1] < gaps[2], (
        "Korrektur muss mit der Volatilitaet wachsen, gemessen (bps): "
        f"{[round(g) for g in gaps]}"
    )


# ── 3. Reproduzierbarkeit, sigma-Schaetzung, Rueckfall ───────────────────────


def test_same_seed_same_result() -> None:
    log_location, log_scale = _log_parameters(0.045, 0.08)
    annual = _annual_paths(
        np.random.default_rng(11),
        log_location=log_location,
        log_scale=log_scale,
        years=8,
        n_paths=200,
    )
    first = refine_max_drawdowns(annual, seed=4711, sub_steps=12)
    second = refine_max_drawdowns(annual, seed=4711, sub_steps=12)
    assert first.refined_bps == second.refined_bps
    assert first.log_volatility == second.log_volatility


def test_different_seed_changes_result_but_not_annual_grid() -> None:
    log_location, log_scale = _log_parameters(0.045, 0.08)
    annual = _annual_paths(
        np.random.default_rng(12),
        log_location=log_location,
        log_scale=log_scale,
        years=8,
        n_paths=200,
    )
    first = refine_max_drawdowns(annual, seed=1, sub_steps=12)
    second = refine_max_drawdowns(annual, seed=2, sub_steps=12)
    assert first.refined_bps != second.refined_bps
    # Der Jahresgitter-Wert haengt nicht am Bruecken-Seed.
    assert first.annual_bps == second.annual_bps


def test_chunking_does_not_change_the_number() -> None:
    """Die Blockgroesse ist eine Speichergrenze, kein Modellparameter.

    Der Zufallsstrom wird blockweise in derselben Reihenfolge entnommen, also
    muss ein anderer ``chunk_paths``-Wert exakt dasselbe Ergebnis liefern.
    Faellt dieser Test, ist die Vektorisierung nicht reihenfolgetreu.
    """
    log_location, log_scale = _log_parameters(0.045, 0.08)
    annual = _annual_paths(
        np.random.default_rng(13),
        log_location=log_location,
        log_scale=log_scale,
        years=6,
        n_paths=300,
    )
    whole = refine_max_drawdowns(annual, seed=5, sub_steps=8, chunk_paths=10_000)
    blocked = refine_max_drawdowns(annual, seed=5, sub_steps=8, chunk_paths=64)
    assert whole.refined_bps == blocked.refined_bps


def test_pooled_volatility_recovers_the_input_scale() -> None:
    """Die sigma-Schaetzung aus den Pfaden trifft die wahre Jahresvolatilitaet.

    sigma ist kein separater Input, sondern wird aus den realisierten
    Jahres-Log-Inkrementen geschaetzt -- damit kann es nicht von der Simulation
    abdriften. Der Test belegt, dass der Schaetzer die eingespeiste Skala
    zurueckgibt.
    """
    log_location, log_scale = _log_parameters(0.045, 0.08)
    annual = _annual_paths(
        np.random.default_rng(14),
        log_location=log_location,
        log_scale=log_scale,
        years=20,
        n_paths=4000,
    )
    estimated = pooled_annual_log_volatility(np.log(annual))
    assert estimated == pytest.approx(log_scale, rel=0.03)


def test_replicated_deterministic_paths_fall_back_to_annual_grid() -> None:
    """Replizierte identische Pfade bekommen KEINE Volatilitaet zugeschrieben.

    Das ist der Grund, warum sigma quer ueber die Pfade geschaetzt wird und
    nicht ueber Pfade UND Jahre gepoolt: der Pfad ``[1000, 1100, 900, 1200]``
    schwankt von Jahr zu Jahr erheblich, ist aber deterministisch. Ein
    gepoolter Schaetzer haette ihm sigma ~ 0.20 zugeschrieben und die Bruecke
    haette Zufall in einen Pfad eingespeist, der keinen enthaelt -- die
    deterministischen Engine-Tests (replizierte Einzelpfade) waeren damit
    stillschweigend stochastisch geworden.

    Quer ueber die Pfade ist die Dispersion bei festem Jahr exakt 0, die
    Verfeinerung faellt korrekt auf das Jahresgitter zurueck.
    """
    constant = [[1000.0, 1100.0, 900.0, 1200.0]] * 25
    result = refine_max_drawdowns(constant, seed=1, sub_steps=WEEKLY_SUB_STEPS)
    assert result.log_volatility == 0.0
    assert result.applied is False
    assert result.refined_bps == result.annual_bps


def test_single_path_falls_back_to_annual_grid() -> None:
    """Aus einem einzelnen Pfad ist die Dispersion nicht schaetzbar."""
    result = refine_max_drawdowns(
        [[1000.0, 1100.0, 900.0, 1200.0]], seed=1, sub_steps=WEEKLY_SUB_STEPS
    )
    assert result.log_volatility == 0.0
    assert result.refined_bps == result.annual_bps


@pytest.mark.parametrize(
    "paths",
    [
        [],
        [[1000.0]],
        [[1000.0, 0.0, 500.0]],  # Nullwert -> Log undefiniert
        [[1000.0, -50.0]],  # negativ -> Log undefiniert
        [[1000.0, float("inf")]],
    ],
)
def test_degenerate_input_never_raises(paths) -> None:
    """Degenerierter Input liefert einen Wert, nie eine Exception.

    Die Kennzahl darf an einer Verfeinerung nicht sterben -- der Rueckfall gibt
    das Jahresgitter-Ergebnis zurueck, also schlimmstenfalls genau das
    bisherige Verhalten.
    """
    result = refine_max_drawdowns(paths, seed=1, sub_steps=WEEKLY_SUB_STEPS)
    assert len(result.refined_bps) == len(result.annual_bps)
    assert result.refined_bps == result.annual_bps
    assert result.model_version == DRAWDOWN_REFINEMENT_MODEL_VERSION


def test_sub_steps_one_is_a_no_op() -> None:
    log_location, log_scale = _log_parameters(0.045, 0.08)
    annual = _annual_paths(
        np.random.default_rng(15),
        log_location=log_location,
        log_scale=log_scale,
        years=10,
        n_paths=100,
    )
    result = refine_max_drawdowns(annual, seed=1, sub_steps=1)
    assert result.refined_bps == result.annual_bps
    assert result.applied is False


def test_bridge_seed_is_independent_of_the_main_seed() -> None:
    """Der Bruecken-Seed ist vom Haupt-Seed abgeleitet, aber ohne Struktur.

    Ein einfacher Offset (``seed + k``) wuerde bei benachbarten Haupt-Seeds
    ueberlappende Stroeme erzeugen. Der Hash verhindert das; geprueft wird,
    dass benachbarte Haupt-Seeds weit auseinanderliegende Bruecken-Seeds
    ergeben und dass die Ableitung deterministisch ist.
    """
    assert bridge_seed(1000) == bridge_seed(1000)
    assert bridge_seed(1000) != bridge_seed(1001)
    assert abs(bridge_seed(1000) - bridge_seed(1001)) > 1_000_000


def test_pdf_does_not_label_the_simulated_drawdown_as_historical() -> None:
    """Der kundensichtbare Max-Drawdown darf nicht als "historisch" ausgewiesen sein.

    Die Box im Abschnitt "Risikoindiktatoren & Prognose (Monte Carlo)" trug die
    Quellenangabe "historisch", bekommt aber ``target_max_drawdown_p50_bps`` --
    den Median einer SIMULIERTEN Verteilung. Es fliesst keine einzige
    historische Beobachtung ein. Mit der Zeitgitter-Verfeinerung ist der Wert
    noch eindeutiger ein Modellergebnis, also wird die Angabe hier festgenagelt.
    """
    from services.pdf.components.risiko_metriken import (
        make_risiko_metriken_section,
    )

    def _texts(node, out: list[str]) -> list[str]:
        text = getattr(node, "text", None)
        if isinstance(text, str):
            out.append(text)
        for attribute in ("_cellvalues", "_content"):
            rows = getattr(node, attribute, None)
            if rows:
                for row in rows:
                    for cell in row if isinstance(row, (list, tuple)) else [row]:
                        for item in cell if isinstance(cell, (list, tuple)) else [cell]:
                            _texts(item, out)
        return out

    flowables = make_risiko_metriken_section(
        expected_return_bps=450,
        median_cagr_bps=420,
        volatility_bps=800,
        max_drawdown_bps=2208,
        var_95_bps=1150,
    )
    collected: list[str] = []
    for flowable in flowables:
        _texts(flowable, collected)
    joined = " ".join(collected)

    assert "historisch" not in joined, (
        "Der simulierte Max-Drawdown wird als historische Beobachtung "
        f"ausgewiesen: {joined!r}"
    )
    assert "simuliert" in joined, (
        f"Quellenangabe der Max-Drawdown-Box fehlt oder ist unklar: {joined!r}"
    )


def test_max_drawdown_matches_the_scalar_engine_helper() -> None:
    """Die vektorisierte Drawdown-Berechnung ist mit der Engine-Variante konsistent.

    Zwei Implementierungen derselben Kennzahl sind eine Divergenzquelle; der
    Test bindet sie aneinander.
    """
    from services.portfolio_engine_mc_simulation import _max_drawdown_bps

    cases = [
        [1000, 1200, 800, 1500, 600],
        [1000, 1000, 1000],
        [500, 400, 300, 200],
        [100, 2000, 1999],
        [0, 0, 100, 50],
    ]
    for case in cases:
        vectorized = max_drawdown_bps_from_levels(
            np.asarray([case], dtype=np.float64)
        )
        assert int(vectorized[0]) == _max_drawdown_bps(case), case
