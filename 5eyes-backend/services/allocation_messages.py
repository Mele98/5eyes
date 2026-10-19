"""Stage 4 Foundation: Konflikt-Messages-Konstanten + Formatter.

Single Source of Truth für die advisor- und kundentauglichen Texte der
Allocation-Engine-Konflikt-/Hinweismeldungen. Sprachlich abgesichert gegen
verbotene Formulierungen (keine Aufforderung zur Risikoerhöhung, keine
Garantieversprechen, keine Marketing-Superlative).

Codex (Stage 4): nutzt MESSAGE_TEMPLATES + format_message() für die
Klassifizierungs-Funktion classify_messages(allocation, achievability,
optimization_status, mandate, assessment) → list[dict]. Diese Funktion
ist hier NICHT implementiert — sie ist Codex' Stage 4 Aufgabe.

Quelle: docs/planning/2026-05-23-stochastic-ux-and-messages-spec.md §1.
"""
from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------
# Code-Konstanten (stabil über Backend/Frontend/PDF)
# --------------------------------------------------------------------------

OK_COMFORTABLE = "OK_COMFORTABLE"
OK_TIGHT = "OK_TIGHT"
CONFLICT_PROFILE_LIMITS = "CONFLICT_PROFILE_LIMITS"
CONFLICT_GOAL_INCOMPATIBLE = "CONFLICT_GOAL_INCOMPATIBLE"
# GOAL-ACHIEVABILITY-ATTRIBUTION-001: mehrere bindende Ziele scheitern am
# SELBEN Engpass (gleiche failure_event_id) -- das ist EIN Konflikt, kein
# Mehrzielkonflikt zwischen unabhaengigen Ursachen.
CONFLICT_SHARED_BOTTLENECK = "CONFLICT_SHARED_BOTTLENECK"
CONFLICT_DATA_INSUFFICIENT = "CONFLICT_DATA_INSUFFICIENT"
WARN_FALLBACK = "WARN_FALLBACK"
WARN_OVERRIDE = "WARN_OVERRIDE"
WARN_BAND_OUTSIDE_HOUSE_MATRIX = "WARN_BAND_OUTSIDE_HOUSE_MATRIX"
WARN_GLOBAL_CAP_CLAMP = "WARN_GLOBAL_CAP_CLAMP"

ALL_CODES: tuple[str, ...] = (
    OK_COMFORTABLE,
    OK_TIGHT,
    CONFLICT_PROFILE_LIMITS,
    CONFLICT_GOAL_INCOMPATIBLE,
    CONFLICT_SHARED_BOTTLENECK,
    CONFLICT_DATA_INSUFFICIENT,
    WARN_FALLBACK,
    WARN_OVERRIDE,
    WARN_BAND_OUTSIDE_HOUSE_MATRIX,
    WARN_GLOBAL_CAP_CLAMP,
)

# Severities mappen auf die Frontend-Render-Klassen aus der UX-Spec §1.1.
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CONFLICT = "conflict"


# --------------------------------------------------------------------------
# Templates — sprachlich final, Placeholder via {curly}
# --------------------------------------------------------------------------

