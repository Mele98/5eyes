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

from sqlalchemy import Column, Integer, String

from database import Base


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
# Scoring-Wirkung, siehe FZK-Cap in 5eyes_v2.html).
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

    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)
