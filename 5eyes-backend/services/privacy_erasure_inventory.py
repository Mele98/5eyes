"""Loeschinventar personenbezogener Daten (PRIVACY-001).

Jede Tabelle mit Kunden- oder Mandatsbezug ist hier mit ihren Datenkategorien
erfasst. Ein Loeschgesuch (services/privacy_erasure.py) durchsucht genau
dieses Inventar, und jede Kategorie bekommt im Vorgang eine eigene
Disposition (``DELETE``, ``ANONYMIZE``, ``PARTIAL_DELETE_MINIMIZE``,
``RETAIN_RESTRICTED``, ``LEGAL_HOLD``). Ein Datensatz kann so mehrere
Dispositionen haben, etwa Identitaet geloescht und Entscheid gesperrt behalten.

Dieses Modul enthaelt keine Fristen und keine Rechtsgrundlagen. Welche
Disposition gilt, entscheidet allein eine genehmigte Policy-Zeile der
Aufbewahrungsmatrix (``privacy_retention_policies``, Status ``APPROVED``).
Fehlt sie, bleibt die Kategorie "Entscheid ausstehend" (fail-closed).

Kategorien
----------
``IDENTITY``          direkt identifizierende Felder
``FREE_TEXT``         freie Notiz-/Begruendungsfelder im Klartext
``SEALED_FREE_TEXT``  Freitext, mit dem Kundenschluessel versiegelt
                      (services/pii_vault.py)
``SIGNATURE``         Signatur-Artefakte (Bild, Name, IP)
``DOCUMENT_CONTENT``  gerenderter Dokumentinhalt
``ACCESS``            Zugangsstatus des Kundenportals
``KEY_MATERIAL``      Kundenschluessel fuer versiegelte Freitexte
``RECORD``            uebrige strukturierte Felder des Datensatzes

Methoden (was der Code heute ausfuehren kann)
---------------------------------------------
``TIER_A_REDACTION``  services/client_erasure.py::erase_client_personal_data
                      (fixer Marker bzw. NULL, Zugang deaktiviert)
``CRYPTO_SHRED``      Vernichtung des Kundenschluessels (pii_vault)
``None``              keine Loesch-/Anonymisierungsmethode implementiert;
                      eine loeschende Disposition scheitert dann sichtbar
                      (``METHOD_NOT_IMPLEMENTED``), statt still zu entfallen.

``tests/test_privacy_erasure_inventory_guard.py`` ist die Ratsche: jede
Tabelle mit Kunden-/Mandatsbezug im Tenant-Inventar braucht hier einen
Eintrag (oder eine begruendete Ausnahme), und jede genannte Spalte muss
existieren.
"""
from __future__ import annotations

from dataclasses import dataclass

INVENTORY_VERSION = "2026-10-27.1"

DELETE = "DELETE"
ANONYMIZE = "ANONYMIZE"
PARTIAL_DELETE_MINIMIZE = "PARTIAL_DELETE_MINIMIZE"
RETAIN_RESTRICTED = "RETAIN_RESTRICTED"
LEGAL_HOLD = "LEGAL_HOLD"

DISPOSITIONS = (DELETE, ANONYMIZE, PARTIAL_DELETE_MINIMIZE, RETAIN_RESTRICTED, LEGAL_HOLD)
ERASING_DISPOSITIONS = frozenset({DELETE, ANONYMIZE, PARTIAL_DELETE_MINIMIZE})
RESTRICTING_DISPOSITIONS = frozenset({RETAIN_RESTRICTED, LEGAL_HOLD})

IDENTITY = "IDENTITY"
FREE_TEXT = "FREE_TEXT"
SEALED_FREE_TEXT = "SEALED_FREE_TEXT"
SIGNATURE = "SIGNATURE"
DOCUMENT_CONTENT = "DOCUMENT_CONTENT"
ACCESS = "ACCESS"
KEY_MATERIAL = "KEY_MATERIAL"
RECORD = "RECORD"

DATA_CATEGORIES = (
    IDENTITY, FREE_TEXT, SEALED_FREE_TEXT, SIGNATURE, DOCUMENT_CONTENT, ACCESS, KEY_MATERIAL, RECORD,
)

