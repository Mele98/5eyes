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

import hashlib
import json
import re
import unicodedata
from typing import Any, Iterable

from sqlalchemy import text

from services.risk_scoring import (
    HORIZON_YEARS,
    Q11_KNOCKOUT_MAX_SCORE_X10,
    Q13_NOT_INVESTED_INDEX,
    QUESTIONNAIRE_V1,
    QUESTIONNAIRE_V2,
    V2_WILLINGNESS_CAPS_X10,
    canonicalize_horizon_label,
    compute_willingness_v2,
)

REASON_NOT_STANDARD = "RISK_QUESTIONNAIRE_NOT_STANDARD"
REASON_POINTS_MISMATCH = "RISK_ANSWER_POINTS_MISMATCH"
REASON_HORIZON_MISMATCH = "RISK_ANSWER_HORIZON_MISMATCH"
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
        # H5c: Erfahrung getrennt von Kenntnissen ("experienced"); Altprofile
        # ohne diesen Schluessel bleiben gueltig.
        if not isinstance(row, dict) or not set(row) <= {"known", "experienced", "informed"}:
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
    """Antwortstruktur pruefen, Punkte ableiten und gegen den Client abgleichen.

    Fragen 1-11 sind in v1 und v2 identisch. Zusatzangaben von v2
    (questionnaire_v2_answers, consistency_note) sind nur mit
    questionnaire_version='v2' zulaessig und werden in
    ``evaluate_v2_submission`` geprueft.
    """
    if submission_version(body) == QUESTIONNAIRE_V1 and (
        getattr(body, "questionnaire_v2_answers", None) or getattr(body, "consistency_note", None)
    ):
        raise _not_standard("Angaben des Fragebogens v2 ohne Fragebogen-Version v2")
    for raw in (getattr(body, "knowledge_services_json", None), getattr(body, "knowledge_instruments_json", None)):
        if _has_nonstandard_source_marker(raw):
            raise _not_standard("Quelle ist nicht der Standard-Fragebogen")
    answers = getattr(body, "answers", None) or []
    derived, horizon_option = derive_standard_points(answers)

    mismatches = []
    for answer in _persistable_answers(answers):
        question = _int_or_none(_answer_value(answer, "question_number"))
        expected = derived.get(POINT_FIELD_BY_QUESTION.get(question, ""), 0)
        sent = _int_or_none(_answer_value(answer, "answer_points"))
        if sent != expected:
            mismatches.append({"field": f"answers[{question}].answer_points", "sent": sent, "derived": expected})
    for field, expected in derived.items():
        sent = _int_or_none(getattr(body, field, None))
        if sent != expected:
            mismatches.append({"field": field, "sent": sent, "derived": expected})
    if mismatches:
        raise RiskQuestionnaireIntegrityError(
            REASON_POINTS_MISMATCH,
            "Die mitgesendeten Punkte passen nicht zu den gewaehlten Antworten. "
            "Bitte den Fragebogen neu laden und erneut speichern.",
            mismatches=mismatches,
        )

    expected_years = HORIZON_YEARS[canonicalize_horizon_label(horizon_option)]
    label = canonicalize_horizon_label(getattr(body, "investment_horizon_label", ""))
    sent_years = _int_or_none(getattr(body, "investment_horizon_years", None))
    if HORIZON_YEARS.get(label) != expected_years or sent_years != expected_years:
        raise RiskQuestionnaireIntegrityError(
            REASON_HORIZON_MISMATCH,
            "Der Anlagehorizont passt nicht zur gewaehlten Antwort in Frage 8. "
            "Bitte den Fragebogen neu laden und erneut speichern.",
            answer_horizon=horizon_option,
            investment_horizon_label=getattr(body, "investment_horizon_label", None),
            investment_horizon_years=sent_years,
        )
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


