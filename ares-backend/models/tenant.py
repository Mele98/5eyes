"""Sprint T1 (2026-06-08): Tenant-Model fuer 3-Tier-Hosting-Architektur.

Siehe docs/adr/ADR-009-3-tier-hosting-architecture.md fuer den
strategischen Rahmen.

# Konzept
Auch in Tier 1 (Self-Hosted) + Tier 3 (Dedicated) existiert das tenants-
Table mit GENAU EINEM Eintrag. Damit:
- Code-Pfade sind tier-uebergreifend konsistent
- Cross-Tenant-Leak-Tests laufen in jeder Konfiguration
- Migration Tier 1 -> Tier 2 ist "Daten in shared-Cloud importieren"

In Tier 2 (Shared-Cloud) ist tenants Multi-Row mit echter Isolation.

# Backwards-Compat
tenant_id wird auf bestehenden Models als NULLABLE eingefuehrt.
Default-Tenant 'main' wird via Migration angelegt. Existing Daten
ohne tenant_id werden Schritt-fuer-Schritt zu 'main' migriert.

# Single-Source-of-Truth
Tenant-Name + hosting_tier + license_status leben hier. Auth-Layer
(T2-Sprint) liest tenant_id aus JWT-Claim.
"""
from __future__ import annotations

from sqlalchemy import DDL, CheckConstraint, Column, ForeignKey, Integer, String, UniqueConstraint, event, text

from database import (
    KYC_REVIEW_POLICY_ACTIVATION_SQLITE_TRIGGERS,
    KYC_REVIEW_POLICY_SQLITE_TRIGGERS,
    Base,
)


# Tier-Konstanten (Single-Source-of-Truth, referenziert in config.py + Tests)
TIER_1_SELF_HOSTED = "tier1"
TIER_2_SHARED_CLOUD = "tier2"
TIER_3_DEDICATED = "tier3"

ALLOWED_TIERS = (TIER_1_SELF_HOSTED, TIER_2_SHARED_CLOUD, TIER_3_DEDICATED)

# License-Status (lifecycle)
LICENSE_STATUS_TRIAL = "trial"
LICENSE_STATUS_ACTIVE = "active"
LICENSE_STATUS_SUSPENDED = "suspended"
LICENSE_STATUS_EXPIRED = "expired"

ALLOWED_LICENSE_STATUS = (
    LICENSE_STATUS_TRIAL,
    LICENSE_STATUS_ACTIVE,
    LICENSE_STATUS_SUSPENDED,
    LICENSE_STATUS_EXPIRED,
)

# Default-Tenant-Marker (verwendet in Tier 1 + 3 — single-Row-Setup)
DEFAULT_TENANT_ID = "main"

# Presentation-Mode (HUD-Polish, 2026-08-02): rein UI-seitige "Maske" der
# App -- Wealthmanagement zeigt zusaetzliche Depotueberwachungs-Funktionen
# (Depot-Check, Live-Preise), Consulting blendet diese aus (reine
# Anlageberatung ohne laufende Depotueberwachung). KEINE Compliance-/
# Engine-Wirkung, bewusst getrennt von mandate_type (das hat reale
# Scoring-Wirkung, siehe FZK-Cap in ares.html).
PRESENTATION_MODE_WEALTHMANAGEMENT = "wealthmanagement"
PRESENTATION_MODE_CONSULTING = "consulting"

ALLOWED_PRESENTATION_MODES = (
    PRESENTATION_MODE_WEALTHMANAGEMENT,
    PRESENTATION_MODE_CONSULTING,
)


