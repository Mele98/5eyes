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
CONFLICT_DATA_INSUFFICIENT = "CONFLICT_DATA_INSUFFICIENT"
WARN_FALLBACK = "WARN_FALLBACK"
WARN_OVERRIDE = "WARN_OVERRIDE"

ALL_CODES: tuple[str, ...] = (
    OK_COMFORTABLE,
    OK_TIGHT,
    CONFLICT_PROFILE_LIMITS,
    CONFLICT_GOAL_INCOMPATIBLE,
    CONFLICT_DATA_INSUFFICIENT,
    WARN_FALLBACK,
    WARN_OVERRIDE,
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
        "title": "Optimierer auf Bandbreiten-Mitte zurückgesetzt",
        "body_advisor": (
            "Der stochastische Optimierer konnte unter den aktuellen Constraints nicht "
            "konvergieren. Die Strategie verwendet stattdessen den Bandbreiten-Mittelwert "
            "des Risikoprofils. Bitte Ziele, Bandbreiten und Liquiditätsreserve prüfen."
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
