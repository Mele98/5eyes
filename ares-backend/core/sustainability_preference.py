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
    "Abgleich der Merkmale (SDGs bzw. ESG-Faktoren) mit den empfohlenen "
    "Produkten findet heute noch nicht statt. Ausschlusswünsche werden bei der "
    "Produktauswahl berücksichtigt, soweit im Beratungsprotokoll beschrieben."
)
HARD_EXCLUSION_LOCKED_NOTE = (
    "Harte, am Produkt belegte Ausschlüsse (inklusive Durchleuchtung breit "
    "diversifizierter Fonds) sind noch nicht verfügbar und können nicht "
    "vereinbart werden. Erfasste Ausschlusswünsche gelten als Vorgabe für die "
    "Produktauswahl."
)
# N-888-05 (Formulierungsvorschlag Dok. 86): Quelle der Themenzuordnung =
# Produktkatalog der Firma, keine internen Begriffe. NUR ausgeben, wenn die
# aktuelle Anlagestrategie die Ausschluesse nachweislich umsetzt (N-888-01);
# sonst EXCLUSION_DEVIATION_TEXT bzw. EXCLUSION_NO_STRATEGY_TEXT.
EXCLUSION_LIMIT_TEXT = (
    "Ausschlusswünsche: Produkte, die im Produktkatalog der Firma einem dieser "
    "Themen zugeordnet sind (z. B. Themenfonds), werden bei der Produktauswahl "
    "nicht verwendet. Die Zuordnung beruht auf Katalogangaben der Firma, nicht "
    "auf Daten eines ESG-Datenanbieters. Breit diversifizierte Fonds und ETFs "
    "werden nicht durchleuchtet und können Titel dieser Themen enthalten."
)
EXCLUSION_DEVIATION_TEXT = (
    "Ausschlusswünsche: Die aktuelle Anlagestrategie berücksichtigt die "
    "Ausschlusswünsche ({labels}) noch nicht. Sie darf so weder empfohlen "
    "noch umgesetzt werden und ist mit den Ausschlüssen neu zu berechnen."
)
EXCLUSION_NO_STRATEGY_TEXT = (
    "Ausschlusswünsche: Es ist noch keine Anlagestrategie berechnet. Die "
    "Ausschlusswünsche sind bei der Berechnung und Produktauswahl einzuhalten."
)
WAIVER_VOID_TEXT = (
    "Ein dokumentierter Kundenverzicht ist unwirksam, weil das Mandat keine "
    "Anlageberatung ist; die Ausschlusswünsche gelten vollständig."
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


def limit_texts(profile_code, exclusions, floor_status=None) -> list:
    """Protokoll/Ergebnis: was im Portfolio heute nicht beruecksichtigt wird.

    ``floor_status`` (evaluate_floor der aktuellen Anlagestrategie): der Satz
    zur Produktauswahl steht nur bei ``ok``; ``violated`` nennt die
    Abweichung, ``no_strategy``/``unreadable`` den offenen Stand. ``None``
    (Maske ohne Strategiebezug) beschreibt die Regel als Vorgabe."""
    texts = []
    if profile_code in PROFILE_LIMIT_TEXTS:
        texts.append(PROFILE_LIMIT_TEXTS[profile_code])
    if exclusions:
        if floor_status == FLOOR_VIOLATED:
            texts.append(EXCLUSION_DEVIATION_TEXT.format(labels=", ".join(exclusion_labels(exclusions))))
        elif floor_status in (FLOOR_NO_STRATEGY, FLOOR_UNREADABLE):
            texts.append(EXCLUSION_NO_STRATEGY_TEXT)
        else:
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


# ── N-888-01: Untergrenze an allen Wegen (eine Logik) ───────────────────────
# Aufrufer: routers/allocation.py (Generate, manuelles POST, Sensitivity) und
# services/recommendation_release_gate.py (Produktlauf, Finalize, Signatur,
# Advisory-PDF, Handoff). Beide holen die aktuelle Erfassung mit
# CURRENT_DECISION_SQL und entscheiden ausschliesslich mit evaluate_floor().
FLOOR_NONE = "none"                # keine Erfassung oder keine wirksamen Ausschluesse
FLOOR_OK = "ok"                    # Ausschluesse in den Praeferenzen wirksam gescreent
FLOOR_VIOLATED = "violated"        # mindestens ein Ausschluss gelockert
FLOOR_UNREADABLE = "unreadable"    # Erfassung oder Praeferenz-Snapshot nicht lesbar
FLOOR_NO_STRATEGY = "no_strategy"  # Ausschluesse, aber keine Anlagestrategie

CURRENT_DECISION_SQL = (
    "SELECT id, exclusions_json, waived_exclusions_json, review_due_on, captured_at "
    "FROM investment_preference_decisions WHERE mandate_id = :mandate_id "
    "ORDER BY sequence_no DESC LIMIT 1"
)

FLOOR_CHANNEL_LABELS = {
    "generate": "Die Anlagestrategie kann nicht berechnet werden",
    "manual_allocation": "Die manuelle Soll-Allokation kann nicht gespeichert werden",
    "sensitivity": "Die Sensitivitätsanalyse kann nicht berechnet werden",
    "recommendation": "Die Empfehlung kann nicht erstellt werden",
    "finalize": "Die Empfehlung kann nicht finalisiert werden",
    "advisory_pdf": "Der Advisory-Report kann nicht exportiert werden",
    "signature": "Das Dokument kann nicht unterzeichnet werden",
    "handoff": "Die Handelsliste kann nicht weitergeleitet werden",
    "client_pdf": "Das Kundendokument kann nicht erstellt werden",
}


def preferences_sha256(preferences_json) -> str | None:
    """SHA-256 des gespeicherten Praeferenz-Snapshots (Text, wie in der DB)."""
    if preferences_json is None:
        return None
    return hashlib.sha256(str(preferences_json).encode("utf-8")).hexdigest()


DOCUMENT_UNBOUND_TEXT = (
    "ist keiner Anlagestrategie eindeutig zugeordnet (vor der Bindung erzeugt "
    "oder Inhalt geändert). Bitte das Dokument neu erzeugen."
)
DOCUMENT_OUTDATED_TEXT = (
    "wurde vor der aktuellen Nachhaltigkeitspräferenz erzeugt. Bitte das "
    "Dokument neu erzeugen."
)


def effective_exclusions(decision, mandate_type):
    """(wirksame Ausschluesse, Verzicht unwirksam?) einer Erfassung.

    Ein Kundenverzicht wirkt nur, solange das Mandat Anlageberatung ist
    (N-888-03); ``ValueError`` bei unlesbaren Listen (fail-closed)."""
    if not decision:
        return [], False
    exclusions = json.loads(decision.get("exclusions_json") or "[]")
    waived = json.loads(decision.get("waived_exclusions_json") or "[]")
    if not isinstance(exclusions, list) or not isinstance(waived, list):
        raise ValueError("Ausschlusslisten sind keine Listen.")
    normalize_exclusions(exclusions)
    waiver_void = bool(waived) and mandate_type != WAIVER_MANDATE_TYPE
    if waiver_void:
        waived = []
    return [key for key in EXCLUSION_KEYS if key in exclusions and key not in waived], waiver_void


def evaluate_floor(decision, mandate_type, preferences_json, *, has_strategy=True) -> dict:
    """Untergrenze fuer genau einen Praeferenz-Stand.

    ``preferences_json``: dict oder JSON-Text (Snapshot der Soll-Allokation);
    ``None`` mit ``has_strategy=True`` = Altbestand ohne Snapshot -> keine
    Tilts -> nicht gescreent (fail-closed)."""
    result = {"status": FLOOR_NONE, "themes": [], "waiver_void": False,
              "decision_id": (decision or {}).get("id")}
    try:
        effective, waiver_void = effective_exclusions(decision, mandate_type)
    except (TypeError, ValueError):
        result["status"] = FLOOR_UNREADABLE
        return result
    result["waiver_void"] = waiver_void
    if not effective:
        return result
    if not has_strategy:
        result.update(status=FLOOR_NO_STRATEGY, themes=effective)
        return result
    prefs = preferences_json
    if isinstance(prefs, str):
        try:
            prefs = json.loads(prefs)
        except (TypeError, ValueError):
            result.update(status=FLOOR_UNREADABLE, themes=effective)
            return result
    if prefs is not None and not isinstance(prefs, dict):
        result.update(status=FLOOR_UNREADABLE, themes=effective)
        return result
    violations = floor_violations(prefs or {}, effective, [])
    result.update(status=FLOOR_VIOLATED if violations else FLOOR_OK, themes=violations or effective)
    return result


def floor_blocks(result) -> bool:
    return result.get("status") in (FLOOR_VIOLATED, FLOOR_UNREADABLE)


def floor_message(result, channel) -> str:
    label = FLOOR_CHANNEL_LABELS.get(channel, "Freigabe nicht möglich")
    if result.get("status") == FLOOR_UNREADABLE:
        return (
            f"{label}: Die Nachhaltigkeitspräferenz oder die Präferenzen der "
            "Anlagestrategie sind nicht lesbar."
        )
    labels = ", ".join(exclusion_labels(result.get("themes") or ()))
    return (
        f"{label}: Ausschlusswunsch der Kundin bzw. des Kunden ({labels}) ist in der "
        "Anlagestrategie gelockert. Bitte «Ausschliessen» oder «Untergewichten» "
        "wählen und neu berechnen; Lockern nur mit dokumentiertem Kundenverzicht "
        "(nur Anlageberatung)."
    )


def floor_stale_notice(result):
    """Hinweis in Maske/State: die aktuelle Strategie ist veraltet (N-888-01)."""
    if result.get("status") == FLOOR_UNREADABLE:
        return "Die Nachhaltigkeitspräferenz oder die Anlagestrategie ist nicht lesbar – bitte prüfen."
    if result.get("status") != FLOOR_VIOLATED:
        return None
    labels = ", ".join(exclusion_labels(result.get("themes") or ()))
    return (
        f"Anlagestrategie veraltet: Sie hält die Ausschlusswünsche ({labels}) nicht ein. "
        "Empfehlung, Finalisierung und Freigabe sind gesperrt, bis sie mit «Ausschliessen» "
        "bzw. «Untergewichten» neu berechnet ist."
    )


def floor_audit_payload(result, channel) -> str:
    return json.dumps({
        "event": "sustainability_floor_blocked",
        "channel": channel,
        "status": result.get("status"),
        "themes": list(result.get("themes") or ()),
        "decision_id": result.get("decision_id"),
    }, sort_keys=True)


def preference_notice(decision, today_iso) -> dict:
    """N-888-04: Status fuer Eignungspruefung, Produktlauf und Review."""
    if not decision:
        return {
            "status": REVIEW_MISSING,
            "notice": "Nachhaltigkeitspräferenz nicht erfasst (Erhebung nach dem Risikoprofil).",
        }
    due_on = decision.get("review_due_on")
    status = review_status(due_on, today_iso)
    return {"status": status, "notice": review_due_text(due_on) if status == REVIEW_DUE else None}
