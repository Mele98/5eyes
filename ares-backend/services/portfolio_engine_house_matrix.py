"""ADR-014, Schritt 8 (letzter Schritt): House-Matrix/Tilt-Cluster, extrahiert
aus `services/portfolio_engine.py` (God-Modul-Split, Welle 3.2).

Reine Datei-Grenz-Verschiebung, 0 Zeilen Fachlogik-Aenderung: die 24
Funktionen unten sind Byte-fuer-Byte-Kopien ihrer vormaligen Definitionen in
`portfolio_engine.py`. Extraktion per Python-`ast`-Funktions-Span-Analyse
(nicht per Zeilennummer-Heuristik) durchgefuehrt -- diese Methode wurde
eingefuehrt, nachdem zwei fruehere Schritte (5 und 7) durch manuelle
Zeilennummer-Grenzen echte Fehler produzierten (Schritt 5: 2 unbeteiligte
Payload-Bau-Funktionen versehentlich mitgeloescht, weil Kontiguitaet
faelschlich angenommen wurde; Schritt 7: ein Kontiguitaets-Scan, der nur
`def`-Zeilen prueft, uebersah Import-Re-Export-Bloecke aus Schritten 3+5,
die mitten im geplanten Loeschbereich standen). Beide wurden vom
Golden-Snapshot-Test sofort gefangen, zurueckgesetzt und korrekt neu gemacht.

Dies ist laut ADR-014 der am staerksten verflochtene Cluster ("Hoch"-Risiko):
1. `_apply_goal_and_reserve_tilts` ruft direkt in den Reserve-Cluster
   (`_compute_reserve_for_inputs`, Schritt 4) -- die zentrale Cross-Bucket-
   Bruecke Reserve -> House-Matrix.
2. `_build_sub_allocations`/`_apply_illiquid_cap`/
   `_enrich_sub_allocations_with_risk` werden im Haupt-Orchestrator
   `generate_target_allocation` in einer 3-stufigen Risk-Budget-
   Eskalationskaskade mit unterschiedlichen Zwischenzustaenden aufgerufen
   (verifiziert: je 3 Call-Sites in der Kaskade + 1 weiterer in
   `build_target_payload_from_allocation`, insgesamt 4).
3. Zwei Namen (`_house_matrix_or_default`, `_baseline_target_bands`) werden
   extern importiert -- nicht nur von `services/backtest_ab.py` (ADR-014s
   eigene Liste), sondern auch von `routers/wealth.py`
   (`calculate_max_pension_spending`), das zusaetzlich `_build_sub_allocations`,
   `_enrich_sub_allocations_with_risk` und `_building_block_risky_map` direkt
   importiert -- ein Fund, der beim Draften dieses Schritts gemacht wurde,
   nicht im urspruenglichen ADR-014 gelistet.

Kontiguitaets-Scan (per `ast`, ueber den gesamten Bereich Zeile 613-2492 vor
dieser Extraktion): die 24 Zielfunktionen liegen NICHT als ein Block, sondern
mit mehreren bereits bekannten Interlopern/Re-Exports durchsetzt, die
bewusst UNVERAENDERT in `portfolio_engine.py` bleiben: `_resolve_jurisdiction_
context` (CORE), die Re-Export-Bloecke aus Schritt 3 (CMA) und Schritt 5
(MC-Simulation), diverse Payload-Bau/Goal-Metadaten-Funktionen (Schritt 7,
z.B. `_goal_hardness_key`, `_goal_projection_years`) sowie mehrere CORE-
Referenzdaten-Bootstrap-Funktionen (u.a. `_ensure_runtime_reference_data_ch`,
die zwei der von House-Matrix-bezogenen Text-Scan-Tests gepruefte
Literal-Bloecke enthaelt -- siehe unten). Die AST-Span-Methode extrahiert
exakt die 24 Ziel-`def`s unabhaengig davon, was dazwischen steht.

Text-Scan-Test-Pruefung (Lektion aus Schritt 5/6/7): 5 Testdateien wurden
identifiziert, die `portfolio_engine.py` als Roh-Text lesen und Muster mit
House-Matrix-Bezug pruefen (`test_bb_risky_fractions_audit.py`,
`test_house_matrix_risk_budget_consistency.py`,
`test_house_matrix_yaml_loader.py`, `test_liquidity_cascade_warning.py`,
`test_liquidity_hard_cap_in_fallback.py`). Alle 5 wurden verifiziert: ihre
geprueften String-Muster (`building_blocks = [`,
`_normalize_house_matrix_defaults([`, `_SAA_LIQUIDITY_HARD_CAP_BPS: int = 300`,
`hard_capped = max(`, etc.) liegen ausschliesslich in
`_ensure_runtime_reference_data_ch` (CORE, Referenzdaten-Bootstrap) oder im
Haupt-Orchestrator `generate_target_allocation` -- BEIDE bleiben unveraendert
in `portfolio_engine.py`. Keine dieser 5 Testdateien ist von dieser
Extraktion betroffen (false positives beim initialen breiten Grep).

Zirkular-Import-Haertung (identisches Muster zu den Schritten 1-7): CORE-
Namen aus `services.portfolio_engine` (`_norm_text`, `_bucket_key`,
`_coerce_band_bps`, `BUCKET_LABELS`, `BUCKET_FIELDS`,
`DEFAULT_ASSET_RISKY_WEIGHTS_BPS`, `_normalize_preferences`,
`ALLOWED_HOUSE_MATRIX_PROFILES`, `_ILLIQUID_SUB_ASSET_CLASSES`,
`_SAA_LIQUIDITY_HARD_CAP_BPS`, `_bps`) sowie bereits extrahierte
Cross-Cluster-Namen (`_goal_hardness_key`/`_goal_projection_years` aus
Schritt 7, `_resolve_home_equity_label` aus Schritt 3,
`_compute_reserve_for_inputs` aus Schritt 4 -- alle ueber den bestehenden
Re-Export von `services.portfolio_engine` erreichbar) werden function-local
(lazy) importiert, NIE auf Modul-Ebene. `DEFAULT_ASSET_RISKY_WEIGHTS_BPS`
und `_ILLIQUID_SUB_ASSET_CLASSES` sind zwar Cluster-exklusiv genutzte
Konstanten, bleiben aber bewusst in `portfolio_engine.py` (statt mitzuziehen)
-- geringeres Risiko fuer den hoechst-riskanten Schritt, per Lazy-Import
zurueckgeholt statt dupliziert.

Modelle (`HouseMatrix`, `BuildingBlock`, `OptimizerPolicy`),
`services.jurisdiction.*`-Funktionen/Konstanten und `database.new_uuid`
haengen NICHT von `services.portfolio_engine` ab und werden daher normal
auf Modul-Ebene importiert (kein Zyklus moeglich). `Goal`/`Mandate`/
`HouseMatrix` in reinen Typ-Hinweisen laufen ueber `from __future__ import
annotations` + `TYPE_CHECKING`, wo kein echter Laufzeit-Gebrauch vorliegt.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from database import new_uuid
from models.allocation import BuildingBlock, HouseMatrix, OptimizerPolicy
from services.jurisdiction.de_seed import (
    DE_DEFAULT_BONDS_DURATION,
    DE_DEFAULT_EQUITIES_GEO,
    DE_DEFAULT_REALESTATE_MARKET,
)
from services.jurisdiction.resolve import (
    resolve_building_blocks_for_jurisdiction,
    resolve_home_bias_defaults,
)

if TYPE_CHECKING:
    from models.wealth import Goal


def _building_block_risky_map(
    db: Session,
    policy_id: str,
    investment_universe: str | None = None,
    jurisdiction: str | None = "CH",
) -> dict[tuple[str, str], int]:
    """Sprint B4 (2026-05-07): respektiert mandate.investment_universe.

    Wenn ein Universum gewaehlt ist und BuildingBlocks fuer dieses Universum
    existieren, werden NUR diese geladen. Sonst Fallback auf alle aktiven BBs
    (backwards-compat fuer bestehende Mandate ohne explizite Universum-Wahl).

    WP-A (2026-08-01, Risky-Fraction-Gewichtung jurisdiktions-bewusst):
    jurisdiction wird 1:1 an _building_block_rows_for_policy() durchgereicht,
    siehe dort fuer die CH-vs-Nicht-CH-Semantik.
    """
    from services.portfolio_engine import _norm_text

    rows = _building_block_rows_for_policy(db, policy_id, investment_universe, jurisdiction)
    return {
        (_norm_text(row.asset_class), _norm_text(row.sub_asset_class)): int(row.risky_fraction_bps or 0)
        for row in rows
    }


def _building_block_rows_for_policy(
    db: Session,
    policy_id: str,
    investment_universe: str | None = None,
    jurisdiction: str | None = "CH",
) -> list[BuildingBlock]:
    """Laedt die aktiven BuildingBlock-Zeilen einer Policy fuer die
    Risky-Fraction-Gewichtung.

    WP-A (2026-08-01, Risky-Fraction-Gewichtung jurisdiktions-bewusst):
    - jurisdiction in (None, "CH") (Default, Constraint 1 der Welle):
      EXAKT die heutige Query/Fallback-Logik -- KEIN BuildingBlock.jurisdiction-
      Filter, byte-identisch zum Bestandsverhalten (Golden-Snapshot-Beweis).
    - andere jurisdiction: delegiert an
      services.jurisdiction.resolve.resolve_building_blocks_for_jurisdiction(),
      damit die dortige Fail-Fast-Semantik (leeres Ergebnis fuer diese
      Jurisdiktion+Policy -> JurisdictionReferenceDataMissingError statt
      stillschweigend 0 oder — schlimmer — CH+DE gemischte Gewichte) auch
      fuer die tatsaechliche Risky-Fraction-Berechnung gilt, nicht nur fuer
      die bisherige isolierte Validierung in ensure_runtime_reference_data().
    """
    if jurisdiction in (None, "CH"):
        return resolve_building_blocks_for_jurisdiction(
            db,
            policy_id,
            "CH",
            investment_universe=investment_universe,
        )
    return resolve_building_blocks_for_jurisdiction(
        db, policy_id, jurisdiction, investment_universe=investment_universe,
    )


def _asset_risky_weight_fallbacks() -> dict[str, int]:
    from services.portfolio_engine import DEFAULT_ASSET_RISKY_WEIGHTS_BPS

    return DEFAULT_ASSET_RISKY_WEIGHTS_BPS.copy()


def _apply_band_preferences(
    bands: dict | None,
    targets: dict[str, int],
    minimums: dict[str, int],
    maximums: dict[str, int],
    reasoning: list[str],
    *,
    warnings: list[dict] | None = None,
    house_profile: str | None = None,
    score_bucket: int | None = None,
) -> None:
    """Applies a bands override, keeping hard Bounds and Target Intent
    orthogonal (CERT-ALLOCATION-INTENT-001 / BAND-PARTIAL-OVERRIDE-001).

    `min_bps`/`max_bps` are independent hard constraints: they are validated
    against each other (0 <= min <= max <= 10000), NEVER against a stale
    baseline `target_bps` the advisor did not even send in this request. A
    bucket without an EXPLICIT `target_bps` in `bands` has no Target Intent
    at all -- its pre-existing `targets[bucket]` value is treated purely as
    a technical feasible seed (clamped into the possibly-narrowed bounds),
    not as a published Soll/preference. Whether the resulting bounds can
    actually be rebalanced to exactly 10000 bps is `_rebalance_to_total()`'s
    job (called by every real caller right after this function, and already
    raising its own clear error for a genuinely infeasible envelope) -- this
    function only applies the delta and the per-bucket sanity that is
    independent of what the OTHER buckets' bounds happen to be.

    A bucket WITH an explicit `target_bps` is a genuine advisor-stated Soft
    Preference and must itself respect that bucket's own (possibly just-
    overridden) bounds -- violating that is a real, reported conflict, never
    silently clamped away.

    BAND-OVERRIDE-DISCLOSURE-001 (Audit 2026-10-14):
    - F-BAND-1: die Bounds beim Eintritt sind die (policy-bereinigte)
      Hausmatrix-Bandbreite des Risikoprofils -- der Eignungsrahmen. Ein
      Berater-Band, das diesen Rahmen verlaesst, bleibt erlaubt, wird aber
      wie ``policy_band_clamp_notes()`` im Reasoning und -- falls
      ``warnings`` uebergeben -- als ``WARN_BAND_OUTSIDE_HOUSE_MATRIX``
      ausgewiesen.
    - F-BAND-3: ist der Bounds-Satz unerfuellbar, nennt der Fehler auf
      Deutsch, WELCHE Grenze vom Berater und welche aus der Hausmatrix
      stammt. ``_rebalance_to_total()`` wuerde fuer diesen Fall (Summe der
      Minima > 100 %; nachfolgende Schritte heben Minima nur an) ohnehin
      werfen, aber nur mit einem internen englischen Text. Exception-Typ
      bleibt ValueError.
    """
    from services.portfolio_engine import BUCKET_FIELDS, BUCKET_LABELS, _bucket_key, _coerce_band_bps

    if not bands:
        return
    house_minimums = {key: int(minimums[key]) for key in BUCKET_FIELDS}
    house_maximums = {key: int(maximums[key]) for key in BUCKET_FIELDS}
    advisor_min_buckets: set[str] = set()
    advisor_max_buckets: set[str] = set()
    applied = []
    explicit_target_buckets: set[str] = set()
    for raw_key, override in bands.items():
        bucket = _bucket_key(raw_key)
        if not bucket or not isinstance(override, dict):
            continue
        minimum = _coerce_band_bps(override.get("min_bps"))
        target = _coerce_band_bps(override.get("target_bps"))
        maximum = _coerce_band_bps(override.get("max_bps"))
        if minimum is not None:
            minimums[bucket] = minimum
            advisor_min_buckets.add(bucket)
        if maximum is not None:
            maximums[bucket] = maximum
            advisor_max_buckets.add(bucket)
        if target is not None:
            targets[bucket] = target
            explicit_target_buckets.add(bucket)
        applied.append(BUCKET_LABELS[bucket])
    if not applied:
        return

    # Hard bounds are orthogonal to Target Intent: per-bucket sanity,
    # independent of any target value and of what other buckets' bounds are
    # (spec Sec. 6.2). Cross-bucket sum-to-10000 feasibility is enforced by
    # `_rebalance_to_total()` downstream, where it belongs: that is the step
    # that actually needs the full bounds set to produce a concrete 10000-bps
    # allocation, and it already fails loudly (no silent fallback) if none
    # exists.
    for key in BUCKET_FIELDS:
        minimum, maximum = minimums[key], maximums[key]
        if minimum < 0 or maximum > 10000:
            raise ValueError(
                f"Bandbreiten fuer {BUCKET_LABELS[key]} sind inkonsistent: "
                f"Min {minimum} / Max {maximum} (0..10000 bps, Min darf Max nicht ueberschreiten)."
            )
        if minimum > maximum:
            # F-BAND-3: benennen, woher jede der beiden Grenzen stammt -- ein
            # "Min 500 / Max 0" fuer ein Minimum, das der Berater nie gesetzt
            # hat, ist nicht nachvollziehbar.
            min_source = (
                "das Berater-Minimum" if key in advisor_min_buckets
                else "das Hausmatrix-Minimum des Risikoprofils"
            )
            max_source = (
                "dem Berater-Maximum" if key in advisor_max_buckets
                else "dem Hausmatrix-Maximum des Risikoprofils"
            )
            hint = ""
            if key not in advisor_min_buckets:
                hint = (
                    " Soll die Anlageklasse tiefer gewichtet oder ausgeschlossen "
                    "werden, ist auch das Minimum als Berater-Vorgabe zu setzen; "
                    "die Abweichung von der Hausmatrix wird dann offengelegt."
                )
            raise ValueError(
                f"Bandbreiten fuer {BUCKET_LABELS[key]} sind nicht vereinbar: "
                f"{min_source} von {_band_pct(minimum)} % liegt ueber "
                f"{max_source} von {_band_pct(maximum)} %.{hint}"
            )

    # A bucket with an EXPLICIT Target Intent must itself respect that same
    # bucket's bounds -- a real advisor-stated conflict, reported as such.
    for key in explicit_target_buckets:
        if not (minimums[key] <= targets[key] <= maximums[key]):
            raise ValueError(
                f"Bandbreiten fuer {BUCKET_LABELS[key]} sind inkonsistent: "
                f"Min {minimums[key]} / Ziel {targets[key]} / Max {maximums[key]}."
            )

    # F-BAND-3: cross-bucket envelope, explained in German with provenance
    # (same ValueError type; see docstring for why this is no new rule).
    _raise_if_band_envelope_infeasible(
        minimums,
        advisor_min_buckets=advisor_min_buckets,
    )

    # Every OTHER bucket keeps no Target Intent at all: its carried-over
    # value is only a feasible seed for the deterministic rebalance every
    # caller runs afterwards, clamped into the (possibly narrowed) bounds so
    # it is itself a valid starting point -- never published as a Soll.
    for key in BUCKET_FIELDS:
        if key not in explicit_target_buckets:
            targets[key] = max(minimums[key], min(maximums[key], targets[key]))

    if explicit_target_buckets == set(BUCKET_FIELDS):
        # A FULL explicit Target Intent set is itself a complete allocation
        # and must sum to exactly 10000 bps (spec Sec. 6.3) -- unlike a
        # partial Soft Preference, which legitimately need not.
        total = sum(int(targets[key]) for key in BUCKET_FIELDS)
        if total != 10000:
            raise ValueError(f"Mandatsspezifische Zielquoten muessen 100% ergeben (aktuell {total / 100:.2f}%).")
    reasoning.append("Mandatsspezifische Soll-Quoten und Bandbreiten werden als Simulations-Constraint beruecksichtigt.")

    # F-BAND-1: jede Mandatsbandbreite ausserhalb der Hausmatrix-Bandbreite
    # des Risikoprofils wird offengelegt (Muster policy_band_clamp_notes).
    deviations = advisor_band_house_deviations(bands, house_minimums, house_maximums)
    for deviation in deviations:
        reasoning.append(
            house_band_deviation_note(
                deviation, house_profile=house_profile, score_bucket=score_bucket,
            )
        )
        if warnings is not None:
            from services.allocation_messages import (
                WARN_BAND_OUTSIDE_HOUSE_MATRIX,
                format_message,
            )

            warnings.append(format_message(
                WARN_BAND_OUTSIDE_HOUSE_MATRIX,
                bucket_label=deviation["bucket_label"],
                mandate_min=_band_pct(deviation["mandate_min_bps"]),
                mandate_max=_band_pct(deviation["mandate_max_bps"]),
                house_min=_band_pct(deviation["house_min_bps"]),
                house_max=_band_pct(deviation["house_max_bps"]),
                profile_label=house_profile or "unbekannt",
                score_bucket=score_bucket if score_bucket is not None else "?",
            ))


def _band_pct(bps: int) -> str:
    return f"{int(bps) / 100:.2f}"


def _raise_if_band_envelope_infeasible(
    minimums: dict[str, int],
    *,
    advisor_min_buckets: set[str],
) -> None:
    """BAND-OVERRIDE-DISCLOSURE-001 (F-BAND-3): deutsche, bucket-genaue
    Erklaerung fuer einen unerfuellbaren Bounds-Satz.

    Eine Summe der Minima ueber 100 % laesst ``_rebalance_to_total()`` in
    jedem Fall scheitern -- alle nachfolgenden Schritte (Tilts, globale
    Caps/Floors, Reserve) heben Minima hoechstens an. Dort fehlt aber die
    Herkunft der Grenzen (Berater vs. Hausmatrix).

    Bewusst NICHT geprueft: Summe der Maxima unter 100 %. Die Liquiditaets-
    Obergrenze kann danach noch angehoben werden (Reserve-Normierung,
    Liquiditaets-Eskalation); eine Vorab-Pruefung wuerde heute erfolgreiche
    Allokationen ablehnen.
    """
    from services.portfolio_engine import BUCKET_FIELDS, BUCKET_LABELS

    total_min = sum(int(minimums[key]) for key in BUCKET_FIELDS)
    if total_min > 10000:
        parts = [
            f"{BUCKET_LABELS[key]} {_band_pct(minimums[key])} % "
            f"({'Berater-Vorgabe' if key in advisor_min_buckets else 'Hausmatrix-Minimum'})"
            for key in BUCKET_FIELDS
            if int(minimums[key]) > 0
        ]
        raise ValueError(
            f"Die Mindestquoten summieren sich auf {_band_pct(total_min)} % "
            f"({', '.join(parts)}) und uebersteigen 100 %. Bitte die "
            "Berater-Vorgaben so anpassen, dass die Mindestquoten zusammen "
            "hoechstens 100 % ergeben."
        )


def _disclose_global_cap_clamp(
    bucket: str,
    requested_max_bps: int,
    cap_bps: int,
    reasoning: list[str],
    warnings: list,
) -> None:
    """BAND-OVERRIDE-DISCLOSURE-001 (F-BAND-2): Klemmung auf die globale
    Modell-Obergrenze offenlegen.

    Die Klemmung war lautlos -- ein Berater-Maximum/-Ziel von 30 % Alternative
    endete ohne Hinweis bei 10 %. Der Aufrufer ruft dies nur, wenn das Modell
    die aktive Allokation stellt; im Shadow-Modus betrifft die Klemmung nur
    den Vergleichskandidaten. Ohne Klemmung (``requested_max_bps <= cap_bps``)
    passiert nichts.
    """
    from services.allocation_messages import WARN_GLOBAL_CAP_CLAMP, format_message
    from services.portfolio_engine import BUCKET_LABELS

    if requested_max_bps <= cap_bps:
        return
    bucket_label = BUCKET_LABELS.get(bucket, bucket)
    reasoning.append(
        f"{bucket_label}: Die vorgegebene Obergrenze von "
        f"{requested_max_bps / 100:.2f} % wurde auf die globale "
        f"Modell-Obergrenze von {cap_bps / 100:.2f} % begrenzt."
    )
    warnings.append(format_message(
        WARN_GLOBAL_CAP_CLAMP,
        bucket_label=bucket_label,
        requested_max=f"{requested_max_bps / 100:.2f}",
        cap=f"{cap_bps / 100:.2f}",
    ))


def advisor_band_house_deviations(
    bands: dict | None,
    house_minimums: dict[str, int],
    house_maximums: dict[str, int],
) -> list[dict]:
    """BAND-OVERRIDE-DISCLOSURE-001 (F-BAND-1): Buckets, deren vom Berater
    gesetzte Mandatsbandbreite die Hausmatrix-Bandbreite verlaesst.

    Reine Funktion, geteilt zwischen Generate (Reasoning + Warning) und dem
    Freigabe-Gate (``routers/review.py``), damit beide dieselbe Regel lesen.
    Eine Verengung INNERHALB des Hausbands ist keine Abweichung. Nicht
    gesetzte Grenzen eines Buckets erben die Hausmatrix-Grenze.
    """
    from services.portfolio_engine import BUCKET_FIELDS, BUCKET_LABELS, _bucket_key, _coerce_band_bps

    if not isinstance(bands, dict):
        return []
    requested: dict[str, dict[str, int]] = {}
    for raw_key, override in bands.items():
        bucket = _bucket_key(raw_key)
        if not bucket or not isinstance(override, dict):
            continue
        entry = requested.setdefault(bucket, {})
        minimum = _coerce_band_bps(override.get("min_bps"))
        maximum = _coerce_band_bps(override.get("max_bps"))
        if minimum is not None:
            entry["min"] = int(minimum)
        if maximum is not None:
            entry["max"] = int(maximum)
    deviations: list[dict] = []
    for bucket in BUCKET_FIELDS:
        entry = requested.get(bucket)
        if not entry:
            continue
        house_min = int(house_minimums[bucket])
        house_max = int(house_maximums[bucket])
        mandate_min = int(entry.get("min", house_min))
        mandate_max = int(entry.get("max", house_max))
        if house_min <= mandate_min and mandate_max <= house_max:
            continue
        deviations.append({
            "bucket": bucket,
            "bucket_label": BUCKET_LABELS[bucket],
            "house_min_bps": house_min,
            "house_max_bps": house_max,
            "mandate_min_bps": mandate_min,
            "mandate_max_bps": mandate_max,
        })
    return deviations


def house_band_deviation_note(
    deviation: dict,
    *,
    house_profile: str | None,
    score_bucket: int | None,
) -> str:
    profile = house_profile or "unbekannt"
    score = score_bucket if score_bucket is not None else "?"
    return (
        f"{deviation['bucket_label']}: Mandatsbandbreite "
        f"{_band_pct(deviation['mandate_min_bps'])} % bis "
        f"{_band_pct(deviation['mandate_max_bps'])} % liegt ausserhalb der "
        f"Hausmatrix-Bandbreite {_band_pct(deviation['house_min_bps'])} % bis "
        f"{_band_pct(deviation['house_max_bps'])} % fuer Score {score} "
        f"({profile}); die Allokation kann damit den Eignungsrahmen des "
        "Risikoprofils verlassen."
    )


def house_band_deviation_disclosure_for_allocation(
    db: Session,
    allocation,
    assessment,
    policy: OptimizerPolicy,
) -> dict:
    """BAND-DEVIATION-REASON-REQUIRED-001: eine Quelle fuer Freigabe-Gate
    und Kundendokumente.

    Liest den persistierten Praeferenz-Snapshot der Soll-Allokation (nie die
    Live-Praeferenzen) und liefert:

    - ``deviations``: strukturierte Abweichungen je Bucket
      (``advisor_band_house_deviations``),
    - ``notes``: Berater-Hinweistexte (``house_band_deviation_note``),
    - ``profile`` / ``score_bucket``: Hausmatrix-Profil des Ankers,
    - ``reason``: die dokumentierte Begruendung (``bandDeviationReason``)
      oder ``None``.
    """
    from services.portfolio_engine import (
        _allocation_snapshot_preferences,
        _house_matrix_or_default,
        _risk_score_bucket,
    )

    prefs = _allocation_snapshot_preferences(allocation) or {}
    bands = prefs.get("bands") if isinstance(prefs, dict) else None
    raw_reason = prefs.get("bandDeviationReason") if isinstance(prefs, dict) else None
    reason = str(raw_reason).strip() if isinstance(raw_reason, str) and raw_reason.strip() else None
    empty = {
        "deviations": [],
        "notes": [],
        "profile": None,
        "score_bucket": None,
        "reason": reason,
    }
    if not bands:
        return empty
    score_bucket = _risk_score_bucket(assessment)
    house_matrix = _house_matrix_or_default(db, policy, score_bucket)
    _targets, house_minimums, house_maximums = _baseline_target_bands(house_matrix, policy)
    deviations = advisor_band_house_deviations(bands, house_minimums, house_maximums)
    return {
        "deviations": deviations,
        "notes": [
            house_band_deviation_note(
                deviation,
                house_profile=house_matrix.profile_name,
                score_bucket=score_bucket,
            )
            for deviation in deviations
        ],
        "profile": house_matrix.profile_name,
        "score_bucket": score_bucket,
        "reason": reason,
    }


def house_matrix_bands_payload(house_matrix: HouseMatrix, policy: OptimizerPolicy) -> dict:
    """BAND-DEVIATION-REASON-REQUIRED-001: die (policy-bereinigte)
    Hausmatrix-Bandbreite je Bucket fuer den Bandbreiten-Editor. Die
    Bucket-Bandbreite im Payload ist nach einem Override bereits die
    Mandatsbandbreite und taugt daher nicht als Vergleichsbasis."""
    from services.portfolio_engine import BUCKET_FIELDS

    _targets, minimums, maximums = _baseline_target_bands(house_matrix, policy)
    return {
        key: {"min_bps": int(minimums[key]), "max_bps": int(maximums[key])}
        for key in BUCKET_FIELDS
    }


def _apply_band_min_max_overrides(
    bands: dict | None,
    minimums: dict[str, int],
    maximums: dict[str, int],
) -> bool:
    """Wendet NUR die harten Mindest-/Maximalgrenzen (min_bps/max_bps) eines
    Bandbreiten-Overrides an, OHNE target_bps und OHNE die
    Summe-muss-10000-Validierung von `_apply_band_preferences`.

    Sicherheits-Fix (2026-08-03): wird verwendet, wenn der Risikobudget-
    Fallback `targets`/`minimums`/`maximums` per `_house_matrix_mid_targets`
    komplett auf die Haus-Matrix-Bandbreiten-Mitte zuruecksetzt. Vorher ging
    dabei eine bereits erfolgreich per `_apply_band_preferences` angewendete
    Mandats-Restriktion (z.B. "Aktien max. 20%") stillschweigend verloren --
    der Reset ersetzte minimums/maximums komplett durch die Haus-Matrix-
    Defaults, ohne den Override erneut anzuwenden (live reproduziert:
    Berater-Maximum 2000 bps, Endresultat 3500 bps, keine Warnung).

    Warum NICHT einfach `_apply_band_preferences` erneut aufrufen: dessen
    Summe-10000-Validierung bezieht sich auf `targets`, die bereits von der
    NEUEN Haus-Matrix-Mitte stammen -- ein `target_bps`-Override, der beim
    ERSTEN Aufruf (gegen die urspruengliche Baseline) exakt auf 10000 bps
    aufging, kann nach einem Baseline-Wechsel eine andere, dann invalide
    Summe ergeben und wuerde faelschlich einen ValueError werfen, selbst
    wenn der Override selbst unveraendert und weiterhin gueltig ist. Die
    harten Grenzen (min/max) sind dagegen baseline-unabhaengige Invarianten
    (eine vom Berater gesetzte Restriktion wie "nicht mehr als 20%" gilt
    unabhaengig davon, welche Baseline die anderen Buckets gerade haben) und
    werden hier separat, ohne Summen-Constraint, wiederhergestellt. Der
    nachfolgende `_rebalance_to_total()`-Aufruf bringt `targets` unter
    Beachtung dieser (wiederhergestellten) Grenzen wieder auf 10000 bps.

    Returns True, wenn mindestens eine Grenze wiederhergestellt wurde (fuer
    einen praezisen Reasoning-Hinweis beim Aufrufer).
    """
    from services.portfolio_engine import _bucket_key, _coerce_band_bps

    if not bands:
        return False
    restored = False
    for raw_key, override in (bands or {}).items():
        bucket = _bucket_key(raw_key)
        if not bucket or not isinstance(override, dict):
            continue
        minimum = _coerce_band_bps(override.get("min_bps"))
        maximum = _coerce_band_bps(override.get("max_bps"))
        if minimum is not None:
            minimums[bucket] = minimum
            restored = True
        if maximum is not None:
            maximums[bucket] = maximum
            restored = True
    return restored


def _has_manual_target_overrides(bands: dict | None) -> bool:
    from services.portfolio_engine import _coerce_band_bps

    if not isinstance(bands, dict):
        return False
    return any(
        isinstance(override, dict) and _coerce_band_bps(override.get("target_bps")) is not None
        for override in bands.values()
    )


def _rebalance_to_total(targets: dict[str, int], minimums: dict[str, int], maximums: dict[str, int]) -> dict[str, int]:
    from services.portfolio_engine import BUCKET_FIELDS

    adjusted = {key: int(targets[key]) for key in BUCKET_FIELDS}
    for key in BUCKET_FIELDS:
        adjusted[key] = max(minimums[key], min(maximums[key], adjusted[key]))

    def _room_up(name: str) -> int:
        return maximums[name] - adjusted[name]

    def _room_down(name: str) -> int:
        return adjusted[name] - minimums[name]

    current_total = sum(adjusted.values())
    delta = 10000 - current_total
    if delta > 0:
        for key in ("bonds", "liquidity", "equities", "real_estate", "alternatives"):
            if delta <= 0:
                break
            step = min(delta, _room_up(key))
            if step > 0:
                adjusted[key] += step
                delta -= step
    elif delta < 0:
        delta = abs(delta)
        for key in ("equities", "alternatives", "real_estate", "bonds", "liquidity"):
            if delta <= 0:
                break
            step = min(delta, _room_down(key))
            if step > 0:
                adjusted[key] -= step
                delta -= step
    final_total = sum(adjusted.values())
    if final_total != 10000:
        raise ValueError(
            f"Target allocation cannot be normalized to 10000 bps within min/max bounds "
            f"(total={final_total}, targets={adjusted})."
        )
    return adjusted


def _enrich_sub_allocations_with_risk(
    sub_allocations: list[dict],
    risky_map: dict[tuple[str, str], int],
) -> tuple[list[dict], dict[str, int], int]:
    from services.portfolio_engine import BUCKET_FIELDS, _bucket_key, _norm_text

    enriched: list[dict] = []
    weighted_totals = {key: 0 for key in BUCKET_FIELDS}
    weight_totals = {key: 0 for key in BUCKET_FIELDS}
    for sub in sub_allocations:
        bucket = _bucket_key(sub.get("asset_class"))
        if not bucket:
            continue
        stored_risky_fraction = sub.get("risky_fraction_bps")
        key = (
            _norm_text(sub.get("asset_class")),
            _norm_text(sub.get("sub_asset_class")),
        )
        raw_risky_fraction = (
            stored_risky_fraction
            if stored_risky_fraction is not None
            else risky_map.get(key)
        )
        if (
            isinstance(raw_risky_fraction, bool)
            or not isinstance(raw_risky_fraction, int)
            or not 0 <= raw_risky_fraction <= 10_000
        ):
            from services.optimizer.constraints import OptimizerInputError

            raise OptimizerInputError(
                "Fuer die verwendete Sub-Asset-Klasse fehlt eine gueltige "
                "BuildingBlock-Risikofraktion (0..10000 bps): "
                f"{key}."
            )
        risky_fraction_bps = raw_risky_fraction
        portfolio_weight = int(sub.get("target_weight_bps") or 0)
        mix_weight = int(
            sub.get("within_bucket_weight_bps")
            if sub.get("within_bucket_weight_bps") is not None
            else portfolio_weight
        )
        weighted_totals[bucket] += mix_weight * int(risky_fraction_bps)
        weight_totals[bucket] += mix_weight
        enriched.append({**sub, "risky_fraction_bps": int(risky_fraction_bps)})
    asset_risky_weights = _asset_risky_weight_fallbacks()
    for bucket in BUCKET_FIELDS:
        if weight_totals[bucket] > 0:
            asset_risky_weights[bucket] = int(round(weighted_totals[bucket] / weight_totals[bucket]))
    portfolio_weights = {bucket: 0 for bucket in BUCKET_FIELDS}
    for row in enriched:
        bucket = _bucket_key(row.get("asset_class"))
        if bucket in portfolio_weights:
            portfolio_weights[bucket] += int(row.get("target_weight_bps") or 0)
    # Round once from the exact integer bucket coefficients. This is the same
    # functional used for solver input, final audit and persistence; summing
    # separately rounded sleeve contributions can differ at a binding cap.
    total_risky_fraction_bps = _risk_budget_from_targets(
        portfolio_weights,
        asset_risky_weights,
    )
    return enriched, asset_risky_weights, total_risky_fraction_bps


def _risk_budget_from_targets(targets: dict[str, int], asset_risky_weights: dict[str, int]) -> int:
    from services.portfolio_engine import BUCKET_FIELDS

    return int(round(sum(int(targets[key]) * int(asset_risky_weights.get(key, 0)) for key in BUCKET_FIELDS) / 10000))


def _enforce_risk_budget(
    targets: dict[str, int],
    minimums: dict[str, int],
    maximums: dict[str, int],
    asset_risky_weights: dict[str, int],
    risk_budget_bps: int,
    allow_best_effort: bool = False,
) -> tuple[dict[str, int], int]:
    from services.portfolio_engine import BUCKET_FIELDS

    adjusted = {key: int(targets[key]) for key in BUCKET_FIELDS}
    current_risk = _risk_budget_from_targets(adjusted, asset_risky_weights)
    loops = 0
    while current_risk > risk_budget_bps and loops < 400:
        loops += 1
        receiver = "bonds" if adjusted["bonds"] < maximums["bonds"] else ("liquidity" if adjusted["liquidity"] < maximums["liquidity"] else None)
        if not receiver:
            break
        receiver_room = maximums[receiver] - adjusted[receiver]
        if receiver_room <= 0:
            break
        donors = [
            key for key in ("equities", "alternatives", "real_estate", "bonds")
            if adjusted[key] > minimums[key] and asset_risky_weights.get(key, 0) > asset_risky_weights.get(receiver, 0)
        ]
        if not donors:
            break
        donor = sorted(
            donors,
            key=lambda key: (asset_risky_weights.get(key, 0), adjusted[key] - minimums[key]),
            reverse=True,
        )[0]
        step = min(100, adjusted[donor] - minimums[donor], receiver_room)
        if step <= 0:
            break
        adjusted[donor] -= step
        adjusted[receiver] += step
        current_risk = _risk_budget_from_targets(adjusted, asset_risky_weights)
    if current_risk > risk_budget_bps:
        if allow_best_effort:
            # Validierung 2026-06-11 (#AA-1): strukturell unerreichbares Budget
            # (Mindestquoten lassen die Risky-Fraction nicht unter den Cap). Statt
            # hart zu werfen die konservativste ERREICHBARE Allokation zurueckgeben;
            # der Aufrufer (letzte Eskalationsstufe) behandelt die Ueberschreitung
            # graceful (Compliance-Warnung) statt die SAA-Generierung abzubrechen.
            return adjusted, current_risk
        overshoot_bps = current_risk - risk_budget_bps
        raise ValueError(
            f"Risikobudget konnte nicht eingehalten werden: "
            f"Ist={current_risk} bps, Limit={risk_budget_bps} bps, "
            f"Überschreitung={overshoot_bps} bps. "
            f"Bitte Mindestquoten der Anlageklassen prüfen oder Kundenprofil korrigieren."
        )
    return adjusted, current_risk


def _growth_goals_for_equity_tilt(goals: list[Goal]) -> list[Goal]:
    from services.portfolio_engine import _goal_hardness_key, _norm_text

    has_hard_protection_goal = any(
        _goal_hardness_key(goal) == "hart"
        and _norm_text(goal.goal_type) in (
            "Kapitalerhalt",
            "Vermoegensziel",
            "Pensionsausgabe",
            "Wiederkehrende_Ausgabe",
        )
        for goal in goals
    )
    eligible = []
    for goal in goals:
        goal_type = _norm_text(goal.goal_type)
        hardness_key = _goal_hardness_key(goal)
        if hardness_key == "opportunistisch":
            continue
        if goal_type in ("Vermoegensziel", "Maximierung"):
            eligible.append(goal)
            continue
        if goal_type == "Renditeziel" and not has_hard_protection_goal:
            eligible.append(goal)
    return eligible


def _normalize_splits(
    splits: list[tuple[str, int, str]],
) -> list[tuple[str, int, str]]:
    """Skaliert Sub-Asset-Class-Splits proportional auf Summe 10000.

    C4: Vor dem Fix wurde nach Filterung (z.B. !bondsHighYield, !noEm)
    der Rest dem letzten Eintrag zugeschlagen ('letzter bekommt
    remainder'), was diesen unbeabsichtigt uebergewichtete. Hier
    skalieren wir proportional, der Rundungsrest geht an den
    groessten Eintrag (stabil und reproduzierbar).
    """
    if not splits:
        return []
    total = sum(int(bps) for _, bps, _ in splits)
    if total == 10000 or total <= 0:
        return list(splits)
    scaled: list[tuple[str, int, str]] = []
    accumulated = 0
    for label, bps, rationale in splits:
        new_bps = int(round(int(bps) * 10000 / total))
        scaled.append((label, new_bps, rationale))
        accumulated += new_bps
    delta = 10000 - accumulated
    if delta != 0 and scaled:
        idx_max = max(range(len(scaled)), key=lambda i: scaled[i][1])
        label, bps, rationale = scaled[idx_max]
        scaled[idx_max] = (label, bps + delta, rationale)
    return scaled


def _preference_choice(value, fallback: str) -> str:
    """Normalisiert UI- und Legacy-Werte auf die internen ASCII-Vergleiche."""
    from services.portfolio_engine import _norm_text

    raw = value if value not in (None, "") else fallback
    return _norm_text(raw).strip()


def _build_sub_allocations(
    targets: dict[str, int],
    preferences: dict,
    jurisdiction: str = "CH",
    db: Session | None = None,
) -> list[dict]:
    """Baut die Sub-Allokation (Sub-Asset-Class-Gewichte) aus Bucket-Targets +
    Anlagepraeferenzen.

    WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): jurisdiction in (None, "CH")
    verwendet unveraendert die hartcodierten CH-Home-Bias-Splits (Constraint 1:
    CH-Pfad byte-identisch). Fuer andere jurisdiction kommen die Home-Bias-
    Splits stattdessen aus resolve_home_bias_defaults() (services/jurisdiction/
    resolve.py) -- dafuer wird zusaetzlich ein db-Parameter benoetigt (siehe
    ValueError unten, falls db fehlt).

    Die generischen Filter (geo_prefs.noEm, overweight_tilts, bondsHighYield/
    Emerging) operieren auf den literalen Sub-Asset-Class-Labels "Aktien
    Schwellenlaender" / "Aktien Global" / "Obligationen High Yield" /
    "Obligationen Emerging" -- diese Labels sind laut services/jurisdiction/
    de_seed.py bewusst IDENTISCH fuer CH und DE (nur die Heimmarkt-Labels
    "Aktien Schweiz"/"Obligationen CHF IG"/"Obligationen Global Hedged"/
    "Immobilien Schweiz" wurden fuer DE uebersetzt) -- die Filter bleiben also
    OHNE Aenderung generisch fuer beide Jurisdiktionen anwendbar. Die zwei
    Stellen, die tatsaechlich ein CH-spezifisches Heimmarkt-Label hartcodieren
    (equities_smid-Satellit "Aktien Schweiz", IG-Bond-Filter "Obligationen CHF
    IG"/"Obligationen Global Hedged") werden daher pro Jurisdiktion getrennt
    aufgebaut (siehe Kommentare unten).
    """
    from services.portfolio_engine import _normalize_preferences, _resolve_home_equity_label

    prefs = _normalize_preferences(preferences)
    asset_prefs = prefs["assetClasses"]
    geo_prefs = prefs["geo"]
    tilts = prefs["tilts"]
    sub_allocations: list[dict] = []
    is_ch = jurisdiction in (None, "CH")
    if not is_ch and db is None:
        raise ValueError(
            "_build_sub_allocations() braucht fuer jurisdiction != 'CH' einen "
            "db-Parameter (fuer resolve_home_bias_defaults())."
        )

    def _flag_enabled(name: str, default: bool = False) -> bool:
        value = asset_prefs.get(name)
        if value is None:
            return default
        if type(value) is not bool:
            raise ValueError(
                f"Anlagepraeferenz {name} muss true oder false sein; "
                f"erhalten: {value!r}."
            )
        return value

    if "noEm" in geo_prefs and type(geo_prefs["noEm"]) is not bool:
        raise ValueError(
            "Anlagepraeferenz noEm muss true oder false sein."
        )

    def _append_split(asset_class: str, bucket_weight: int, splits: list[tuple[str, int, str]]):
        if bucket_weight <= 0 or not splits:
            return
        # C4: Splits auf Summe 10000 normalisieren bevor verteilt wird,
        # damit Filter (HY/EM raus etc.) keine Uebergewichtung des
        # letzten Eintrags erzeugen.
        normalized = _normalize_splits(splits)
        weights: list[int] = []
        remaining = bucket_weight
        for idx, (_label, split_bps, _rationale) in enumerate(normalized):
            if idx == len(normalized) - 1:
                weight = remaining
            else:
                weight = int(round(bucket_weight * split_bps / 10000))
                remaining -= weight
            weights.append(weight)
        if any(weight < 0 for weight in weights):
            # SUB-SPLIT-ROUNDING-001: bei kleinen Buckets ueberstiegen die
            # einzeln gerundeten Sleeves bereits das Bucket (13 bps Aktien mit
            # drei Thema-Tilts -> 6+4+1+1+1+1 = 14), der Rest wurde negativ und
            # verworfen -- das Bucket behielt den Ueberschuss. Dann exakte
            # Largest-Remainder-Verteilung (wie _materialize_sub_allocation_plan);
            # fuer alle anderen Gewichte bleibt die bisherige Rundung unveraendert.
            floors = [bucket_weight * split_bps // 10000 for _l, split_bps, _r in normalized]
            remainders = [bucket_weight * split_bps % 10000 for _l, split_bps, _r in normalized]
            missing = bucket_weight - sum(floors)
            order = sorted(range(len(normalized)), key=lambda i: (-remainders[i], i))
            for i in order[:missing]:
                floors[i] += 1
            weights = floors
        for (label, _split_bps, rationale), weight in zip(normalized, weights):
            if weight <= 0:
                continue
            sub_allocations.append(
                {
                    "asset_class": asset_class,
                    "sub_asset_class": label,
                    "target_weight_bps": weight,
                    "rationale": rationale,
                }
            )

    equities_large_cap = _flag_enabled("equitiesLargeCap", True)
    equities_smid = _flag_enabled("equitiesSmid", False)
    if targets["equities"] > 0 and not equities_large_cap:
        if equities_smid:
            raise ValueError(
                "Anlagepraeferenzen nicht umsetzbar: Aktien Large Cap ist ausgeschaltet, "
                "aber das aktuelle strategische Universum enthaelt nur einen Small-/Mid-Cap-Satelliten. "
                "Bitte Large Cap aktivieren oder ein vollstaendiges Small-/Mid-Cap-Universum hinterlegen."
            )
        raise ValueError(
            "Anlagepraeferenzen unvollstaendig: Bei Aktien muss mindestens ein Segment aktiv sein."
        )

    if is_ch:
        equities_geo = _preference_choice(asset_prefs.get("equitiesGeo"), "Schweiz Fokus")
        if equities_geo not in {
            "Schweiz Fokus", "Global", "Europa", "Schwellenlaender",
        }:
            raise ValueError(
                f"Unbekannte CH-Aktienpraeferenz {equities_geo!r}."
            )
        if geo_prefs.get("noEm") and equities_geo == "Schwellenlaender":
            raise ValueError(
                "Anlagepraeferenzen widerspruechlich: Schwellenlaender-Fokus ist gewaehlt, "
                "aber Kein EM-Exposure ist aktiv."
            )
        if equities_geo == "Global":
            eq_splits = [("Aktien Global", 6500, "Globaler Kernbaustein"), ("Aktien Schweiz", 1500, "Heimmarkt-Anker"), ("Aktien Europa", 1000, "Europa-Diversifikation"), ("Aktien Schwellenlaender", 1000, "Wachstumsbaustein")]
        elif equities_geo == "Europa":
            eq_splits = [("Aktien Europa", 4000, "Europa-Fokus gemaess Mandat"), ("Aktien Global", 2500, "Globaler Kernbaustein"), ("Aktien Schweiz", 2500, "Heimmarkt-Anker"), ("Aktien Schwellenlaender", 1000, "Wachstumsbaustein")]
        elif equities_geo == "Schwellenlaender":
            eq_splits = [("Aktien Global", 4000, "Globaler Kernbaustein"), ("Aktien Schweiz", 2000, "Heimmarkt-Anker"), ("Aktien Europa", 1500, "Europa-Diversifikation"), ("Aktien Schwellenlaender", 2500, "Mandatierter EM-Fokus")]
        else:
            eq_splits = [("Aktien Schweiz", 4500, "Mandatierter Schweiz-Fokus"), ("Aktien Global", 4000, "Globaler Kernbaustein"), ("Aktien Europa", 1000, "Europa-Diversifikation"), ("Aktien Schwellenlaender", 500, "Wachstumsbaustein")]
        if geo_prefs.get("noEm"):
            remainder = 0
            filtered = []
            for label, split_bps, rationale in eq_splits:
                if label == "Aktien Schwellenlaender":
                    remainder += split_bps
                else:
                    filtered.append((label, split_bps, rationale))
            if filtered and remainder:
                label, split_bps, rationale = filtered[0]
                filtered[0] = (label, split_bps + remainder, rationale + "; EM ausgeschlossen")
            eq_splits = filtered
        if equities_smid:
            for idx, item in enumerate(eq_splits):
                if item[0] == "Aktien Schweiz":
                    eq_splits[idx] = (item[0], max(0, item[1] - 1000), item[2])
                    eq_splits.append(("Aktien Schweiz Small/Mid", 1000, "Mandatierter Small-/Mid-Cap-Baustein"))
                    break
    else:
        # Nicht-CH (WP2, 2026-07-31): Home-Bias-Splits kommen 1:1 aus
        # resolve_home_bias_defaults() (services/jurisdiction/resolve.py) --
        # KEINE erfundenen Zahlen, siehe services/jurisdiction/de_seed.py fuer
        # die DE-Seed-Werte (mechanische CH-Spiegelung, is_provisional=1).
        equities_geo = _preference_choice(asset_prefs.get("equitiesGeo"), DE_DEFAULT_EQUITIES_GEO)
        if geo_prefs.get("noEm") and equities_geo == "Schwellenlaender":
            raise ValueError(
                "Anlagepraeferenzen widerspruechlich: Schwellenlaender-Fokus ist gewaehlt, "
                "aber Kein EM-Exposure ist aktiv."
            )
        eq_splits = list(resolve_home_bias_defaults(db, jurisdiction, "equitiesGeo", equities_geo))
        # Heimmarkt-Label fuer den Small/Mid-Satelliten unten: staerkstes Label
        # der equitiesGeo-DEFAULT-Variante (siehe _resolve_home_equity_label()
        # Docstring fuer die Begruendung dieser pragmatischen Wahl).
        home_equity_label = _resolve_home_equity_label(db, jurisdiction)
        if geo_prefs.get("noEm"):
            remainder = 0
            filtered = []
            for label, split_bps, rationale in eq_splits:
                if label == "Aktien Schwellenlaender":
                    remainder += split_bps
                else:
                    filtered.append((label, split_bps, rationale))
            if filtered and remainder:
                label, split_bps, rationale = filtered[0]
                filtered[0] = (label, split_bps + remainder, rationale + "; EM ausgeschlossen")
            eq_splits = filtered
        if equities_smid:
            for idx, item in enumerate(eq_splits):
                if item[0] == home_equity_label:
                    eq_splits[idx] = (item[0], max(0, item[1] - 1000), item[2])
                    eq_splits.append((f"{home_equity_label} Small/Mid", 1000, "Mandatierter Small-/Mid-Cap-Baustein"))
                    break

    overweight_tilts = [key for key, value in tilts.items() if value == "overweight"]
    if overweight_tilts and targets["equities"] > 0:
        theme_map = {
            "defense": "Thema Verteidigung",
            "fossil": "Thema Fossile Energie",
            "tobacco": "Thema Tabak",
            "alcohol": "Thema Alkohol",
            "gaming": "Thema Gluecksspiel",
            "nuclear": "Thema Kernenergie",
        }
        # #AA-7 Fix (2026-06-12): eq_splits leben im Per-Bucket-Raum (sie summieren
        # zu 10000 und werden in _append_split renormalisiert). Der Theme-Tilt muss
        # daher relativ zu 10000 statt zur Portfolio-Aktienquote targets["equities"]
        # definiert werden — sonst haengt die EFFEKTIVE Themen-Gewichtung von der
        # Aktienquote des Risikoprofils ab (eq=8000 -> ~12%, eq=2000 -> ~3%), statt
        # konsistent zu sein. Cap 1200 (= 12% des Aktien-Buckets) bleibt die Obergrenze.
        theme_total = min(int(round(10000 * 0.15)), 1200)
        if theme_total > 0:
            slice_per_theme = max(100, int(round(theme_total / len(overweight_tilts))))
            for idx, item in enumerate(eq_splits):
                if item[0] == "Aktien Global":
                    reduction = min(item[1], slice_per_theme * len(overweight_tilts))
                    eq_splits[idx] = (item[0], item[1] - reduction, item[2] + "; Kernbaustein zugunsten thematischer Tilts reduziert")
                    break
            for tilt in overweight_tilts:
                label = theme_map.get(tilt)
                if label:
                    eq_splits.append((label, slice_per_theme, "Positiver Tilt gemaess Mandatsvorgabe"))

    _append_split("Aktien", targets["equities"], eq_splits)

    if geo_prefs.get("noEm") and asset_prefs.get("bondsEmerging"):
        raise ValueError(
            "Anlagepraeferenzen widerspruechlich: Obligationen Emerging Markets ist aktiv, "
            "aber Kein EM-Exposure ist aktiv."
        )
    if is_ch:
        bonds_duration = _preference_choice(asset_prefs.get("bondsDuration"), "Langfristig")
        if bonds_duration not in {"Langfristig", "Kurzfristig", "Gemischt"}:
            raise ValueError(
                f"Unbekannte Obligationen-Laufzeitpraeferenz {bonds_duration!r}."
            )
        if bonds_duration == "Kurzfristig":
            bond_splits = [("Obligationen CHF IG", 7000, "Kurzfristige CHF-Qualitaet"), ("Obligationen Global Hedged", 2500, "Ergaenzende Diversifikation"), ("Obligationen High Yield", 300, "Renditebeimischung"), ("Obligationen Emerging", 200, "Diversifikation")]
        elif bonds_duration == "Gemischt":
            bond_splits = [("Obligationen CHF IG", 6000, "Gemischter CHF-Kern"), ("Obligationen Global Hedged", 3000, "Globale Diversifikation"), ("Obligationen High Yield", 500, "Renditebeimischung"), ("Obligationen Emerging", 500, "Diversifikation")]
        else:
            bond_splits = [("Obligationen CHF IG", 5500, "Langfristiger CHF-Kern"), ("Obligationen Global Hedged", 3500, "Globale Diversifikation"), ("Obligationen High Yield", 500, "Renditebeimischung"), ("Obligationen Emerging", 500, "Diversifikation")]
        if not _flag_enabled("bondsInvestmentGrade", True):
            bond_splits = [item for item in bond_splits if item[0] not in ("Obligationen CHF IG", "Obligationen Global Hedged")]
    else:
        # Nicht-CH (WP2, 2026-07-31): siehe eq_splits-Kommentar oben. Fuer den
        # bondsInvestmentGrade-Filter gibt es KEIN generisches, jurisdiktions-
        # unabhaengiges Home-IG-Label (die DE-Labels "Obligationen EUR IG"/
        # "Obligationen Global EUR-Hedged" unterscheiden sich bewusst von den
        # CH-Labels). Generalisierung (dokumentierte, pragmatische Wahl): die
        # beiden NICHT-Home-Sleeves "Obligationen High Yield"/"Obligationen
        # Emerging" sind laut de_seed.py IMMER identisch benannt -- daher wird
        # bondsInvestmentGrade=aus stattdessen als "behalte nur HY/EM-Sleeves"
        # ausgedrueckt (Komplement derselben Filterwirkung wie im CH-Zweig).
        bonds_duration = _preference_choice(asset_prefs.get("bondsDuration"), DE_DEFAULT_BONDS_DURATION)
        bond_splits = list(resolve_home_bias_defaults(db, jurisdiction, "bondsDuration", bonds_duration))
        if not _flag_enabled("bondsInvestmentGrade", True):
            bond_splits = [
                item for item in bond_splits
                if item[0] in ("Obligationen High Yield", "Obligationen Emerging")
            ]
    if not _flag_enabled("bondsHighYield", False):
        bond_splits = [item for item in bond_splits if item[0] != "Obligationen High Yield"]
    if not _flag_enabled("bondsEmerging", False) or geo_prefs.get("noEm"):
        bond_splits = [item for item in bond_splits if item[0] != "Obligationen Emerging"]
    if targets["bonds"] > 0 and not bond_splits:
        raise ValueError(
            "Anlagepraeferenzen unvollstaendig: Die Obligationen-Auswahl schliesst alle "
            "umsetzbaren Segmente aus. Bitte Investment Grade, High Yield oder Emerging Markets aktivieren."
        )
    _append_split("Obligationen", targets["bonds"], bond_splits)

    realestate_funds = _flag_enabled("realestateFunds", True)
    realestate_direct = _flag_enabled("realestateDirect", False)
    if targets["real_estate"] > 0:
        if not realestate_funds and not realestate_direct:
            raise ValueError(
                "Anlagepraeferenzen unvollstaendig: Bei Immobilien muss Fonds/REIT oder Direkt aktiv sein."
            )
        if realestate_direct and not realestate_funds:
            raise ValueError(
                "Anlagepraeferenzen nicht umsetzbar: Direktimmobilien-only kann im aktuellen "
                "produktiven Beratungsuniversum nicht als handelbare Zielallokation umgesetzt werden."
            )

    if is_ch:
        realestate_market = _preference_choice(asset_prefs.get("realestateMarket"), "Schweiz")
        if realestate_market not in {"Schweiz", "Ausland", "Gemischt"}:
            raise ValueError(
                f"Unbekannte CH-Immobilienpraeferenz {realestate_market!r}."
            )
        if realestate_market == "Ausland":
            re_splits = [("Immobilien Global", 7000, "Auslandsfokus fuer Immobilien"), ("Immobilien Schweiz", 3000, "Heimmarkt-Stabilisator")]
        elif realestate_market == "Gemischt":
            re_splits = [("Immobilien Schweiz", 5000, "Gemischter Immobilienbaustein"), ("Immobilien Global", 5000, "Gemischter Immobilienbaustein")]
        else:
            re_splits = [("Immobilien Schweiz", 8000, "Schweizer Immobilienfokus"), ("Immobilien Global", 2000, "Ergaenzende Diversifikation")]
    else:
        # Nicht-CH (WP2, 2026-07-31): siehe eq_splits-Kommentar oben.
        realestate_market = _preference_choice(asset_prefs.get("realestateMarket"), DE_DEFAULT_REALESTATE_MARKET)
        re_splits = list(resolve_home_bias_defaults(db, jurisdiction, "realestateMarket", realestate_market))
    if realestate_direct:
        re_splits = [
            (label, bps, rationale + "; Direktimmobilien werden ueber das Gesamtvermoegen beruecksichtigt")
            for label, bps, rationale in re_splits
        ]
    _append_split("Immobilien", targets["real_estate"], re_splits)

    alt_splits = []
    explicit_alt_keys = {"altsGold", "altsLiquidAlts", "altsHedge", "altsPe", "altsCrypto"}.intersection(asset_prefs.keys())
    if _flag_enabled("altsGold", False):
        alt_splits.append(("Gold / Rohstoffe", 4000, "Stabilisierender Sachwertbaustein"))
    if _flag_enabled("altsLiquidAlts", False):
        alt_splits.append(("Liquid Alternatives", 2000, "Diversifizierende Alternative"))
    if _flag_enabled("altsHedge", False):
        alt_splits.append(("Hedge Funds", 1500, "Alternative Renditequelle"))
    if _flag_enabled("altsPe", False):
        alt_splits.append(("Private Equity", 1500, "Illiquider Wachstumsbaustein"))
    if _flag_enabled("altsCrypto", False):
        alt_splits.append(("Krypto", 1000, "Satellit gemaess Mandatsvorgabe"))
    if not alt_splits:
        if targets["alternatives"] > 0 and explicit_alt_keys:
            raise ValueError(
                "Anlagepraeferenzen unvollstaendig: Bei Alternativen Anlagen muss mindestens "
                "ein Instrument aktiv sein."
            )
        alt_splits.append(("Gold / Rohstoffe", 10000, "Standardbaustein fuer Alternative Anlagen"))
    _append_split("Alternative", targets["alternatives"], alt_splits)

    liquidity_label = asset_prefs.get("liquidityInstrument") or "Geldmarktfonds"
    _append_split("Liquiditaet", targets["liquidity"], [(liquidity_label, 10000, "Liquiditaetsreserve gemaess Mandatsvorgabe")])
    return sub_allocations


def _apply_illiquid_cap(
    sub_allocations: list[dict],
    targets: dict[str, int],
    max_illiquid_bps: int | None,
    reasoning: list[str],
    maximums: dict[str, int] | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Deckelt den ECHT illiquiden Anteil (Private Equity) auf max_illiquid_bps.

    Methodik-konform (Referenzmethodik): nur der illiquide Baustein wird reduziert, nicht
    die ganze Alternatives-Quote. Der freiwerdende Anteil wird primaer innerhalb
    der Alternativen zu liquiden Sleeves (Gold, Liquid Alts, ...) verschoben — die
    Alternatives-Quote bleibt dann unveraendert, nur ihre Zusammensetzung wird
    liquider. Gibt es keinen liquiden Alt-Sleeve, wandert der Rest in die Liquiditaet.

    `maximums` (optional, Rueckwaerts-kompatibel None): Sicherheits-Fix
    (2026-08-03) -- ohne liquiden Alt-Sleeve floss der freiwerdende Anteil
    bisher UNGEPRUEFT in `targets["liquidity"]`, auch wenn eine vom Berater
    gesetzte Bandbreiten-Restriktion (`_apply_band_preferences`) die
    Liquiditaet bereits auf ein niedrigeres Maximum begrenzt hatte. Wird
    `maximums` mitgegeben, wird der Illiquid-Cap-Zielwert VORAB (vor dem
    Herunterskalieren der PE-Sub-Allokation) an die verfuegbare Liquiditaets-
    Kapazitaet angepasst, statt hinterher zu "reparieren" (das wuerde die
    bereits skalierte PE-Sub-Allokation inkonsistent machen). Konsequenz:
    der Mandats-Cap fuer illiquide Anlagen wird in diesem Randfall ggf. nicht
    zu 100% erreicht -- Prioritaet hat die explizite Bandbreiten-Restriktion.
    """
    from services.portfolio_engine import _ILLIQUID_SUB_ASSET_CLASSES, _norm_text

    if max_illiquid_bps is None:
        return sub_allocations, targets
    illiquid = [
        sub for sub in sub_allocations
        if _norm_text(sub.get("sub_asset_class")).strip().lower() in _ILLIQUID_SUB_ASSET_CLASSES
    ]
    illiquid_bps = sum(int(sub.get("target_weight_bps") or 0) for sub in illiquid)
    if illiquid_bps <= max_illiquid_bps or illiquid_bps <= 0:
        return sub_allocations, targets

    liquid_alts = [
        sub for sub in sub_allocations
        if _norm_text(sub.get("asset_class")) == _norm_text("Alternative")
        and _norm_text(sub.get("sub_asset_class")).strip().lower() not in _ILLIQUID_SUB_ASSET_CLASSES
    ]
    effective_max_illiquid_bps = max_illiquid_bps
    liquidity_capped = False
    if not liquid_alts and maximums is not None:
        liquidity_room = max(0, int(maximums.get("liquidity", 10000)) - int(targets["liquidity"]))
        adjusted = max(max_illiquid_bps, illiquid_bps - liquidity_room)
        if adjusted > max_illiquid_bps:
            liquidity_capped = True
        effective_max_illiquid_bps = adjusted

    freed = 0
    scale = effective_max_illiquid_bps / illiquid_bps
    for sub in illiquid:
        old = int(sub.get("target_weight_bps") or 0)
        new = int(round(old * scale))
        freed += old - new
        sub["target_weight_bps"] = new
    if freed <= 0:
        return sub_allocations, targets

    if liquidity_capped:
        reasoning.append(
            "Die Mandatsgrenze fuer illiquide Anlagen (Private Equity) konnte wegen der "
            "gesetzten Liquiditaets-Maximalgrenze nicht vollstaendig erreicht werden; "
            "die Bandbreiten-Restriktion hat Vorrang."
        )

    if liquid_alts:
        # Innerhalb der Alternativen umschichten: PE -> liquide Sleeves. Alternatives-Quote bleibt.
        receiver = max(liquid_alts, key=lambda s: int(s.get("target_weight_bps") or 0))
        receiver["target_weight_bps"] = int(receiver.get("target_weight_bps") or 0) + freed
        reasoning.append(
            "Mandatsgrenze fuer illiquide Anlagen: Private Equity gedeckelt, "
            "freiwerdender Anteil innerhalb der Alternativen zu liquiden Bausteinen verschoben."
        )
    else:
        # Kein liquider Alt-Sleeve vorhanden -> raus aus Alternativen in die Liquiditaet.
        targets["alternatives"] = max(0, int(targets["alternatives"]) - freed)
        targets["liquidity"] = int(targets["liquidity"]) + freed
        liq_sub = next(
            (s for s in sub_allocations if _norm_text(s.get("asset_class")) == _norm_text("Liquiditaet")),
            None,
        )
        if liq_sub is not None:
            liq_sub["target_weight_bps"] = int(liq_sub.get("target_weight_bps") or 0) + freed
        else:
            sub_allocations.append({
                "asset_class": "Liquiditaet",
                "sub_asset_class": "Geldmarktfonds",
                "target_weight_bps": freed,
                "rationale": "Liquiditaetsreserve nach Deckelung illiquider Anlagen",
            })
        reasoning.append(
            "Mandatsgrenze fuer illiquide Anlagen: Private Equity gedeckelt, "
            "freiwerdender Anteil in die Liquiditaet umgeschichtet (kein liquider Alternativ-Baustein aktiv)."
        )
    return sub_allocations, targets


def _canonicalize_sub_allocation_mix(
    sub_allocations: list[dict],
) -> list[dict]:
    """Return a deterministic, bucket-relative sub-allocation plan.

    ``_build_sub_allocations`` materialises portfolio weights.  The stochastic
    optimizer, however, needs a *fixed* composition per bucket: otherwise a
    later change of a bucket weight can silently change the CMA and risky-
    fraction inputs that were used to optimise it.  This helper normalises
    every populated bucket to exactly 10'000 bps while preserving labels,
    rationale and ordering.

    The returned ``target_weight_bps`` therefore means "bps within this
    bucket".  It must be materialised with
    ``_materialize_sub_allocation_plan`` before it is exposed or persisted.
    ``scenario_inputs_from_cma`` and the risky-fraction aggregation both
    normalise within buckets already, so this canonical representation is
    also their safest input format.
    """
    from services.portfolio_engine import _bucket_key

    by_bucket: dict[str, list[dict]] = {}
    bucket_order: list[str] = []
    for item in sub_allocations or []:
        bucket = _bucket_key(item.get("asset_class"))
        raw_weight = (
            item.get("within_bucket_weight_bps")
            if item.get("within_bucket_weight_bps") is not None
            else item.get("target_weight_bps")
        )
        weight = max(0, int(raw_weight or 0))
        if not bucket or weight <= 0:
            continue
        if bucket not in by_bucket:
            by_bucket[bucket] = []
            bucket_order.append(bucket)
        by_bucket[bucket].append(dict(item))

    canonical: list[dict] = []
    for bucket in bucket_order:
        rows = by_bucket[bucket]
        source_weights = [
            max(
                0,
                int(
                    row.get("within_bucket_weight_bps")
                    if row.get("within_bucket_weight_bps") is not None
                    else row.get("target_weight_bps")
                    or 0
                ),
            )
            for row in rows
        ]
        total = sum(source_weights)
        if total <= 0:
            continue
        scaled: list[dict] = []
        remainders: list[int] = []
        for row, source_weight in zip(rows, source_weights):
            numerator = source_weight * 10000
            weight = numerator // total
            remainders.append(numerator % total)
            scaled.append({
                **row,
                "target_weight_bps": weight,
                "within_bucket_weight_bps": weight,
            })
        residual = 10000 - sum(
            int(row["target_weight_bps"]) for row in scaled
        )
        order = sorted(
            range(len(scaled)),
            key=lambda idx: (
                -remainders[idx],
                int(scaled[idx].get("risky_fraction_bps") or 0),
                idx,
            ),
        )
        for idx in order[:residual]:
            scaled[idx]["target_weight_bps"] += 1
            scaled[idx]["within_bucket_weight_bps"] += 1
        canonical.extend(scaled)
    return canonical


def _materialize_sub_allocation_plan(
    plan: list[dict],
    targets: dict[str, int],
) -> list[dict]:
    """Scale a canonical per-bucket plan to final portfolio target weights.

    Rounding is resolved inside every bucket, so the sub-weights reproduce
    each final bucket target exactly.  This is the key invariant that keeps
    solver CMA/risk inputs and all downstream metrics on the same sub-mix.
    """
    from services.portfolio_engine import BUCKET_FIELDS, _bucket_key

    by_bucket: dict[str, list[dict]] = {bucket: [] for bucket in BUCKET_FIELDS}
    for item in plan or []:
        bucket = _bucket_key(item.get("asset_class"))
        if bucket in by_bucket:
            by_bucket[bucket].append(dict(item))

    materialized: list[dict] = []
    for bucket in BUCKET_FIELDS:
        bucket_target = max(0, int(targets.get(bucket, 0) or 0))
        rows = by_bucket[bucket]
        if not rows:
            continue
        mix_weights = [
            max(
                0,
                int(
                    row.get("within_bucket_weight_bps")
                    if row.get("within_bucket_weight_bps") is not None
                    else row.get("target_weight_bps")
                    or 0
                ),
            )
            for row in rows
        ]
        plan_total = sum(mix_weights)
        if plan_total <= 0:
            continue
        if bucket_target == 0:
            # Preserve the exact sleeve blueprint for a currently empty
            # bucket. Its maximum may still be positive, so sensitivity/replay
            # must not fall back to generic CMA/risk assumptions later.
            materialized.extend({
                **row,
                "target_weight_bps": 0,
                "within_bucket_weight_bps": mix_weight,
            } for row, mix_weight in zip(rows, mix_weights))
            continue
        scaled: list[dict] = []
        remainders: list[int] = []
        for row, mix_weight in zip(rows, mix_weights):
            numerator = bucket_target * mix_weight
            weight = numerator // plan_total
            remainders.append(numerator % plan_total)
            scaled.append({
                **row,
                "target_weight_bps": weight,
                "within_bucket_weight_bps": mix_weight,
            })
        residual = bucket_target - sum(
            int(row["target_weight_bps"]) for row in scaled
        )
        order = sorted(
            range(len(scaled)),
            key=lambda idx: (
                -remainders[idx],
                int(scaled[idx].get("risky_fraction_bps") or 0),
                idx,
            ),
        )
        for idx in order[:residual]:
            scaled[idx]["target_weight_bps"] += 1
        # Keep zero-weight sleeves as immutable context rows. They contribute
        # nothing to the active portfolio but retain the accepted model mix.
        materialized.extend(scaled)
    return materialized


def _build_stochastic_sub_allocation_plan(
    *,
    targets: dict[str, int],
    minimums: dict[str, int],
    maximums: dict[str, int],
    preferences: dict,
    max_illiquid_bps: int | None,
    reasoning: list[str],
    jurisdiction: str = "CH",
    db: Session | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Build the immutable sub-allocation plan used by the stochastic model.

    The plan is calibrated at the largest simultaneously reachable bucket
    weights.  Consequently an absolute ``maxIlliquid`` limit remains valid
    for *every* allocation inside the effective bounds, while the sub-mix is
    constant during optimisation and downstream reporting.

    If the alternatives universe is entirely illiquid (for example PE-only),
    composition cannot absorb the cap.  In that case the alternatives upper
    bound itself is tightened.  A conflicting minimum is a domain error: it
    must not be hidden by a House-Matrix fallback that would violate the same
    hard mandate rule.
    """
    from services.portfolio_engine import (
        BUCKET_FIELDS,
        _ILLIQUID_SUB_ASSET_CLASSES,
        _norm_text,
    )
    from services.optimizer.constraints import OptimizerInputError

    effective_maximums = {
        bucket: int(maximums[bucket]) for bucket in BUCKET_FIELDS
    }
    minimum_total = sum(int(minimums[bucket]) for bucket in BUCKET_FIELDS)
    if minimum_total > 10000:
        raise OptimizerInputError(
            "Mandatsspezifische Mindestquoten sind unloesbar: ihre Summe "
            f"betraegt {minimum_total / 100:.2f}% statt hoechstens 100%."
        )

    reference_targets: dict[str, int] = {}
    for bucket in BUCKET_FIELDS:
        other_minimums = sum(
            int(minimums[other]) for other in BUCKET_FIELDS if other != bucket
        )
        simultaneously_reachable = max(0, 10000 - other_minimums)
        reference_targets[bucket] = min(
            int(effective_maximums[bucket]), simultaneously_reachable
        )

    raw = _build_sub_allocations(
        reference_targets,
        preferences,
        jurisdiction=jurisdiction,
        db=db,
    )

    if max_illiquid_bps is not None:
        alternatives_reference = max(0, int(reference_targets["alternatives"]))
        alt_rows = [
            row for row in raw
            if _norm_text(row.get("asset_class")) == _norm_text("Alternative")
        ]
        illiquid_rows = [
            row for row in alt_rows
            if _norm_text(row.get("sub_asset_class")).strip().lower()
            in _ILLIQUID_SUB_ASSET_CLASSES
        ]
        liquid_rows = [row for row in alt_rows if row not in illiquid_rows]
        illiquid_at_reference = sum(
            max(0, int(row.get("target_weight_bps") or 0)) for row in illiquid_rows
        )

        if (
            alternatives_reference > 0
            and illiquid_at_reference > max_illiquid_bps
            and illiquid_rows
            and not liquid_rows
        ):
            # General formula L/q_illiquid, evaluated without floats:
            # max_alt = floor(L * alt_reference / illiquid_at_reference).
            cap_for_alternatives = max(
                0,
                int(max_illiquid_bps) * alternatives_reference // illiquid_at_reference,
            )
            effective_maximums["alternatives"] = min(
                effective_maximums["alternatives"], cap_for_alternatives
            )
            if int(minimums["alternatives"]) > effective_maximums["alternatives"]:
                raise OptimizerInputError(
                    "Mandatsvorgaben sind unloesbar: Das Mindestgewicht fuer "
                    "Alternative Anlagen ist mit der maximal erlaubten "
                    "Illiquiditaet nicht vereinbar."
                )
            reference_targets["alternatives"] = min(
                reference_targets["alternatives"],
                effective_maximums["alternatives"],
            )
            raw = _build_sub_allocations(
                reference_targets,
                preferences,
                jurisdiction=jurisdiction,
                db=db,
            )
            reasoning.append(
                "Die Obergrenze fuer Alternative Anlagen wurde so reduziert, "
                "dass das PE-only-Universum die Illiquiditaetsgrenze in jeder "
                "zulaessigen Solver-Allokation einhaelt."
            )

        # Mixed alternatives: reduce PE at the worst-case reachable alternatives
        # weight and redistribute within the bucket.  The canonicalised mix is
        # then safe at all lower weights as well.
        raw, reference_targets = _apply_illiquid_cap(
            raw,
            reference_targets,
            max_illiquid_bps,
            reasoning,
            maximums=effective_maximums,
        )

    if sum(int(effective_maximums[bucket]) for bucket in BUCKET_FIELDS) < 10000:
        raise OptimizerInputError(
            "Mandatsspezifische Maximalquoten sind unloesbar: ihre Summe "
            "reicht nicht fuer eine voll investierte Allokation von 100%."
        )

    return _canonicalize_sub_allocation_mix(raw), effective_maximums


def _house_matrix_or_default(db: Session, policy: OptimizerPolicy, score_bucket: int) -> HouseMatrix:
    candidates = db.query(HouseMatrix).filter(
        HouseMatrix.policy_id == policy.id,
        HouseMatrix.score_from <= score_bucket,
        HouseMatrix.score_to >= score_bucket,
        HouseMatrix.is_active == 1,
    ).all()
    if len(candidates) > 1:
        raise ValueError(
            f"HouseMatrix ist fuer Score {score_bucket} mehrdeutig; "
            "aktive Score-Bereiche ueberlappen sich."
        )
    if candidates:
        return candidates[0]
    raise ValueError(f"HouseMatrix unvollstaendig fuer Score {score_bucket}")


def _validate_house_matrix_defaults(defaults: list[tuple]) -> None:
    from services.portfolio_engine import ALLOWED_HOUSE_MATRIX_PROFILES

    covered_scores: list[int] = []
    for entry in defaults:
        (
            score_from,
            score_to,
            profile_name,
            liq_min,
            liq_target,
            liq_max,
            bonds_min,
            bonds_target,
            bonds_max,
            eq_min,
            eq_target,
            eq_max,
            re_min,
            re_target,
            re_max,
            alt_min,
            alt_target,
            alt_max,
            risky,
            equity_floor,
        ) = entry
        if profile_name not in ALLOWED_HOUSE_MATRIX_PROFILES:
            raise ValueError(f"Unzulaessiger House-Matrix-Profilname: {profile_name}.")
        if score_from > score_to:
            raise ValueError(f"Ungueltige Score-Range fuer {profile_name}: {score_from}-{score_to}.")
        covered_scores.extend(range(score_from, score_to + 1))
        target_total = liq_target + bonds_target + eq_target + re_target + alt_target
        if target_total != 10000:
            raise ValueError(f"House-Matrix-Targets fuer {profile_name} ({score_from}-{score_to}) summieren sich auf {target_total} statt 10000 Bps.")
        if not 0 <= risky <= 10000:
            raise ValueError(
                f"House-Matrix-Risky-Fraction fuer {profile_name} ({score_from}-{score_to}) liegt ausserhalb von 0-10000 Bps."
            )
        bounds = (
            ("Liquiditaet", liq_min, liq_target, liq_max),
            ("Obligationen", bonds_min, bonds_target, bonds_max),
            ("Aktien", eq_min, eq_target, eq_max),
            ("Immobilien", re_min, re_target, re_max),
            ("Alternative", alt_min, alt_target, alt_max),
        )
        for label, minimum, target, maximum in bounds:
            if not minimum <= target <= maximum:
                raise ValueError(
                    f"House-Matrix-Band verletzt fuer {profile_name} ({score_from}-{score_to}) in {label}: {minimum}/{target}/{maximum}."
                )
        if equity_floor and not (eq_min <= equity_floor <= eq_max):
            raise ValueError(
                f"House-Matrix-Aktienminimum fuer {profile_name} ({score_from}-{score_to}) ist ausserhalb des Bandes: {equity_floor}."
            )
    if sorted(covered_scores) != list(range(1, 11)):
        raise ValueError("House-Matrix-Defaults muessen jeden Score von 1 bis 10 genau einmal abdecken.")


def _normalize_house_matrix_defaults(defaults: list[tuple]) -> list[tuple]:
    normalized: list[tuple] = []
    for entry in defaults:
        values = list(entry)
        target_indexes = {
            "liquidity": 4,
            "bonds": 7,
            "equities": 10,
            "real_estate": 13,
            "alternatives": 16,
        }
        max_indexes = {
            "liquidity": 5,
            "bonds": 8,
            "equities": 11,
            "real_estate": 14,
            "alternatives": 17,
        }
        total = sum(int(values[index]) for index in target_indexes.values())
        delta = 10000 - total
        if delta != 0:
            # Fachtabellen koennen gerundete Prozentsaetze enthalten; die Runtime braucht dennoch exakt 100%.
            for bucket in ("liquidity", "bonds", "alternatives", "real_estate", "equities"):
                target_idx = target_indexes[bucket]
                max_idx = max_indexes[bucket]
                room = int(values[max_idx]) - int(values[target_idx])
                if delta > 0 and room <= 0:
                    continue
                if delta < 0 and int(values[target_idx]) <= 0:
                    continue
                step = delta
                if delta > 0:
                    step = min(delta, room)
                else:
                    step = max(delta, -int(values[target_idx]))
                if step == 0:
                    continue
                values[target_idx] = int(values[target_idx]) + int(step)
                delta -= int(step)
                if delta == 0:
                    break
        if delta != 0:
            raise ValueError(
                f"House-Matrix-Defaults fuer {values[2]} ({values[0]}-{values[1]}) koennen nicht auf 10000 Bps normalisiert werden."
            )
        normalized.append(tuple(values))
    return normalized


def _seed_house_matrix_rows(db: Session, policy_id: str, defaults: list[tuple], now: str) -> None:
    for (
        score_from,
        score_to,
        profile_name,
        liq_min,
        liq_target,
        liq_max,
        bonds_min,
        bonds_target,
        bonds_max,
        eq_min,
        eq_target,
        eq_max,
        re_min,
        re_target,
        re_max,
        alt_min,
        alt_target,
        alt_max,
        risky,
        equity_floor,
    ) in defaults:
        db.add(
            HouseMatrix(
                id=new_uuid(),
                policy_id=policy_id,
                score_from=score_from,
                score_to=score_to,
                profile_name=profile_name,
                liq_min_bps=liq_min,
                liq_target_bps=liq_target,
                liq_max_bps=liq_max,
                bonds_min_bps=bonds_min,
                bonds_target_bps=bonds_target,
                bonds_max_bps=bonds_max,
                equity_min_bps=eq_min,
                equity_target_bps=eq_target,
                equity_max_bps=eq_max,
                real_estate_min_bps=re_min,
                real_estate_target_bps=re_target,
                real_estate_max_bps=re_max,
                alt_min_bps=alt_min,
                alt_target_bps=alt_target,
                alt_max_bps=alt_max,
                equity_minimum_bps=equity_floor,
                max_risky_fraction_bps=risky,
                is_active=1,
                created_at=now,
                updated_at=now,
            )
        )


def _seed_building_blocks(db: Session, policy_id: str, building_blocks: list[tuple], now: str) -> None:
    for asset_class, sub_asset_class, risky_fraction in building_blocks:
        db.add(
            BuildingBlock(
                id=new_uuid(),
                policy_id=policy_id,
                asset_class=asset_class,
                sub_asset_class=sub_asset_class,
                universe="Standard",
                advisory=1,
                risky_fraction_bps=risky_fraction,
                contribution_standard_bps=risky_fraction,
                contribution_alternative_bps=risky_fraction,
                is_active=1,
                created_at=now,
                updated_at=now,
            )
        )


_POLICY_CAP_UNSET_BPS = 10000
"""Ersatzwert fuer eine NICHT GESETZTE Policy-Obergrenze (= kein Cap)."""


def _policy_value_or_unset(value, *, unset_default: int) -> int:
    """Nur NULL heisst "nicht gesetzt" -- eine explizite 0 ist ein echter Wert.

    ZERO-CONSTRAINT-SEMANTICS-001: hier stand ``policy.max_real_estate_bps or
    10000``. Python behandelt die Zahl 0 als falsy, also wurde ein
    ausdruecklich gesetztes Cap von 0 bps ("diese Anlageklasse ganz
    ausschliessen") wie "kein Cap gesetzt" behandelt und durch 10000 (= 100 %,
    also gar keine Begrenzung) ersetzt. Der Berater, der "0 % Alternative"
    festlegt, bekam das Hausmatrix-Maximum.

    Besonders eindeutig wird der Befund am Datenmodell:
    ``max_real_estate_bps``, ``max_alternatives_bps`` und
    ``min_liquidity_bps`` sind alle ``nullable=False`` **mit Default**. Der
    Wert ist in der Datenbank also NIE NULL -- der ``or``-Zweig konnte
    ueberhaupt nur fuer die 0 greifen. Er existierte nicht, um einen fehlenden
    Wert abzufangen, sondern ausschliesslich, um explizite Nullen zu
    zerstoeren.

    Dieselbe Semantik wie ``_cma_value_or_default()`` im CMA-Cluster
    ("Preserve an explicit 0 bps CMA; only NULL means 'use fallback'").
    """
    return int(unset_default if value is None else value)


def policy_band_clamp_notes(
    house_matrix: HouseMatrix, policy: OptimizerPolicy
) -> list[str]:
    """Beschreibt jede Bandgrenze, die eine Policy gegen die Hausmatrix verschiebt.

    Die Aufloesung in ``_baseline_target_bands()`` ist deterministisch, aber
    sie veraendert eine firmenweite Vorgabe fuer ein einzelnes Mandat. Das darf
    nicht still geschehen: wer ein Hausmatrix-Minimum von 5 % auf 0 %
    herunterzieht, weil das Mandat die Anlageklasse ausschliesst, soll das im
    Nachweis lesen koennen.

    Reine Funktion ohne Seiteneffekte, bewusst getrennt von
    ``_baseline_target_bands()`` -- dessen Signatur hat fuenf Aufrufstellen und
    eine dokumentierte Drei-Tupel-Konvention (AB-MODEL-001).
    """
    notes: list[str] = []
    for bucket_label, house_min_attr, house_max_attr, cap_attr in (
        ("Immobilien", "real_estate_min_bps", "real_estate_max_bps", "max_real_estate_bps"),
        ("Alternative", "alt_min_bps", "alt_max_bps", "max_alternatives_bps"),
    ):
        cap = _policy_value_or_unset(
            getattr(policy, cap_attr, None), unset_default=_POLICY_CAP_UNSET_BPS
        )
        house_max = int(getattr(house_matrix, house_max_attr))
        house_min = int(getattr(house_matrix, house_min_attr))
        effective_max = min(house_max, cap)
        if cap < house_max:
            notes.append(
                f"{bucket_label}: Mandats-Policy begrenzt auf "
                f"{cap / 100:.2f} % (Hausmatrix-Maximum "
                f"{house_max / 100:.2f} %)."
            )
        if house_min > effective_max:
            notes.append(
                f"{bucket_label}: Hausmatrix-Minimum "
                f"{house_min / 100:.2f} % wurde auf die Policy-Obergrenze "
                f"{effective_max / 100:.2f} % herabgesetzt, damit die "
                "Bandbreite nicht invertiert."
            )
    policy_liq_min = _policy_value_or_unset(
        getattr(policy, "min_liquidity_bps", None), unset_default=0
    )
    house_liq_max = int(house_matrix.liq_max_bps)
    if policy_liq_min > house_liq_max:
        notes.append(
            f"Liquiditaet: Policy-Mindestquote {policy_liq_min / 100:.2f} % "
            f"liegt ueber dem Hausmatrix-Maximum {house_liq_max / 100:.2f} %; "
            "das Maximum wurde angehoben, damit die Bandbreite nicht "
            "invertiert."
        )
    return notes


def _baseline_target_bands(house_matrix: HouseMatrix, policy: OptimizerPolicy) -> tuple[dict, dict, dict]:
    """House-Matrix-Bands, durch die Mandats-Policy verschaerft.

    Targets bleiben bewusst die ROHEN Hausmatrix-Werte -- sie koennen ihre
    eigenen Bands verletzen. Jeder Konsument projiziert mit
    ``_rebalance_to_total()`` (dokumentierte Konvention AB-MODEL-001); hier zu
    klemmen wuerde diese Trennung aufweichen.

    Auflösungsregel bei Konflikt zwischen Policy und Hausmatrix
    -----------------------------------------------------------
    POLICY-ACTIVATION-COMPLETENESS-001: eine Policy-Obergrenze UNTER dem
    Hausmatrix-Minimum erzeugte eine invertierte Bandbreite (min > max). Das
    Dict wurde so zurueckgegeben, und ``_rebalance_to_total()`` klemmt mit
    ``max(min, min(max, wert))`` -- bei invertiertem Band gewinnt damit immer
    das (hoehere) Minimum. Ergebnis: die Policy-Obergrenze wurde praktisch
    ignoriert, und zwar lautlos.

    Aufgeloest wird zugunsten der POLICY: sie ist die mandatsspezifische
    Anweisung, die Hausmatrix die firmenweite Standard-Bandbreite. Ein
    "dieser Kunde haelt keine Immobilien" ist eine legitime Weisung und kein
    Konfigurationsfehler, also wird das Minimum auf die Obergrenze
    herabgezogen.

    Das ist hier unbedenklich, weil die ``OptimizerPolicy`` genau drei
    Band-Felder hat -- ``max_real_estate_bps``, ``max_alternatives_bps``,
    ``min_liquidity_bps``. Sie kann also ausschliesslich SATELLITEN
    verschieben; die Aktien- und Obligationen-Untergrenzen, in denen die
    Eignung sitzt, erreicht sie nicht, und das Risikobudget
    (``max_risky_fraction_bps``) wird separat erzwungen.

    Jede so verschobene Grenze ist ueber ``policy_band_clamp_notes()``
    nachlesbar -- eine firmenweite Vorgabe fuer ein Mandat zu aendern darf
    nicht still geschehen.

    Eine hausmatrix-INTERNE Inversion (min > max in der Zeile selbst, ohne
    Policy-Beteiligung) ist dagegen korrupte Referenzdaten und wird
    abgelehnt, nicht geklemmt.
    """
    targets = {
        "equities": int(house_matrix.equity_target_bps),
        "bonds": int(house_matrix.bonds_target_bps),
        "real_estate": int(house_matrix.real_estate_target_bps),
        "alternatives": int(house_matrix.alt_target_bps),
        "liquidity": int(house_matrix.liq_target_bps),
    }
    real_estate_max = min(
        int(house_matrix.real_estate_max_bps),
        _policy_value_or_unset(
            policy.max_real_estate_bps, unset_default=_POLICY_CAP_UNSET_BPS
        ),
    )
    alternatives_max = min(
        int(house_matrix.alt_max_bps),
        _policy_value_or_unset(
            policy.max_alternatives_bps, unset_default=_POLICY_CAP_UNSET_BPS
        ),
    )
    policy_liquidity_min = _policy_value_or_unset(
        policy.min_liquidity_bps, unset_default=0
    )
    liquidity_min = max(int(house_matrix.liq_min_bps), policy_liquidity_min)
    minimums = {
        "equities": max(int(house_matrix.equity_min_bps), int(house_matrix.equity_minimum_bps or 0)),
        "bonds": int(house_matrix.bonds_min_bps),
        # Policy gewinnt: das Minimum folgt der Obergrenze nach unten.
        "real_estate": min(int(house_matrix.real_estate_min_bps), real_estate_max),
        "alternatives": min(int(house_matrix.alt_min_bps), alternatives_max),
        "liquidity": liquidity_min,
    }
    maximums = {
        "equities": int(house_matrix.equity_max_bps),
        "bonds": int(house_matrix.bonds_max_bps),
        "real_estate": real_estate_max,
        "alternatives": alternatives_max,
        # Symmetrisch zur Regel oben: eine Policy-Mindestquote ueber dem
        # Hausmatrix-Maximum hebt das Maximum an, statt zu invertieren. Fuer
        # Liquiditaet ist die hoehere Quote die konservativere Richtung.
        "liquidity": max(int(house_matrix.liq_max_bps), liquidity_min),
    }
    _reject_house_matrix_internal_band_inversion(house_matrix)
    return targets, minimums, maximums


def _reject_house_matrix_internal_band_inversion(house_matrix: HouseMatrix) -> None:
    """Weist eine Hausmatrix-Zeile ab, deren Band schon ohne Policy invertiert ist.

    Die Policy-Konflikte oben sind legitime Konfigurationen und werden nach
    einer dokumentierten Regel aufgeloest. Ein ``min > max`` in der Zeile
    selbst ist dagegen kein Konflikt, sondern korrupte Referenzdaten -- dafuer
    gibt es keine sinnvolle Aufloesung, und still zu klemmen hiesse, eine
    kaputte Bandbreite in eine Allokation zu uebersetzen.

    Das Eingabe-Schema prueft das bereits (``schemas/allocation.py``: "min_bps
    darf max_bps nicht ueberschreiten"); diese Pruefung faengt Zeilen, die
    nicht ueber die API kamen -- YAML-Defaults, Migrationen, Altbestand.
    """
    for bucket_label, min_attr, max_attr in (
        ("Aktien", "equity_min_bps", "equity_max_bps"),
        ("Obligationen", "bonds_min_bps", "bonds_max_bps"),
        ("Immobilien", "real_estate_min_bps", "real_estate_max_bps"),
        ("Alternative", "alt_min_bps", "alt_max_bps"),
        ("Liquiditaet", "liq_min_bps", "liq_max_bps"),
    ):
        lower = int(getattr(house_matrix, min_attr))
        upper = int(getattr(house_matrix, max_attr))
        if lower > upper:
            raise ValueError(
                f"Hausmatrix-Zeile hat eine invertierte Bandbreite fuer "
                f"{bucket_label}: {min_attr}={lower} > {max_attr}={upper}. "
                "Das sind korrupte Referenzdaten und keine "
                "Policy-Verschaerfung -- die Zeile muss korrigiert werden."
            )


APPROVED_ALLOCATION_BASIS = "approved_target_allocation"
HOUSE_MATRIX_BASELINE_BASIS = "house_matrix_baseline_projected"


def approved_or_baseline_targets(
    allocation,
    house_matrix: HouseMatrix,
    policy: OptimizerPolicy,
) -> tuple[dict[str, int], str]:
    """Die Allokation, die tatsaechlich gilt -- plus woher sie kommt.

    RETIREMENT-ALLOCATION-BASIS-001: mehrere Verbraucher leiteten ihre
    Kennzahlen aus ``_baseline_target_bands()`` ab, also aus der ROHEN
    Hausmatrix-Bandbreite des Risiko-Buckets, und haben die tatsaechlich
    genehmigte ``TargetAllocation`` des Mandats nie geladen. Weicht die
    freigegebene Strategie von der Baseline ab -- etwa weil eine
    Aktien-Untergrenze gegriffen hat und Immobilien/Alternative gedeckelt
    wurden --, rechnet der Verbraucher auf einer Allokation, die so nie
    beschlossen wurde.

    Zweiter, dabei auffallender Punkt: die rohen ``*_target_bps`` der
    Hausmatrix koennen ihre EIGENEN Bandbreiten verletzen (dokumentiert als
    AB-MODEL-001). Der Fallback projiziert sie deshalb mit
    ``_rebalance_to_total()``, wie es der echte Allokations-Pfad immer tut.
    Die rohen Werte ungeklemmt weiterzugeben hiesse, mit einer Allokation zu
    rechnen, die das System in der Generierung nie zulassen wuerde.

    Bewusst eine reine Funktion ohne DB-Zugriff: die eindeutige Auflösung des
    aktuellen Strategieentscheids ist Sache von
    ``_current_target_allocation_or_none()`` (das bei mehreren aktuellen
    Zeilen abbricht statt eine zu waehlen). Hier wird nur entschieden, WELCHE
    Zahlen gelten.

    Liefert ``(targets_bps, basis_id)``.
    """
    if allocation is not None:
        return (
            {
                "equities": int(allocation.target_equities_bps or 0),
                "bonds": int(allocation.target_bonds_bps or 0),
                "real_estate": int(allocation.target_real_estate_bps or 0),
                "alternatives": int(allocation.target_alternatives_bps or 0),
                "liquidity": int(allocation.target_liquidity_bps or 0),
            },
            APPROVED_ALLOCATION_BASIS,
        )
    raw_targets, minimums, maximums = _baseline_target_bands(house_matrix, policy)
    return (
        _rebalance_to_total(raw_targets, minimums, maximums),
        HOUSE_MATRIX_BASELINE_BASIS,
    )


def allocation_basis_note(basis_id: str) -> str:
    """Beraterlesbare Begruendung, auf welcher Allokation eine Zahl steht."""
    if basis_id == APPROVED_ALLOCATION_BASIS:
        return (
            "Berechnungsbasis: die aktuell genehmigte Soll-Allokation dieses "
            "Mandats."
        )
    return (
        "Berechnungsbasis: die Hausmatrix-Bandbreite des Risikoprofils (in "
        "die eigenen Bandbreiten projiziert) -- fuer dieses Mandat ist noch "
        "keine Soll-Allokation freigegeben."
    )


def _house_matrix_mid_targets(house_matrix: HouseMatrix, policy: OptimizerPolicy) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    from services.portfolio_engine import BUCKET_FIELDS

    _targets, minimums, maximums = _baseline_target_bands(house_matrix, policy)
    midpoint_targets = {
        bucket: int(round((int(minimums[bucket]) + int(maximums[bucket])) / 2))
        for bucket in BUCKET_FIELDS
    }
    return _rebalance_to_total(midpoint_targets, minimums, maximums), minimums, maximums


def _apply_external_exposure_tilts(
    targets: dict,
    minimums: dict,
    maximums: dict,
    total_summary,
    house_matrix: HouseMatrix,
    manual_target_override: bool,
    reasoning: list[str],
) -> None:
    from services.portfolio_engine import _bps

    # VORSORGE-PROJECTION-001 (2026-10-18): Vorsorge-Fortschreibung offenlegen
    # -- auch bei manuellen Soll-Quoten, sie praegt die Gesamtvermoegens-Sicht.
    for note in getattr(total_summary, "assumption_notes", ()) or ():
        if note not in reasoning:
            reasoning.append(note)

    if manual_target_override:
        return

    # VORSORGE-PROJECTION-001: externe Vorsorge (nicht verwaltet, eigene
    # Kategorie) fliesst weder in Zaehler noch Nenner der Exposure-Quoten ein
    # -- ausser der Berater hat bewusst eine Aufteilung erfasst.
    pension_exposure = getattr(total_summary, "pension_exposure_amounts_rappen", None) or {}
    exposure_amounts = {
        key: int(total_summary.amounts_rappen.get(key, 0)) + int(pension_exposure.get(key, 0))
        for key in total_summary.amounts_rappen
    }
    exposure_base = (
        int(total_summary.total_rappen)
        - int(getattr(total_summary, "pension_bound_rappen", 0) or 0)
        + sum(int(value) for value in pension_exposure.values())
    )
    external_real_estate_bps = _bps(exposure_amounts["real_estate"], max(1, exposure_base))
    if external_real_estate_bps > 3000:
        reduction = min(500, int(round((external_real_estate_bps - 3000) * 0.25)))
        targets["real_estate"] = max(minimums["real_estate"], targets["real_estate"] - reduction)
        reasoning.append("Das hohe Immobilien-Exposure im Gesamtvermoegen reduziert den Immobilienanteil im Beratungsvermoegen.")

    external_equity_bps = _bps(exposure_amounts["equities"], max(1, exposure_base))
    if external_equity_bps > 5000:
        reduction = min(400, int(round((external_equity_bps - 5000) * 0.2)))
        # Sicherheits-Fix (2026-08-03): Boden UND Decke muessen die AKTUELLEN
        # minimums/maximums respektieren (die ggf. per Bandbreiten-Override
        # verschaerft wurden), nicht die statischen House-Matrix-Werte.
        # Diese Funktion laeuft weiterhin, wenn NUR min_bps/max_bps (kein
        # target_bps) gesetzt wurde, da _has_manual_target_overrides()
        # (siehe manual_target_override oben) reine Min/Max-Overrides ohne
        # Zielquote nicht erfasst -- vorher konnte eine Bonds-Maximal-
        # Restriktion hier unbemerkt ueberschritten werden (live
        # reproduziert). Boden = das STRENGERE (hoehere) von House-Matrix-
        # Absolutfloor und aktuellem minimums["equities"], damit ein per
        # Override angehobenes Minimum nicht durch den statischen, ggf.
        # niedrigeren House-Matrix-Floor unterlaufen wird.
        equity_floor = max(int(house_matrix.equity_minimum_bps or 0), int(minimums["equities"]))
        targets["equities"] = max(equity_floor, targets["equities"] - reduction)
        targets["bonds"] = min(int(maximums["bonds"]), targets["bonds"] + reduction)
        reasoning.append("Bereits bestehende Aktienexposures im Gesamtvermoegen werden auf die Advisory-Strategie angerechnet.")


def _renditeziel_equity_tilt_bps(
    *,
    target_return_bps: int,
    current_equity_bps: int,
    min_equity_bps: int,
    max_equity_bps: int,
) -> int:
    """Sprint 2026-06-08 Option C: Equity-Tilt fuer Renditeziel-Goals.

    Returns signed delta in bps:
    - positiv = Equity-Erhoehung (Wachstums-Tilt fuer hohes Target)
    - negativ = Equity-Reduktion (Defensiv-Tilt fuer niedriges Target)
    - 0 = kein Tilt

    Logik (target in bps):
    - target < 250 bps (< 2.5% p.a.): Defensiv-Tilt von max 150 bps
    - target 250-400: kein Tilt (Standard-Bereich)
    - target 400-600: Wachstums-Tilt von max 150 bps
    - target > 600: Wachstums-Tilt von max 200 bps

    Resultat wird automatisch an die House-Matrix-Bandbreiten geclippt:
    - Equity-Erhoehung max = max_equity_bps - current_equity_bps (room nach oben)
    - Equity-Reduktion max = current_equity_bps - min_equity_bps (room nach unten)

    Strategietreue gewahrt: Tilt verlaesst NIE die Bandbreiten des Risikoprofils.
    """
    if target_return_bps <= 0:
        return 0

    # Raw Tilt-Magnitude basierend auf Target
    if target_return_bps < 250:
        raw_tilt = -150  # defensiver Tilt
    elif target_return_bps < 400:
        raw_tilt = 0  # Standard-Bereich, kein Tilt
    elif target_return_bps < 600:
        raw_tilt = 150  # leichter Wachstums-Tilt
    else:
        raw_tilt = 200  # staerkerer Wachstums-Tilt

    if raw_tilt == 0:
        return 0

    if raw_tilt > 0:
        # Wachstums-Tilt: clippen auf room nach oben
        room_up = max(0, int(max_equity_bps) - int(current_equity_bps))
        return min(raw_tilt, room_up)
    # Defensiv-Tilt: clippen auf room nach unten
    room_down = max(0, int(current_equity_bps) - int(min_equity_bps))
    return -min(abs(raw_tilt), room_down)


def _apply_goal_and_reserve_tilts(
    targets: dict,
    minimums: dict,
    maximums: dict,
    goals: list[Goal],
    limits_prefs: dict,
    asset_class_prefs: dict,
    recurring_net_cashflow_rappen: int,
    recurring_cashflow_projection_series_rappen: list[int],
    advisory_wealth_rappen: int,
    reasoning: list[str],
    unlocked_other_assets_rappen: int = 0,
    inflow_projection_series_rappen: list[int] | None = None,
) -> tuple[int, int]:
    from services.portfolio_engine import (
        _bps,
        _compute_reserve_for_inputs,
        _goal_projection_years,
        _norm_text,
        _saa_liquidity_ceiling_bps,
    )

    # C7: Reserve-Berechnung wird zentral in _compute_reserve_for_inputs gehandelt
    # (StrategyContext-Konsolidierung), Goal-Tilts auf Bandbreiten passieren hier.
    saa_liq_ceiling_bps: int = _saa_liquidity_ceiling_bps(maximums["liquidity"])
    reserve_needed_rappen, external_reserve_rappen = _compute_reserve_for_inputs(
        goals=goals,
        limits_prefs=limits_prefs,
        asset_class_prefs=asset_class_prefs,
        recurring_net_cashflow_rappen=recurring_net_cashflow_rappen,
        recurring_cashflow_projection_series_rappen=recurring_cashflow_projection_series_rappen,
        advisory_wealth_rappen=advisory_wealth_rappen,
        saa_liquidity_ceiling_bps=saa_liq_ceiling_bps,
        reasoning=reasoning,
        unlocked_other_assets_rappen=unlocked_other_assets_rappen,
        inflow_projection_series_rappen=inflow_projection_series_rappen,
    )
    # Goal-spezifische Bandbreiten-Tilts (Reduktion Aktien fuer kurze Vermoegensziele)
    for goal in goals:
        years = _goal_projection_years(goal)
        goal_type = _norm_text(goal.goal_type)
        if goal_type in ("Kapitalerhalt", "Vermoegensziel") and years <= 5:
            eq_reduction = min(200, max(0, targets["equities"] - minimums["equities"]))
            if eq_reduction > 0:
                # Sicherheits-Fix (2026-08-03): die Empfaenger-Seite (bonds/
                # liquidity) war bisher NICHT gegen die aktuellen Maximal-
                # grenzen geclippt -- im Unterschied zum Renditeziel-Tilt
                # direkt unterhalb, der das fuer seine bonds-Empfaenger-Seite
                # bereits korrekt tut (bonds_available-Berechnung). Eine vom
                # Berater gesetzte Bandbreiten-Restriktion auf bonds/liquidity
                # (_apply_band_preferences, laeuft VOR diesem Tilt) konnte
                # dadurch hier verletzt werden -- das nachgelagerte
                # _rebalance_to_total()-Sicherheitsnetz haelt zwar am Ende
                # die Grenzen ein, aber durch eine vom Tilt nicht beabsich-
                # tigte, im Reasoning-Text nicht sichtbare Umverteilung in
                # ANDERE Buckets. Hier bereits an der Quelle korrekt clippen,
                # symmetrisch zum Spender (equities via minimums).
                liquidity_room = max(0, int(maximums.get("liquidity", 10000)) - int(targets["liquidity"]))
                bonds_room = max(0, int(maximums.get("bonds", 10000)) - int(targets["bonds"]))
                eq_reduction = min(eq_reduction, 2 * liquidity_room, 2 * bonds_room)
            if eq_reduction > 0:
                targets["equities"] -= eq_reduction
                targets["liquidity"] += eq_reduction // 2
                targets["bonds"] += eq_reduction - eq_reduction // 2
                reasoning.append(f"Das Vermoegensziel '{goal.label}' mit kurzem Horizont reduziert den Aktienanteil leicht.")

    # Sprint 2026-06-08 Option C: Goal-Tilt fuer Renditeziele.
    # SAA bleibt Risikoprofil-bound (FINMA/Strategietreue), aber innerhalb der
    # House-Matrix-Bandbreiten reagiert sie auf das Renditeziel-Target:
    # - Niedriges Target (<2.5%): leichte Aktien-Reduktion (Kapitalerhalt-Tilt)
    # - Mittleres Target (2.5-4%): kein Tilt (Standard)
    # - Hohes Target (>4%): leichte Aktien-Erhoehung (Wachstums-Tilt)
    # Max ±200 bps pro Goal, immer geclippt an den Bandbreiten (min/max).
    # Opportunistische Renditeziele tilten NICHT (Hardness-Filter, ADR-konform).
    for goal in goals:
        goal_type = _norm_text(goal.goal_type)
        if goal_type != "Renditeziel":
            continue
        hardness = _norm_text(goal.hardness).lower()
        # ADR: nur Primaer-Renditeziele tilten (Hart wird im Frontend geblockt;
        # Opportunistisch ist nicht-tilt-wuerdig per Anlagephilosophie).
        if hardness not in ("primaer", "primary"):
            continue
        target_bps = int(getattr(goal, "target_return_bps", None) or 0)
        if target_bps <= 0:
            continue
        eq_shift = _renditeziel_equity_tilt_bps(
            target_return_bps=target_bps,
            current_equity_bps=int(targets.get("equities", 0)),
            min_equity_bps=int(minimums.get("equities", 0)),
            max_equity_bps=int(maximums.get("equities", 10000)),
        )
        if eq_shift == 0:
            continue
        if eq_shift > 0:
            # Wachstums-Tilt: Equity hoch, Bonds runter
            bonds_floor = int(minimums.get("bonds", 0))
            bonds_available = max(0, int(targets.get("bonds", 0)) - bonds_floor)
            eq_shift_capped = min(eq_shift, bonds_available)
            if eq_shift_capped > 0:
                targets["equities"] += eq_shift_capped
                targets["bonds"] -= eq_shift_capped
                reasoning.append(
                    f"Renditeziel '{goal.label}' ({target_bps/100:.2f}% p.a.) "
                    f"hebt den Aktienanteil um {eq_shift_capped} bps an (innerhalb der "
                    f"Bandbreiten, Strategietreue gewahrt)."
                )
        else:
            # Defensiver Tilt: Equity runter, Bonds hoch
            shift_abs = abs(eq_shift)
            bonds_ceiling = int(maximums.get("bonds", 10000))
            bonds_room = max(0, bonds_ceiling - int(targets.get("bonds", 0)))
            shift_capped = min(shift_abs, bonds_room)
            if shift_capped > 0:
                targets["equities"] -= shift_capped
                targets["bonds"] += shift_capped
                reasoning.append(
                    f"Renditeziel '{goal.label}' ({target_bps/100:.2f}% p.a.) "
                    f"senkt den Aktienanteil um {shift_capped} bps zugunsten Bonds "
                    f"(innerhalb der Bandbreiten)."
                )

    if advisory_wealth_rappen <= 0 or reserve_needed_rappen <= 0:
        return reserve_needed_rappen, 0

    # Auch fuer Tilt-Logik: capped_bps berechnen
    uncapped_required_liquidity_bps = _bps(reserve_needed_rappen, advisory_wealth_rappen)
    saa_required_bps = min(uncapped_required_liquidity_bps, saa_liq_ceiling_bps)

    if saa_required_bps <= targets["liquidity"]:
        return reserve_needed_rappen, external_reserve_rappen

    shift = saa_required_bps - targets["liquidity"]
    remaining = max(0, shift)
    for donor in ("bonds", "equities", "alternatives", "real_estate"):
        if remaining <= 0:
            break
        donor_floor = minimums[donor]
        available = max(0, targets[donor] - donor_floor)
        step = min(remaining, available)
        if step <= 0:
            continue
        targets[donor] -= step
        remaining -= step

    funded = shift - remaining
    if funded > 0:
        targets["liquidity"] += funded
        reasoning.append("Die strategische Liquiditaetsquote wird aus der Zielallokation finanziert.")
    return reserve_needed_rappen, external_reserve_rappen