# ── Fragebogen v2 (H5b, Dok. 105 Abschnitt 4) ──────────────────────────────────
#
# Fragen 1-11 bleiben wortgleich und mit ihren Punkten unveraendert. v2
# ergaenzt Q12-Q14 und den Q11-Knock-out -- ausschliesslich als Obergrenze der
# Risikobereitschaft (services.risk_scoring.compute_willingness_v2) -- sowie
# Konsistenz-Flags K1-K6, die das Profil nie aendern und nichts blockieren,
# aber eine dokumentierte Beraternotiz verlangen.
#
# Die v2-Antworten liegen nicht in risk_assessment_answers (Fragen 1-11, dort
# per CHECK begrenzt), sondern als kanonische Evidenz in
# risk_assessments.willingness_v2_json; Version und Definitions-Hash am Profil.
#
# AKTIVIERUNG (N-886-08): Tenant-Policy, Default AUS. tenants.
# risk_questionnaire_v2_enabled wird nur ueber die auditierte Admin-Einstellung
# PUT /tenants/me/risk-questionnaire-policy gesetzt, und nur mit Vermerk der
# IC-/Compliance-Freigabe der Grenzwerte (E3: 40/60/80 sind Startwerte).
# Wirksam ist v2 nur, wenn Flag UND Vermerk gesetzt sind. Ist v2 aktiv, nimmt
# der Server keine neue v1-Erhebung mehr an (N-886-01).
#
# DEFINITIONEN (N-886-04): Jede gespeicherte v2-Erhebung traegt den Hash ihrer
# Definition und wird mit genau dieser Definition nachgerechnet
# (QUESTIONNAIRE_DEFINITIONS). Eine geaenderte Definition (z. B. andere
# Grenzwerte nach IC-Freigabe) ist ein NEUER Eintrag; bestehende Eintraege
# werden nie veraendert (Hash-Pin im Test).

REASON_V2_DISABLED = "RISK_QUESTIONNAIRE_V2_DISABLED"
REASON_V2_REQUIRED = "RISK_QUESTIONNAIRE_V2_REQUIRED"
REASON_CONSISTENCY_NOTE_REQUIRED = "RISK_CONSISTENCY_NOTE_REQUIRED"
REASON_Q12_AMOUNT_IMPLAUSIBLE = "RISK_Q12_AMOUNT_IMPLAUSIBLE"

V2_APPROVAL_STATUS = (
    "Startwerte 40/60/80 (Entscheid E3); Aktivierung je Firma nur mit Vermerk "
    "der IC-/Compliance-Freigabe."
)
V2_EVIDENCE_SCHEMA = "RiskQuestionnaireV2Evidence/1"
REQUIRED_QUESTIONS_V2 = (12, 13, 14)
APPROVAL_REF_MIN_CHARS = 10

V2_QUESTIONS: dict[int, str] = {
    12: "Verlusttoleranz in Franken – Welcher vorübergehende Wertrückgang Ihres Anlagebetrags innerhalb eines Jahres wäre für Sie gerade noch tragbar, ohne die Anlagestrategie zu ändern?",
    13: "Tatsächliches Verhalten – Wie haben Sie in einem früheren starken Kursrückgang (z. B. 2008, März 2020 oder 2022) tatsächlich gehandelt?",
    14: "Dauer einer Verlustphase – Wie lange könnten Sie einen Wertrückgang aussitzen, bis sich die Anlage erholt hat?",
}
V2_OPTIONS: dict[int, tuple[str, ...]] = {
    12: ("Bis 5 %", "5 bis 10 %", "10 bis 20 %", "Über 20 %"),
    13: (
        "Ich habe (fast) alle Anlagen verkauft.",
        "Ich habe einen Teil der Anlagen verkauft.",
        "Ich habe meine Anlagen gehalten.",
        "Ich habe Anlagen hinzugekauft.",
        "Ich war damals nicht investiert.",
    ),
    14: ("Weniger als 1 Jahr", "1 bis 2 Jahre", "2 bis 4 Jahre", "Mehr als 4 Jahre"),
}
# Frage 12: Prozentsatz je Option fuer den vorgerechneten Frankenbetrag.
Q12_PCT: tuple[int, ...] = (5, 10, 20, 20)
# "Bis 5 % · bis ca. CHF 12'500 bei CHF 250'000 Anlagebetrag"
_Q12_AMOUNT_SUFFIX = re.compile(
    r"^(?P<prefix>bis|über|ueber) ca\. (?P<cur>[A-Z]{3}) (?P<amount>[0-9'’]{1,15}) "
    r"bei (?P<cur2>[A-Z]{3}) (?P<base>[0-9'’]{1,15}) Anlagebetrag$"
)