MESSAGE_TEMPLATES: dict[str, dict[str, Any]] = {
    OK_COMFORTABLE: {
        "severity": SEVERITY_INFO,
        "title": "Alle Ziele komfortabel erreichbar",
        "body_advisor": (
            "Die optimierte Allokation erreicht alle harten und primären Ziele mit "
            "einer Wahrscheinlichkeit von 80% oder höher innerhalb des dokumentierten "
            "Risikoprofils."
        ),
        "body_client": (
            "Ihre Ziele sind innerhalb des für Sie passenden Risikorahmens komfortabel "
            "erreichbar."
        ),
        "actions": (),
    },
    OK_TIGHT: {
        "severity": SEVERITY_WARNING,
        "title": "Ziel knapp erreichbar",
        "body_advisor": (
            "«{goal_label}» hat eine Eintrittswahrscheinlichkeit von ca. {prob}% — "
            "über der 50%-Schwelle, aber unter dem komfortablen Niveau von 80%. "
            "Hebel: Sparrate, Horizont, Zielbetrag, Hardness-Priorisierung."
        ),
        "body_client": (
            "Ihr Ziel «{goal_label}» ist erreichbar, aber mit ca. {prob}% knapper. "
            "Eine höhere Sparrate, ein längerer Horizont oder eine kleinere Zielsumme "
            "würden die Sicherheit erhöhen."
        ),
        "actions": ("increase_savings", "extend_horizon", "adjust_goal"),
    },
    CONFLICT_PROFILE_LIMITS: {
        "severity": SEVERITY_CONFLICT,
        "title": "Risikoprofil limitiert das Ziel",
        "body_advisor": (
            "Das gewünschte Ziel «{goal_label}» ist mit dem aktuellen Risikoprofil "
            "«{profile_label}» nicht plausibel erreichbar (P ≈ {prob}%). Eine höhere "
            "Zielrendite würde ein höheres Risikobudget erfordern. Optionen: Ziel "
            "anpassen, Horizont verlängern, Sparrate erhöhen — oder im Rahmen einer "
            "neuen FINMA-Eignungsprüfung die Risikofähigkeit neu erheben."
        ),
        "body_client": (
            "Mit Ihrem heutigen Anlageprofil ist «{goal_label}» schwer erreichbar. "
            "Bevor wir mehr Risiko nehmen, sollten wir prüfen, ob das Ziel oder der "
            "Zeithorizont angepasst werden kann. Eine andere Risikoeinstufung ist nur "
            "nach einer neuen Eignungsprüfung möglich."
        ),
        "actions": (
            "adjust_goal",
            "extend_horizon",
            "increase_savings",
            "review_riskprofile_with_assessment",
        ),
    },
    CONFLICT_GOAL_INCOMPATIBLE: {
        "severity": SEVERITY_CONFLICT,
        "title": "Ziele stehen im Konflikt",
        "body_advisor": (
            "Die Ziele «{goal_a}» und «{goal_b}» schliessen sich mit dem aktuellen "
            "Vermögen und Horizont mathematisch teilweise aus. Eine Priorisierung "
            "(Hardness) oder eine Anpassung eines der beiden Ziele ist nötig."
        ),
        "body_client": (
            "Sie haben zwei Ziele, die sich teilweise widersprechen. Wir sollten "
            "gemeinsam priorisieren, was Ihnen wichtiger ist."
        ),
        "actions": ("prioritize_goals", "adjust_goal"),
    },
    CONFLICT_SHARED_BOTTLENECK: {
        "severity": SEVERITY_CONFLICT,
        "title": "Gemeinsamer Engpass",
        "body_advisor": (
            "Die Ziele {goal_list} scheitern am selben Engpass ({event_label}). "
            "Es handelt sich um EINEN Konflikt, nicht um mehrere unabhängige: "
            "Wird der Engpass behoben (Zielbetrag, Zeitpunkt, Sparrate oder "
            "Priorität), verbessern sich alle betroffenen Ziele gemeinsam."
        ),
        "body_client": (
            "Mehrere Ihrer Ziele hängen am selben finanziellen Engpass. Wenn wir "
            "diesen einen Punkt gemeinsam lösen, profitieren alle betroffenen Ziele."
        ),
        "actions": ("prioritize_goals", "adjust_goal", "increase_savings"),
    },
    CONFLICT_DATA_INSUFFICIENT: {
        "severity": SEVERITY_CONFLICT,
        "title": "Datenbasis reicht für das Ziel nicht aus",
        "body_advisor": (
            "Aus heutigem Vermögen, geplanten Zuflüssen und Anlagehorizont ist "
            "«{goal_label}» mathematisch nicht zu decken — unabhängig vom Risikoprofil. "
            "Bitte Eingaben prüfen: Anlagebetrag, Cashflows, Zielbetrag, Zeithorizont."
        ),
        "body_client": (
            "Mit dem heutigen Anlagebetrag und Ihren geplanten Einzahlungen erreichen "
            "wir «{goal_label}» auch bei höchstem Risikoprofil nicht. Wir müssten "
            "gemeinsam einen Hebel ansetzen — etwa Zielbetrag, Sparrate oder "
            "Zeitrahmen."
        ),
        "actions": ("increase_savings", "extend_horizon", "adjust_goal"),
    },
    WARN_FALLBACK: {
        "severity": SEVERITY_WARNING,
        "title": "Allokation auf Bandbreiten-Mitte zurückgesetzt",
        "body_advisor": (
            # Sicherheits-Fix (2026-08-03): dieser Text feuerte bisher IMMER,
            # wenn der Risikobudget-Fallback greift -- auch im normalen
            # House-Matrix-Modus (Default), in dem gar kein stochastischer
            # Optimierer laeuft. Die vorherige Formulierung beschrieb damit
            # in der Mehrheit der Faelle den falschen Mechanismus.
            "Die berechnete Ziel-Allokation ueberschritt das Risikobudget Ihres "
            "Risikoprofils. Die Strategie verwendet stattdessen den Bandbreiten-Mittelwert "
            "des Risikoprofils als Basis (manuell gesetzte Mindest-/Maximalgrenzen bleiben "
            "dabei in Kraft). Bitte Ziele, Bandbreiten und Liquiditätsreserve prüfen."
        ),
        "body_client": (
            "Wir verwenden für Sie die bewährte Standardallokation Ihres Risikoprofils. "
            "Wenn Sie spezifische Zielvorgaben präzisieren, können wir die Allokation "
            "noch enger auf Sie zuschneiden."
        ),
        "actions": ("adjust_goal", "review_constraints"),
    },
    WARN_OVERRIDE: {
        "severity": SEVERITY_WARNING,
        "title": "Risikoprofil manuell übersteuert",
        "body_advisor": (
            "Das aus der Eignungsprüfung abgeleitete Risikoprofil wurde manuell auf "
            "«{override_label}» übersteuert (Begründung: «{reason}»). Die Allokation "
            "nutzt das übersteuerte Profil; die ursprüngliche Eignungsprüfung bleibt "
            "dokumentiert."
        ),
        "body_client": (
            "Wir haben gemeinsam mit Ihnen ein angepasstes Anlageprofil dokumentiert. "
            "Die ursprüngliche Einschätzung bleibt im Beratungsdossier erhalten."
        ),
        "actions": (),
    },
    # BAND-OVERRIDE-DISCLOSURE-001 (Audit 2026-10-14, F-BAND-1): eine
    # Mandatsbandbreite darf die Hausmatrix-Bandbreite des Risikoprofils
    # verlassen -- aber nie still. Die Hausmatrix ist der Eignungsrahmen.
    WARN_BAND_OUTSIDE_HOUSE_MATRIX: {
        "severity": SEVERITY_WARNING,
        "title": "Mandatsbandbreite ausserhalb der Hausmatrix",
        "body_advisor": (
            "{bucket_label}: Die Mandatsbandbreite {mandate_min} % bis {mandate_max} % "
            "liegt ausserhalb der Hausmatrix-Bandbreite {house_min} % bis {house_max} % "
            "des Risikoprofils «{profile_label}» (Score {score_bucket}). Die Allokation "
            "kann damit den Eignungsrahmen des Risikoprofils verlassen. Abweichung im "
            "Beratungsgespräch begründen und im Bandbreiten-Editor dokumentieren — "
            "ohne dokumentierte Begründung ist die Freigabe blockiert."
        ),
        "body_client": (
            "Für {bucket_label} wurde mit Ihnen eine Bandbreite vereinbart, die vom "
            "Standardrahmen Ihres Anlageprofils abweicht."
        ),
        "actions": ("review_constraints",),
    },
    # BAND-OVERRIDE-DISCLOSURE-001 (F-BAND-2): globale Modell-Obergrenze
    # (services/optimizer/constraints.py) kuerzt eine hoehere Vorgabe.
    WARN_GLOBAL_CAP_CLAMP: {
        "severity": SEVERITY_WARNING,
        "title": "Globale Obergrenze angewendet",
        "body_advisor": (
            "{bucket_label}: Die vorgegebene Obergrenze von {requested_max} % übersteigt "
            "die globale Modell-Obergrenze von {cap} %. Das stochastische Modell rechnet "
            "mit höchstens {cap} %; eine höhere Zielquote wird nicht umgesetzt."
        ),
        "body_client": (
            "Für {bucket_label} gilt eine allgemeine Obergrenze von {cap} %, die auch in "
            "Ihrer Strategie eingehalten wird."
        ),
        "actions": ("review_constraints",),
    },
}


