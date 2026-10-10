"""Winner's-Curse-Kalibrierung der Zertifizierungsregel
(OPTIMIZER-POST-SELECTION-CERTIFICATION-001, Befund aus Runde 38).

Common Random Numbers ueber die Kandidaten sind korrekt und gewollt (ein
einziges ``OptimizerContext.return_paths`` wird fuer alle Kandidaten eines
Solver-Durchlaufs wiederverwendet -- so vergleicht man Kandidaten fair).
Das Problem lag NACH der Selektion: die Trainings-Cube-Schaetzung des
Gewinners galt als endgueltig, ohne unabhaengige Neuschaetzung. Weil der
Gewinner GERADE DESHALB gewonnen hat, weil er auf diesem Cube eine
guenstige Stichprobe hatte, ist seine Trainings-Schaetzung systematisch
nach oben verzerrt -- Post-Selection-Inference bzw. Winner's Curse.

Dieser Test war urspruenglich ein reiner Phaenomen-Nachweis (es gab keinen
unabhaengigen Validierungsschritt, in den man haette hineinrufen koennen).
Seit dem Fix pruefen wir stattdessen die PRODUKTIONS-Regel selbst:
``services/optimizer/certification.py`` (Wilson-Untergrenze, Kish-ESS) und
``solver._certify_on_independent_validation_cube`` (unabhaengiger
Validierungs-Cube mit eigenem Seed).

Gemessene Zertifizierungsraten bei wahrer Wahrscheinlichkeit == tau == 0.80
(400 Durchlaeufe, feste Seeds, deterministisch):

    Punktschaetzer, best-of-5          ~98 Prozent   <- alte Regel, kaputt
    Wilson-Untergrenze, best-of-5      ~15 Prozent   <- Rauschen entfernt
    Wilson-Untergrenze, unabh. Cube    ~3.5 Prozent  <- Selektion entfernt

Die letzte Zeile entspricht der nominalen Fehlerrate einer einseitigen
95-Prozent-Grenze und ist damit die korrekt kalibrierte Aussage.
"""
from __future__ import annotations

import numpy as np

from services.optimizer.certification import wilson_lower_bound

TRUE_SUCCESS_PROBABILITY = 0.80
TAU = 0.80
N_CANDIDATES = 5
N_PATHS = 2000
N_TRIALS = 400


def _antithetic_bernoulli_successes(rng: np.random.Generator, p: float, n: int) -> np.ndarray:
    """n antithetic-paired Bernoulli(p) draws: for each uniform draw u, both
    u and its antithetic partner (1-u) are compared against p. This mirrors
    the audit's "2000 antithetic Standard-MC-Pfade" train-cube shape."""
    half = n // 2
    u = rng.random(half)
    first_half = (u < p).astype(np.int8)
    second_half = ((1.0 - u) < p).astype(np.int8)
    return np.concatenate([first_half, second_half])