# Konsistenz-Flags (Dok. 105, 4.3): keine Punkte, nie Profilaenderung, kein Block.
CONSISTENCY_FLAGS: dict[str, str] = {
    "K1": "Anlageziel Kapitalerhalt (Frage 9) widerspricht der gewählten Risikopräferenz (Frage 10).",
    "K2": "Toleriertes Schwankungsband (Frage 10) passt nicht zur Reaktion auf einen Verlust von 20 % (Frage 11).",
    "K3": "Die Antworten zu den Fragen 9 bis 11 liegen weit auseinander; bitte mit dem Kunden besprechen.",
    "K4": "Risikobereitschaft ab «Wachstumsorientiert» bei wenig Erfahrung (keine eigene Krisenerfahrung nach Frage 13 oder keine dokumentierte Erfahrung mit Aktien bzw. Aktienfonds); erhöhte Aufklärung über Verlustrisiken.",
    "K5": "Risikobereitschaft ab «Wachstumsorientiert», aber für Aktien sind weder Kenntnisse noch Aufklärung dokumentiert (Art. 11/14 FIDLEG).",
    "K6": "Verlustgrenze der Strategie (P10) liegt unter der Untergrenze der Schwankungstoleranz (Frage 10); Verhalten gemäss Verlusttoleranz-Prüfung.",
}
# K4 "wenig Erfahrung" (Dok. 105 4.3: Q13 n.a. oder LB-A-Stufe "wenig"; N-886-07):
# Ares kennt die LB-A-Stufen nicht, sondern seit H5c die getrennte Erfahrung je
# Instrument. "Wenig" = in keiner dieser Zeilen Erfahrung dokumentiert. Bei
# Altprofilen ohne Erfahrungs-Spalte ist das nicht bewertbar -> nur Q13.
K4_EQUITY_EXPERIENCE_ROWS = ("Aktien", "Anlagefonds", "ETF")
# K6 haengt an der Verlusttoleranz-Pruefung P11 (eigenes Modul, inaktiv bis
# P2b, Entscheid E7) und wird erst mit deren Aktivierung gesetzt.
GROWTH_PROFILES = frozenset({"Wachstumsorientiert", "Dynamisch", "Aktien"})
CONSISTENCY_NOTE_MIN_CHARS = 20
CONSISTENCY_NOTE_MIN_WORDS = 3
CONSISTENCY_NOTE_MAX_CHARS = 4000
# Bei einer DSG-Loeschung wird die Notiz redigiert (services/client_erasure.py,
# REDACTION_MARKER); die Notizpflicht gilt dann als erfuellt dokumentiert.
ERASURE_REDACTION_MARKER = "[ERASED-DSG-ART-32]"
_CAP_PROFILE = {40: "Defensiv", 60: "Ausgewogen", 80: "Wachstumsorientiert"}

_V2_OPTION_INDEX = {
    q: {option_key(label): idx for idx, label in enumerate(labels)}
    for q, labels in V2_OPTIONS.items()
}


def _canonical_json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _definition_hash(definition: dict) -> str:
    return hashlib.sha256(_canonical_json(definition).encode("utf-8")).hexdigest()


