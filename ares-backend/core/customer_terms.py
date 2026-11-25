"""KN3-B / N-917R2-04 (E2E2-11): Anzeigeform datengebundener Fachbegriffe in
Kunden-PDFs (reines Blatt, nur Standardbibliothek).

Einige Sub-Anlageklassen und Musterprodukte tragen in den Daten historisch
eine ASCII-Umschrift (z. B. ``"Aktien Schwellenlaender"``). Diese Namen sind
Schluessel: CMA-Zeilen, Bausteine, Produkte, Eignungsregeln und gespeicherte
Allokationen verweisen darauf. Eine Umbenennung in den Daten waere eine
Migration ueber alle diese Tabellen (und ueber versiegelte Entscheide). Die
Kunden-PDFs zeigen deshalb -- wie die Oberflaeche (``aresTerm`` in
ares-desktop/frontend/mandate-view.js) -- die Anzeigeform mit echten Umlauten.

Bewusst eine abschliessende Liste bekannter Datenbegriffe statt einer
generischen ae->ä-Ersetzung: Eigennamen, Firmen- und Personennamen (z. B. in
den rechtlichen Angaben) bleiben, wie sie erfasst wurden.

KN7 (H-181-Pruefung, CTO-Nachtrag): zusaetzlich die Kundentexte der
Geeignetheitspruefung je Pruefgrundlage (``customer_suitability_text``, seit
KN6; genutzt von Advisory-Report Sektion 19/27 und Beratungsentscheid) und die
Anzeigeform interner Kennungen in Kunden-PDFs (``short_reference``,
``customer_reference_text``: UUID/Hash -> 8 Zeichen, «SHA-256» -> «Prüfsumme»).
"""
from __future__ import annotations

# (Umschrift in den Daten, Anzeigeform) -- nur eindeutige Namensbestandteile
# von Sub-Anlageklassen/Musterprodukten (wie ``aresTerm``). Bewusst kein
# allgemeines Wort wie "Liquiditaet": das kaeme auch in Prosa vor und wuerde
# einen Satz nur halb umstellen.
DATA_TERM_DISPLAY = (
    ("Schwellenlaender", "Schwellenländer"),
    ("schwellenlaender", "schwellenländer"),
    ("Gluecksspiel", "Glücksspiel"),
)


def customer_term(text) -> str:
    """Anzeigeform fuer Kunden-PDFs (unveraendert, wenn kein Datenbegriff)."""
    value = "" if text is None else str(text)
    for old, new in DATA_TERM_DISPLAY:
        if old in value:
            value = value.replace(old, new)
    return value


# KN6 / N-917R5-01: Der Kundentext richtet sich nach der Prüfgrundlage
# (``suitability_basis`` aus services/suitability_audit). Eine Prüfung wird nur
# behauptet, wenn sie stattgefunden hat: Execution-only und institutionelle
# Kunden sind von der Prüfpflicht ausgenommen -- dort steht, dass KEINE Prüfung
# durchgeführt wurde. Eine unbekannte/fehlende Grundlage ergibt einen neutralen
# Text mit Hinweis an den Berater, nie «liegt vor».
# Heute erzeugt der Audit: risk_assessment, execution_only_exempt,
# institutional_client_exempt, degraded (audit_degraded). «appropriateness»
# (Angemessenheitsprüfung, Art. 11 FIDLEG) erzeugt noch kein Audit-Pfad; der
# Text steht bereit, damit eine solche Grundlage nie als Geeignetheit erscheint.
SUITABILITY_BASIS_GEEIGNETHEIT = "risk_assessment"
SUITABILITY_BASIS_ANGEMESSENHEIT = "appropriateness"
SUITABILITY_BASIS_EXECUTION_ONLY = "execution_only_exempt"
SUITABILITY_BASIS_INSTITUTIONAL = "institutional_client_exempt"