# --------------------------------------------------------------------------
# Sprachlich verbotene Phrasen (gegen FINMA-/Beratungs-Ethik-Brüche)
# --------------------------------------------------------------------------

# Diese Substrings DÜRFEN in keinem MESSAGE_TEMPLATES-body vorkommen.
# Test deckt das ab. Bei Ergänzungen neuer Templates immer mitprüfen.
_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "Erhöhen Sie Ihr Risiko",
    "Erhöhen Sie das Risiko",
    "raise your risk",
    "garantiert",
    "Garantie",
    "ist sicher",
    "wird erreicht",
    "perfekt",
    "Top-Strategie",
    "Optimal für Sie",  # "Optimal" als Marketing-Superlativ; "optimiert" ist erlaubt
)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def format_message(code: str, **kwargs: Any) -> dict[str, Any]:
    """Liefert eine fertig formatierte Message für den gegebenen Code.

    Args:
        code: einer aus ALL_CODES.
        **kwargs: Placeholder-Werte (z.B. goal_label, prob, profile_label,
            override_label, reason, goal_a, goal_b). Fehlende Placeholder
            bleiben als {name} im Text stehen (defensiv, keine Exception).

    Returns:
        {"code", "severity", "title", "body_advisor", "body_client", "actions",
         "goal_id"} — actions als list[str]; goal_id ist None, wenn nicht
         als kwarg übergeben.

    Raises:
        ValueError: bei unbekanntem code (defensives Fail-Fast — Tippfehler
            in Codex' classify_messages soll sofort knallen, nicht silent).
    """
    template = MESSAGE_TEMPLATES.get(code)
    if template is None:
        raise ValueError(
            f"Unbekannter Message-Code {code!r}. "
            f"Erwartet einer aus: {', '.join(ALL_CODES)}"
        )
    return {
        "code": code,
        "severity": template["severity"],
        "title": _safe_format(template["title"], kwargs),
        "body_advisor": _safe_format(template["body_advisor"], kwargs),
        "body_client": _safe_format(template["body_client"], kwargs),
        "actions": list(template["actions"]),
        "goal_id": kwargs.get("goal_id"),
    }


