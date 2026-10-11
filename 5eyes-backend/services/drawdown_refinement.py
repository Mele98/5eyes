"""Zeitgitter-Verfeinerung des Max-Drawdown via Brownsche Bruecke.

DRAWDOWN-TIME-GRID-001
======================

**Befund.** Die Monte-Carlo-Pfade der Engine werden in Jahresschritten
fortgeschrieben. Der Max-Drawdown wurde auf genau diesen Jahresstuetzstellen
gemessen -- also als tiefster Peak-to-Trough-Verlust *zwischen zwei
Jahresenden*. Die Kennzahl wird dem Kunden aber als "Max. Drawdown" ohne
Einschraenkung ausgewiesen, und das liest sich als schlimmster
Peak-to-Trough-Verlust ueberhaupt. Beides faellt systematisch auseinander:
ein Einbruch, der innerhalb eines Jahres eintritt und sich bis zum Jahresende
wieder erholt, ist auf dem Jahresgitter unsichtbar.

**Groessenordnung** (gemessen, 15 Jahre, 20 000 Pfade, arithmetisch 4.5 %
Rendite):

    Teilschritte/Jahr      1       2       4      12      52     252
    Mittel             11.45%  13.71%  15.18%  16.81%  17.86%  18.45%
    p95                23.31%  25.10%  26.06%  27.49%  28.53%  29.21%

Das Jahresgitter unterschaetzt den Mittelwert also um 7.0 Prozentpunkte. Ein
Quartalsgitter -- die naheliegende Minimalkorrektur -- liegt immer noch
3.3 Prozentpunkte zu tief.

**Warum das mehr als ein Schoenheitsfehler ist.** Die Unterschaetzung ist
keine Konstante, sie waechst mit der Volatilitaet:

    Jahresvolatilitaet      3%      5%      8%     12%     16%
    Unterschaetzung      3.29pp  4.97pp  7.06pp  9.05pp 10.25pp

Das Jahresgitter laesst damit *riskante Mandate relativ sicherer erscheinen
als defensive* -- die falsche Richtung fuer eine Eignungsbeurteilung, weil
genau die Spreizung zwischen den Risikoprofilen zusammengedrueckt wird.

Verfahren
---------

Statt die Pfade feiner zu simulieren (was jede andere Kennzahl, die
Zertifizierung und die Solver/Reporting-Paritaet veraendern wuerde) werden die
**bestehenden** Jahrespfade nachtraeglich verfeinert. Zwischen zwei
Jahresstuetzstellen wird eine Brownsche Bruecke eingesetzt: die bedingte
Verteilung einer Brownschen Bewegung bei bekanntem Anfangs- UND Endwert.

Fuer das Log-Niveau gilt mit Jahres-Log-Inkrement ``d``, Jahresvolatilitaet
``sigma`` und Zeitanteil ``t`` in (0, 1]:

    X(t) = X(0) + t * d + sigma * BB(t),   BB(t) = W(t) - t * W(1)

mit ``W`` einer Standard-Brownschen Bewegung auf [0, 1]. ``BB`` ist die
Standard-Bruecke; sie erfuellt ``BB(0) = BB(1) = 0`` **exakt**, nicht nur im
Erwartungswert. Daraus folgen die beiden Eigenschaften, die dieses Modul
tragen:

1. **Die Jahresstuetzstellen werden exakt reproduziert** (bei ``t = 1`` ist
   ``BB = 0``). Der verfeinerte Pfad ist eine echte Obermenge des Jahrespfades,
   also ist der verfeinerte Drawdown **nie kleiner** als der bisherige. Die
   Korrektur kann die Kennzahl nur in die konservative Richtung bewegen.
2. **Kein anderer Wert aendert sich.** Die Bruecke zieht aus einem eigenen,
   getrennt geseedeten Zufallsstrom. Die Haupt-Simulation entnimmt ihrer
   ``random.Random``-Instanz genau dieselbe Zahlenfolge wie vorher, also
   bleiben CAGR, VaR/CVaR, Verlustwahrscheinlichkeit, Vermoegensperzentile,
   Erschoepfungsjahre, Zielerreichung und jede Zertifizierung bit-identisch.

**Validierung.** Die Bruecken-Verfeinerung wurde gegen eine *nativ* mit K
Teilschritten simulierte Reihe gemessen (identische Log-Parameter, 20 000
Pfade). Abweichung im Mittel <= 0.07pp, im p95 <= 0.42pp -- also innerhalb des
Monte-Carlo-Rauschens. Siehe
``tests/test_drawdown_refinement.py::test_bridge_matches_native_fine_simulation``.

Wahl von K
----------

Die Konvergenz ist O(K^-1/2), es gibt also kein K, ab dem die Kennzahl
"fertig" ist. ``WEEKLY_SUB_STEPS = 52`` nimmt 6.41pp der 7.00pp Verzerrung
(92 %) und laesst einen **dokumentierten** Restbias von ~0.6pp stehen -- immer
noch in der konservativen Richtung (die Kennzahl bleibt eine Untergrenze des
stetigen Drawdown). Wichtiger als das letzte Zehntel ist, dass der Restfehler
bekannt und vorzeichenbestimmt ist, statt unbekannt.

Annahme und ihre Grenze
-----------------------

Innerhalb des Jahres wird der Pfad als Brownsch mit konstanter Volatilitaet
modelliert. Ist das Tail-Modell aktiv (Cornish-Fisher), ist das
Jahres-Inkrement schief/leptokurtisch -- die Bruecke verteilt es dann zwar mit
dem korrekten Endwert, aber mit normalverteilten Zwischenschritten. Der
Jahresendwert und damit das Schiefe-/Kurtosis-Profil des Jahres bleibt exakt
erhalten; nur die *Feinstruktur* innerhalb des Jahres ist gaussisch. Fuer eine
Peak-to-Trough-Kennzahl ueber viele Jahre ist das zweiter Ordnung, weil die
Jahresinkremente -- die den Grossteil der Amplitude tragen -- unangetastet
bleiben.

``sigma`` wird nicht als Parameter gesetzt, sondern **aus den Pfaden selbst**
geschaetzt: Streuung der realisierten Jahres-Log-Inkremente *quer ueber die
Pfade* je Jahr, dann ueber die Jahre gemittelt (siehe
``pooled_annual_log_volatility`` fuer die Begruendung, warum nicht ueber Pfade
UND Jahre gepoolt wird). Der Schaetzer zieht Allokation, Korrelationen,
Rebalancing und Tail-Modell automatisch korrekt mit. Es gibt keinen zweiten,
separat zu pflegenden Volatilitaets-Input, der von der Simulation abdriften
koennte.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

import numpy as np

# Teilschritte pro Jahr. Siehe Modul-Docstring, Abschnitt "Wahl von K".
WEEKLY_SUB_STEPS = 52

# Pfade pro Vektorisierungs-Block. Begrenzt den Speicher auf
# chunk * horizon * sub_steps floats; bei 256 x 60 x 52 sind das ~6 MB pro
# Zwischenarray. Rein eine Speichergrenze, ohne Ergebniswirkung: der
# Zufallsstrom wird blockweise in derselben Reihenfolge entnommen.
DRAWDOWN_CHUNK_PATHS = 256

# Versionskennung fuer den Audit-Trail. Bei jeder Methodenaenderung (anderes K,
# anderes Brueckenmodell, andere sigma-Schaetzung) hochziehen.
DRAWDOWN_REFINEMENT_MODEL_VERSION = "brownian_bridge_weekly_v1"

# Der Bruecken-Zufallsstrom wird vom Haupt-Seed abgeleitet, aber ueber ein
# eigenes Label, damit er nachweislich unabhaengig von der Haupt-Simulation ist
# (siehe Modul-Docstring, Eigenschaft 2).
_BRIDGE_SEED_LABEL = "drawdown_bridge_v1"

_LOG_FLOOR = 1e-12


@dataclass(frozen=True)
class DrawdownRefinement:
    """Ergebnis der Verfeinerung, inklusive Nachweis-Feldern.

    ``annual_bps`` wird mitgeliefert, damit im Audit-Trail nachvollziehbar
    bleibt, wie gross die Korrektur fuer diesen konkreten Lauf war -- die
    Kennzahl selbst ist ``refined_bps``.
    """

    refined_bps: list[int]
    annual_bps: list[int]
    log_volatility: float
    sub_steps: int
    model_version: str = DRAWDOWN_REFINEMENT_MODEL_VERSION

    @property
    def applied(self) -> bool:
        """False, wenn die Verfeinerung nicht greifen konnte (siehe Rueckfall)."""
        return self.sub_steps > 1 and self.log_volatility > 0.0


def drawdown_time_grid_basis(sub_steps: int = WEEKLY_SUB_STEPS) -> dict[str, Any]:
    """Methodenbeschreibung fuer den Modell-Basis-Block.

    Die Kennzahl selbst (``mc_max_drawdown_bps``) wird auf der
    TargetAllocation persistiert, ihre Methode gehoerte bisher nirgendwohin:
    die Nachweis-Felder im ``monte_carlo``-Payload sind live und ueberleben
    den Reload nicht. Ein Jahr spaeter waere an einem gespeicherten Wert nicht
    mehr erkennbar, auf welchem Zeitgitter er entstanden ist -- und die
    Korrektur dieses Gitters bewegt die Zahl um 3 bis 10 Prozentpunkte.
    """
    return {
        "model_version": DRAWDOWN_REFINEMENT_MODEL_VERSION,
        "sub_steps_per_year": int(sub_steps),
        "method": "brownian_bridge_refinement_of_annual_nodes",
        "volatility_source": "pooled_cross_path_annual_log_increments",
    }


def bridge_seed(seed: int) -> int:
    """Leitet den unabhaengigen Bruecken-Seed vom Haupt-Seed ab.

    Deterministisch, damit ein Lauf reproduzierbar bleibt, aber ueber einen
    Hash statt einen Offset, damit kein strukturelles Verhaeltnis zum
    Haupt-Zufallsstrom entsteht.
    """
    payload = f"{int(seed)}|{_BRIDGE_SEED_LABEL}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def max_drawdown_bps_from_levels(values: np.ndarray) -> np.ndarray:
    """Max-Drawdown pro Pfad in bps, vektorisiert ueber Pfade.

    ``values`` hat shape (pfade, stuetzstellen) und enthaelt Niveaus (keine
    Log-Werte). Gleiche Konvention wie die skalare Variante in der Engine:
    laufendes Maximum als Peak, Drawdown relativ zum Peak.
    """
    # Ein nicht-finites Niveau ist kein Vermoegensstand. Es wird auf 0
    # gesetzt, statt als NaN durch die Kennzahl zu laufen -- die skalare
    # Engine-Variante wuerde an so einem Wert mit OverflowError abbrechen.
    values = np.nan_to_num(
        np.asarray(values, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0
    )
    values = np.maximum(values, 0.0)
    peak = np.maximum.accumulate(values, axis=1)
    safe_peak = np.where(peak > 0.0, peak, 1.0)
    drawdown = np.where(peak > 0.0, (peak - values) / safe_peak, 0.0)
    worst = np.clip(drawdown.max(axis=1), 0.0, 1.0)
    return np.rint(worst * 10000.0).astype(np.int64)


def pooled_annual_log_volatility(log_levels: np.ndarray) -> float:
    """Jahresvolatilitaet der Log-Inkremente, geschaetzt QUER UEBER DIE PFADE.

    Pro Jahr wird die Streuung der Log-Inkremente *ueber die Pfade* bestimmt
    und anschliessend ueber die Jahre gemittelt (Varianzen, dann Wurzel).

    **Warum nicht ueber Pfade und Jahre gepoolt.** Ein gepoolter Schaetzer
    zaehlt auch die Variation des Inkrements *von Jahr zu Jahr innerhalb eines
    Pfades* mit. Die ist aber nicht zwingend stochastisch: ein
    deterministischer Pfad (etwa die replizierten identischen Pfade der
    deterministischen Engine-Tests) schwankt ebenfalls von Jahr zu Jahr und
    bekaeme so eine Volatilitaet zugeschrieben, die er nicht hat -- die Bruecke
    wuerde Zufall in einen Pfad einspeisen, der keinen enthaelt.

    Die Streuung quer ueber die Pfade bei festem Jahr ist dagegen genau die
    stochastische Dispersion: die Inkremente sind dort unabhaengige Ziehungen
    aus derselben Verteilung (das Modell ist zeithomogen, ``log_parameters``
    sind in jedem Jahr dieselben). Sie ist 0 fuer replizierte Pfade und
    unverzerrt fuer echte Simulationen. Die Mittelung ueber die Jahre erhoeht
    nur die Praezision.

    Dass Rebalancing die Gewichte -- und damit die Dispersion -- ueber die
    Jahre leicht auseinanderlaufen laesst, ist dabei kein Stoerterm, sondern
    echte Portfolio-Dispersion und gehoert in die Schaetzung.

    Liefert 0.0, wenn weniger als zwei Pfade vorliegen: aus einem einzelnen
    Pfad ist die Dispersion nicht schaetzbar.
    """
    log_levels = np.asarray(log_levels, dtype=np.float64)
    if log_levels.ndim != 2 or log_levels.shape[0] < 2 or log_levels.shape[1] < 2:
        return 0.0
    increments = np.diff(log_levels, axis=1)  # (pfade, jahre)
    per_year_variance = np.var(increments, axis=0, ddof=1)  # quer ueber Pfade
    sigma = float(np.sqrt(np.mean(per_year_variance)))
    if not np.isfinite(sigma) or sigma <= 0.0:
        return 0.0
    return sigma


def refine_max_drawdowns(
    annual_index_paths: Sequence[Sequence[float]],
    *,
    seed: int,
    sub_steps: int = WEEKLY_SUB_STEPS,
    chunk_paths: int = DRAWDOWN_CHUNK_PATHS,
) -> DrawdownRefinement:
    """Verfeinert den Max-Drawdown der uebergebenen Jahres-Indexpfade.

    ``annual_index_paths`` ist eine Liste gleich langer, strikt positiver
    Indexpfade (ein Pfad pro Simulation, Jahresstuetzstellen inklusive
    Startwert) -- in der Engine die cashflow-neutralen Markt-Indexpfade aus
    #AA-10, nicht die Vermoegenspfade.

    Rueckfall ohne Verfeinerung (``refined_bps == annual_bps``), wenn:
      * ``sub_steps <= 1``,
      * weniger als zwei Stuetzstellen oder kein Pfad vorliegt,
      * ein Pfad nicht strikt positiv oder nicht finit ist (Log undefiniert),
      * die geschaetzte Volatilitaet 0 ist (deterministischer Pfad -- dann hat
        die Bruecke keine Streuung und wuerde exakt linear interpolieren,
        was den Drawdown ohnehin nicht veraendert).

    Der Rueckfall ist bewusst still und verlustfrei: er liefert die bisherige
    Kennzahl, nie einen Fehler und nie einen zu niedrigen Wert.
    """
    paths = np.asarray(annual_index_paths, dtype=np.float64)
    if paths.ndim != 2 or paths.shape[0] == 0 or paths.shape[1] < 2:
        flat = paths.reshape(paths.shape[0], -1) if paths.ndim == 2 else np.zeros((0, 0))
        annual = (
            max_drawdown_bps_from_levels(flat).tolist()
            if flat.size
            else [0] * (paths.shape[0] if paths.ndim == 2 else 0)
        )
        return DrawdownRefinement(
            refined_bps=list(annual),
            annual_bps=list(annual),
            log_volatility=0.0,
            sub_steps=1,
        )

    annual_bps = [int(value) for value in max_drawdown_bps_from_levels(paths)]

    sub_steps = int(sub_steps)
    if sub_steps <= 1 or not np.all(np.isfinite(paths)) or not np.all(paths > 0.0):
        return DrawdownRefinement(
            refined_bps=list(annual_bps),
            annual_bps=annual_bps,
            log_volatility=0.0,
            sub_steps=1,
        )

    log_levels = np.log(np.maximum(paths, _LOG_FLOOR))
    sigma = pooled_annual_log_volatility(log_levels)
    if sigma <= 0.0:
        return DrawdownRefinement(
            refined_bps=list(annual_bps),
            annual_bps=annual_bps,
            log_volatility=0.0,
            sub_steps=1,
        )

    rng = np.random.default_rng(bridge_seed(seed))
    n_paths, n_nodes = paths.shape
    n_years = n_nodes - 1
    # Zeitanteile der Teilschritte innerhalb eines Jahres, t_j = j/K fuer
    # j = 1..K. Der letzte Punkt (t = 1) faellt exakt auf die Jahresstuetzstelle.
    t_grid = (np.arange(1, sub_steps + 1, dtype=np.float64) / float(sub_steps))
    chunk = max(1, int(chunk_paths))

    refined: list[int] = []
    for start in range(0, n_paths, chunk):
        block_levels = log_levels[start : start + chunk]
        block_rows = block_levels.shape[0]
        increments = np.diff(block_levels, axis=1)  # (rows, years)

        # Standard-Brownsche Bewegung auf [0, 1] je (Pfad, Jahr):
        # Inkremente N(0, 1/K) kumuliert.
        noise = rng.standard_normal((block_rows, n_years, sub_steps))
        walk = np.cumsum(noise, axis=2) / np.sqrt(float(sub_steps))
        # Standard-Bruecke BB(t) = W(t) - t*W(1); BB am letzten Knoten exakt 0.
        bridge = walk - t_grid * walk[:, :, -1:]

        # X(t) = X(0) + t*d + sigma*BB(t)
        sub_levels = (
            block_levels[:, :-1, None]
            + t_grid * increments[:, :, None]
            + sigma * bridge
        )
        full_levels = np.concatenate(
            [block_levels[:, :1], sub_levels.reshape(block_rows, n_years * sub_steps)],
            axis=1,
        )
        refined.extend(
            int(value) for value in max_drawdown_bps_from_levels(np.exp(full_levels))
        )

    # Die Jahresstuetzstellen sind im verfeinerten Pfad exakt enthalten, also
    # ist der verfeinerte Drawdown mathematisch nie kleiner. Numerisch wird das
    # hier abgesichert, damit ein exp/log-Rundungsrest die Kennzahl nicht
    # unter den bisherigen Wert druecken kann.
    refined = [max(fine, coarse) for fine, coarse in zip(refined, annual_bps)]

    return DrawdownRefinement(
        refined_bps=refined,
        annual_bps=annual_bps,
        log_volatility=sigma,
        sub_steps=sub_steps,
    )