CUSTOMER_SUITABILITY_TEXTS = {
    (SUITABILITY_BASIS_GEEIGNETHEIT, True):
        "Für die dokumentierten Beratungen liegt die erforderliche Geeignetheitsprüfung vor.",
    (SUITABILITY_BASIS_GEEIGNETHEIT, False):
        "Für mindestens eine Beratung fehlt eine gültige Geeignetheitsprüfung. "
        "Ihr Berater ergänzt sie vor einer Umsetzung.",
    (SUITABILITY_BASIS_ANGEMESSENHEIT, True):
        "Für die dokumentierten Dienstleistungen liegt die erforderliche Angemessenheitsprüfung "
        "(Art. 11 FIDLEG) vor. Eine Geeignetheitsprüfung war dafür nicht vorgesehen.",
    (SUITABILITY_BASIS_ANGEMESSENHEIT, False):
        "Für mindestens eine Dienstleistung fehlt eine gültige Angemessenheitsprüfung. "
        "Ihr Berater ergänzt sie vor einer Umsetzung.",
    (SUITABILITY_BASIS_EXECUTION_ONLY, True):
        "Keine Geeignetheits- oder Angemessenheitsprüfung durchgeführt: Das Mandat ist als reine "
        "Auftragsausführung (Execution-only, Art. 13 FIDLEG) erfasst. Dafür ist keine solche "
        "Prüfung vorgesehen.",
    (SUITABILITY_BASIS_INSTITUTIONAL, True):
        "Keine Geeignetheitsprüfung durchgeführt: Sie sind als institutioneller Kunde eingestuft. "
        "Für institutionelle Kunden ist nach FIDLEG keine Geeignetheitsprüfung vorgesehen.",
}
CUSTOMER_SUITABILITY_UNDOCUMENTED = (
    "Prüfgrundlage nicht dokumentiert: Für diesen Bericht ist nicht erfasst, ob eine "
    "Geeignetheits- oder Angemessenheitsprüfung durchgeführt wurde oder eine Ausnahme gilt. "
    "Hinweis für den Berater: Prüfgrundlage im Mandat dokumentieren, bevor die Empfehlung "
    "umgesetzt wird."
)


def customer_suitability_text(data: dict) -> tuple[str, str]:
    """(Status, Kundentext) der Geeignetheitsprüfung je Prüfgrundlage.

    Status: ``ok`` | ``missing`` | ``not_required`` | ``undocumented`` | ``degraded``.
    """
    if data.get("audit_degraded"):
        return "degraded", (
            "Prüfung nicht möglich: Die Geeignetheit konnte für diesen Bericht nicht bestätigt "
            "werden. Ihr Berater klärt dies vor einer Umsetzung.")
    basis = str(data.get("suitability_basis") or "").strip()
    compliant = data.get("is_compliant", True)
    if compliant is False and basis in ("", SUITABILITY_BASIS_GEEIGNETHEIT):
        # Fehlende/ungültige Prüfung: ohne Grundlage verlangt der Audit die
        # Geeignetheitsprüfung (Regelfall Art. 12 FIDLEG).
        return "missing", CUSTOMER_SUITABILITY_TEXTS[(SUITABILITY_BASIS_GEEIGNETHEIT, False)]
    if basis in (SUITABILITY_BASIS_EXECUTION_ONLY, SUITABILITY_BASIS_INSTITUTIONAL):
        return "not_required", CUSTOMER_SUITABILITY_TEXTS[(basis, True)]
    if basis in (SUITABILITY_BASIS_GEEIGNETHEIT, SUITABILITY_BASIS_ANGEMESSENHEIT) and compliant in (True, False):
        return ("ok" if compliant else "missing"), CUSTOMER_SUITABILITY_TEXTS[(basis, bool(compliant))]
    return "undocumented", CUSTOMER_SUITABILITY_UNDOCUMENTED


# -- KN7: Anzeigeform interner Kennungen in Kunden-PDFs ------------------------
# Kunden-PDFs zeigen keine UUID und keinen vollen Hash, sondern eine kurze
# Nummer bzw. Prüfsumme (die ersten 8 Zeichen), wie der Depotcheck seit KN6.
# Die vollständigen Werte bleiben in DB, Audit-Log, Archiv-Hash und in der
# Berater-/Audit-Fassung.
REFERENCE_CHARS = 8
_HEX_DIGITS = "0123456789abcdefABCDEF"
UUID_PART_LENGTHS = (8, 4, 4, 4, 12)