TIER_A_REDACTION = "TIER_A_REDACTION"
CRYPTO_SHRED = "CRYPTO_SHRED"
METHODS = (TIER_A_REDACTION, CRYPTO_SHRED)

# Nachweisarten = Zeilen der Aufbewahrungsmatrix. Die Bezeichnung beschreibt
# nur den Inhalt; Zweck, Rechtsgrundlage und Frist stehen in der Policy.
EVIDENCE_TYPES: dict[str, str] = {
    "client_master_data": "Stammdaten des Kunden",
    "client_classification": "Kundensegmentierung und Opting-Verlauf",
    "kyc_due_diligence": "Sorgfaltspflicht-Erfassung und Steuerdomizile",
    "client_portal_account": "Zugangskonto des Kundenportals",
    "crypto_key_material": "Kundenschluessel fuer versiegelte Freitexte",
    "mandate_contract": "Mandat und Vertragsdokumente",
    "financial_situation": "Vermoegen, Zufluesse, Cashflows, Planungsannahmen",
    "goals_planning": "Ziele, Zielverlauf und Zielrevisionen",
    "risk_profile_evidence": "Risikoprofil, Antworten, Overrides, Signaturen",
    "risk_capacity_plausibility_evidence": "Plausibilitaetsnachweise der Risikofaehigkeit",
    "suitability_evidence": "Kenntnisse, Eignungs- und Produktpruefungen",
    "recommendation_evidence": "Empfehlungen, Allokationen, Uebergaben, Review-Anlaesse",
    "advisory_protocol": "Beratungsprotokoll, Berichtsnotizen, Interessenkonflikte",
    "audit_trail": "Protokolleintraege zum Kunden",
}


@dataclass(frozen=True)
class Category:
    name: str
    evidence_type: str
    columns: tuple[str, ...] = ()  # leer = ganzer Datensatz (RECORD)
    method: str | None = None


@dataclass(frozen=True)
class TableEntry:
    """``route``: (Spalte, Bezug). Bezug ist ``client`` (Kunden-ID),
    ``mandate`` (Mandate des Kunden), ``client_login_user`` (Benutzerkonto
    des Kundenportals) oder eine Elterntabelle dieses Inventars (deren IDs)."""

    route: tuple[str, str]
    categories: tuple[Category, ...]


def _t(route: tuple[str, str], *categories: Category) -> TableEntry:
    return TableEntry(route=route, categories=categories)


def _c(name: str, evidence_type: str, *columns: str, method: str | None = None) -> Category:
    return Category(name=name, evidence_type=evidence_type, columns=tuple(columns), method=method)


_CLIENT = ("client_id", "client")
_MANDATE = ("mandate_id", "mandate")