class Tenant(Base):
    """Tenant = Beratungsfirma / Lizenz-Nehmer.

    In Tier 1 / Tier 3: genau ein Eintrag ('main'). In Tier 2: ein
    Eintrag pro Lizenz-Nehmer.
    """

    __tablename__ = "tenants"

    id = Column(String, primary_key=True)
    # Anzeigename der Firma (z.B. "Mueller Vermoegensverwaltung AG")
    display_name = Column(String, nullable=False)
    # Eindeutiger Slug fuer URLs / Routing (z.B. "mueller-vv")
    slug = Column(String, nullable=False, unique=True)
    # Hosting-Tier — bestimmt Default-Settings + Operations-Verantwortung
    hosting_tier = Column(String, nullable=False, default=TIER_1_SELF_HOSTED)
    # Lizenz-Status fuer Billing / Access-Control
    license_status = Column(String, nullable=False, default=LICENSE_STATUS_TRIAL)
    # Ablauf-Datum des Trials oder Lizenz (ISO-Datum-String, NULL = unbefristet)
    license_valid_until = Column(String)
    # FINMA-Outsourcing-Anzeige (Tier 2/3): Datum der Anzeige
    finma_outsourcing_notified_at = Column(String)
    # AVV (Auftragsverarbeitungsvertrag) signiert: Datum
    avv_signed_at = Column(String)
    # Maximale Anzahl Berater-User in dieser Tenant (Lizenz-Limit)
    max_users = Column(Integer, default=1)
    # Maximale Anzahl Mandate (None = unbegrenzt)
    max_mandates = Column(Integer)
    # Storage-Quota in MB (None = unbegrenzt fuer Tier 1)
    storage_quota_mb = Column(Integer)
    # Envelope encryption: encrypted per-tenant DEK + rotation metadata.
    encrypted_dek = Column(String)
    dek_version = Column(Integer)
    dek_rotated_at = Column(String)
    # AF-5 (Tenant-Crypto-Haertung): Generation der Master-KEK, unter der
    # encrypted_dek verpackt ist (dek_version = Generation des DEK selbst).
    # Heute immer 1; ein spaeterer KEK-Rewrap setzt die neue Generation.
    kek_version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    # 2026-07-27 (Retrozessions-Feature): Firmenweite Vorbelegung fuer neue
    # Interessenkonflikt-Offenlegungen (ConflictOfInterestDisclosure.
    # reimbursed_to_client) -- spiegelt die uebliche Firmenpolicy ("wir
    # erstatten Retrozessionen grundsaetzlich nicht zurueck"), bleibt aber
    # pro Kunde/Mandat individuell ueberschreibbar (der Verzicht ist ein
    # individueller Rechtsakt, keine reine Firmenpolicy).
    default_retrocession_reimbursement = Column(Integer, nullable=False, default=0)
    # 2026-08-01 (Onboarding, Entscheid Auftraggeber): Land, in dem die
    # lizenznehmende Firma domiziliert ist (z.B. "CH", "DE"). Wird bei der
    # Ersteinrichtung (Tier 1: /auth/bootstrap-admin) bzw. bei der Tenant-
    # Erstellung (Tier 2: POST /tenants) gesetzt und dient als DEFAULT fuer
    # neue Mandate (Mandate.jurisdiction), wenn dort kein explizites Land
    # gewaehlt wird -- Firmen mit Kunden in mehreren Laendern koennen das pro
    # Mandat weiterhin ueberschreiben (bestehendes Verhalten unveraendert).
    # NULL = "CH" (gleiches Nullable-Pattern wie ueberall in diesem Bereich).
    home_jurisdiction = Column(String)
    # 2026-08-02 (HUD-Polish): firmenweiter Default fuer die UI-"Maske"
    # (siehe PRESENTATION_MODE_* oben). NULL = "wealthmanagement" (Default,
    # zeigt alle bestehenden Funktionen unveraendert -- reines Opt-in fuer
    # den schlankeren Consulting-Modus). Pro Sitzung im Frontend
    # ueberschreibbar (localStorage), dies ist nur der Firmen-Default.
    default_presentation_mode = Column(String)
    # 2026-08-09 (FINIG-Gate, User-Direktive "Consulting/Wealthmanagement
    # rechtlich sauber halten"): siehe services/tenant_licensing.py fuer die
    # rechtliche Begruendung. Default=1 -- Bestandsmandanten bleiben beim
    # Anlegen dieser Spalte unveraendert funktionsfaehig (kein rueckwirkender
    # Block). NEUE Tenants (schemas/tenants.py::TenantCreate) starten dagegen
    # bewusst mit False (explizites Opt-in fuer die hoehere Bewilligungsstufe,
    # kein Opt-out).
    discretionary_management_licensed = Column(Integer, nullable=False, default=1)
    # E2a Nachhaltigkeitspraeferenzen (Dok. 106, 2026-11-11): Review-Frist der
    # Nachhaltigkeitspraeferenz in Monaten als HAUSPOLITIK des Tenants (keine
    # gesetzliche Frist). NULL = Default 36 (core/sustainability_preference.py).
    sustainability_review_months = Column(Integer)

    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)