def short_reference(value) -> str:
    """Erste 8 Zeichen einer Kennung/eines Hashes; leer -> «-»."""
    text = str(value or "").strip()
    return text[:REFERENCE_CHARS] if text else "-"


def _is_hex(text: str) -> bool:
    return bool(text) and all(ch in _HEX_DIGITS for ch in text)


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _is_uuid(text: str) -> bool:
    parts = text.split("-")
    return tuple(len(part) for part in parts) == UUID_PART_LENGTHS and all(_is_hex(p) for p in parts)


def customer_reference_text(text) -> str:
    """Kürzt Kennungen in einem Kundentext: UUID und Hex-Folgen ab 16 Zeichen
    -> erste 8 Zeichen, «SHA-256 » -> «Prüfsumme ». (Nur Standardbibliothek;
    reines Blatt, daher ohne ``re``.)"""
    value = str(text)
    out: list[str] = []
    i, n = 0, len(value)
    while i < n:
        if _is_word_char(value[i]) and (i == 0 or not _is_word_char(value[i - 1])):
            candidate = value[i:i + 36]
            if _is_uuid(candidate) and (i + 36 == n or not _is_word_char(value[i + 36])):
                out.append(candidate[:REFERENCE_CHARS])
                i += 36
                continue
            j = i
            while j < n and _is_word_char(value[j]):
                j += 1
            word = value[i:j]
            out.append(word[:REFERENCE_CHARS] if len(word) >= 16 and _is_hex(word) else word)
            i = j
            continue
        out.append(value[i])
        i += 1
    return "".join(out).replace("SHA-256 ", "Prüfsumme ")


# CCX P5 (Vertrag §8): jedes Kunden-PDF nennt den versiegelten Beratungsentscheid,
# aus dem seine Zahlen stammen (Pruefnummer = erste 12 Zeichen des Envelope-
# Hashes, Fassung = Schema-Version), oder ausdruecklich, dass keiner gebunden ist.
DECISION_NONE_TEXT = "Beratungsentscheid: keiner versiegelt"
# N-925R-02: versiegelt, aber derzeit nicht auslieferbar (veraltet, Kurs geaendert ...).
DECISION_NOT_DELIVERABLE_TEXT = "Beratungsentscheid: versiegelt, derzeit nicht auslieferbar"


# N-925-05: solange der Risikoparametersatz nicht IC-freigegeben ist, traegt
# jedes Kunden-PDF diesen Vermerk (Text = core.risk_parameter_set.IC_UNRELEASED_LABEL).
IC_UNRELEASED_FOOTER = "Vorlagewerte – nicht IC-freigegeben"


def decision_footer_label(decision_ref) -> str:
    ref = decision_ref or {}
    if ref.get("allocation_free"):
        return ""  # N-925R-02: Dokument ohne Allokation traegt keinen Entscheid-Fuss
    if not ref.get("envelope_hash"):
        label = DECISION_NOT_DELIVERABLE_TEXT if ref.get("decision_state") == "sealed_not_deliverable" \
            else DECISION_NONE_TEXT
    else:
        label = (f"Beratungsentscheid: {str(ref['envelope_hash'])[:12]} "
                 f"· Fassung {ref.get('fassung') or '1'}")
    status = ref.get("ic_release_status")
    if status is not None and status != "RELEASED":
        label += " · " + IC_UNRELEASED_FOOTER
    return label