PERSONAL_DATA_INVENTORY: dict[str, TableEntry] = {
    "clients": _t(
        ("id", "client"),
        _c(IDENTITY, "client_master_data",
           "salutation", "first_name", "last_name", "date_of_birth", "canton", "civil_status",
           "profession", "employer", "partner_salutation", "partner_first_name",
           "partner_last_name", "partner_date_of_birth", "partner_profession",
           method=TIER_A_REDACTION),
        _c(FREE_TEXT, "client_master_data", "notes", method=TIER_A_REDACTION),
        _c(RECORD, "client_master_data"),
    ),
    "client_nationalities": _t(
        _CLIENT,
        _c(IDENTITY, "client_master_data", "country_code", method=TIER_A_REDACTION),
        _c(RECORD, "client_master_data"),
    ),
    "client_opt_history": _t(
        _CLIENT,
        _c(FREE_TEXT, "client_classification", "notes", method=TIER_A_REDACTION),
        _c(RECORD, "client_classification"),
    ),
    "client_due_diligence": _t(
        _CLIENT,
        _c(IDENTITY, "kyc_due_diligence",
           "pep_details", "beneficial_owner_name", "source_of_wealth", "id_document_number",
           method=TIER_A_REDACTION),
        _c(RECORD, "kyc_due_diligence"),
    ),
    "client_tax_residencies": _t(
        _CLIENT,
        _c(IDENTITY, "kyc_due_diligence", "tax_id_number", method=TIER_A_REDACTION),
        _c(RECORD, "kyc_due_diligence"),
    ),
    "client_knowledge": _t(_CLIENT, _c(RECORD, "suitability_evidence")),
    "client_logins": _t(
        _CLIENT,
        _c(ACCESS, "client_portal_account", "is_active", method=TIER_A_REDACTION),
        _c(RECORD, "client_portal_account"),
    ),
    "client_pii_keys": _t(
        _CLIENT,
        _c(KEY_MATERIAL, "crypto_key_material", "key_material", method=CRYPTO_SHRED),
    ),
    "users": _t(
        ("id", "client_login_user"),
        _c(IDENTITY, "client_portal_account",
           "full_name", "email", "totp_secret", "reset_token_hash", "reset_token_expires_at",
           "invite_token_hash", "invite_expires_at",
           method=TIER_A_REDACTION),
        _c(RECORD, "client_portal_account"),
    ),
    "refresh_tokens": _t(
        ("user_id", "client_login_user"),
        _c(ACCESS, "client_portal_account", "revoked_at", method=TIER_A_REDACTION),
        _c(RECORD, "client_portal_account"),
    ),
    "mandates": _t(
        _CLIENT,
        _c(IDENTITY, "mandate_contract",
           "depot_bank", "depot_account_number", "client_sex", "client_birth_year",
           method=TIER_A_REDACTION),
        _c(RECORD, "mandate_contract"),
    ),
    "contract_documents": _t(
        _MANDATE,
        _c(SIGNATURE, "mandate_contract",
           "signature_advisor_image", "signature_advisor_signer_name", "signature_advisor_ip",
           "signature_client_image", "signature_client_signer_name", "signature_client_ip",
           method=TIER_A_REDACTION),
        _c(DOCUMENT_CONTENT, "mandate_contract",
           "title", "content_json", "pdf_path", "checksum_sha256", method=TIER_A_REDACTION),
        _c(RECORD, "mandate_contract"),
    ),
    "wealth_positions": _t(
        _CLIENT,
        _c(IDENTITY, "financial_situation",
           "property_address", "property_zip_city", "depot_bank", "depot_account_number",
           "mortgage_bank",
           method=TIER_A_REDACTION),
        _c(FREE_TEXT, "financial_situation", "notes", method=TIER_A_REDACTION),
        _c(RECORD, "financial_situation"),
    ),
    "wealth_inflows": _t(
        _CLIENT,
        _c(FREE_TEXT, "financial_situation", "notes", method=TIER_A_REDACTION),
        _c(RECORD, "financial_situation"),
    ),
    "cashflows": _t(
        _CLIENT,
        _c(FREE_TEXT, "financial_situation", "notes", method=TIER_A_REDACTION),
        _c(RECORD, "financial_situation"),
    ),
    "planning_assumptions": _t(
        _MANDATE,
        _c(FREE_TEXT, "financial_situation", "notes", method=TIER_A_REDACTION),
        _c(RECORD, "financial_situation"),
    ),
    "goals": _t(
        _MANDATE,
        _c(FREE_TEXT, "goals_planning", "notes", method=TIER_A_REDACTION),
        _c(RECORD, "goals_planning"),
    ),
    "goal_lifecycle_transitions": _t(_MANDATE, _c(RECORD, "goals_planning")),
    "goal_revision_decisions": _t(
        _MANDATE,
        _c(SEALED_FREE_TEXT, "goals_planning", "reason", method=CRYPTO_SHRED),
        _c(RECORD, "goals_planning"),
    ),
    "risk_assessments": _t(
        _MANDATE,
        _c(FREE_TEXT, "risk_profile_evidence", "override_reason", "client_signed_ref",
           method=TIER_A_REDACTION),
        _c(RECORD, "risk_profile_evidence"),
    ),
    "risk_assessment_answers": _t(
        ("assessment_id", "risk_assessments"), _c(RECORD, "risk_profile_evidence"),
    ),
    "risk_override_decisions": _t(
        _MANDATE,
        _c(SEALED_FREE_TEXT, "risk_profile_evidence", "reason", method=CRYPTO_SHRED),
        _c(RECORD, "risk_profile_evidence"),
    ),
    "risk_profile_signoffs": _t(
        _MANDATE,
        _c(SEALED_FREE_TEXT, "risk_profile_evidence", "note", method=CRYPTO_SHRED),
        _c(RECORD, "risk_profile_evidence"),
    ),
    "financial_coverage_attestations": _t(
        _MANDATE,
        _c(SEALED_FREE_TEXT, "risk_capacity_plausibility_evidence",
           "household_persons_json", "note", method=CRYPTO_SHRED),
        _c(RECORD, "risk_capacity_plausibility_evidence"),
    ),
    "risk_capacity_plausibility_evaluations": _t(
        _MANDATE, _c(RECORD, "risk_capacity_plausibility_evidence"),
    ),
    "suitability_checks": _t(_MANDATE, _c(RECORD, "suitability_evidence")),
    "product_eligibility_snapshots": _t(_MANDATE, _c(RECORD, "suitability_evidence")),
    "product_eligibility_decisions": _t(
        ("snapshot_id", "product_eligibility_snapshots"), _c(RECORD, "suitability_evidence"),
    ),
    "product_eligibility_overrides": _t(
        ("snapshot_id", "product_eligibility_snapshots"),
        _c(FREE_TEXT, "suitability_evidence", "reason_text"),
        _c(RECORD, "suitability_evidence"),
    ),
    "recommendation_runs": _t(_MANDATE, _c(RECORD, "recommendation_evidence")),
    "recommendation_positions": _t(
        ("run_id", "recommendation_runs"), _c(RECORD, "recommendation_evidence"),
    ),
    "recommendation_holdings": _t(
        ("run_id", "recommendation_runs"), _c(RECORD, "recommendation_evidence"),
    ),
    "target_allocations": _t(_MANDATE, _c(RECORD, "recommendation_evidence")),
    "strategy_snapshots": _t(_MANDATE, _c(RECORD, "recommendation_evidence")),
    "optimizer_runs": _t(_MANDATE, _c(RECORD, "recommendation_evidence")),
    "portfolio_handoffs": _t(_MANDATE, _c(RECORD, "recommendation_evidence")),
    # DEPOT-E2E-STRESS-001 / DEPOT-E2E-SNAPSHOT-001: append-only IST-Bestand.
    "depot_snapshots": _t(_MANDATE, _c(RECORD, "recommendation_evidence")),
    # SIGN-001: append-only Vor-Ort-Signatur (Ereignisse, Kunden-Challenges,
    # Evidence-Paket). Unveraenderlich per Trigger -> keine Tier-A-Redaktion
    # moeglich; Ausweis-Metadaten sichtbar ohne Methode (METHOD_NOT_IMPLEMENTED),
    # Entscheid ueber die Aufbewahrungsmatrix.
    "onsite_signature_events": _t(_MANDATE, _c(RECORD, "mandate_contract")),
    "onsite_signature_challenges": _t(_MANDATE, _c(RECORD, "mandate_contract")),
    "onsite_signature_evidence": _t(
        _MANDATE,
        _c(IDENTITY, "mandate_contract", "id_document_kind", "id_document_country"),
        _c(RECORD, "mandate_contract"),
    ),
    "review_triggers": _t(_MANDATE, _c(RECORD, "recommendation_evidence")),
    "advisory_log": _t(
        _MANDATE,
        _c(FREE_TEXT, "advisory_protocol", "description", "participants_json"),
        _c(RECORD, "advisory_protocol"),
    ),
    "mandate_report_notes": _t(
        _MANDATE,
        _c(FREE_TEXT, "advisory_protocol",
           "aa_anmerkungen", "waehrungen_erklaerung", "branchen_analyse",
           "vorgehen_block_optimierungen", "vorgehen_block_zielstrategie",
           "vorgehen_offene_fragen_json", "vorgehen_naechster_termin", "vorgehen_todos_json",
           "vorgehen_dokumente_json", "previous_versions_json"),
        _c(RECORD, "advisory_protocol"),
    ),
    "mandate_baustein_selections": _t(_MANDATE, _c(RECORD, "advisory_protocol")),
    "conflict_of_interest_disclosures": _t(
        _MANDATE,
        _c(FREE_TEXT, "advisory_protocol", "description"),
        _c(RECORD, "advisory_protocol"),
    ),
    "audit_log": _t(_CLIENT, _c(RECORD, "audit_trail")),
}