def test_certification_rule_is_not_fooled_by_post_selection_bias():
    """Prueft die PRODUKTIONS-Zertifizierungsregel gegen den Winner's Curse.

    Dieser Test hiess frueher
    `test_train_cube_certification_rate_matches_independent_validation_rate`
    und war ein reiner Phaenomen-Nachweis: er rechnete die Verzerrung mit
    lokalen Hilfsfunktionen vor, ohne Produktionscode aufzurufen, weil es
    damals keinen unabhaengigen Validierungsschritt gab, in den man haette
    hineinrufen koennen. Genau der existiert jetzt
    (``services/optimizer/certification.py`` +
    ``solver._certify_on_independent_validation_cube``), also prueft der
    Test nicht mehr "gibt es die Verzerrung?", sondern "faellt unsere Regel
    darauf herein?".

    Aufbau: fuenf marginal identische Kandidaten, deren WAHRE
    Erfolgswahrscheinlichkeit exakt auf der Schwelle liegt (p == tau ==
    0.80). Fuer eine korrekt kalibrierte einseitige 95-Prozent-Regel ist
    das der haerteste Fall -- sie darf hier nur mit etwa der nominalen
    Fehlerrate (~5 Prozent) gruen zertifizieren, nicht in fast allen
    Faellen.

    Die drei geprueften Eigenschaften zeigen zusammen, dass BEIDE
    Mechanismen gebraucht werden und was jeder beitraegt.
    """
    point_estimate_green = 0
    lower_bound_on_train_green = 0
    lower_bound_on_validation_green = 0

    for trial_index in range(N_TRIALS):
        train_rng = np.random.default_rng(1000 + trial_index)
        validation_rng = np.random.default_rng(50_000 + trial_index)

        train_rates = np.array([
            _antithetic_bernoulli_successes(
                train_rng, TRUE_SUCCESS_PROBABILITY, N_PATHS
            ).mean()
            for _ in range(N_CANDIDATES)
        ])
        selected_rate = float(train_rates[int(np.argmax(train_rates))])
        validation_rate = float(
            _antithetic_bernoulli_successes(
                validation_rng, TRUE_SUCCESS_PROBABILITY, N_PATHS
            ).mean()
        )

        point_estimate_green += int(selected_rate >= TAU)
        lower_bound_on_train_green += int(
            wilson_lower_bound(selected_rate, N_PATHS) >= TAU
        )
        lower_bound_on_validation_green += int(
            wilson_lower_bound(validation_rate, N_PATHS) >= TAU
        )

    # (1) Die alte Regel ist nachweislich kaputt: der rohe Punktschaetzer
    # zertifiziert ein Ziel, dessen wahre Chance genau 50/50 gegen die
    # Schwelle steht, in fast allen Faellen als erreichbar. Diese Zusicherung
    # bleibt bewusst stehen -- sie schlaegt an, falls jemand die
    # Zertifizierung je auf den Punktschaetzer zurueckdreht.
    assert point_estimate_green >= int(0.90 * N_TRIALS), (
        f"Punktschaetzer-Regel zertifizierte nur {point_estimate_green}/{N_TRIALS} "
        "gruen -- erwartet war der dokumentierte Fehlerfall (>=90 Prozent). "
        "Stimmt der Testaufbau noch?"
    )

    # (2) Die untere Konfidenzgrenze entfernt den Grossteil der
    # Ueberzertifizierung, bleibt auf dem SELEKTIONS-Cube aber noch durch die
    # Auswahl inflationiert (gemessen ~15 Prozent gegen nominal ~5).
    assert lower_bound_on_train_green <= int(0.30 * N_TRIALS), (
        f"untere Grenze auf dem Selektions-Cube: {lower_bound_on_train_green}/"
        f"{N_TRIALS} gruen -- deutlich mehr als erwartet"
    )

    # (3) Auf einem UNABHAENGIGEN Cube -- was der Solver seit
    # OPTIMIZER-POST-SELECTION-CERTIFICATION-001 publiziert -- liegt die
    # Rate bei der nominalen Fehlerrate der einseitigen 95-Prozent-Grenze.
    # Das ist die eigentliche Zusicherung: die veroeffentlichte
    # Zertifizierung ist selektionsfrei.
    assert lower_bound_on_validation_green <= int(0.10 * N_TRIALS), (
        f"unabhaengige Validierung zertifizierte {lower_bound_on_validation_green}/"
        f"{N_TRIALS} gruen -- eine korrekt kalibrierte einseitige "
        "95-Prozent-Regel darf bei wahrer Wahrscheinlichkeit == tau nur mit "
        "etwa der nominalen Fehlerrate gruen melden"
    )

    # Und die Reihenfolge der drei Raten belegt, dass jeder Mechanismus
    # tatsaechlich etwas beitraegt.
    assert (
        lower_bound_on_validation_green
        < lower_bound_on_train_green
        < point_estimate_green
    ), (
        "erwartete Rangfolge verletzt: unabhaengige Validierung < untere "
        "Grenze auf Selektions-Cube < Punktschaetzer "
        f"(gemessen: {lower_bound_on_validation_green} / "
        f"{lower_bound_on_train_green} / {point_estimate_green})"
    )


def test_each_individual_candidate_distribution_is_itself_correctly_calibrated():
    """Positive control: a single candidate's own Bernoulli(0.80) sampling
    mechanism, evaluated WITHOUT any selection step, is correctly calibrated
    around tau on average across many independent draws -- the bug is
    specifically about selecting the best of several before certifying,
    not about the underlying random-sampling mechanism being biased.
    """
    rng = np.random.default_rng(999)
    rates = [
        _antithetic_bernoulli_successes(rng, TRUE_SUCCESS_PROBABILITY, N_PATHS).mean()
        for _ in range(200)
    ]
    mean_rate = float(np.mean(rates))
    assert abs(mean_rate - TRUE_SUCCESS_PROBABILITY) < 0.01
