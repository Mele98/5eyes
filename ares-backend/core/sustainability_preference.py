"""E2 Nachhaltigkeitspraeferenzen im Risikoprofil-Flow (Dok. 106, Codex-
Abnahmevertrag E2 2026-11-08, Owner-Vorgaben 2026-11-08).

Reines Blattmodul (nur Standardbibliothek, Architektur-Ratsche
``FAN_OUT_EXEMPT_LEAVES``): Fragebogen-Definition, Ableitung des neutralen
Praeferenzprofils, Zustandsmodell, Kundentexte und Review-Frist-Arithmetik.
Persistenz (``InvestmentPreferenceDecisionV1``, models/profiling.py), Zustand
mit Hash-Pruefung (services/recommendation_release_gate.py::preference_state), API
(routers/profiling.py) und PDF (services/pdf/documents/protokoll.py) lesen
ausschliesslich hier.

E2a = neutrale Erhebung. Leitplanken (FIDLEG / FINMA-Aufsichtsmitteilung
05/2021 Greenwashing, SBVg-Richtlinie):

- Die Erhebung folgt dem Risikoprofil und aendert weder Risikoscore noch
  Risikofaehigkeit, Ziele, Monte-Carlo oder Asset Allocation (Mutationstest
  tests/test_sustainability_e2a_contract.py).
- Zuerst nur Frage 1 (Ja / Nicht relevant / Keine Angabe); Merkmal,
  Ausschlusswuensche, Verzicht und Kenntnisnahme nur bei "Ja".
- Profile sind neutrale Codes. Kein Kundentext bezeichnet Produkte oder das
  Portfolio als "nachhaltig" oder "verantwortungsbewusst"; erlaubt sind nur
  die Begriffe der Kundenpraeferenz (``NEUTRAL_PREFERENCE_PHRASES``).
- Fuenf getrennte Pflichtzustaende (``STATE_*``): nicht beantwortet (keine
  Zeile), keine Praeferenz, Praeferenz angegeben, dokumentierter Verzicht
  (nur Anlageberatung), veraltet. "Keine Angabe" ist ein eigener Zustand,
  nie "keine Praeferenz".
- Nur Erfuellbares anbieten: ein Ausschlusswunsch ist nur waehlbar, wenn das
  aktive Produktuniversum ihn belegt erfuellen kann (E2b, Abdeckungspruefung
  services/portfolio_engine_payload.py::strategy_option_coverage); ohne
  Pruefung ist jeder Ausschluss gesperrt (``EXCLUSION_LOCKED_REASON``), der
  Server lehnt ihn ab (fail-closed). Unbekannt ist nie erfuellt.
- E2b: uebernommene Ausschluesse wirken NUR ueber den bestehenden
  Restriktionsmechanismus der Strategiebausteine (Tilt "Ausschliessen") als
  Untergrenze an allen Kanaelen (Fachvertrag unten).
- Review-Frist = Hauspolitik je Tenant (Default 36 Monate), keine
  gesetzliche Frist; Ereignis, Kundenwunsch oder erneute Eignungspruefung
  koennen frueher eine neue Erhebung ausloesen.

Die Anzeigetexte sind Entwurf (``DISPLAY_TEXT_STATUS``); die Freigabe durch
Compliance und das Merkblatt sind offene Owner-Punkte.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA_VERSION = "InvestmentPreferenceDecisionV1"
QUESTIONNAIRE_VERSION = "praeferenzen-v1"
DERIVATION_VERSION = "praeferenzen-ableitung-v1"
REVIEW_POLICY_VERSION = "praeferenz-review-v1"
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

# Kanal der Erhebung (Codex-Vertrag: Evidenz bindet den Kanal).
CAPTURE_CHANNELS = {
    "in_person": "Persönliches Gespräch",
    "phone": "Telefon",
    "video": "Videogespräch",
    "written": "Schriftlich",
}

# ── Pflichtzustaende (Codex-Vertrag E2, "getrennt und unverwechselbar") ──────
STATE_UNANSWERED = "unanswered"          # keine Erfassung (keine Zeile)
STATE_NO_PREFERENCE = "no_preference"    # Frage 1 = "Nicht relevant"
STATE_DECLINED = "declined"              # Frage 1 = "Keine Angabe"
STATE_PREFERENCE = "preference_stated"   # Frage 1 = "Ja"
STATE_WAIVER = "waiver_documented"       # "Ja" + dokumentierter Verzicht (nur Anlageberatung)
STATE_STALE = "stale"                    # veraltet: erneute Erhebung erforderlich
STATE_UNREADABLE = "unreadable"          # Nachweis nicht lesbar / Hash verletzt (fail-closed)
STATES = (
    STATE_UNANSWERED, STATE_NO_PREFERENCE, STATE_DECLINED, STATE_PREFERENCE,
    STATE_WAIVER, STATE_STALE, STATE_UNREADABLE,
)
STATE_LABELS = {
    STATE_UNANSWERED: "Noch nicht erfasst",
    STATE_NO_PREFERENCE: "Keine Präferenz (nicht relevant)",
    STATE_DECLINED: "Keine Angabe",
    STATE_PREFERENCE: "Präferenz angegeben",
    STATE_WAIVER: "Präferenz angegeben, Verzicht dokumentiert (Anlageberatung)",
    STATE_STALE: "Veraltet – erneute Erhebung erforderlich",
    STATE_UNREADABLE: "Nicht lesbar – bitte prüfen",
}
# Gruende fuer "veraltet" (mehrere moeglich, Reihenfolge = Anzeige).
STALE_DEFINITION = "definition_outdated"
STALE_REVIEW_POLICY = "review_policy_changed"
STALE_REVIEW_DUE = "review_due"
STALE_WAIVER_VOID = "waiver_void"
STALE_REASON_TEXTS = {
    STALE_DEFINITION: "Der Fragebogen wurde seit der Erfassung geändert.",
    STALE_REVIEW_POLICY: "Die Überprüfungsfrist (Hauspolitik) wurde seit der Erfassung geändert.",
    STALE_REVIEW_DUE: "Die Überprüfungsfrist (Hauspolitik) ist abgelaufen.",
    STALE_WAIVER_VOID: (
        "Der dokumentierte Verzicht ist nur in der Anlageberatung zulässig; das Mandat "
        "ist keine Anlageberatung mehr."
    ),
}

# Ausschlusswuensche: dasselbe Themen-Vokabular wie die Strategiebausteine
# (services/portfolio_engine_payload.py::THEME_SUB_ASSET_CLASSES, per Test
# gepinnt).
EXCLUSION_LABELS = {
    "fossil": "Fossile Energie",
    "defense": "Verteidigung",
    "tobacco": "Tabak",
    "alcohol": "Alkohol",
    "gaming": "Glücksspiel",
    "nuclear": "Kernenergie",
}
EXCLUSION_KEYS = ("fossil", "defense", "tobacco", "alcohol", "gaming", "nuclear")
# E2a: keine Abdeckungspruefung -> nichts ist belegt erfuellbar.
EXCLUSION_LOCKED_REASON = "Nicht wählbar: kein belegter Produktnachweis im Produktuniversum."

DEFAULT_REVIEW_MONTHS = 36
REVIEW_MONTHS_MIN = 6
REVIEW_MONTHS_MAX = 120
WAIVER_REASON_MIN_LENGTH = 20
# Verzicht nur in der Anlageberatung (T-E5); in der Vermoegensverwaltung kein
# pauschaler Verzichtspfad. Wert = Mandate.mandate_type.
WAIVER_MANDATE_TYPE = "Anlageberatung"

REVIEW_CURRENT = "current"
REVIEW_DUE = "due"
REVIEW_MISSING = "missing"

INTRO_TEXT = (
    "Nach dem Risikoprofil fragen wir, ob Nachhaltigkeitsaspekte bei Ihrer "
    "Geldanlage berücksichtigt werden sollen. Ihre Angaben verändern Ihr "
    "Risikoprofil nicht."
)
INFORMATION_TEXT = (
    "Information: Unterschieden werden die Ziele für nachhaltige Entwicklung der "
    "Vereinten Nationen (SDGs, 17 globale Ziele) und ESG-Faktoren (Umwelt, "
    "Soziales und Unternehmensführung). Ihre Angabe beschreibt Ihren Wunsch. Sie "
    "ist keine Aussage über Eigenschaften der empfohlenen Produkte oder des "
    "Portfolios. Ein Abgleich der Merkmale mit den empfohlenen Produkten findet "
    "heute nicht statt."
)
WAIVER_TEXT = (
    "Die Kundin bzw. der Kunde verzichtet darauf, dass die angegebene "
    "Nachhaltigkeitspräferenz bei der Empfehlung berücksichtigt wird "
    "(nur Anlageberatung, mit Begründung)."
)
WAIVER_NOT_ALLOWED_TEXT = (
    "Ein Verzicht ist nur in der Anlageberatung möglich; in der "
    "Vermögensverwaltung gibt es keinen pauschalen Verzicht."
)
NO_RISK_EFFECT_TEXT = "Die Nachhaltigkeitspräferenz verändert das Risikoprofil nicht."
NOT_CAPTURED_TEXT = "Nicht erfasst. Die Erhebung erfolgt nach dem Risikoprofil."

QUESTIONS = (
    {
        "number": 1,
        "key": "esg_relevance",
        "text": "Sollen Nachhaltigkeitsaspekte bei Ihrer Geldanlage berücksichtigt werden?",
        "options": (
            {"value": RELEVANCE_YES, "label": "Ja"},
            {"value": RELEVANCE_NOT_RELEVANT, "label": "Nicht relevant"},
        ),
        "declined_label": "Keine Angabe",
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
    {
        "number": 4,
        "key": "preference_waived",
        "text": "Verzicht (nur Anlageberatung, optional)",
        "only_if": {"esg_relevance": RELEVANCE_YES},
        "options": ({"value": "true", "label": WAIVER_TEXT},),
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

# Was Ares heute im Portfolio NICHT beruecksichtigt (Protokoll-Pflicht).
PROFILE_LIMIT_TEXTS = {
    PROFILE_SDG_GOALS: (
        "Nicht berücksichtigt: Ares prüft heute nicht, ob Produkte oder das "
        "Portfolio mit SDGs vereinbar sind oder zu ihnen beitragen. Die Präferenz "
        "ist dokumentiert, im Portfolio aber nicht abgebildet."
    ),
    PROFILE_ESG_FACTORS: (
        "Nicht berücksichtigt: Ares wertet heute keine ESG-Daten eines "
        "Datenanbieters aus. Ein Abgleich der Präferenz mit dem Portfolio findet "
        "nicht statt."
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
        "waiver_text": WAIVER_TEXT,
        "no_risk_effect_text": NO_RISK_EFFECT_TEXT,
        "capture_channels": dict(CAPTURE_CHANNELS),
        "questions": [
            {**q, "options": [dict(o) for o in q["options"]]} for q in QUESTIONS
        ],
        "profile_texts": dict(PROFILE_TEXTS),
        "profile_limit_texts": dict(PROFILE_LIMIT_TEXTS),
        "state_labels": dict(STATE_LABELS),
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


def locked_exclusion_options(reason: str = EXCLUSION_LOCKED_REASON) -> list:
    """E2a: alle Ausschlusswuensche gesperrt (keine Abdeckungspruefung)."""
    return [
        {"key": key, "label": EXCLUSION_LABELS[key], "available": False, "reason": reason}
        for key in EXCLUSION_KEYS
    ]


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
        f"{int(months)} Monaten (keine gesetzliche Frist; Ereignisse, Kundenwunsch "
        "oder eine erneute Eignungsprüfung können eine frühere Erhebung auslösen)."
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


def limit_texts(profile_code) -> list:
    """Protokoll/Ergebnis: was im Portfolio heute nicht beruecksichtigt wird."""
    return [PROFILE_LIMIT_TEXTS[profile_code]] if profile_code in PROFILE_LIMIT_TEXTS else []


def decision_snapshot(fields) -> dict:
    """Kanonischer Hash-Inhalt einer InvestmentPreferenceDecisionV1 (ohne
    id, tenant_id, created_at und decision_hash). ``fields``: Spalten als
    dict; Listen als JSON-Text oder Liste."""
    def get(name):
        return fields.get(name)

    value = get("exclusions_json")
    if isinstance(value, str):
        value = json.loads(value or "[]")
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
        "exclusions": list(value or []),
        "preference_waived": bool(get("preference_waived")),
        "waiver_reason_sealed": get("waiver_reason_sealed"),
        "profile_code": get("profile_code"),
        "information_acknowledged": bool(get("information_acknowledged")),
        "client_confirmed": bool(get("client_confirmed")),
        "capture_channel": get("capture_channel"),
        "mandate_type_at_capture": get("mandate_type_at_capture"),
        "review_policy_version": get("review_policy_version"),
        "review_policy_months": int(get("review_policy_months") or 0),
        "review_due_on": get("review_due_on"),
        "captured_by": get("captured_by"),
        "captured_at": get("captured_at"),
    }


def base_state(decision) -> str:
    """Zustand aus den Antworten allein (ohne Aktualitaetspruefung)."""
    if not decision:
        return STATE_UNANSWERED
    if decision.get("response_status") == RESPONSE_DECLINED:
        return STATE_DECLINED
    if decision.get("esg_relevance") == RELEVANCE_NOT_RELEVANT:
        return STATE_NO_PREFERENCE
    if decision.get("preference_waived"):
        return STATE_WAIVER
    return STATE_PREFERENCE


def stale_reasons(
    decision, *, today_iso, current_definition_hash, current_review_months, mandate_type,
) -> list:
    """Gruende, aus denen eine Erfassung veraltet ist (leer = aktuell)."""
    if not decision:
        return []
    reasons = []
    if (
        decision.get("definition_hash") != current_definition_hash
        or decision.get("questionnaire_version") != QUESTIONNAIRE_VERSION
    ):
        reasons.append(STALE_DEFINITION)
    if (
        decision.get("review_policy_version") != REVIEW_POLICY_VERSION
        or int(decision.get("review_policy_months") or 0) != int(current_review_months)
    ):
        reasons.append(STALE_REVIEW_POLICY)
    if review_status(decision.get("review_due_on"), today_iso) == REVIEW_DUE:
        reasons.append(STALE_REVIEW_DUE)
    if decision.get("preference_waived") and mandate_type != WAIVER_MANDATE_TYPE:
        reasons.append(STALE_WAIVER_VOID)
    return reasons


def preference_state(
    decision, *, today_iso, current_definition_hash, current_review_months, mandate_type,
    hash_valid=True,
) -> dict:
    """Ein Zustand fuer UI, API, PDF, Audit und Gates (Negativfall 10).

    ``hash_valid=False`` (gespeicherter decision_hash passt nicht zum Inhalt)
    -> ``unreadable`` (fail-closed). Veraltet hat Vorrang vor dem
    Antwortzustand; ``answer_state`` bleibt fuer die Anzeige erhalten."""
    answer_state = base_state(decision)
    if decision and not hash_valid:
        return {"state": STATE_UNREADABLE, "answer_state": answer_state, "stale_reasons": [],
                "label": STATE_LABELS[STATE_UNREADABLE], "notice": STATE_LABELS[STATE_UNREADABLE]}
    reasons = stale_reasons(
        decision, today_iso=today_iso, current_definition_hash=current_definition_hash,
        current_review_months=current_review_months, mandate_type=mandate_type,
    )
    state = STATE_STALE if reasons else answer_state
    notice = None
    if reasons:
        notice = "Erneute Erhebung erforderlich: " + " ".join(STALE_REASON_TEXTS[r] for r in reasons)
    elif state == STATE_UNANSWERED:
        notice = ("Nachhaltigkeitspräferenz nicht erfasst. " + REQUIRED_ANSWER_TEXT
                  + " (vor der Finalisierung erforderlich)")
    return {"state": state, "answer_state": answer_state, "stale_reasons": reasons,
            "label": STATE_LABELS[state], "notice": notice}


# ── Laden (eine Logik fuer API, PDF, Gates, Eignungspruefung) ─────────────────
# Das Blatt importiert keine DB-Schicht: Aufrufer reichen ``fetch_row`` /
# ``fetch_scalar`` (SQL + Parameter -> Zeile als dict bzw. Skalar) und die
# Hash-Funktion (core.evidence.evidence_hash) herein.
CURRENT_DECISION_SQL = (
    "SELECT * FROM investment_preference_decisions WHERE mandate_id = :mandate_id "
    "ORDER BY sequence_no DESC LIMIT 1"
)
TENANT_REVIEW_MONTHS_SQL = "SELECT sustainability_review_months FROM tenants WHERE id = :tid"


def decision_hash_valid(decision, hash_fn) -> bool:
    """Gespeicherter decision_hash == Hash des kanonischen Inhalts?"""
    if not decision:
        return True
    try:
        return hash_fn(decision_snapshot(decision)) == decision.get("decision_hash")
    except (TypeError, ValueError):
        return False


def load_state(fetch_row, fetch_scalar, hash_fn, *, mandate_id, tenant_id, mandate_type, today_iso,
               decision=None, decision_loaded=False) -> dict:
    """{decision, state, answer_state, stale_reasons, label, notice,
    review_months, binding} fuer ein Mandat (Negativfall 10: eine Quelle)."""
    if not decision_loaded:
        row = fetch_row(CURRENT_DECISION_SQL, {"mandate_id": mandate_id})
        decision = dict(row) if row else None
    months = resolve_review_months(
        fetch_scalar(TENANT_REVIEW_MONTHS_SQL, {"tid": tenant_id}) if tenant_id else None
    )
    info = preference_state(
        decision,
        today_iso=today_iso,
        current_definition_hash=definition_hash(),
        current_review_months=months,
        mandate_type=mandate_type,
        hash_valid=decision_hash_valid(decision, hash_fn),
    )
    return {**info, "decision": decision, "review_months": months,
            "binding": document_binding((decision or {}).get("decision_hash"), mandate_id)}


def release_violation(state_info, channel):
    """(reason_code, message) wenn veraltet/nicht lesbar, sonst None.

    Nachtrag 1 (Owner-Vertretung 2026-11-12, CH-Branchenstandard): vor der
    Finalisierung muss Frage 1 beantwortet sein ("Keine Angabe" zaehlt als
    beantwortet). "Noch nicht beantwortet" bleibt ein eigener Zustand und
    sperrt nur die Finalisierung; kein stilles Backfill fuer Bestandsmandate."""
    if channel == "finalize" and state_info.get("state") == STATE_UNANSWERED:
        label = RELEASE_CHANNEL_LABELS.get(channel, "Freigabe nicht möglich")
        return "SUSTAINABILITY_PREFERENCE_REQUIRED", f"{label}: {REQUIRED_ANSWER_TEXT}"
    if not state_blocks_release(state_info.get("state")):
        return None
    code = ("SUSTAINABILITY_PREFERENCE_UNREADABLE" if state_info.get("state") == STATE_UNREADABLE
            else "SUSTAINABILITY_PREFERENCE_STALE")
    return code, release_block_message(state_info, channel)


def document_violation(state_info, document_type, bound, title, channel):
    """Negativfall 7: (reason_code, message, state) wenn ein Kundendokument
    nicht an die AKTUELLE Erfassung gebunden ist, sonst None. Altbestand
    ohne Bindung (NULL) bleibt gueltig, solange keine Erfassung existiert."""
    if str(document_type or "") not in PREFERENCE_BOUND_DOCUMENT_TYPES:
        return None
    if bound is None and state_info.get("decision") is None:
        return None
    if bound == state_info.get("binding"):
        return None
    label = RELEASE_CHANNEL_LABELS.get(channel, "Freigabe nicht möglich")
    unbound = bound is None
    text = DOCUMENT_UNBOUND_TEXT if unbound else DOCUMENT_OUTDATED_TEXT
    return (
        "SUSTAINABILITY_DOCUMENT_UNBOUND" if unbound else "SUSTAINABILITY_DOCUMENT_OUTDATED",
        f"{label}: Das Dokument «{title}» {text}",
        "document_unbound" if unbound else "document_outdated",
    )


# Kundendokumente, die an die Erfassung gebunden sind (Signatur-Kanaele).
PREFERENCE_BOUND_DOCUMENT_TYPES = (
    "Anlagestrategie",
    "Anlagerezept",
    "Beratungsprotokoll",
    "Eignungsprüfung",
    "Override-Zustimmung",
    "Kostenausweis",
)


def state_blocks_release(state: str) -> bool:
    """Veraltet oder nicht lesbar blockiert Finalisierung, Signatur und
    Weiterleitung (Negativfaelle 4/6). "Nicht erfasst" blockiert nicht
    (Hinweis), wird aber nie als "keine Praeferenz" ausgegeben."""
    return state in (STATE_STALE, STATE_UNREADABLE)


# ── Dokumentbindung (Negativfaelle 6/7) ──────────────────────────────────────
# Jedes archivierte Kundendokument traegt die bei der Erzeugung aktuelle
# Erfassung (decision_hash) bzw. die Markierung "keine Erfassung". Signatur,
# Vor-Ort-Signatur und Weiterleitung vergleichen sie mit der aktuellen
# Erfassung: jede neue Version macht alte Dokumente unwirksam.
NO_DECISION_BINDING_PREFIX = "keine-erfassung:"

RELEASE_CHANNEL_LABELS = {
    "finalize": "Die Empfehlung kann nicht finalisiert werden",
    "signature": "Das Dokument kann nicht unterzeichnet werden",
    "handoff": "Die Handelsliste kann nicht weitergeleitet werden",
    "advisory_pdf": "Der Advisory-Report kann nicht exportiert werden",
    "recommendation": "Die Empfehlung kann nicht erstellt werden",
}


def document_binding(decision_hash, mandate_id) -> str:
    """Bindungswert eines Kundendokuments an die aktuelle Erfassung."""
    if decision_hash:
        return str(decision_hash)
    return NO_DECISION_BINDING_PREFIX + str(mandate_id or "")


DOCUMENT_OUTDATED_TEXT = (
    "gehört nicht zur aktuellen Nachhaltigkeitspräferenz (vorher erzeugt oder "
    "Inhalt geändert). Bitte das Dokument neu erzeugen."
)
DOCUMENT_UNBOUND_TEXT = (
    "ist keiner Nachhaltigkeitspräferenz zugeordnet (vor der Bindung erzeugt). "
    "Bitte das Dokument neu erzeugen."
)


def release_block_message(state_info, channel) -> str:
    label = RELEASE_CHANNEL_LABELS.get(channel, "Freigabe nicht möglich")
    if state_info.get("state") == STATE_UNREADABLE:
        return f"{label}: Der Nachweis der Nachhaltigkeitspräferenz ist nicht lesbar. Bitte prüfen."
    return f"{label}: Nachhaltigkeitspräferenz veraltet. Bitte erneut erfassen."


def release_audit_payload(state_info, channel, decision_id) -> str:
    return json.dumps({
        "event": "sustainability_preference_release_blocked",
        "channel": channel,
        "state": state_info.get("state"),
        "stale_reasons": list(state_info.get("stale_reasons") or ()),
        "decision_id": decision_id,
    }, sort_keys=True)


# ══ E2b: Uebernahme in die Strategiebausteine + Erfuellbarkeit ══════════════
# Fachvertrag (Handoff H-151, Abschnitt "Fachvertrag E2b"):
# - Ein Ausschlusswunsch der Kundin bzw. des Kunden ist nur waehlbar, wenn
#   das aktive Produktuniversum des Mandats je benoetigter Sub-Anlageklasse
#   mindestens ein Produkt mit freigegebenem, gueltigem Ausschlussnachweis
#   (Quelle, Stichtag; product_sustainability_attributes, Vier-Augen) hat.
#   Unbekannt, Entwurf, abgelaufen oder Seed-Feld zaehlen nie als erfuellt.
# - Wirkung NUR ueber den bestehenden Restriktionsmechanismus: der Ausschluss
#   wird im Block Nachhaltigkeit als Tilt "Ausschliessen" uebernommen
#   (read-only, "aus Kundenpraeferenz"); die Beraterin bzw. der Berater kann
#   nur strenger werden, nie lockern (Untergrenze an allen Kanaelen).
# - Kein positiver Nachhaltigkeits-Claim; die Offenlegung nennt die Quelle
#   der Zuordnung und dass breite Fonds nicht durchleuchtet werden.
EXCLUSION_EVIDENCE_CATEGORIES = {
    "fossil": "fossil_fuels",
    "defense": "weapons",
    "tobacco": "tobacco",
    "alcohol": "alcohol",
    "gaming": "gambling",
    "nuclear": "nuclear_power",
}
COVERAGE_EXEMPT_ASSET_CLASS = "Liquiditaet"
COVERAGE_NO_UNIVERSE_REASON = "Nicht wählbar: kein Produkt im aktiven Produktuniversum."


def coverage_reason(missing_sub_asset_classes) -> str:
    subs = ", ".join(str(s) for s in missing_sub_asset_classes)
    return f"Nicht wählbar: kein belegtes Produkt für {subs}."


def coverage_option(key, label, missing, needed, evidence=None) -> dict:
    """Ein Eintrag der Abdeckungspruefung (verfuegbar nur ohne Luecke)."""
    available = bool(needed) and not missing
    reason = None
    if not needed:
        reason = COVERAGE_NO_UNIVERSE_REASON
    elif missing:
        reason = coverage_reason(missing)
    return {"key": key, "label": label, "available": available, "reason": reason,
            "missing_sub_asset_classes": list(missing), "evidence": list(evidence or [])}


# Untergrenze (N-888-01, uebernommen und neu geprueft): eine Logik fuer alle
# Kanaele. Strenger als E1-E3: nur "Ausschliessen" haelt die Untergrenze ein
# (die Uebernahme ist read-only; "Untergewichten" waere eine Lockerung der
# Bezeichnung) und es gibt keinen Verzicht auf einen Ausschluss.
FLOOR_NONE = "none"
FLOOR_OK = "ok"
FLOOR_VIOLATED = "violated"
FLOOR_UNREADABLE = "unreadable"
FLOOR_NO_STRATEGY = "no_strategy"

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

EXCLUSION_LIMIT_TEXT = (
    "Ausschlusswünsche: In der Empfehlung werden ausserhalb der Liquidität nur "
    "Produkte verwendet, für die ein freigegebener Nachweis (Quelle, Stichtag) "
    "belegt, dass sie Unternehmen dieser Themen gemäss der Ausschlussschwelle "
    "der Firma ausschliessen. Massgeblich ist die Ausschlussrichtlinie des "
    "Produkts gemäss Nachweis; die einzelnen Titel breit diversifizierter Fonds "
    "werden nicht zusätzlich durchleuchtet."
)
EXCLUSION_NO_RUN_TEXT = (
    "Ausschlusswünsche: Es ist noch keine Produktauswahl erstellt. Sie verwendet "
    "ausserhalb der Liquidität nur Produkte mit belegtem Nachweis."
)
EXCLUSION_UNEVIDENCED_TEXT = (
    "Ausschlusswünsche: Die aktuelle Produktauswahl ist für die Ausschlusswünsche "
    "({labels}) nicht belegt. Sie darf so weder empfohlen noch umgesetzt werden; "
    "die Empfehlung ist neu zu erstellen."
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


def screened_themes(prefs) -> list:
    """Themen, die die Strategiebausteine wirksam AUSSCHLIESSEN (Tilt
    "exclude" oder neutral/fehlend bei ESG-Policy Negativ-Screening)."""
    prefs = prefs if isinstance(prefs, dict) else {}
    tilts = prefs.get("tilts") if isinstance(prefs.get("tilts"), dict) else {}
    policy = prefs.get("policy") if isinstance(prefs.get("policy"), dict) else {}
    negative_screening = policy.get("esg") == "negative_screening"
    screened = []
    for key in EXCLUSION_KEYS:
        mode = tilts.get(key)
        if mode in (None, "neutral") and negative_screening:
            mode = "exclude"
        if mode == "exclude":
            screened.append(key)
    return screened


def floor_violations(prefs, exclusions) -> list:
    required = set(exclusions or ())
    screened = set(screened_themes(prefs))
    return [key for key in EXCLUSION_KEYS if key in required and key not in screened]


def effective_exclusions(decision) -> list:
    """Ausschluesse der aktuellen Erfassung; ``ValueError`` wenn unlesbar."""
    if not decision:
        return []
    raw = decision.get("exclusions_json")
    exclusions = json.loads(raw or "[]") if isinstance(raw, str) else list(raw or [])
    if not isinstance(exclusions, list):
        raise ValueError("Ausschlussliste ist keine Liste.")
    return normalize_exclusions(exclusions)


def evaluate_floor(decision, preferences_json, *, has_strategy=True) -> dict:
    result = {"status": FLOOR_NONE, "themes": [], "decision_id": (decision or {}).get("id")}
    try:
        effective = effective_exclusions(decision)
    except (TypeError, ValueError):
        result["status"] = FLOOR_UNREADABLE
        return result
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
    violations = floor_violations(prefs or {}, effective)
    result.update(status=FLOOR_VIOLATED if violations else FLOOR_OK, themes=violations or effective)
    return result


def floor_blocks(result) -> bool:
    return result.get("status") in (FLOOR_VIOLATED, FLOOR_UNREADABLE)


def floor_message(result, channel) -> str:
    """Kurz: Kernaussage + Einstellung + was tun."""
    label = FLOOR_CHANNEL_LABELS.get(channel, "Freigabe nicht möglich")
    if result.get("status") == FLOOR_UNREADABLE:
        return f"{label}: Nachhaltigkeitspräferenz oder Strategie nicht lesbar. Bitte prüfen."
    labels = ", ".join(exclusion_labels(result.get("themes") or ()))
    return (
        f"{label}: Ausschlusswunsch ({labels}) gelockert. Einstellung: Strategiebausteine, "
        "Nachhaltigkeit. Bitte «Ausschliessen» lassen und neu berechnen."
    )


def floor_detail(result) -> str:
    labels = ", ".join(exclusion_labels(result.get("themes") or ()))
    return (
        f"Die Nachhaltigkeitspräferenz der Kundin bzw. des Kunden schliesst {labels} aus. "
        "Die Strategiebausteine übernehmen das als Untergrenze; Lockern ist nur über eine "
        "neue Erhebung der Präferenz möglich."
    )


def floor_stale_notice(result):
    if result.get("status") == FLOOR_UNREADABLE:
        return "Nachhaltigkeitspräferenz oder Anlagestrategie nicht lesbar – bitte prüfen."
    if result.get("status") != FLOOR_VIOLATED:
        return None
    labels = ", ".join(exclusion_labels(result.get("themes") or ()))
    return (
        f"Anlagestrategie veraltet: Ausschlusswunsch ({labels}) nicht eingehalten. "
        "Empfehlung, Finalisierung und Freigabe sind gesperrt, bis sie neu berechnet ist."
    )


def floor_audit_payload(result, channel) -> str:
    return json.dumps({
        "event": "sustainability_floor_blocked",
        "channel": channel,
        "status": result.get("status"),
        "themes": list(result.get("themes") or ()),
        "decision_id": result.get("decision_id"),
    }, sort_keys=True)


def preferences_sha256(preferences_json):
    """SHA-256 des gespeicherten Praeferenz-Snapshots (Text, wie in der DB)."""
    if preferences_json is None:
        return None
    return hashlib.sha256(str(preferences_json).encode("utf-8")).hexdigest()


def exclusion_limit_texts(exclusions, floor_status, evidence_status=None) -> list:
    """Kundentext zum Ausschluss: die Umsetzung wird NUR behauptet, wenn die
    Strategie die Untergrenze haelt UND die Produktauswahl belegt ist
    (``evidence_status`` == RUN_EVIDENCE_OK); ohne Produktauswahl steht die
    Regel als Vorgabe (``None``)."""
    if not exclusions:
        return []
    if floor_status == FLOOR_OK and evidence_status == RUN_EVIDENCE_MISSING:
        return [EXCLUSION_UNEVIDENCED_TEXT.format(labels=", ".join(exclusion_labels(exclusions)))]
    if floor_status == FLOOR_OK and evidence_status != RUN_EVIDENCE_OK:
        return [EXCLUSION_NO_RUN_TEXT]
    if floor_status == FLOOR_VIOLATED:
        return [EXCLUSION_DEVIATION_TEXT.format(labels=", ".join(exclusion_labels(exclusions)))]
    if floor_status in (FLOOR_NO_STRATEGY, FLOOR_UNREADABLE):
        return [EXCLUSION_NO_STRATEGY_TEXT]
    return [EXCLUSION_LIMIT_TEXT]


# N-888-15 (uebernommen): ein Beratungsprotokoll ohne Anlagestrategie traegt
# keine Produkt-/Allokationsaussage; es wird an die Erfassung selbst gebunden.
NO_STRATEGY_DOCUMENT_TYPES = ("Beratungsprotokoll",)
NO_STRATEGY_BINDING_PREFIX = "keine-strategie:"


def no_strategy_binding(decision):
    if not decision or not decision.get("decision_hash"):
        return None
    return NO_STRATEGY_BINDING_PREFIX + str(decision["decision_hash"])


DOCUMENT_STRATEGY_UNBOUND_TEXT = (
    "ist keiner Anlagestrategie eindeutig zugeordnet (vor der Bindung erzeugt "
    "oder Inhalt geändert). Bitte das Dokument neu erzeugen."
)


# ── E2b Nachtrag 1: Belege der Produktauswahl (an der Empfehlung) ────────────
RUN_EVIDENCE_NONE = "none"        # kein Ausschluss aktiv
RUN_EVIDENCE_OK = "ok"            # alle Positionen belegt, zur aktuellen Erfassung
RUN_EVIDENCE_MISSING = "missing"  # Altlauf, andere Erfassung oder Luecke


def run_evidence_status(decision, snapshot_json) -> str:
    """Ist die Produktauswahl einer Empfehlung fuer die AKTUELLEN Ausschluesse
    belegt? Fail-closed: unlesbar, andere Erfassung, fehlendes Thema oder
    Luecke = missing."""
    try:
        exclusions = effective_exclusions(decision)
    except (TypeError, ValueError):
        return RUN_EVIDENCE_MISSING
    if not exclusions:
        return RUN_EVIDENCE_NONE
    try:
        snap = json.loads(snapshot_json) if snapshot_json else None
    except (TypeError, ValueError):
        snap = None
    if not isinstance(snap, dict) or snap.get("decision_hash") != (decision or {}).get("decision_hash"):
        return RUN_EVIDENCE_MISSING
    if not set(exclusions) <= set(snap.get("themes") or ()) or snap.get("complete") is not True:
        return RUN_EVIDENCE_MISSING
    return RUN_EVIDENCE_OK


RUN_EVIDENCE_MESSAGE = (
    "{label}: Die Produktauswahl ist für den Ausschluss ({labels}) nicht belegt. "
    "Bitte die Empfehlung neu erstellen."
)


def run_evidence_message(decision, channel) -> str:
    label = FLOOR_CHANNEL_LABELS.get(channel, "Freigabe nicht möglich")
    try:
        labels = ", ".join(exclusion_labels(effective_exclusions(decision)))
    except (TypeError, ValueError):
        labels = ""
    return RUN_EVIDENCE_MESSAGE.format(label=label, labels=labels)


REQUIRED_ANSWER_TEXT = "Frage zur Nachhaltigkeit im Risikoprofil beantworten."
