"""ADR-014, Schritt 4: Reserve-Cluster, extrahiert aus
`services/portfolio_engine.py` (God-Modul-Split, Welle 3.2).

Reine Datei-Grenz-Verschiebung, 0 Zeilen Fachlogik-Aenderung: die Funktionen
unten sind Byte-fuer-Byte-Kopien ihrer vormaligen Definitionen in
`portfolio_engine.py` (Zeilen 84-222, 2292-2335, 4465-4653 und 5860-5885 zum
Zeitpunkt der Extraktion, siehe ADR-014 -- Zeilenangaben im ADR selbst sind
stale, weil Schritte 1-3 (Gesamtvermoegen, Live-Rebalancing, CMA) bereits vor
dieser Extraktion vorgenommen wurden und Zeilen nach oben verschoben haben).
`portfolio_engine.py` re-exportiert diese Namen weiterhin unter denselben
Namen (Rueckwaerts-Kompatibilitaet fuer `services/advisory_report.py`
(importiert `_compute_reserve_for_inputs` direkt, per Lazy-Import in
`_recompute_reserve_reasoning` -- verifiziert per grep) und
`tests/test_portfolio_engine_regressions.py` (importiert
`_compute_reserve_requirements` direkt beim Namen, Zeile 28 des Test-Files --
verifiziert per grep, ADR-Behauptung ist korrekt) sowie alle weiteren
Test-Dateien, die z.B. `pe._goal_reserve_for_goal`, `pe._goal_is_conditional`
o.ae. nutzen).

Goal-Metadaten-Helfer-Aufloesung (Auftrag dieser Extraktion -- das ADR ist an
dieser Stelle in sich widersprechend, siehe unten):

Das ADR behauptet in seinem Reserve-Abschnitt, Reserve haenge von "5
Goal-Metadaten-Helfern" ab (`_goal_projection_years`, `_annualize_goal_amount`,
`_goal_hardness_key`, `_goal_probability_factor`, `_goal_pension_state_funded`),
die alle physisch im Payload-Bau-Abschnitt stehen. Per `grep -n "^def "` auf
die AKTUELLE Datei ist das nur fuer 2 der 5 Namen zutreffend:

- `_goal_projection_years` und `_annualize_goal_amount` sind tatsaechlich im
  Payload-Bau/Goal-Metadaten-Abschnitt DEFINIERT (Zeilen 2244 bzw. 2258 der
  aktuellen Datei, unmittelbar neben `_goal_hardness_key`, `_goal_weight`,
  `_goal_timing_label` etc.) und werden von 4-5 verschiedenen Stellen aus
  mehreren Clustern gerufen (Reserve: `_goal_reserve_for_goal`,
  `_compute_reserve_for_inputs`; Payload-Bau: `_build_goal_analysis`;
  MC-Simulation: `_year_index_for_goal`, `_monte_carlo_goal_summary`;
  House-Matrix/Tilt: `_apply_goal_and_reserve_tilts`). Diese 2 Helfer BLEIBEN
  daher in `portfolio_engine.py` (echte Drei-plus-Cluster-Verflechtung) und
  werden hier NUR per function-lokalem Lazy-Import zurueckgeholt.
- `_goal_hardness_key` ist ABWEICHEND von der ADR-Behauptung KEINE
  Reserve-Abhaengigkeit: weder `_goal_reserve_for_goal` noch
  `_compute_reserve_for_inputs` rufen sie auf (verifiziert per grep im
  4465-4653- bzw. 2292-2335-Bereich der aktuellen Datei -- kein Treffer).
  Sie wird stattdessen von Payload-Bau (`_goal_weight`, `_build_mandate_score`
  via `_build_goal_analysis`), House-Matrix/Tilt (`_growth_goals_for_equity_tilt`)
  und MC-Simulation (`_monte_carlo_goal_summary`) genutzt. Bleibt unangetastet
  in `portfolio_engine.py`, taucht in diesem Modul gar nicht auf.
- `_goal_probability_factor` und `_goal_pension_state_funded` sind KEINE
  externen Payload-Bau-Abhaengigkeiten, sondern WERDEN HIER DEFINIERT (Zeilen
  184 bzw. 216 der aktuellen Datei, zusammen mit `_goal_is_conditional` und
  `_goal_pension_pillar` im selben physischen Block ganz am Dateianfang, weit
  vor dem Payload-Bau-Abschnitt). Sie ziehen damit vollstaendig in dieses
  Modul um (keine Rueckwaerts-Importe fuer sie noetig); MC-Simulation
  (`_monte_carlo_goal_summary`) und Payload-Bau, die sie ebenfalls rufen,
  muessen sie -- solange sie noch in `portfolio_engine.py` verbleiben -- ganz
  normal ueber den am Dateiende von `portfolio_engine.py` eingefuegten
  Re-Export beziehen (kein Zyklus, da Re-Export-Zeile nach allen Aufrufstellen
  im selben Modul ausgefuehrt wird).

Fazit: von den 5 im ADR genannten Namen bleiben effektiv nur 2
(`_goal_projection_years`, `_annualize_goal_amount`) in `portfolio_engine.py`
und werden von hier zurueckimportiert; 1 (`_goal_hardness_key`) ist gar keine
Reserve-Abhaengigkeit; 2 (`_goal_probability_factor`,
`_goal_pension_state_funded`) sind in Wahrheit Teil DIESES Clusters und ziehen
mit um.

Cross-Cluster-Aufrufe IN dieses Modul hinein (zum Zeitpunkt der Extraktion,
noch unveraendert in `portfolio_engine.py`, per grep verifiziert):
- `_apply_goal_and_reserve_tilts` (House-Matrix/Tilt-Cluster) ruft
  `_compute_reserve_for_inputs` auf -- die zentrale Cross-Bucket-Bruecke
  Reserve -> House-Matrix.
- `_monte_carlo_goal_summary` (MC-Simulation-Cluster) ruft
  `_goal_pension_state_funded` und `_goal_probability_factor` auf.
- `_build_goal_analysis` bzw. `_monte_carlo_goal_summary` rufen
  `_goal_reserve_for_goal` auf (Scoring-Pfad-Kongruenz-Check, siehe
  Sprint-B-Tests).

Zirkular-Import-Haertung (identisches Muster zu den Schritten 1-3): Funktionen,
die Konstanten/Helfer aus `services.portfolio_engine` selbst brauchen
(`_norm_text`, `_parse_rappen`, `_bps`, `_goal_projection_years`,
`_annualize_goal_amount`) importieren diese function-local (lazy), NICHT auf
Modul-Ebene -- ein Modul-Top-Level-Import waere nur sicher, wenn
`portfolio_engine.py` IMMER der Einstiegspunkt der Import-Kette ist, was
nicht garantiert ist. Das `Goal`-Modell ist dagegen ein ganz normaler
Modul-Top-Level-Import -- es haengt nicht von `services.portfolio_engine` ab,
also kein Zyklus moeglich.
"""
from __future__ import annotations