def _v2_definition_2026_11_07() -> dict:
    """Definition v2 vom 2026-11-07 (Texte, Optionen, Grenzwerte, Regeln). Nie aendern."""
    return {
        "questionnaire_version": QUESTIONNAIRE_V2,
        "rules_version": "ares-risk-questionnaire-v2/2026-11-07b",
        "base_questions": "Fragen 1-11 unveraendert (v1, Vorlage)",
        "questions": [
            {
                "number": q,
                "text": V2_QUESTIONS[q],
                "options": list(V2_OPTIONS[q]),
                "max_score_x10": list(V2_WILLINGNESS_CAPS_X10[q]),
            }
            for q in REQUIRED_QUESTIONS_V2
        ],
        "q12_amount_pct": list(Q12_PCT),
        "q11_knockout": {"q_risk_behavior_points": 1, "max_score_x10": Q11_KNOCKOUT_MAX_SCORE_X10},
        "q13_not_invested_option": Q13_NOT_INVESTED_INDEX,
        "k4_experience_rows": list(K4_EQUITY_EXPERIENCE_ROWS),
        "consistency_flags": [{"code": c, "message": m} for c, m in CONSISTENCY_FLAGS.items()],
        "flag_rules": "K1-K6/2026-11-07b: K4 = Q13 n.a. oder keine Erfahrung in "
                      + "/".join(K4_EQUITY_EXPERIENCE_ROWS) + "; K5 = Aktien ohne Kenntnis/Aufklaerung",
        "consistency_note_min_chars": CONSISTENCY_NOTE_MIN_CHARS,
        "consistency_note_min_words": CONSISTENCY_NOTE_MIN_WORDS,
        "formula": "will_v2 = MIN(will_core, caps); final = MIN(capacity, will_v2); FZK <= 75",
    }


_CURRENT_DEFINITION = _v2_definition_2026_11_07()
QUESTIONNAIRE_V2_HASH = _definition_hash(_CURRENT_DEFINITION)
V2_RULES_VERSION = _CURRENT_DEFINITION["rules_version"]
# Registry: Hash -> Definition. Neue Definitionen werden ergaenzt, nie ersetzt.
QUESTIONNAIRE_DEFINITIONS: dict[str, dict] = {QUESTIONNAIRE_V2_HASH: _CURRENT_DEFINITION}


def questionnaire_v2_definition() -> dict:
    """Aktuelle (fuer neue Erhebungen gueltige) Definition v2."""
    return json.loads(_canonical_json(_CURRENT_DEFINITION))


def definition_for_hash(definition_hash) -> dict | None:
    definition = QUESTIONNAIRE_DEFINITIONS.get(str(definition_hash or ""))
    if definition is None or _definition_hash(definition) != definition_hash:
        return None
    return definition


def _definition_caps(definition: dict) -> dict[int, tuple[int, ...]]:
    return {int(q["number"]): tuple(int(v) for v in q["max_score_x10"]) for q in definition["questions"]}


def _definition_options(definition: dict) -> dict[int, tuple[str, ...]]:
    return {int(q["number"]): tuple(q["options"]) for q in definition["questions"]}


# ── Tenant-Policy (N-886-08) ──────────────────────────────────────────────────

_DEFAULT_TENANT_ID = "main"


def tenant_policy_row(db, tenant_id) -> tuple[int, str | None] | None:
    """(Flag, Freigabe-Vermerk) der Firma; None = keine Firma gefunden."""
    row = db.execute(
        text(
            "SELECT risk_questionnaire_v2_enabled, risk_questionnaire_v2_approval_ref "
            "FROM tenants WHERE id = :tid AND deleted_at IS NULL"
        ),
        {"tid": str(tenant_id or _DEFAULT_TENANT_ID)},
    ).first()
    if row is None:
        return None
    return int(row[0] or 0), (str(row[1]) if row[1] is not None else None)


def approval_ref_ok(ref) -> bool:
    return len(re.sub(r"\s+", " ", str(ref or "")).strip()) >= APPROVAL_REF_MIN_CHARS


def questionnaire_v2_state(db, user) -> dict:
    """Wirksame Policy der Firma des Benutzers (fail-closed: im Zweifel aus)."""
    row = tenant_policy_row(db, getattr(user, "tenant_id", None))
    flag, ref = row if row is not None else (0, None)
    return {
        "v2_enabled": bool(flag == 1 and approval_ref_ok(ref)),
        "approval_reference": ref if flag == 1 else None,
    }