# Tabellen mit Kunden-/Mandatsbezug, die bewusst nicht durchsucht werden.
# Der Grund steht dabei; die Ratsche akzeptiert nur Eintraege mit Grund.
EXEMPT_TABLES: dict[str, str] = {
    "privacy_erasure_cases": (
        "Bearbeitungsnachweis des Loeschgesuchs selbst (Vorgangs-ID, Kategorien, "
        "Zaehlungen, Digests; keine kopierten Personendaten)"
    ),
    "privacy_erasure_dispositions": "Dispositionszeilen des Loeschgesuchs selbst",
    "privacy_legal_holds": "Legal-Hold-Register (Fall-ID, Rechtsgrund, Umfang, Genehmiger)",
}


def categories_for(table: str) -> tuple[Category, ...]:
    entry = PERSONAL_DATA_INVENTORY.get(table)
    return entry.categories if entry else ()


def client_bound_tables(metadata_tables: dict, derived_routes: dict[str, tuple[str, str]]) -> set[str]:
    """Tabellen mit Kunden-/Mandatsbezug: ``clients``/``mandates``, jede
    Tabelle mit ``client_id``/``mandate_id`` und jede Tabelle, deren
    Mandanten-Ableitung (Tenant-Inventar) ueber eine solche Tabelle laeuft."""
    bound: set[str] = {"clients", "mandates"} & set(metadata_tables)
    for name, table in metadata_tables.items():
        columns = set(table.c.keys())
        if "client_id" in columns or "mandate_id" in columns:
            bound.add(name)
    changed = True
    while changed:
        changed = False
        for name, (_column, parent) in derived_routes.items():
            if name in metadata_tables and name not in bound and parent in bound:
                bound.add(name)
                changed = True
    return bound


