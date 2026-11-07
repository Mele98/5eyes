"""E1-E3 Nachhaltigkeitspraeferenzen (Dok. 106, Entscheid E0, 2026-11-07).

Reines Blattmodul (nur Standardbibliothek, Architektur-Ratsche
``FAN_OUT_EXEMPT_LEAVES``): Fragebogen-Definition, Ableitung des neutralen
Praeferenzprofils, Kundentexte, Review-Frist-Arithmetik und die Untergrenze
der Strategiebausteine. Persistenz (``InvestmentPreferenceDecisionV1``,
models/profiling.py), API (routers/profiling.py) und PDF
(services/pdf/documents/protokoll.py) lesen ausschliesslich hier.

Leitplanken (FIDLEG / FINMA-Aufsichtsmitteilung 05/2021 Greenwashing):

- Die Erhebung folgt dem Risikoprofil und aendert den Risikoscore nie.
- Profile sind neutrale Codes. Kein Kundentext bezeichnet Produkte oder das
  Portfolio als "nachhaltig" oder "verantwortungsbewusst"; erlaubt sind nur
  die Begriffe der Kundenpraeferenz (``NEUTRAL_PREFERENCE_PHRASES``).
- ``answered``/``declined`` und "nicht erfasst" (keine Zeile) bleiben
  getrennt; ``not_relevant`` ist eine Antwort, keine fehlende Angabe.
- Keine Engine-Wirkung: Ausschlusswuensche wirken nur als Untergrenze der
  Strategiebausteine (Validierung beim Generieren). Harte, am Produkt
  belegte Ausschluesse bleiben bis E4/E5 gesperrt (Codex F10).
- Review-Frist = Hauspolitik je Tenant (Default 36 Monate), keine
  gesetzliche Frist. Ablauf -> Hinweis "Eignungspruefung faellig", kein
  stilles Sperren.

Die Anzeigetexte sind Entwurf (``DISPLAY_TEXT_STATUS``); die Freigabe durch
Compliance und das Merkblatt sind offene Owner-Punkte.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA_VERSION = "InvestmentPreferenceDecisionV1"
QUESTIONNAIRE_VERSION = "praeferenzen-v1"
DERIVATION_VERSION = "praeferenzen-ableitung-v1"
DISPLAY_TEXT_STATUS = "entwurf_compliance_freigabe_offen"

RESPONSE_ANSWERED = "answered"
RESPONSE_DECLINED = "declined"
RESPONSE_STATUSES = (RESPONSE_ANSWERED, RESPONSE_DECLINED)

RELEVANCE_YES = "yes"
RELEVANCE_NOT_RELEVANT = "not_relevant"
RELEVANCES = (RELEVANCE_YES, RELEVANCE_NOT_RELEVANT)

CHARACTERISTIC_SDG = "sdg_alignment"
CHARACTERISTIC_ESG = "esg_factors"
CHARACTERISTIC_NONE = "no_specific"
CHARACTERISTICS = (CHARACTERISTIC_SDG, CHARACTERISTIC_ESG, CHARACTERISTIC_NONE)

# Neutrale Profilcodes (keine Labels "nachhaltig"/"verantwortungsbewusst").
PROFILE_NO_PREFERENCE = "no_preference"
PROFILE_SDG_GOALS = "sdg_goals"
PROFILE_ESG_FACTORS = "esg_factors"
PROFILE_UNSPECIFIED = "unspecified"
PROFILE_DECLINED = "declined"
PROFILE_CODES = (
    PROFILE_NO_PREFERENCE, PROFILE_SDG_GOALS, PROFILE_ESG_FACTORS,
    PROFILE_UNSPECIFIED, PROFILE_DECLINED,
)

# Ausschlusswuensche: dasselbe Themen-Vokabular wie die Strategiebausteine
# (services/portfolio_engine_payload.py::THEME_SUB_ASSET_CLASSES, per Test
# gepinnt). Die T-E1-Kategorien (kontroverse Waffen, Kohle, UNGC ...) folgen
# mit E4 (Audit 05 T2).
EXCLUSION_LABELS = {
    "fossil": "Fossile Energie",
    "defense": "Verteidigung",
    "tobacco": "Tabak",
    "alcohol": "Alkohol",
    "gaming": "Glücksspiel",
    "nuclear": "Kernenergie",
}
EXCLUSION_KEYS = ("fossil", "defense", "tobacco", "alcohol", "gaming", "nuclear")

DEFAULT_REVIEW_MONTHS = 36
REVIEW_MONTHS_MIN = 6
REVIEW_MONTHS_MAX = 120
WAIVER_REASON_MIN_LENGTH = 20
# Kundenverzicht nur in der Anlageberatung (T-E5); in der Vermoegensverwaltung
# ist ein Ausschluss eine Weisung (Art. 397 OR). Wert = Mandate.mandate_type.
WAIVER_MANDATE_TYPE = "Anlageberatung"

REVIEW_CURRENT = "current"
REVIEW_DUE = "due"
REVIEW_MISSING = "missing"

# Strategiebausteine: Tilt-Modi mit Produktwirkung "keine Themenprodukte"
# (Spiegel von portfolio_engine_payload.effective_theme_screening, per Test
# fuer alle Kombinationen gepinnt).
_SCREENING_MODES = frozenset({"exclude", "underweight"})

INTRO_TEXT = (
    "Nach dem Risikoprofil erfassen wir, ob und wie Nachhaltigkeitsaspekte bei "
    "Ihrer Geldanlage berücksichtigt werden sollen. Ihre Angaben verändern Ihr "
    "Risikoprofil nicht. Unterschieden werden die Ziele für nachhaltige "
    "Entwicklung der Vereinten Nationen (SDGs, 17 globale Ziele) und "
    "ESG-Faktoren (Umwelt, Soziales und Unternehmensführung)."
)
INFORMATION_TEXT = (
    "Information: Die Angabe beschreibt Ihren Wunsch. Sie ist keine Aussage "
    "über Eigenschaften der empfohlenen Produkte oder des Portfolios. Ein "
    "Abgleich Ihrer Präferenz mit den empfohlenen Produkten findet heute noch "
    "nicht statt; welche Angaben im Portfolio nicht berücksichtigt werden "
    "können, steht im Beratungsprotokoll."
)
HARD_EXCLUSION_LOCKED_NOTE = (
    "Harte, am Produkt belegte Ausschlüsse (inklusive Durchleuchtung breit "
    "diversifizierter Fonds) sind noch nicht verfügbar und können nicht "
    "vereinbart werden. Erfasste Ausschlusswünsche wirken als Vorgabe für die "
    "Strategiebausteine."
)
EXCLUSION_LIMIT_TEXT = (
    "Ausschlusswünsche: Produkte, die als Themenprodukt klassifiziert sind, "
    "werden nicht empfohlen. Breit diversifizierte Fonds und ETFs werden noch "
    "nicht durchleuchtet und können Titel dieser Themen enthalten. Ein am "
    "Produkt belegter harter Ausschluss ist noch nicht verfügbar."
)
NO_RISK_EFFECT_TEXT = "Die Nachhaltigkeitspräferenz verändert das Risikoprofil nicht."

QUESTIONS = (
    {
        "number": 1,
        "key": "esg_relevance",
        "text": "Sollen Nachhaltigkeitsaspekte bei Ihrer Geldanlage berücksichtigt werden?",
        "options": (
            {"value": RELEVANCE_YES, "label": "Ja"},
            {"value": RELEVANCE_NOT_RELEVANT, "label": "Nicht relevant"},
        ),
        "declined_label": "Keine Angabe (Kundin bzw. Kunde möchte sich nicht äussern)",
    },
    {
        "number": 2,
        "key": "esg_characteristic",
        "text": "Welches Merkmal soll bei Ihrer Anlage berücksichtigt werden? (eine Antwort)",
        "only_if": {"esg_relevance": RELEVANCE_YES},
        "options": (
            {
                "value": CHARACTERISTIC_SDG,
                "label": (
                    "Die Anlage soll mit einem oder mehreren Zielen für nachhaltige "
                    "Entwicklung der Vereinten Nationen (SDGs) vereinbar sein oder "
                    "zu ihnen beitragen."
                ),
            },
            {
                "value": CHARACTERISTIC_ESG,
                "label": (
                    "Die Anlage soll ökologische, soziale und "
                    "Unternehmensführungsfaktoren (ESG) berücksichtigen, die sich auf "
                    "die Wertentwicklung auswirken können."
                ),
            },
            {"value": CHARACTERISTIC_NONE, "label": "Keine bestimmte Präferenz"},
        ),
    },
    {
        "number": 3,
        "key": "exclusions",
        "text": "Gibt es Themen, die Sie in Ihrer Anlage ausschliessen möchten? (optional)",
        "only_if": {"esg_relevance": RELEVANCE_YES},
        "options": (
            {"value": "fossil", "label": "Fossile Energie"},
            {"value": "defense", "label": "Verteidigung"},
            {"value": "tobacco", "label": "Tabak"},
            {"value": "alcohol", "label": "Alkohol"},
            {"value": "gaming", "label": "Glücksspiel"},
            {"value": "nuclear", "label": "Kernenergie"},
        ),
    },
)

PROFILE_TEXTS = {
    PROFILE_NO_PREFERENCE: (
        "Erfasste Nachhaltigkeitspräferenz: keine. Nachhaltigkeitsaspekte sind "
        "bei der Geldanlage nicht relevant."
    ),
    PROFILE_SDG_GOALS: (
        "Erfasste Nachhaltigkeitspräferenz: Berücksichtigung von Zielen für "
        "nachhaltige Entwicklung der Vereinten Nationen (SDGs) gewünscht."
    ),
    PROFILE_ESG_FACTORS: (
        "Erfasste Nachhaltigkeitspräferenz: Berücksichtigung von ESG-Faktoren "
        "(Umwelt, Soziales, Unternehmensführung) mit möglicher Auswirkung auf die "
        "Wertentwicklung gewünscht."
    ),
    PROFILE_UNSPECIFIED: (
        "Erfasste Nachhaltigkeitspräferenz: Nachhaltigkeitsaspekte sind relevant, "
        "ohne Präferenz für ein bestimmtes Merkmal."
    ),
    PROFILE_DECLINED: (
        "Keine Angabe: Zu Nachhaltigkeitspräferenzen wurden keine Angaben gemacht."
    ),
}

# Was Ares heute im Portfolio NICHT beruecksichtigen kann (Protokoll-Pflicht).
PROFILE_LIMIT_TEXTS = {
    PROFILE_SDG_GOALS: (
        "Nicht berücksichtigt: Ares prüft heute nicht, ob Produkte oder das "
        "Portfolio mit SDGs vereinbar sind oder zu ihnen beitragen. Die Präferenz "
        "ist dokumentiert, im Portfolio aber nicht abgebildet."
    ),
    PROFILE_ESG_FACTORS: (
        "Nicht berücksichtigt: Ares wertet heute keine ESG-Daten eines "
        "Datenanbieters aus. Ein Abgleich der Präferenz mit dem Portfolio findet "
        "nicht statt; ein vom Berater gewähltes Auswahlkriterium der "
        "Produktauswahl steht im Dokument Anlagestrategie."
    ),
    PROFILE_UNSPECIFIED: (
        "Nicht berücksichtigt: Ein Abgleich der Präferenz mit dem Portfolio "
        "findet heute nicht statt."
    ),
}

# Erlaubte Kundenbegriffe trotz Claim-Waechter (ESG_CUSTOMER_CLAIM_LABELS
# enthaelt "Nachhaltig"): sie beschreiben die Praeferenz der Kundin bzw. des
# Kunden oder den Eigennamen der UN-Ziele, nie ein Produkt/Portfolio.
NEUTRAL_PREFERENCE_PHRASES = (
    "Nachhaltigkeitspräferenzen",
    "Nachhaltigkeitspräferenz",
    "Nachhaltigkeitspraeferenzen",
    "Nachhaltigkeitspraeferenz",
    "Nachhaltigkeitsaspekte",
    "Ziele für nachhaltige Entwicklung",
    "Zielen für nachhaltige Entwicklung",
)


def definition() -> dict:
    """Versionierte Fragebogen-Definition (Texte, Optionen, Ableitung)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "questionnaire_version": QUESTIONNAIRE_VERSION,
        "derivation_version": DERIVATION_VERSION,
        "display_text_status": DISPLAY_TEXT_STATUS,
        "intro_text": INTRO_TEXT,
        "information_text": INFORMATION_TEXT,
        "hard_exclusion_locked_note": HARD_EXCLUSION_LOCKED_NOTE,
        "exclusion_limit_text": EXCLUSION_LIMIT_TEXT,
        "no_risk_effect_text": NO_RISK_EFFECT_TEXT,
        "questions": [
            {**q, "options": [dict(o) for o in q["options"]]} for q in QUESTIONS
        ],
        "profile_texts": dict(PROFILE_TEXTS),
        "profile_limit_texts": dict(PROFILE_LIMIT_TEXTS),
        "derivation": {
            "declined": PROFILE_DECLINED,
            "not_relevant": PROFILE_NO_PREFERENCE,
            "yes+" + CHARACTERISTIC_SDG: PROFILE_SDG_GOALS,
            "yes+" + CHARACTERISTIC_ESG: PROFILE_ESG_FACTORS,
            "yes+" + CHARACTERISTIC_NONE: PROFILE_UNSPECIFIED,
        },
    }