def classify_messages(
    allocation: Any,
    achievability: list[dict] | tuple[dict, ...] | None,
    optimization_status: str | None,
    mandate: Any,
    assessment: Any,
) -> list[dict[str, Any]]:
    """Klassifiziert Allocation-/Goal-Zustand in advisor-facing Messages.

    Die Funktion ist deterministisch und nutzt nur persistierbare Inputs:
    TargetAllocation-Felder, Achievability-Liste und RiskAssessment-Override.
    Dadurch kann /current/payload ohne neuen Solver-Lauf dieselben Messages
    rekonstruieren.
    """
    del mandate  # reserved for later mandate-level data checks
    messages: list[dict[str, Any]] = []
    status = str(optimization_status or _get(allocation, "optimization_status") or "")
    limiting_factor = str(_get(allocation, "limiting_factor") or "")
    if status == "fallback_house_matrix":
        messages.append(format_message(WARN_FALLBACK))

    if int(_get(assessment, "is_overridden", 0) or 0) == 1 and _get(assessment, "override_score_x10") is not None:
        override_message = format_message(
            WARN_OVERRIDE,
            override_label=_get(assessment, "override_profile") or _get(assessment, "final_profile") or "Override",
            reason=_get(assessment, "override_reason") or "dokumentiert",
        )
        # RISK-OVERRIDE-WRITE-BOUNDARY-001 Restbefund B: die Meldung nennt die
        # wirksame RiskOverrideDecisionV1 (ID + Hash), damit Strategie-
        # Begruendung und Decision-Log eindeutig verknuepft sind.
        from services.risk_override_decision import decision_reference

        decision_id = _get(assessment, "override_decision_id")
        decision_hash = _get(assessment, "override_decision_hash")
        override_message["override_decision_id"] = decision_id
        override_message["override_decision_hash"] = decision_hash
        override_message["body_advisor"] += (
            f" Override-Entscheid: {decision_reference(decision_id, decision_hash)}."
            if decision_id
            else " Override ohne Decision-Nachweis (Altbestand vor RiskOverrideDecisionV1)."
        )
        messages.append(override_message)

    # GOAL-ACHIEVABILITY-ATTRIBUTION-001: die Plan-Solvenz-Zeile
    # (evaluation_scope=joint_plan) ist kein Ziel und erzeugt keine
    # Zielmeldung.
    priority_rows = [
        row for row in (list(achievability or []))
        if str(row.get("evaluation_scope") or "") != "joint_plan"
        and _hardness_key(row.get("hardness")) in ("hart", "primaer")
    ]
    if not priority_rows:
        return _dedupe_messages(messages)

    not_reachable = [
        row for row in priority_rows
        if str(row.get("status") or "") == "nicht_erreichbar"
    ]
    tight_rows = [
        row for row in priority_rows
        if str(row.get("status") or "") == "knapp"
    ]

    shared_event = _single_shared_failure_event(not_reachable)
    if len(not_reachable) >= 2 and shared_event is not None:
        # GOAL-ACHIEVABILITY-ATTRIBUTION-001: alle nicht erreichbaren
        # bindenden Ziele tragen dieselbe typisierte Ursache -> genau EINE
        # Konfliktmeldung, die alle betroffenen Ziele nennt.
        worst = _sort_by_probability(not_reachable)
        messages.append(format_message(
            CONFLICT_SHARED_BOTTLENECK,
            goal_list=", ".join(f"«{_goal_label(row)}»" for row in worst),
            event_label=_failure_event_label(shared_event),
            goal_id=worst[0].get("goal_id"),
        ))
    elif len(not_reachable) >= 2:
        worst = _sort_by_probability(not_reachable)
        messages.append(format_message(
            CONFLICT_GOAL_INCOMPATIBLE,
            goal_a=_goal_label(worst[0]),
            goal_b=_goal_label(worst[1]),
            goal_id=worst[0].get("goal_id"),
        ))
    elif not_reachable:
        row = _sort_by_probability(not_reachable)[0]
        if _is_profile_limited(allocation, limiting_factor):
            messages.append(format_message(
                CONFLICT_PROFILE_LIMITS,
                goal_label=_goal_label(row),
                profile_label=_profile_label(assessment),
                prob=_prob_pct(row),
                goal_id=row.get("goal_id"),
            ))
        else:
            messages.append(format_message(
                CONFLICT_DATA_INSUFFICIENT,
                goal_label=_goal_label(row),
                goal_id=row.get("goal_id"),
            ))
    elif tight_rows:
        row = _sort_by_probability(tight_rows)[0]
        messages.append(format_message(
            OK_TIGHT,
            goal_label=_goal_label(row),
            prob=_prob_pct(row),
            goal_id=row.get("goal_id"),
        ))
    else:
        messages.append(format_message(OK_COMFORTABLE))

    return _dedupe_messages(messages)