from models.wealth import Goal


# Sprint A4 (2026-05-06): Smoother Reserve-Decay statt Stufenfunktion.
# factor = exp(-years/_RESERVE_DECAY_TAU), geclamped auf [_MIN, _MAX].
_RESERVE_DECAY_TAU: float = 5.0
_RESERVE_DECAY_MIN: float = 0.05  # bei sehr langem Horizont noch 5% Tail-Risk-Reserve
_RESERVE_DECAY_MAX: float = 1.0   # bei years=0 (sofort) genau 100%


def _reserve_decay_mode_smooth() -> bool:
    """Liest die Konfig: smooth-decay nur wenn explizit RESERVE_DECAY_MODE=smooth.
    Default bleibt 'stufen' (audit-konsistent zu Z2/B5/B6).
    """
    import os
    return str(os.environ.get("RESERVE_DECAY_MODE", "stufen")).strip().lower() == "smooth"


def _reserve_decay_factor(years: int) -> float:
    """Hybrid-Decay-Faktor [0.05, 1.0] fuer Reserve-Berechnung.

    Plateau fuer kurzfristige Goals (Berater-Intuition + Audit-Z2-Konsistenz),
    dann exponentielles Abklingen ab Year 4 mit tau=4. Smoother als die alte
    Stufenfunktion {≤3:100%, 4-7:50%, >7:0%} — kein Klippeneffekt mehr bei
    3.0 vs 3.1 Jahren, aber nahe Goals bleiben voll abgesichert.

    years=0..1 -> 1.00 (sofort fällig, voll Reserve)
    years=2    -> 0.95
    years=3    -> 0.90
    years=4    -> 0.82
    years=5    -> 0.67
    years=6    -> 0.55
    years=7    -> 0.45
    years=10   -> 0.25
    years=15   -> 0.09
    years=20+  -> 0.05 (clamp-min)
    """
    import math
    if years is None:
        return _RESERVE_DECAY_MAX
    y = max(0, int(years))
    if y <= 1:
        return _RESERVE_DECAY_MAX
    if y == 2:
        return 0.95
    if y == 3:
        return 0.90
    raw = math.exp(-(y - 3) / _RESERVE_DECAY_TAU)
    return max(_RESERVE_DECAY_MIN, min(_RESERVE_DECAY_MAX, raw))


