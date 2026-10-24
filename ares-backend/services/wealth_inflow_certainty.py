"""INFLOW-CERTAINTY-001 (CIO-Entscheid 2026-10-21, konservativ).

Vermoegenszufluesse (WealthInflow) tragen eine Gewissheit:

- ``sicher``   -- vertraglich/fix (Verkaufserloes mit Vertrag, zugesagter
  Bonus, Vorsorgebezug). Default fuer Bestandszeilen (``NULL`` = sicher):
  keine Verhaltensaenderung fuer bestehende Daten.
- ``unsicher`` -- Erbschaft/Bonus ohne Zusage. Ein unsicherer Zufluss senkt
  die Liquiditaetsreserve NICHT und fliesst NICHT in die Strategie-Simulation;
  er erscheint nur im Reasoning ("nicht eingerechnet (unsicher)") und als
  Info-Sensitivitaet "mit Zufluss".

Ein mit einer Vorsorge-Position verknuepfter Zufluss (``linked_position_id``,
VORSORGE-TRANSFER-001) ist eine Umbuchung innerhalb des Gesamtvermoegens und
damit immer ``sicher`` -- die API lehnt ``unsicher`` dort ab, und die Engine
behandelt Rohdaten mit Link unabhaengig vom Feld als sicher (die Quelle wird
ab dem Bezugsjahr ausgebucht; das Geld darf nicht verschwinden).

Eigenes Modul, damit ``services/portfolio_engine.py`` nicht waechst.
"""
from __future__ import annotations

CERTAINTY_CERTAIN = "sicher"
CERTAINTY_UNCERTAIN = "unsicher"
WEALTH_INFLOW_CERTAINTIES = (CERTAINTY_CERTAIN, CERTAINTY_UNCERTAIN)

UNCERTAIN_NOTE_MARKER = "nicht eingerechnet (unsicher)"
SENSITIVITY_LABEL = "mit Zufluss"


def effective_certainty(inflow) -> str:
    """Wirksame Gewissheit eines Zuflusses (fail-closed bei Fremdwerten)."""
    if getattr(inflow, "linked_position_id", None):
        return CERTAINTY_CERTAIN
    raw = getattr(inflow, "certainty", None)
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return CERTAINTY_CERTAIN
    value = str(raw).strip().lower() if isinstance(raw, str) else raw
    if value not in WEALTH_INFLOW_CERTAINTIES:
        raise ValueError(
            "Vermoegenszufluss: certainty muss 'sicher' oder 'unsicher' sein."
        )
    return value


def is_uncertain(inflow) -> bool:
    return effective_certainty(inflow) == CERTAINTY_UNCERTAIN


def scope_active_mandate_inflows(db, mandate, rows) -> list:
    """Aktive Zufluesse des Mandats (client-weit oder genau dieses Mandat).

    Vorher zweimal identisch in ``portfolio_engine`` (generate- und
    rebuild-Pfad). Fail-closed: ungueltiges is_active oder ein Mandat eines
    anderen Kunden bricht ab statt still zu verschwinden.
    """
    from models.mandates import Mandate

    scoped = []
    for inflow in rows:
        active = getattr(inflow, "is_active", None)
        if isinstance(active, bool) or not isinstance(active, int) or active not in (0, 1):
            raise ValueError("Vermoegenszufluss: is_active muss exakt 0 oder 1 sein.")
        inflow_mandate_id = getattr(inflow, "mandate_id", None)
        if inflow_mandate_id:
            inflow_mandate = db.query(Mandate).filter(Mandate.id == inflow_mandate_id).first()
            if inflow_mandate is None or inflow_mandate.client_id != mandate.client_id:
                raise ValueError(
                    "Vermoegenszufluss verweist auf ein Mandat eines anderen "
                    "Kunden oder auf ein fehlendes Mandat."
                )
            if inflow_mandate_id != mandate.id:
                continue
        if active == 1:
            scoped.append(inflow)
    return scoped


def split_by_certainty(inflows) -> tuple[list, list]:
    """(sichere, unsichere) Zufluesse; Reihenfolge bleibt erhalten."""
    certain: list = []
    uncertain: list = []
    for inflow in inflows or []:
        (uncertain if is_uncertain(inflow) else certain).append(inflow)
    return certain, uncertain


def certain_inflows(inflows) -> list:
    return split_by_certainty(inflows)[0]