def questionnaire_v2_enabled(db, user) -> bool:
    return questionnaire_v2_state(db, user)["v2_enabled"]


def questionnaire_v2_policy(db=None, user=None, *, enabled: bool | None = None) -> dict:
    """Antwort von GET /risk-questionnaire/policy (die Maske liest die Texte hier).

    ``enabled`` nur fuer Tests ohne Datenbank.
    """
    if enabled is None:
        state = questionnaire_v2_state(db, user)
    else:
        state = {"v2_enabled": bool(enabled), "approval_reference": None}
    on = state["v2_enabled"]
    return {
        "v2_enabled": on,
        "active_version": QUESTIONNAIRE_V2 if on else QUESTIONNAIRE_V1,
        "approval_reference": state["approval_reference"],
        "questionnaire_hash": QUESTIONNAIRE_V2_HASH,
        "approval_status": V2_APPROVAL_STATUS,
        **questionnaire_v2_definition(),
    }


# ── Erhebung ─────────────────────────────────────────────────────────────────

def submission_version(body) -> str:
    version = getattr(body, "questionnaire_version", None) or QUESTIONNAIRE_V1
    if version not in (QUESTIONNAIRE_V1, QUESTIONNAIRE_V2):
        raise _not_standard("unbekannte Fragebogen-Version")
    return version


def derive_v2_options(v2_answers, *, definition: dict | None = None) -> tuple[dict[int, int], list[dict]]:
    """Option je Zusatzfrage 12-14 und die kanonischen Antwortzeilen (fail-closed)."""
    options_by_q = _definition_options(definition) if definition else V2_OPTIONS
    index = (
        {q: {option_key(label): i for i, label in enumerate(labels)} for q, labels in options_by_q.items()}
        if definition else _V2_OPTION_INDEX
    )
    by_question: dict[int, str] = {}
    for answer in v2_answers or ():
        question = _int_or_none(_answer_value(answer, "question_number"))
        if question not in REQUIRED_QUESTIONS_V2:
            raise _not_standard("Fragebogen v2: unbekannte Zusatzfrage", question_number=question)
        if question in by_question:
            raise _not_standard(f"Frage {question} mehrfach beantwortet", question_number=question)
        by_question[question] = str(_answer_value(answer, "answer_label") or "").strip()
    missing = [q for q in REQUIRED_QUESTIONS_V2 if not by_question.get(q)]
    if missing:
        raise _not_standard("Fragebogen v2: Zusatzfragen fehlen", missing_questions=missing)
    options: dict[int, int] = {}
    rows: list[dict] = []
    for question in REQUIRED_QUESTIONS_V2:
        label = by_question[question]
        base, sep, suffix = label.partition(" · ")
        if sep and (question != 12 or not _Q12_AMOUNT_SUFFIX.match(suffix.strip())):
            raise _not_standard(f"Frage {question}: unbekannte Antwortoption", question_number=question)
        idx = index[question].get(option_key(base))
        if idx is None:
            raise _not_standard(f"Frage {question}: unbekannte Antwortoption", question_number=question)
        options[question] = idx
        rows.append({"question_number": question, "option_index": idx, "answer_label": label})
    return options, rows


def _amount(raw: str) -> int:
    return int(re.sub(r"['’]", "", raw))