# ---------------------------------------------------------------------------
# H8 C-2 (Compliance-Audit 2026-11-07, Luecke 2): Rechtliche Angaben der Firma
# fuer die Kundeninformation nach Art. 8 Abs. 1 FIDLEG (lit. a Name und
# Adresse, lit. b Taetigkeitsfeld und Aufsichtsstatus, lit. c Ombudsverfahren;
# lit. d allgemeine Risiken liefert die Vorlage selbst) und Art. 9 FIDLEG
# (Abgabe vor Vertragsabschluss).
#
# Eine Zeile je Tenant. Ares belegt KEINEN Wert vor: keine Firma, keine
# Adresse, keine Ombudsstelle, keine Aufsichtsorganisation. Fehlt eine
# Pflichtangabe, sperren Kundeninformations-PDF, Finalisierung und
# Vertragsunterzeichnung fail-closed (services/recommendation_release_gate.py::
# client_onboarding_findings) und nennen die fehlende Angabe.
#
# Jede Aenderung wird feldweise im Audit-Log festgehalten; ``revision`` steigt
# mit jeder inhaltlichen Aenderung, ``profile_hash`` ist der SHA-256 ueber die
# kanonischen Inhaltsfelder. Eine abgegebene Kundeninformation haelt Revision
# und Hash fest (models/review.py::ClientInformationDelivery).
# ---------------------------------------------------------------------------

# Aufsichtsstatus (Art. 8 Abs. 1 lit. b FIDLEG). Bewusst grob und neutral; den
# Wortlaut der Aufsicht (Behoerde, Aufsichtsorganisation, Register) erfasst der
# Owner selbst.
SUPERVISION_PORTFOLIO_MANAGER = "vermoegensverwalter_finig"
SUPERVISION_OTHER_LICENSE = "andere_finma_bewilligung"
SUPERVISION_ADVISER_REGISTER = "anlageberater_ohne_prudenzielle_aufsicht"

ALLOWED_SUPERVISION_TYPES = (
    SUPERVISION_PORTFOLIO_MANAGER,
    SUPERVISION_OTHER_LICENSE,
    SUPERVISION_ADVISER_REGISTER,
)


class TenantLegalProfile(Base):
    __tablename__ = "tenant_legal_profiles"

    # Eigene ``id`` wie jede Tenant-Tabelle (RLS-/Inventar-Konvention);
    # ``tenant_id`` ist eindeutig -- eine Zeile je Tenant.
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, unique=True)
    legal_name = Column(String)
    address_street = Column(String)
    address_postal_code = Column(String)
    address_city = Column(String)
    # ISO-3166-Alpha-2 des Sitzes. Bestimmt das Informationsregime (heute nur
    # Sitz Schweiz = FIDLEG abgebildet; alles andere sperrt fail-closed).
    address_country = Column(String)
    business_activity = Column(String)
    supervision_type = Column(String)
    supervisory_authority = Column(String)
    supervisory_organisation = Column(String)
    license_reference = Column(String)
    ombudsman_name = Column(String)
    ombudsman_address = Column(String)
    contact_phone = Column(String)
    contact_email = Column(String)
    contact_website = Column(String)
    revision = Column(Integer, nullable=False, default=0, server_default=text("0"))
    profile_hash = Column(String)
    updated_by = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