def definition_hash() -> str:
    """SHA-256 ueber die kanonische Definition (sortiert, kompakt, UTF-8)."""
    raw = json.dumps(definition(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def derive_profile(response_status, esg_relevance, esg_characteristic) -> str:
    """Neutraler Profilcode; ``ValueError`` bei widerspruechlichen Antworten."""
    if response_status == RESPONSE_DECLINED:
        if esg_relevance is not None or esg_characteristic is not None:
            raise ValueError("Bei 'Keine Angabe' duerfen keine Antworten gesetzt sein.")
        return PROFILE_DECLINED
    if response_status != RESPONSE_ANSWERED:
        raise ValueError(f"Unbekannter Antwortstatus {response_status!r}.")
    if esg_relevance == RELEVANCE_NOT_RELEVANT:
        if esg_characteristic is not None:
            raise ValueError("Bei 'Nicht relevant' entfaellt Frage 2.")
        return PROFILE_NO_PREFERENCE
    if esg_relevance != RELEVANCE_YES:
        raise ValueError("Frage 1 (Relevanz) ist nicht beantwortet.")
    if esg_characteristic == CHARACTERISTIC_SDG:
        return PROFILE_SDG_GOALS
    if esg_characteristic == CHARACTERISTIC_ESG:
        return PROFILE_ESG_FACTORS
    if esg_characteristic == CHARACTERISTIC_NONE:
        return PROFILE_UNSPECIFIED
    raise ValueError("Frage 2 (Merkmal) ist nicht beantwortet.")


def normalize_exclusions(values) -> list:
    """Sortierte, deduplizierte Themen-Keys; unbekannte Keys -> ValueError."""
    keys = set()
    for value in values or ():
        if not isinstance(value, str) or value not in EXCLUSION_LABELS:
            raise ValueError(f"Unbekannter Ausschluss {value!r} (erlaubt: {list(EXCLUSION_KEYS)}).")
        keys.add(value)
    return [key for key in EXCLUSION_KEYS if key in keys]


def exclusion_labels(keys) -> list:
    return [EXCLUSION_LABELS[key] for key in EXCLUSION_KEYS if key in set(keys or ())]


def screened_themes(prefs) -> frozenset:
    """Themen, deren Produkte die Strategiebausteine NICHT empfehlen
    (Semantik von effective_theme_screening: exclude/underweight; neutral
    oder fehlend + ESG-Policy Negativ-Screening = exclude)."""
    prefs = prefs if isinstance(prefs, dict) else {}
    tilts = prefs.get("tilts") if isinstance(prefs.get("tilts"), dict) else {}
    policy = prefs.get("policy") if isinstance(prefs.get("policy"), dict) else {}
    negative_screening = policy.get("esg") == "negative_screening"
    screened = set()
    for key in EXCLUSION_KEYS:
        mode = tilts.get(key)
        if mode in (None, "neutral") and negative_screening:
            mode = "exclude"
        if mode in _SCREENING_MODES:
            screened.add(key)
    return frozenset(screened)


def floor_violations(prefs, exclusions, waived) -> list:
    """Kundenausschluesse (ohne dokumentierten Verzicht), die die
    Strategiebausteine lockern wuerden -- in Katalogreihenfolge."""
    required = set(exclusions or ()) - set(waived or ())
    screened = screened_themes(prefs)
    return [key for key in EXCLUSION_KEYS if key in required and key not in screened]


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    return 30 if month in (4, 6, 9, 11) else 31


def add_months_iso(iso_date: str, months: int) -> str:
    """'YYYY-MM-DD' + n Monate (Monatsende geklemmt, 31.01. + 1 = 28./29.02.)."""
    year, month, day = (int(part) for part in str(iso_date)[:10].split("-"))
    total = year * 12 + (month - 1) + int(months)
    new_year, new_month = divmod(total, 12)
    new_month += 1
    new_day = min(day, _days_in_month(new_year, new_month))
    return f"{new_year:04d}-{new_month:02d}-{new_day:02d}"


def resolve_review_months(tenant_value) -> int:
    """Tenant-Policy (Hauspolitik); NULL/ungueltig -> Default 36 Monate."""
    if isinstance(tenant_value, bool) or not isinstance(tenant_value, int):
        return DEFAULT_REVIEW_MONTHS
    if REVIEW_MONTHS_MIN <= tenant_value <= REVIEW_MONTHS_MAX:
        return tenant_value
    return DEFAULT_REVIEW_MONTHS


def review_policy_label(months: int) -> str:
    return (
        f"Hauspolitik: Überprüfung der Nachhaltigkeitspräferenz spätestens nach "
        f"{int(months)} Monaten (keine gesetzliche Frist)."
    )


def review_status(review_due_on, today_iso: str) -> str:
    if not review_due_on:
        return REVIEW_MISSING
    return REVIEW_DUE if str(today_iso)[:10] > str(review_due_on)[:10] else REVIEW_CURRENT


def review_due_text(review_due_on: str) -> str:
    return (
        "Eignungsprüfung fällig: Die Nachhaltigkeitspräferenz ist seit dem "
        f"{format_date_ch(review_due_on)} nicht mehr überprüft (Hauspolitik). "
        "Bitte mit der Kundin bzw. dem Kunden erneut erfassen."
    )


def format_date_ch(iso_date) -> str:
    raw = str(iso_date or "")[:10]
    parts = raw.split("-")
    return ".".join(reversed(parts)) if len(parts) == 3 else raw


def customer_text_claim_hits(text: str, claim_labels) -> list:
    """Claim-Waechter fuer Kundentexte: Treffer aus ``claim_labels`` nach
    Entfernen der erlaubten Praeferenz-Begriffe (Gross-/Kleinschreibung egal)."""
    lowered = str(text or "").lower()
    for phrase in sorted(NEUTRAL_PREFERENCE_PHRASES, key=len, reverse=True):
        lowered = lowered.replace(phrase.lower(), " ")
    return [label for label in claim_labels if str(label).lower() in lowered]


def limit_texts(profile_code, exclusions) -> list:
    """Protokoll/Ergebnis: was im Portfolio heute nicht beruecksichtigt wird."""
    texts = []
    if profile_code in PROFILE_LIMIT_TEXTS:
        texts.append(PROFILE_LIMIT_TEXTS[profile_code])
    if exclusions:
        texts.append(EXCLUSION_LIMIT_TEXT)
    return texts


def decision_snapshot(fields) -> dict:
    """Kanonischer Hash-Inhalt einer InvestmentPreferenceDecisionV1 (ohne
    id, tenant_id, created_at und decision_hash). ``fields``: Spalten als
    dict; Listen als JSON-Text oder Liste."""
    def get(name):
        return fields.get(name)

    def as_list(name):
        value = get(name)
        if isinstance(value, str):
            value = json.loads(value or "[]")
        return list(value or [])

    return {
        "schema_version": get("schema_version") or SCHEMA_VERSION,
        "mandate_id": get("mandate_id"),
        "client_id": get("client_id"),
        "sequence_no": int(get("sequence_no") or 0),
        "supersedes_id": get("supersedes_id"),
        "questionnaire_version": get("questionnaire_version"),
        "definition_hash": get("definition_hash"),
        "derivation_version": get("derivation_version"),
        "response_status": get("response_status"),
        "esg_relevance": get("esg_relevance"),
        "esg_characteristic": get("esg_characteristic"),
        "exclusions": as_list("exclusions_json"),
        "waived_exclusions": as_list("waived_exclusions_json"),
        "waiver_reasons_sealed": get("waiver_reasons_sealed"),
        "profile_code": get("profile_code"),
        "information_acknowledged": bool(get("information_acknowledged")),
        "client_confirmed": bool(get("client_confirmed")),
        "mandate_type_at_capture": get("mandate_type_at_capture"),
        "review_policy_months": int(get("review_policy_months") or 0),
        "review_due_on": get("review_due_on"),
        "captured_by": get("captured_by"),
        "captured_at": get("captured_at"),
    }