def check_q12_amount(label: str, option_index: int, *, currency: str, ceiling_chf: int | None) -> None:
    """N-886-05: vorgerechneter Frankenbetrag in Frage 12 (falls vorhanden) pruefen.

    Betrag > 0, Anlagebetrag > 0, Betrag <= Anlagebetrag, Betrag = Prozentsatz
    der Option (Rundung +-1), Waehrung = Referenzwaehrung des Mandats und
    Anlagebetrag <= erfasstes Bruttovermoegen (nur CHF, ``ceiling_chf``).
    """
    _base, sep, suffix = str(label).partition(" · ")
    if not sep:
        return
    match = _Q12_AMOUNT_SUFFIX.match(suffix.strip())

    def fail(problem: str):
        raise RiskQuestionnaireIntegrityError(
            REASON_Q12_AMOUNT_IMPLAUSIBLE,
            f"Frage 12: Der Frankenbetrag ist nicht plausibel ({problem}). Bitte das "
            "Vermoegen pruefen und den Fragebogen neu laden.",
            question_number=12,
        )

    if match is None:
        fail("Format")
    amount, base = _amount(match["amount"]), _amount(match["base"])
    cur = str(currency or "CHF").upper()
    if match["cur"] != match["cur2"] or match["cur"] != cur:
        fail("Waehrung")
    if amount <= 0 or base <= 0 or amount > base:
        fail("Betrag ausserhalb des Anlagebetrags")
    expected = round(base * Q12_PCT[option_index] / 100)
    if abs(amount - expected) > 1:
        fail("Betrag passt nicht zur gewaehlten Prozentstufe")
    if (option_index < 3) != (match["prefix"] == "bis"):
        fail("bis/ueber passt nicht zur Option")
    if cur == "CHF":
        if not ceiling_chf or ceiling_chf <= 0:
            fail("kein Vermoegen erfasst")
        if base > ceiling_chf + 1:
            fail("Anlagebetrag uebersteigt das erfasste Vermoegen")


def _instrument_value(knowledge_instruments_json, row: str) -> dict | None:
    try:
        parsed = json.loads(knowledge_instruments_json or "{}")
    except (TypeError, ValueError):
        return None
    value = parsed.get(row) if isinstance(parsed, dict) else None
    return value if isinstance(value, dict) else None


def _instrument_documented(knowledge_instruments_json, row: str) -> bool:
    """N-886-06: Kenntnis ODER Aufklaerung (wie ELIG-KNOWLEDGE-001); Erfahrung allein genuegt nicht."""
    value = _instrument_value(knowledge_instruments_json, row) or {}
    return any(value.get(k) == 1 for k in ("known", "informed"))


def _little_experience(knowledge_instruments_json) -> bool:
    """K4-Teil "wenig Erfahrung": neue Erhebung (Spalte vorhanden) ohne Erfahrung."""
    try:
        parsed = json.loads(knowledge_instruments_json or "{}")
    except (TypeError, ValueError):
        return False
    if not isinstance(parsed, dict):
        return False
    rows = [v for v in parsed.values() if isinstance(v, dict)]
    if not rows or not any("experienced" in v for v in rows):
        return False  # Altprofil: Erfahrung nicht getrennt erfasst -> nicht bewertbar
    return not any(
        (_instrument_value(knowledge_instruments_json, r) or {}).get("experienced") == 1
        for r in K4_EQUITY_EXPERIENCE_ROWS
    )


def consistency_flags(
    *,
    q9: int,
    q10: int,
    q11: int,
    q13_option: int,
    effective_willingness_profile: str,
    knowledge_instruments_json,
    loss_tolerance_breach: bool | None = None,
) -> list[str]:
    """Reason-Codes K1-K6 (Reihenfolge stabil). Aendern nie das Profil."""
    flags: list[str] = []
    if q9 == 1 and q10 >= 3:
        flags.append("K1")
    if q10 >= 3 and q11 <= 2:
        flags.append("K2")
    if max(q9, q10, q11) - min(q9, q10, q11) >= 2:
        flags.append("K3")
    growth = effective_willingness_profile in GROWTH_PROFILES
    if growth and (q13_option == Q13_NOT_INVESTED_INDEX or _little_experience(knowledge_instruments_json)):
        flags.append("K4")
    if growth and not _instrument_documented(knowledge_instruments_json, "Aktien"):
        flags.append("K5")
    if loss_tolerance_breach:
        flags.append("K6")
    return flags


def consistency_note_ok(note) -> bool:
    text_ = re.sub(r"\s+", " ", str(note or "")).strip()
    return (
        CONSISTENCY_NOTE_MIN_CHARS <= len(text_) <= CONSISTENCY_NOTE_MAX_CHARS
        and len(text_.split(" ")) >= CONSISTENCY_NOTE_MIN_WORDS
    )


