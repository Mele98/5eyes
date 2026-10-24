"""Integritaet des Risikoprofil-Fragebogens (Standard-Fragebogen nach Vorlage).

Zwei Aufgaben, beide fail-closed:

1. Beim Speichern (``validate_standard_submission``): Die Antwortstruktur muss
   dem Standard-Fragebogen entsprechen (Fragen 1-11 genau einmal, nur bekannte
   Optionen, keine pauschalen Platzhalter). Der Server leitet die Punkte selbst
   aus den gewaehlten Optionen ab -- mit derselben Zuordnung Index -> Punkte wie
   der Fragebogen im Desktop-Frontend. Weichen die mitgesendeten Punkte
   (``answers[*].answer_points`` oder ``q_*_points``) davon ab, wird abgelehnt
   statt still korrigiert.
2. Beim Verwenden eines gespeicherten Profils (``known_nonstandard_evidence``,
   ausgewertet in ``validate_risk_assessment_model_input``):
   Profile, die nachweislich aus dem gesperrten Beta-Editor stammen, sind nicht
   strategiefaehig. Altprofile aus dem Standard-Fragebogen bleiben unberuehrt
   (die bisherige Legacy-Erkennung bleibt massgeblich); es wird nur ein
   positiver Nachweis der Fremdherkunft ausgewertet.

Optionstexte und Punkttabellen sind 1:1 aus dem Fragebogen im Desktop-
Frontend uebernommen; ``test_risk_questionnaire_frontend_parity`` haelt sie
gegen die HTML-Quelle synchron.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Iterable

REASON_NOT_STANDARD = "RISK_QUESTIONNAIRE_NOT_STANDARD"
RECAPTURE_HINT = "Risikoprofil mit dem Standard-Fragebogen neu erfassen."

REQUIRED_QUESTIONS = tuple(range(1, 12))

# Antwortoptionen je bewerteter Frage in Anzeige-Reihenfolge (Index = Position).
STANDARD_OPTIONS: dict[int, tuple[str, ...]] = {
    3: ("Bis CHF 6'000", "CHF 6'000 bis 9'000", "CHF 9'000 bis 12'000",
        "CHF 12'000 bis 20'000", "Über CHF 20'000"),
    5: ("Bis CHF 3'000", "CHF 3'000 bis 5'000", "CHF 5'000 bis 8'000",
        "CHF 8'000 bis 12'000", "Über CHF 12'000"),
    6: ("Bis CHF 100'000", "CHF 100'000 bis 250'000", "CHF 250'000 bis 1'000'000",
        "CHF 1'000'000 bis 2'000'000", "Über CHF 2'000'000"),
    7: ("0 %", "1 bis 10 %", "10 bis 25 %", "25 bis 50 %", "Über 50 %"),
    9: (
        "Das investierte Kapital soll erhalten bleiben.",
        "Mit dem Ertrag soll die heutige Kaufkraft beibehalten werden, wobei eine geringe Volatilität in Kauf genommen wird.",
        "Das investierte Kapital soll sich stetig vermehren unter Inkaufnahme des damit verbundenen Verlustrisikos.",
        "Es soll ein erhebliches Kapitalwachstum angestrebt werden unter Inkaufnahme des damit verbundenen höheren Verlustrisikos.",
    ),
    10: (
        "Ich bevorzuge Anlagen mit relativ geringem Risiko. Die Rendite steht für mich nicht im Vordergrund. (Wertschwankung ca. −4 % bis +6 %)",
        "Ich bin bereit, für eine moderate Rendite ein leicht höheres Risiko in Kauf zu nehmen. (Wertschwankung ca. −6 % bis +10 %)",
        "Ich strebe eine höhere Rendite an und bin bereit, dafür ein erhöhtes Risiko einzugehen. (Wertschwankung ca. −10 % bis +16 %)",
        "Ich strebe nach der maximalen Rendite und nehme hohe Risiken in Kauf. (Wertschwankung ca. −16 % bis +24 %)",
    ),
    11: (
        "Ein solch hoher Verlust bereitet mir grosse Angst und ich möchte alle Anlagen sofort verkaufen.",
        "Ich bin durch den Verlust sehr beunruhigt, handle aber vorerst noch nicht oder möchte höchstens einzelne Positionen verkaufen.",
        "Ich kann den Verlust vorübergehend akzeptieren und halte an meinen Anlagen fest.",
        "Ich investiere langfristig, deshalb akzeptiere ich solche Schwankungen und kaufe eventuell sogar hinzu.",
    ),
}
# Index -> Punkte, identisch zu RISK_*_POINTS bzw. idx+1 im Frontend.
STANDARD_POINTS: dict[int, tuple[int, ...]] = {
    3: (0, 1, 2, 3, 4),      # Einkommen
    5: (4, 3, 2, 1, 0),      # Verpflichtungen (invers)
    6: (0, 3, 6, 9, 12),     # freies Vermoegen
    7: (0, 3, 6, 9, 12),     # Sparquote
    9: (1, 2, 3, 4),
    10: (1, 2, 3, 4),
    11: (1, 2, 3, 4),
}
POINT_FIELD_BY_QUESTION: dict[int, str] = {
    3: "q_income_points",
    5: "q_obligations_points",
    6: "q_wealth_points",
    7: "q_savings_points",
    9: "q_investment_goal_points",
    10: "q_risk_preference_points",
    11: "q_risk_behavior_points",
}
HORIZON_OPTIONS: tuple[str, ...] = (
    "Bis 2 Jahre", "2 bis 3 Jahre", "3 bis 5 Jahre",
    "5 bis 7 Jahre", "8 bis 11 Jahre", "Mehr als 12 Jahre",
)
INCOME_SOURCE_OPTIONS: tuple[str, ...] = (
    "Berufliche Tätigkeit (selbstständig oder unselbstständig)",
    "Rente",
    "Vermietung von Liegenschaften",
    "Erträgen aus Anlagen",
    "Sonstige Quellen",
)
NO_INCOME_SOURCE = "Keine Angabe"
UNSCORED_PREFIX = {1: "Finanzdienstleistungen:", 2: "Finanzinstrumente:", 4: "Herkunft:"}

# Nachweis-Merkmale des gesperrten Beta-Editors (Payload-Builder dort).
NONSTANDARD_SOURCE_MARKERS = frozenset({"react_profiling_editor"})
NONSTANDARD_PLACEHOLDER_LABELS = (
    "Finanzdienstleistungen: dokumentiert im Beratungsgespraech",
    "Finanzinstrumente: dokumentiert im Beratungsgespraech",
    "Herkunft: Einkommen und Vermoegen plausibilisiert",
)

_UMLAUTS = str.maketrans({
    "\xe4": "ae", "\xf6": "oe", "\xfc": "ue",
    "\xc4": "Ae", "\xd6": "Oe", "\xdc": "Ue", "\xdf": "ss",
})


def norm_text(value) -> str:
    """Umlaute ausschreiben und trimmen (Readiness-Heuristik)."""
    return str(value or "").strip().translate(_UMLAUTS)


def option_key(value) -> str:
    """Vergleichsschluessel fuer Optionstexte (Leerraum, Striche, Umlaute)."""
    text = unicodedata.normalize("NFC", str(value or ""))
    text = text.replace(" ", " ")
    text = re.sub("[–—−]", "-", text)
    text = re.sub("[‘’´`]", "'", text)
    text = re.sub(r"\s+", " ", text).strip()
    return norm_text(text).casefold()


_OPTION_INDEX = {
    q: {option_key(label): idx for idx, label in enumerate(labels)}
    for q, labels in STANDARD_OPTIONS.items()
}
_HORIZON_INDEX = {option_key(label): label for label in HORIZON_OPTIONS}
_INCOME_SOURCE_KEYS = frozenset(option_key(label) for label in INCOME_SOURCE_OPTIONS)
_PLACEHOLDER_KEYS = frozenset(option_key(label) for label in NONSTANDARD_PLACEHOLDER_LABELS)
_HORIZON_SUFFIX = re.compile(r"^(?P<horizon>.+?)\s*[·-]\s*matrix-faktor$")


class RiskQuestionnaireIntegrityError(ValueError):
    """Antwortstruktur oder Punkte widersprechen dem Standard-Fragebogen."""

    def __init__(self, reason_code: str, message: str, **context: Any) -> None:
        self.reason_code = reason_code
        self.message = message
        self.context = context
        super().__init__(f"{message} [{reason_code}]")

    def as_detail(self) -> dict:
        return {"reason_code": self.reason_code, "message": self.message, **self.context}


def _not_standard(problem: str, **context: Any) -> RiskQuestionnaireIntegrityError:
    return RiskQuestionnaireIntegrityError(
        REASON_NOT_STANDARD,
        f"Antworten entsprechen nicht dem Standard-Fragebogen ({problem}). {RECAPTURE_HINT}",
        **context,
    )


def _answer_value(answer, key: str):
    if isinstance(answer, dict):
        return answer.get(key)
    return getattr(answer, key, None)


def _persistable_answers(answers: Iterable | None) -> list:
    """Dieselbe Filterung wie beim Persistieren (leere Zeilen fallen weg)."""
    kept = []
    for answer in answers or ():
        label = _answer_value(answer, "answer_label")
        if _answer_value(answer, "question_number") is None or _answer_value(answer, "answer_points") is None:
            continue
        if label is None or not str(label).strip():
            continue
        kept.append(answer)
    return kept


def _int_or_none(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _knowledge_table_ok(raw: str) -> bool:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return False
    if not isinstance(parsed, dict):
        return False
    for row in parsed.values():
        if not isinstance(row, dict) or not set(row) <= {"known", "informed"}:
            return False
        if any(v not in (0, 1) or isinstance(v, bool) for v in row.values()):
            return False
    return True


def _check_unscored(question: int, label: str) -> None:
    prefix = UNSCORED_PREFIX[question]
    if not label.startswith(prefix):
        raise _not_standard(f"Frage {question}: Antwort ohne Standard-Praefix", question_number=question)
    rest = label[len(prefix):].strip()
    if question in (1, 2):
        if not _knowledge_table_ok(rest):
            raise _not_standard(f"Frage {question}: keine Kenntnis-Tabelle", question_number=question)
        return
    if option_key(rest) == option_key(NO_INCOME_SOURCE):
        return
    parts = [option_key(part) for part in rest.split(",")]
    if not parts or any(part not in _INCOME_SOURCE_KEYS for part in parts):
        raise _not_standard("Frage 4: unbekannte Herkunft", question_number=question)


def _horizon_option(label: str) -> str:
    match = _HORIZON_SUFFIX.match(option_key(label))
    option = _HORIZON_INDEX.get(match.group("horizon")) if match else None
    if option is None:
        raise _not_standard("Frage 8: unbekannter Anlagehorizont", question_number=8)
    return option


def derive_standard_points(answers: Iterable | None) -> tuple[dict[str, int], str]:
    """Punkte je Score-Feld und Horizont-Option aus den gewaehlten Antworten.

    Raises RiskQuestionnaireIntegrityError (REASON_NOT_STANDARD), wenn die
    Antwortstruktur nicht dem Standard-Fragebogen entspricht.
    """
    by_question: dict[int, Any] = {}
    for answer in _persistable_answers(answers):
        question = _int_or_none(_answer_value(answer, "question_number"))
        if question not in REQUIRED_QUESTIONS:
            raise _not_standard("unbekannte Fragenummer", question_number=_answer_value(answer, "question_number"))
        if question in by_question:
            raise _not_standard(f"Frage {question} mehrfach beantwortet", question_number=question)
        by_question[question] = answer
    missing = [q for q in REQUIRED_QUESTIONS if q not in by_question]
    if missing:
        raise _not_standard("Fragen fehlen", missing_questions=missing)

    derived: dict[str, int] = {}
    for question in REQUIRED_QUESTIONS:
        label = str(_answer_value(by_question[question], "answer_label")).strip()
        if question in UNSCORED_PREFIX:
            _check_unscored(question, label)
        elif question in STANDARD_OPTIONS:
            idx = _OPTION_INDEX[question].get(option_key(label))
            if idx is None:
                raise _not_standard(f"Frage {question}: unbekannte Antwortoption", question_number=question)
            derived[POINT_FIELD_BY_QUESTION[question]] = STANDARD_POINTS[question][idx]
    return derived, _horizon_option(str(_answer_value(by_question[8], "answer_label")))


def validate_standard_submission(body) -> dict[str, int]:
    """Antwortstruktur gegen den Standard-Fragebogen pruefen."""
    for raw in (getattr(body, "knowledge_services_json", None), getattr(body, "knowledge_instruments_json", None)):
        if _has_nonstandard_source_marker(raw):
            raise _not_standard("Quelle ist nicht der Standard-Fragebogen")
    derived, _horizon = derive_standard_points(getattr(body, "answers", None) or [])
    return derived


def _has_nonstandard_source_marker(raw) -> bool:
    if raw is None:
        return False
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict) and parsed.get("source") in NONSTANDARD_SOURCE_MARKERS


def _loaded_answers(assessment) -> list:
    # Bei ORM-Zeilen nur bereits geladene Antworten auswerten (kein Lazy-Load,
    # kein DetachedInstanceError); der Quell-Marker reicht als Nachweis.
    state = getattr(assessment, "__dict__", {})
    if "_sa_instance_state" in state:
        return list(state.get("answers") or [])
    return list(getattr(assessment, "answers", None) or [])


def known_nonstandard_evidence(assessment) -> str | None:
    """Nachweis, dass ein gespeichertes Profil nicht aus dem Standard-Fragebogen stammt."""
    for field in ("knowledge_services_json", "knowledge_instruments_json"):
        if _has_nonstandard_source_marker(getattr(assessment, field, None)):
            return f"{field}: Quelle Beta-Editor"
    for answer in _loaded_answers(assessment):
        if option_key(_answer_value(answer, "answer_label")) in _PLACEHOLDER_KEYS:
            return f"Frage {_answer_value(answer, 'question_number')}: pauschale Platzhalter-Antwort"
    return None


def nonstandard_profile_message(evidence: str) -> str:
    return (
        "Risikoprofil stammt nicht aus dem Standard-Fragebogen und ist nicht "
        f"strategiefaehig ({evidence}). {RECAPTURE_HINT} [{REASON_NOT_STANDARD}]"
    )