# Sprint B5 (2026-05-07): Time-Bucket-Reserve mit drei Fristen.
# Berater-Heuristik PB/Brunel-Das Bucket-Strategy: kurz = mehr Cash, mittel = halbe
# Reserve, lang = kein Liquiditaets-Anker. Feinere Granularitaet als legacy
# Stufenfunktion {≤3:100%, ≤7:50%, >7:0%}, opt-in via RESERVE_BUCKET_MODE.
_TIME_BUCKET_FACTORS: tuple[tuple[int, float, str], ...] = (
    (1, 1.00, "≤1J"),
    (3, 0.80, "1-3J"),
    (7, 0.35, "3-7J"),
)
_TIME_BUCKET_LONG_LABEL = ">7J"


def _reserve_bucket_mode_time_bucket() -> bool:
    """Opt-in: B5 Time-Bucket nur wenn RESERVE_BUCKET_MODE=time_bucket.
    Default 'legacy' (audit-konsistent zu Z2/B5-stufen).
    """
    import os
    return str(os.environ.get("RESERVE_BUCKET_MODE", "legacy")).strip().lower() == "time_bucket"


def _time_bucket_reserve_factor(years: int | None) -> float:
    """Time-Bucket-Faktor fuer Reserve nach Fristigkeit.

    ≤1J -> 1.00 (sofort faellig, voll Reserve)
    1-3J -> 0.80
    3-7J -> 0.35
    >7J  -> 0.00
    """
    if years is None:
        return _TIME_BUCKET_FACTORS[0][1]
    y = max(0, int(years))
    for upper, factor, _label in _TIME_BUCKET_FACTORS:
        if y <= upper:
            return factor
    return 0.0


def _time_bucket_label(years: int | None) -> str:
    """Bucket-Label fuer Reasoning-Texte."""
    if years is None:
        return _TIME_BUCKET_FACTORS[0][2]
    y = max(0, int(years))
    for upper, _factor, label in _TIME_BUCKET_FACTORS:
        if y <= upper:
            return label
    return _TIME_BUCKET_LONG_LABEL


# Sprint B6 (2026-05-08): Bedingte Goals (Conditional Goals).
# Goals haben eine Eintrittswahrscheinlichkeit `probability_pct` (0-100).
# Linear gewichtete Reserve: contribution = target * factor * (prob/100).
# NULL/fehlend -> 100 (sicher, backwards-compat).
def _goal_probability_factor(goal: object) -> float:
    raw = getattr(goal, "probability_pct", None)
    if raw is None:
        return 1.0
    try:
        pct = int(raw)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(100, pct)) / 100.0


def _goal_is_conditional(goal: object) -> bool:
    return _goal_probability_factor(goal) < 1.0


# Sprint B3 (2026-05-08): Vorsorge-Saeulen-Differenzierung.
# AHV ist staatlich gedeckt -> kein Reserve-Beitrag aus dem Beratungsportfolio,
# Goal-Score wird als 'voll erfuellt' gewertet (funded_ratio 100%).
# BVG/3a/1e/FZG werden hier (Phase 1) nicht engine-seitig differenziert; sie
# fungieren als Metadata fuer FE-Anzeige und spaetere Liability-Pfade.
PENSION_PILLARS = ("AHV", "BVG", "3a", "1e", "FZG")
PENSION_PILLAR_STATE_FUNDED = ("AHV",)