def _single_shared_failure_event(rows: list[dict]) -> str | None:
    """Gemeinsame typisierte Ursache ALLER Zeilen, sonst None.

    Nur ``failure_event_id`` zaehlt (vom Optimizer typisiert, siehe
    services/optimizer/goal_attribution.py). Zeilen ohne Ursache -- etwa
    Altbewertungen -- gelten konservativ als je eigene Ursache.
    """
    events = {str(row.get("failure_event_id") or "") for row in rows}
    if len(events) == 1:
        event = next(iter(events))
        return event or None
    return None


def _failure_event_label(event_id: str) -> str:
    prefix = "liquiditaetsengpass-jahr-"
    if event_id.startswith(prefix):
        return f"Liquiditätsengpass im Planjahr {event_id[len(prefix):]}"
    return "gemeinsame Zielschwelle"


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _hardness_key(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("hart", "hard"):
        return "hart"
    if raw in ("primaer", "primär", "primary"):
        return "primaer"
    if raw in ("opportunistisch", "opportunistic", "opp"):
        return "opportunistisch"
    return raw


def _goal_label(row: dict[str, Any]) -> str:
    return str(row.get("label") or row.get("goal_label") or row.get("goal_id") or "Ziel")


def _prob_pct(row: dict[str, Any]) -> int:
    try:
        return int(round(float(row.get("probability") or 0.0) * 100))
    except (TypeError, ValueError):
        return 0


def _sort_by_probability(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: float(row.get("probability") or 0.0))


def _profile_label(assessment: Any) -> str:
    if int(_get(assessment, "is_overridden", 0) or 0) == 1:
        return str(_get(assessment, "override_profile") or _get(assessment, "final_profile") or "dokumentiertes Profil")
    return str(_get(assessment, "final_profile") or "dokumentiertes Profil")


def _is_profile_limited(allocation: Any, limiting_factor: str) -> bool:
    if limiting_factor == "risikoprofil":
        return True
    risky = _get(allocation, "risky_fraction_bps_at_generation", None)
    if risky is None:
        risky = _get(allocation, "risky_fraction_bps", None)
    budget = _get(allocation, "risk_budget_bps_at_generation", None)
    if risky is None or budget is None:
        return False
    try:
        return int(risky) >= int(budget) - 50
    except (TypeError, ValueError):
        return False


def _dedupe_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str | None]] = set()
    out: list[dict[str, Any]] = []
    for msg in messages:
        key = (str(msg.get("code") or ""), msg.get("goal_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(msg)
    return out


def _safe_format(text: str, kwargs: dict[str, Any]) -> str:
    """str.format mit defensivem Fallback: fehlende Placeholder bleiben
    als {name} im Text stehen, statt eine KeyError-Exception zu werfen.

    Begründung: bei verschachtelten Aufrufen aus Codex' classify_messages
    soll ein vergessener Placeholder im UI sichtbar werden (Debug-Hilfe),
    nicht das gesamte Backend-Response zerstören.
    """
    class _SilentDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    return text.format_map(_SilentDict(kwargs))