def _caps_payload(result) -> list[dict]:
    return [
        {"source": c.source, "option_index": c.option_index, "max_score_x10": c.max_score_x10}
        for c in result.caps
    ]


def _compute_for(definition: dict, *, core: int, q11: int, options: dict[int, int]):
    return compute_willingness_v2(
        core_willingness_score_x10=core,
        q_risk_behavior_points=q11,
        q12_option=options[12],
        q13_option=options[13],
        q14_option=options[14],
        caps_table=_definition_caps(definition),
        knockout_max_score_x10=int(definition["q11_knockout"]["max_score_x10"]),
    )


def _flag_messages(definition: dict) -> dict[str, str]:
    return {f["code"]: f["message"] for f in definition.get("consistency_flags") or []}


def evaluate_v2_submission(
    body,
    *,
    core_willingness_score_x10: int,
    currency: str = "CHF",
    ceiling_chf: int | None = None,
) -> dict:
    """v2-Teil beim Speichern: Optionen, Kappung, Flags, Notizpflicht, Evidenz.

    Raises RiskQuestionnaireIntegrityError (fail-closed).
    """
    definition = _CURRENT_DEFINITION
    options, rows = derive_v2_options(getattr(body, "questionnaire_v2_answers", None))
    check_q12_amount(rows[0]["answer_label"], options[12], currency=currency, ceiling_chf=ceiling_chf)
    result = _compute_for(
        definition, core=core_willingness_score_x10, q11=int(body.q_risk_behavior_points), options=options,
    )
    flags = consistency_flags(
        q9=int(body.q_investment_goal_points),
        q10=int(body.q_risk_preference_points),
        q11=int(body.q_risk_behavior_points),
        q13_option=options[13],
        effective_willingness_profile=result.effective_profile,
        knowledge_instruments_json=getattr(body, "knowledge_instruments_json", None),
    )
    note = re.sub(r"\s+", " ", str(getattr(body, "consistency_note", None) or "")).strip()
    if flags and not consistency_note_ok(note):
        raise RiskQuestionnaireIntegrityError(
            REASON_CONSISTENCY_NOTE_REQUIRED,
            "Die Antworten zur Risikobereitschaft enthalten Widersprueche. Bitte das "
            "Gespraech dazu in der Beraternotiz dokumentieren (mindestens "
            f"{CONSISTENCY_NOTE_MIN_CHARS} Zeichen); das Profil wird dadurch nicht veraendert.",
            consistency_flags=[{"code": c, "message": CONSISTENCY_FLAGS[c]} for c in flags],
        )
    if len(note) > CONSISTENCY_NOTE_MAX_CHARS:
        raise _not_standard("Beraternotiz zu lang")
    evidence = _evidence(definition, rows, result, flags)
    return {
        "result": result,
        "flags": flags,
        "note": note or None,
        "evidence_json": _canonical_json(evidence),
        "definition_hash": QUESTIONNAIRE_V2_HASH,
    }


def _evidence(definition: dict, rows: list[dict], result, flags: list[str]) -> dict:
    evidence = {
        "schema": V2_EVIDENCE_SCHEMA,
        "rules_version": definition["rules_version"],
        "answers": rows,
        "core_willingness_score_x10": result.core_score_x10,
        "willingness_cap_x10": result.cap_score_x10,
        "effective_willingness_score_x10": result.effective_score_x10,
        "caps": _caps_payload(result),
        "consistency_flags": flags,
    }
    # Kundenlesbare Saetze fuer PDF/Protokoll, mit der Evidenz gebunden.
    evidence["cap_reasons"] = v2_cap_reason_lines(evidence, definition=definition)
    evidence["consistency_messages"] = v2_flag_lines(evidence, definition=definition)
    return evidence