def _goal_pension_pillar(goal: object) -> str | None:
    raw = getattr(goal, "pension_pillar", None)
    if raw is None:
        return None
    text = str(raw).strip()
    return text if text in PENSION_PILLARS else None


def _goal_pension_state_funded(goal: object) -> bool:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _norm_text

    pillar = _goal_pension_pillar(goal)
    if pillar is None:
        return False
    if _norm_text(getattr(goal, "goal_type", "")) != "Pensionsausgabe":
        return False
    return pillar in PENSION_PILLAR_STATE_FUNDED


def _goal_reserve_for_goal(goal: Goal) -> int:
    """Zielbezogene Liquiditaetsreserve fuer Spending-Goals.

    C5: Vor dem Fix wurde im Goal-Scoring der globale reserve_needed_rappen
    (Maximum aller reserve_candidates) als 'available' verwendet, wodurch
    ein grosses Ziel kleinere automatisch auf 'On Track' hob. Hier
    spiegeln wir die ohnehin schon in _apply_goal_and_reserve_tilts
    angewandte zielbezogene Logik (years<=3: 100%, 4-7: 50%, >7: 0%)
    zentral wider, damit das Scoring konsistent zur Reserve-Empfehlung
    bleibt.

    Sprint A4 (2026-05-06): Smooth-Decay-Variante via Feature-Flag
    RESERVE_DECAY_MODE=smooth. Default bleibt 'stufen' (audit-konsistent).
    Sprint B5 (2026-05-07): Time-Bucket-Variante via RESERVE_BUCKET_MODE=
    time_bucket — kongruent zu _compute_reserve_for_inputs, damit Scoring
    nicht von der Reserve-Empfehlung abweicht.
    Sprint B6 (2026-05-08): Bedingte Goals — target * (probability_pct/100)
    bevor Mode-Faktor angewandt wird.
    Sprint B3 (2026-05-08): AHV-Goals werden als 'voll erfuellt' gewertet
    (Score 100%): wir liefern den vollen target zurueck, weil die staatliche
    Saeule die Auszahlung deckt — kein Portfolio-Asset noetig.
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _annualize_goal_amount, _goal_projection_years, _norm_text

    goal_type = _norm_text(goal.goal_type)
    if goal_type not in ("Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe"):
        return 0
    base_target = (
        _annualize_goal_amount(goal)
        if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe")
        else int(goal.target_amount_rappen or 0)
    )
    if _goal_pension_state_funded(goal):
        return int(round(base_target * _goal_probability_factor(goal)))
    target_amount = int(round(base_target * _goal_probability_factor(goal)))
    years = _goal_projection_years(goal)
    if _reserve_decay_mode_smooth():
        return int(round(target_amount * _reserve_decay_factor(years)))
    if _reserve_bucket_mode_time_bucket():
        return int(round(target_amount * _time_bucket_reserve_factor(years)))
    # Default Stufenfunktion (Audit-Z2-konsistent)
    if years <= 3:
        return target_amount
    if years <= 7:
        return int(round(target_amount * 0.5))
    return 0


def _compute_reserve_for_inputs(
    *,
    goals: list[Goal],
    limits_prefs: dict,
    asset_class_prefs: dict,
    recurring_net_cashflow_rappen: int,
    recurring_cashflow_projection_series_rappen: list[int],
    advisory_wealth_rappen: int,
    saa_liquidity_ceiling_bps: int,
    reasoning: list[str] | None = None,
    unlocked_other_assets_rappen: int = 0,
    inflow_projection_series_rappen: list[int] | None = None,
) -> tuple[int, int]:
    """C7 StrategyContext: Single Source of Truth fuer Reserve-Berechnung.

    Wird sowohl von ``_apply_goal_and_reserve_tilts`` (generate-Pfad)
    als auch von ``build_target_payload_from_allocation`` (rebuild-Pfad)
    aufgerufen, damit Reserve-Logik nicht zwischen Generierung und
    Wiederaufbau driften kann. Liefert (reserve_needed, external_reserve).

    ``reasoning`` ist optional: wenn vorhanden, werden Erklaerungstexte
    fuer den Berater angehaengt; sonst nur Zahlen berechnet.
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import (
        _annualize_goal_amount,
        _bps,
        _goal_projection_years,
        _norm_text,
        _parse_rappen,
    )

    reserve_candidates: list[int] = [0]
    manual_reserve = _parse_rappen(limits_prefs.get("minReserve"))
    liquidity_target = _parse_rappen(asset_class_prefs.get("liquidityReserveTarget"))
    if manual_reserve:
        reserve_candidates.append(manual_reserve)
    if liquidity_target:
        reserve_candidates.append(liquidity_target)

    near_term_cashflow_series = [int(value or 0) for value in (recurring_cashflow_projection_series_rappen or [])[:3]]
    # Sprint U-P2 Fix H11: Wealth-Inflows (Erbschaft, Bonus, einmalige
    # Verkaufserloese) reduzieren die near_term Reserve wenn sie in den
    # ersten 3 Jahren liegen. Vorher wurden Inflows NUR in
    # cashflow_projection_series_rappen (fuer Goal-Achievement + MC) addiert,
    # aber NICHT in der recurring-Series — Folge: Erbschaft erhoehte
    # Goal-Achievement aber reduzierte reserve_needed nicht. Jetzt mit-
    # subtrahiert (wirkt wie zusaetzlicher Net-Inflow).
    near_term_inflow_series = [
        max(0, int(value or 0))
        for value in (inflow_projection_series_rappen or [])[:3]
    ]
    near_term_inflows = sum(near_term_inflow_series)
    # 2026-07-24 (RES-1, Formel-Audit): Running-Minimum statt reiner Endsumme.
    # Vorher: max(0, -sum(series) - inflows) -- das misst nur den kumulativen
    # STAND NACH dem letzten Jahr, nicht den TIEFSTEN Punkt dazwischen. Bei
    # einer gemischten Serie (z.B. -50k/+40k/-10k) ergibt die Endsumme -20k,
    # obwohl der tatsaechliche Tiefpunkt bereits in Jahr 1 bei -50k liegt --
    # der Kunde braucht dort mehr Liquiditaet als die Endsumme nahelegt, sonst
    # droht ein Notverkauf zum unguenstigen Zeitpunkt. Fix: kumulative
    # Partialsummen ueber die Jahre bilden, den tiefsten Punkt (running min,
    # nie ueber 0) nehmen. Ist die Serie monoton (Mehrheit der Faelle), ist
    # der tiefste Punkt = die Endsumme -> identisches Verhalten wie vorher.
    # In JEDEM Fall gilt: running_min <= end_sum, also kann dieser Fix die
    # empfohlene Reserve nur erhoehen oder gleich lassen, nie senken.
    cumulative = 0
    running_min = 0
    for idx, cashflow_value in enumerate(near_term_cashflow_series):
        cumulative += cashflow_value + (near_term_inflow_series[idx] if idx < len(near_term_inflow_series) else 0)
        running_min = min(running_min, cumulative)
    near_term_shortfall_rappen = max(0, -running_min)
    cashflow_liquidity_component = 0
    if near_term_shortfall_rappen > 0:
        cashflow_liquidity_component = near_term_shortfall_rappen
        if reasoning is not None:
            reasoning.append("Zeitlich datierte Netto-Cashflows erhoehen die erforderliche Liquiditaetsreserve fuer die naechsten Jahre.")
    elif recurring_net_cashflow_rappen < 0 and near_term_inflows <= 0:
        cashflow_liquidity_component = abs(recurring_net_cashflow_rappen) * 3
        if reasoning is not None:
            reasoning.append("Negativer laufender Netto-Cashflow erhoeht die erforderliche Liquiditaetsreserve.")

    # #AA-8 Fix (2026-06-12): Spending-Goal-Reserven SUMMIEREN sich untereinander
    # (mehrere gleichzeitige Nahziele = additiver Liquiditaetsbedarf), statt via
    # max() zu konkurrieren (vorher: nur das groesste Ziel zaehlte -> systematische
    # Unterreservierung). Floor-Kandidaten (manuelle/Liquiditaets-Reserve,
    # Cashflow-Shortfall) bleiben max()-kombiniert.
    goal_reserve_sum: int = 0
    for goal in goals:
        years = _goal_projection_years(goal)
        goal_type = _norm_text(goal.goal_type)
        if goal_type in ("Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe"):
            # Sprint B3: AHV-Goals sind staatlich gedeckt -> kein Reserve-Beitrag
            # aus dem Beratungsportfolio. Reasoning erklaert die Auslassung.
            if _goal_pension_state_funded(goal):
                if reasoning is not None:
                    pillar = _goal_pension_pillar(goal) or "AHV"
                    reasoning.append(
                        f"Das Ziel '{goal.label}' ist {pillar}-finanziert (staatliche Saeule) "
                        "und benoetigt keine Liquiditaetsreserve aus dem Beratungsmandat."
                    )
                continue
            base_target = (
                _annualize_goal_amount(goal)
                if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe")
                else int(goal.target_amount_rappen or 0)
            )
            # Sprint B6: bedingte Goals werden linear gewichtet (target * prob/100).
            prob_factor = _goal_probability_factor(goal)
            target_amount = int(round(base_target * prob_factor))
            if reasoning is not None and prob_factor < 1.0 and base_target > 0:
                reasoning.append(
                    f"Das Ziel '{goal.label}' ist bedingt mit {int(round(prob_factor*100))}% "
                    "Wahrscheinlichkeit; Reserve-Beitrag entsprechend skaliert."
                )
            # Sprint A4: Smooth-Decay opt-in via RESERVE_DECAY_MODE=smooth.
            # Sprint B5: Time-Bucket opt-in via RESERVE_BUCKET_MODE=time_bucket.
            # Default Stufenfunktion bleibt audit-konsistent.
            if _reserve_decay_mode_smooth():
                factor = _reserve_decay_factor(years)
                reserve_amount = int(round(target_amount * factor))
                if reserve_amount > 0:
                    goal_reserve_sum += reserve_amount
                    if reasoning is not None:
                        reasoning.append(
                            f"Das Ziel '{goal.label}' (in {years}J) traegt zu {factor*100:.0f}% "
                            "zur Liquiditaetsreserve bei (smooth-decay)."
                        )
            elif _reserve_bucket_mode_time_bucket():
                factor = _time_bucket_reserve_factor(years)
                reserve_amount = int(round(target_amount * factor))
                if reserve_amount > 0:
                    goal_reserve_sum += reserve_amount
                    if reasoning is not None:
                        bucket = _time_bucket_label(years)
                        reasoning.append(
                            f"Das Ziel '{goal.label}' faellt in den Zeit-Bucket {bucket} "
                            f"und traegt zu {factor*100:.0f}% zur Liquiditaetsreserve bei."
                        )
            else:
                if years <= 3:
                    goal_reserve_sum += target_amount
                    if reasoning is not None:
                        reasoning.append(f"Das Ziel '{goal.label}' wird als kurzfristiger Liquiditaetsbedarf beruecksichtigt.")
                elif years <= 7:
                    goal_reserve_sum += int(round(target_amount * 0.5))

    # 2026-08-07 (CEO/CFO/CIO-Audit, RES-1-Nachtrag): der Cashflow-
    # Liquiditaetsbedarf (aus geloggten laufenden Ein-/Ausgaben) und der
    # Ziel-Reserve-Bedarf (aus separat erfassten Nahzielen) sind ZWEI
    # UNABHAENGIGE Geldabfluesse -- sie muessen sich ADDIEREN, nicht per
    # max() konkurrieren. Sonst wird bei gleichzeitigem Cashflow-Defizit UND
    # Nahziel systematisch unterreserviert (der Kunde braucht Bargeld fuer
    # BEIDE, nicht nur fuer den groesseren Posten). Nur die reinen Floor-
    # Kandidaten (manuelle Reserve, Liquiditaets-Praeferenz -- beides ein
    # Mindestbetrag, kein zusaetzlicher Geldabfluss) bleiben max()-kombiniert
    # gegen den kombinierten Bedarf.
    computed_liquidity_need = cashflow_liquidity_component + goal_reserve_sum
    if computed_liquidity_need > 0:
        reserve_candidates.append(computed_liquidity_need)
    reserve_needed_rappen = max(reserve_candidates)
    external_reserve_rappen = 0
    if reserve_needed_rappen <= 0 or advisory_wealth_rappen <= 0:
        return reserve_needed_rappen, 0

    uncapped_required_liquidity_bps = _bps(reserve_needed_rappen, advisory_wealth_rappen)
    if uncapped_required_liquidity_bps > saa_liquidity_ceiling_bps:
        saa_reserve_rappen = int(round(saa_liquidity_ceiling_bps * advisory_wealth_rappen / 10000))
        external_reserve_rappen = max(0, reserve_needed_rappen - saa_reserve_rappen)
        # Sprint B2: Anderes-Vermoegen-Schloss reduziert die externe Reserve,
        # weil verfuegbares 'anderes Vermoegen' den Reserve-Bedarf decken kann.
        unlocked = max(0, int(unlocked_other_assets_rappen or 0))
        if unlocked > 0 and external_reserve_rappen > 0:
            absorbed = min(unlocked, external_reserve_rappen)
            external_reserve_rappen = max(0, external_reserve_rappen - absorbed)
            if reasoning is not None and absorbed > 0:
                chf_unlocked = absorbed // 100
                reasoning.append(
                    f"Anderes Vermoegen mit Goal-Funding-Schloss (CHF {chf_unlocked:,}) "
                    "deckt einen Teil des externen Reservebedarfs."
                )
        if reasoning is not None and external_reserve_rappen > 0:
            chf_external = external_reserve_rappen // 100
            reasoning.append(
                f"Ein Liquiditaetsbedarf von CHF {chf_external:,} wird als externe Reserve ausserhalb "
                f"des Beratungsmandats empfohlen. Die SAA-Liquiditaet bleibt auf {saa_liquidity_ceiling_bps / 100:.1f}%."
            )
        # 2026-07-24 (RES-2, Formel-Audit): external_reserve_rappen war bisher
        # ungecappt gegen advisory_wealth_rappen. Bei mehreren summierten
        # Nahzielen (#AA-8) oder einem hohen manuellen Reserve-Override kann
        # der berechnete Bedarf das GESAMTE Beratungsvermoegen uebersteigen ->
        # investable_advisory_wealth_rappen faellt auf 0, die SOLL-Simulation
        # laeuft mit Start=0, und das Frontend schlaegt eine externe Reserve
        # oben auf die SOLL-Kurve, die > 100% des Vermoegens waere -- ohne
        # jede Warnung an den Berater. Fix: hart auf advisory_wealth_rappen
        # cappen + Warnung, damit die Deckungsluecke sichtbar bleibt statt
        # sich in einer unplausiblen Kennzahl zu verstecken.
        if external_reserve_rappen > advisory_wealth_rappen:
            if reasoning is not None:
                chf_needed = reserve_needed_rappen // 100
                chf_available = advisory_wealth_rappen // 100
                reasoning.append(
                    f"Der berechnete Liquiditaetsbedarf (CHF {chf_needed:,}) uebersteigt das "
                    f"gesamte Beratungsvermoegen (CHF {chf_available:,}) -- nicht alle Nahziele "
                    "sind aus diesem Mandat allein deckbar. Die externe Reserve wird auf das "
                    "verfuegbare Vermoegen begrenzt; die Deckungsluecke muss ausserhalb des "
                    "Mandats geschlossen werden (z.B. anderes Vermoegen, zusaetzliches Sparen)."
                )
            external_reserve_rappen = advisory_wealth_rappen

    return reserve_needed_rappen, external_reserve_rappen


# --------------------------------------------------------------------------
# Compat-Wrapper aus rp-ueberarbeitung — Tests in test_portfolio_engine_regressions
# importieren diese Namen direkt. Audit-master/Optimizer haben die zentrale
# Logik in _compute_reserve_for_inputs + _strategy_drift_warnings konsolidiert.
# --------------------------------------------------------------------------
def _compute_reserve_requirements(
    *,
    goals,
    limits_prefs,
    asset_class_prefs,
    recurring_net_cashflow_rappen,
    recurring_cashflow_projection_series_rappen,
    advisory_wealth_rappen,
    saa_liq_ceiling_bps,
    reasoning=None,
):
    return _compute_reserve_for_inputs(
        goals=goals,
        limits_prefs=limits_prefs,
        asset_class_prefs=asset_class_prefs,
        recurring_net_cashflow_rappen=recurring_net_cashflow_rappen,
        recurring_cashflow_projection_series_rappen=recurring_cashflow_projection_series_rappen,
        advisory_wealth_rappen=advisory_wealth_rappen,
        saa_liquidity_ceiling_bps=saa_liq_ceiling_bps,
        reasoning=reasoning,
    )