# --- Markierungszustand der Kunden-PDFs (Entwurf / Ansicht / final) ---
WATERMARK_MODES = (
    "none", "entwurf", "vertraulich", "vorvertrag", "unpublished", "vertragsvorlage", "depotbank", "gebuehren",
    "ansicht",
)
# C-890-01 Nachtrag 4 (N-897-12): kundenwirksamer Bericht ohne jede
# KYC-Bestaetigung -> sichtbar als Entwurf vor Vertragsabschluss.
VORVERTRAG_TEXT = "Entwurf – vor Vertragsabschluss (ohne KYC-Bestätigung)"
# CCX-P4: Kundendokument einer nicht (gueltig) publizierten Soll-Allokation.
UNPUBLISHED_TEXT = "Entwurf – Soll-Allokation nicht publiziert"
# H-179 V-1: Vertrag ohne freigegebene Vertragsvorlage bzw. ohne Ort.
CONTRACT_DRAFT_TEXT = "Entwurf – Vertragsvorlage nicht freigegeben"
# N-927-06: Kostenausweis ohne gueltige Angabe zu Zuwendungen der Depotbank.
DEPOT_BANK_DRAFT_TEXT = "Entwurf – Angabe zu Zuwendungen der Depotbank fehlt"
# EXE-P (H-187): Kostenausweis ohne Gebuehrenvereinbarung -- nie ein erfundener Satz.
FEE_AGREEMENT_DRAFT_TEXT = "Entwurf – keine Gebührenvereinbarung erfasst"
# ROL-b (CTO-Entscheid H-187): Abruf durch die Rolle "Lesend" -- eine Ansicht,
# kein abgegebenes Dokument (nie archiviert, nicht signierbar).
READONLY_VIEW_TEXT = "Ansicht – nicht abgegeben"


# H-193 Fixrunde 1 (N-939-01/-05): eine Quelle fuer "final oder nicht".
# Final -- und damit archivierbar und unterschreibbar -- ist nur eine Fassung
# ohne jeden Markierungsmodus ("none"). Jeder andere, auch ein unbekannter,
# Modus ist eine Nicht-Final-Fassung (fail-closed): Entwurf, nicht publiziert,
# Ansicht durch "Lesend" usw. Gleiche Regel wie _archive_final (nur "none") und
# services.signature_artifact (Vermerk != "none" -> nicht signierbar).
FINAL_MODE = "none"
READONLY_VIEW_MODE = "ansicht"
# Fehlender, leerer oder unbekannter Modus: nie final, aber sichtbar.
UNKNOWN_MODE = "unbekannt"
UNKNOWN_DRAFT_TEXT = "Entwurf – nicht final"
# Zeile oben auf jeder Seite (Wasserzeichen und Fuss) je Nicht-Final-Modus;
# jeder hier nicht genannte Nicht-Final-Modus traegt UNKNOWN_DRAFT_TEXT.
DRAFT_HEADLINES = {
    "vorvertrag": VORVERTRAG_TEXT,
    "unpublished": UNPUBLISHED_TEXT,
    "vertragsvorlage": CONTRACT_DRAFT_TEXT,
    "depotbank": DEPOT_BANK_DRAFT_TEXT,
    "gebuehren": FEE_AGREEMENT_DRAFT_TEXT,
    READONLY_VIEW_MODE: READONLY_VIEW_TEXT,
}


def is_final_document(mode: str | None) -> bool:
    """True nur fuer den ausdruecklichen Modus "none". Fehlend, None, leer oder
    unbekannt ist keine belegte Finalitaet (fail-closed)."""
    return isinstance(mode, str) and mode == FINAL_MODE


def normalize_mode(mode: str | None) -> str:
    """"none" nur, wenn ausdruecklich so gesetzt; sonst ein bekannter
    Entwurfsmodus oder ``UNKNOWN_MODE``."""
    if is_final_document(mode):
        return FINAL_MODE
    candidate = str(mode or "").strip().lower()
    return candidate if candidate in WATERMARK_MODES and candidate != FINAL_MODE else UNKNOWN_MODE


def draft_headline(mode: str | None, view_reason: str | None = None) -> str | None:
    """Kennzeichnung einer Nicht-Final-Fassung (None nur fuer final).
    N-939-05: eine Ansicht durch "Lesend" verdeckt den eigentlichen Grund nicht
    -- z. B. "Ansicht – nicht abgegeben · Entwurf – Soll-Allokation nicht publiziert"."""
    normalized = normalize_mode(mode)
    if normalized == FINAL_MODE:
        return None
    text = DRAFT_HEADLINES.get(normalized, UNKNOWN_DRAFT_TEXT)
    if normalized == READONLY_VIEW_MODE and view_reason:
        reason = draft_headline(view_reason)
        if reason and reason != text:
            return f"{text} · {reason}"
    return text