def validate_v2_persisted(assessment, *, core_willingness_score_x10: int) -> int:
    """Gespeichertes v2-Profil mit SEINER Definition nachrechnen.

    Prueft Kappung, Begruendungen, Konsistenz-Flags (neu abgeleitet aus Q9-Q11,
    Q13 und den Kenntnissen) und die Notizpflicht (N-886-03). Liefert die
    wirksame Bereitschaft. Raises ValueError (fail-closed, kein Raten).
    """
    definition = definition_for_hash(getattr(assessment, "questionnaire_hash", None))
    if definition is None:
        raise ValueError("Fragebogen-v2-Definition (Hash) unbekannt")
    try:
        evidence = json.loads(getattr(assessment, "willingness_v2_json", None) or "")
    except (TypeError, ValueError) as exc:
        raise ValueError("willingness_v2_json fehlt oder ist ungueltig") from exc
    if not isinstance(evidence, dict) or evidence.get("schema") != V2_EVIDENCE_SCHEMA:
        raise ValueError("willingness_v2_json hat ein unbekanntes Schema")
    try:
        options, rows = derive_v2_options(evidence.get("answers"), definition=definition)
    except RiskQuestionnaireIntegrityError as exc:
        raise ValueError(exc.message) from exc
    if evidence.get("answers") != rows:
        raise ValueError("v2-Antwortindex passt nicht zum Antworttext")
    q11 = int(getattr(assessment, "q_risk_behavior_points", 0) or 0)
    result = _compute_for(definition, core=core_willingness_score_x10, q11=q11, options=options)
    flags = consistency_flags(
        q9=int(getattr(assessment, "q_investment_goal_points", 0) or 0),
        q10=int(getattr(assessment, "q_risk_preference_points", 0) or 0),
        q11=q11,
        q13_option=options[13],
        effective_willingness_profile=result.effective_profile,
        knowledge_instruments_json=getattr(assessment, "knowledge_instruments_json", None),
    )
    expected = _evidence(definition, rows, result, flags)
    for key, value in expected.items():
        if evidence.get(key) != value:
            raise ValueError(f"willingness_v2_json.{key} passt nicht zur Herleitung")
    note = getattr(assessment, "consistency_note", None)
    if flags and not (consistency_note_ok(note) or str(note or "").strip() == ERASURE_REDACTION_MARKER):
        raise ValueError("Konsistenzhinweise ohne dokumentierte Beraternotiz")
    return result.effective_score_x10


def v2_columns_empty(assessment) -> bool:
    """N-886-02: ohne Version muessen alle v2-Spalten leer sein."""
    return all(
        getattr(assessment, name, None) in (None, "")
        for name in ("questionnaire_hash", "willingness_v2_json", "consistency_note")
    )


def v2_evidence(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def v2_cap_reason_lines(raw, *, definition: dict | None = None) -> list[str]:
    """Kundenlesbare Saetze zu wirksamen Kappungen (ohne interne Punkte)."""
    evidence = v2_evidence(raw)
    options_by_q = _definition_options(definition) if definition else V2_OPTIONS
    core = int(evidence.get("core_willingness_score_x10") or 0)
    lines = []
    for cap in evidence.get("caps") or []:
        source = str(cap.get("source") or "")
        limit = int(cap.get("max_score_x10") or 0)
        if limit >= core:
            continue  # Grenze liegt ueber der Kern-Bereitschaft: nicht wirksam
        if source == "Q11":
            reason = "Frage 11: Bei einem Verlust von 20 % alle Anlagen sofort verkaufen"
        else:
            q = int(source[1:]) if source[1:].isdigit() else 0
            opts = options_by_q.get(q, ())
            idx = int(cap.get("option_index") or 0)
            reason = f"Frage {q}: {opts[idx] if 0 <= idx < len(opts) else '?'}"
        profile = _CAP_PROFILE.get(limit, "eine tiefere Stufe")
        lines.append(f"{reason} – begrenzt die Risikobereitschaft auf höchstens «{profile}».")
    return lines


def v2_flag_lines(raw, *, definition: dict | None = None) -> list[str]:
    messages = _flag_messages(definition) if definition else CONSISTENCY_FLAGS
    return [
        f"{code}: {messages[code]}"
        for code in v2_evidence(raw).get("consistency_flags") or []
        if code in messages
    ]