def _fmt(rappen: int, currency: str) -> str:
    return f"{currency} " + f"{int(round(int(rappen) / 100)):,}".replace(",", "'")


def uncertain_inflow_sensitivity(
    *,
    uncertain_inflows: list,
    projection_years: int,
    start_year: int,
    inflation_series_bps: list[int] | None,
    reserve_inputs: dict,
    saa_liquidity_ceiling_bps: int,
    reserve_needed_rappen: int,
    external_reserve_rappen: int,
    currency: str = "CHF",
    reasoning: list[str] | None = None,
) -> dict | None:
    """Reasoning + Info-Sensitivitaet "mit Zufluss" fuer unsichere Zufluesse.

    Rein informativ: die Strategie (Reserve, Simulation, Gewichte) bleibt beim
    Szenario OHNE unsichere Zufluesse. Die Sensitivitaet rechnet nur die
    Reserve mit derselben Single-Source-Funktion
    (``_compute_reserve_for_inputs``) einmal mit eingerechneten Zufluessen nach,
    damit der Berater die Groessenordnung sieht.
    """
    if not uncertain_inflows:
        return None
    from services.portfolio_engine_gesamtvermoegen import _wealth_inflow_series_rappen
    from services.portfolio_engine_reserve import _compute_reserve_for_inputs

    uncertain_series = _wealth_inflow_series_rappen(
        uncertain_inflows, projection_years, start_year, inflation_series_bps,
    )
    base_series = [int(v) for v in (reserve_inputs.get("inflow_projection_series_rappen") or [])]
    length = max(len(base_series), len(uncertain_series))
    base_series += [0] * (length - len(base_series))
    combined = [
        base_series[i] + (int(uncertain_series[i]) if i < len(uncertain_series) else 0)
        for i in range(length)
    ]
    with_kwargs = dict(reserve_inputs)
    with_kwargs["inflow_projection_series_rappen"] = combined
    with_needed, with_external = _compute_reserve_for_inputs(
        saa_liquidity_ceiling_bps=int(saa_liquidity_ceiling_bps),
        reasoning=None,
        **with_kwargs,
    )

    items = []
    for inflow in uncertain_inflows:
        items.append({
            "id": str(getattr(inflow, "id", "") or ""),
            "label": str(getattr(inflow, "label", "") or ""),
            "source_type": str(getattr(inflow, "source_type", "") or ""),
            "expected_year": int(getattr(inflow, "expected_year", 0) or 0),
            "amount_rappen": int(getattr(inflow, "amount_rappen", 0) or 0),
            "is_recurring": int(getattr(inflow, "is_recurring", 0) or 0),
        })
    in_horizon_rappen = int(sum(int(v) for v in uncertain_series))
    info = {
        "label": SENSITIVITY_LABEL,
        "informational_only": True,
        "inflows": items,
        "in_horizon_amount_rappen": in_horizon_rappen,
        "without_inflow": {
            "reserve_needed_rappen": int(reserve_needed_rappen),
            "external_reserve_rappen": int(external_reserve_rappen),
        },
        "with_inflow": {
            "reserve_needed_rappen": int(with_needed),
            "external_reserve_rappen": int(with_external),
        },
    }
    if reasoning is not None:
        for item in items:
            recurring = " p.a." if item["is_recurring"] else ""
            reasoning.append(
                f"Vermoegenszufluss '{item['label']}' ({item['source_type']}, "
                f"{item['expected_year']}, {_fmt(item['amount_rappen'], currency)}{recurring}): "
                f"{UNCERTAIN_NOTE_MARKER} -- er senkt die Liquiditaetsreserve nicht "
                "und fliesst nicht in die Strategie-Simulation."
            )
        reasoning.append(
            f"Info-Sensitivitaet '{SENSITIVITY_LABEL}': wuerden die unsicheren "
            f"Zufluesse ({_fmt(in_horizon_rappen, currency)} im Simulationshorizont) "
            "eingerechnet, laege der Liquiditaetsreservebedarf bei "
            f"{_fmt(with_needed, currency)} statt {_fmt(reserve_needed_rappen, currency)} "
            f"(ausserhalb der SAA {_fmt(with_external, currency)} statt "
            f"{_fmt(external_reserve_rappen, currency)}). Nur Information -- die "
            "Strategie basiert auf dem Szenario ohne diese Zufluesse."
        )
    return info