def inventory_problems(metadata_tables: dict, derived_routes: dict[str, tuple[str, str]]) -> list[str]:
    """Widersprueche zwischen Loeschinventar und Schema (leer = vollstaendig)."""
    problems: list[str] = []
    names = set(metadata_tables)
    required = client_bound_tables(metadata_tables, derived_routes)
    classified = set(PERSONAL_DATA_INVENTORY) | set(EXEMPT_TABLES)
    for name in sorted(required - classified):
        problems.append(f"Tabelle mit Kunden-/Mandatsbezug ohne Disposition-Klassifikation: {name}")
    for name in sorted(set(PERSONAL_DATA_INVENTORY) & set(EXEMPT_TABLES)):
        problems.append(f"{name}: zugleich inventarisiert und ausgenommen")
    for name, reason in sorted(EXEMPT_TABLES.items()):
        if not reason.strip():
            problems.append(f"{name}: Ausnahme ohne Begruendung")
    for name in sorted(set(PERSONAL_DATA_INVENTORY) - names):
        problems.append(f"Loeschinventar nennt unbekannte Tabelle: {name}")
    for name in sorted(set(PERSONAL_DATA_INVENTORY) & names):
        entry = PERSONAL_DATA_INVENTORY[name]
        columns = set(metadata_tables[name].c.keys())
        route_column, scope = entry.route
        if route_column not in columns:
            problems.append(f"{name}: Bezugsspalte {route_column} fehlt")
        if scope not in ("client", "mandate", "client_login_user") and scope not in PERSONAL_DATA_INVENTORY:
            problems.append(f"{name}: Bezug {scope} ist weder Kunde/Mandat noch inventarisierte Tabelle")
        seen: set[str] = set()
        if not entry.categories:
            problems.append(f"{name}: keine Datenkategorie")
        for category in entry.categories:
            if category.name in seen:
                problems.append(f"{name}: Kategorie {category.name} doppelt")
            seen.add(category.name)
            if category.name not in DATA_CATEGORIES:
                problems.append(f"{name}: unbekannte Kategorie {category.name}")
            if category.evidence_type not in EVIDENCE_TYPES:
                problems.append(f"{name}: unbekannte Nachweisart {category.evidence_type}")
            if category.method is not None and category.method not in METHODS:
                problems.append(f"{name}: unbekannte Methode {category.method}")
            if category.name == RECORD and category.columns:
                problems.append(f"{name}: RECORD umfasst den ganzen Datensatz, keine Spaltenliste")
            if category.name != RECORD and not category.columns:
                problems.append(f"{name}: Kategorie {category.name} ohne Spalten")
            for column in category.columns:
                if column not in columns:
                    problems.append(f"{name}.{column}: Spalte existiert nicht")
    return problems