# ---------------------------------------------------------------------------
# C-890-01: Wiedervorlage-Policy der KYC-Bestaetigung (je Tenant/Jurisdiktion).
#
# Ares erfindet KEINE Frist. Der maximale Abstand zwischen Abschluss der
# GwG-Abklaerung und naechster Aktualisierung kommt ausschliesslich aus einer
# vom Owner erfassten und von einer zweiten Person (Admin) freigegebenen
# Policy. Ohne wirksame Policy blockieren Erfassung und Kundenfreigabe
# (services/recommendation_release_gate.py, fail-closed).
#
# Beide Tabellen sind append-only (Trigger SQLite/PostgreSQL): eine Aenderung
# ist eine neue Version, die erneut freigegeben wird. Die Aktivierungen bilden
# je Tenant/Jurisdiktion eine lineare Kette (UNIQUE auf den Vorgaenger, erste
# Aktivierung mit dem Vorgaenger "GENESIS"): zwei parallele Aktivierungen auf
# denselben Stand koennen nie beide gelingen.
# ---------------------------------------------------------------------------

KYC_REVIEW_RISK_NORMAL = "normal"
KYC_REVIEW_RISK_ELEVATED = "erhoeht"
KYC_REVIEW_GENESIS = "GENESIS"


class KycReviewPolicy(Base):
    __tablename__ = "kyc_review_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "jurisdiction", "version", name="uq_kyc_review_policies_version"),
        CheckConstraint("version > 0", name="ck_kyc_review_policies_version"),
        CheckConstraint("normal_max_months > 0", name="ck_kyc_review_policies_normal"),
        CheckConstraint(
            "elevated_max_months IS NULL OR "
            "(elevated_max_months > 0 AND elevated_max_months <= normal_max_months)",
            name="ck_kyc_review_policies_elevated",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="ck_kyc_review_policies_validity",
        ),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    jurisdiction = Column(String, nullable=False)
    policy_id = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    normal_max_months = Column(Integer, nullable=False)
    elevated_max_months = Column(Integer)
    valid_from = Column(String, nullable=False)
    valid_until = Column(String)
    source_reference = Column(String, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    policy_hash = Column(String, nullable=False)


class KycReviewPolicyActivation(Base):
    """Vier-Augen-Freigabe = Aktivierung einer Policy-Version. Bindet den
    gesehenen ``policy_hash`` und die unveraenderliche Freigabereferenz."""

    __tablename__ = "kyc_review_policy_activations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "jurisdiction", "predecessor_activation_id",
            name="uq_kyc_review_policy_activations_chain",
        ),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    jurisdiction = Column(String, nullable=False)
    policy_row_id = Column(String, nullable=False, unique=True)
    predecessor_activation_id = Column(String, nullable=False)
    approved_by = Column(String, ForeignKey("users.id"), nullable=False)
    approved_at = Column(String, nullable=False)
    approval_reference = Column(String, nullable=False)
    policy_hash = Column(String, nullable=False)
    activation_hash = Column(String, nullable=False)
    # Nachtrag 4 (N-897-13): Bereitschaft des Freigebers zum Freigabezeitpunkt
    # (1 = geprueft; NULL = Bestand, dann zaehlt der heutige Kontostand).
    approver_ready = Column(Integer)


for _model, _ddls in (
    (KycReviewPolicy, KYC_REVIEW_POLICY_SQLITE_TRIGGERS),
    (KycReviewPolicyActivation, KYC_REVIEW_POLICY_ACTIVATION_SQLITE_TRIGGERS),
):
    for _trigger_ddl in _ddls:
        event.listen(
            _model.__table__,
            "after_create",
            DDL(_trigger_ddl).execute_if(dialect="sqlite"),
        )
