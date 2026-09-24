from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    # Sprint T1 (2026-06-08): tenant_id fuer 3-Tier-Architektur.
    # Nullable in Stage 9 fuer Backwards-Compat — Default-Tenant 'main'
    # wird via Migration / init_db angelegt und existing User darauf gemappt.
    # Siehe docs/adr/ADR-009-3-tier-hosting-architecture.md
    tenant_id = Column(String, ForeignKey("tenants.id"))
    username = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    email = Column(String)
    role = Column(String, nullable=False, default="advisor")
    is_active = Column(Integer, nullable=False, default=1)
    last_login_at = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)
    # E1 (2026-06-13): TOTP-2FA fuer externe Logins. Nullable/BC.
    totp_secret = Column(String)                              # Base32; bei Setup gesetzt
    totp_enabled = Column(Integer, nullable=False, default=0)  # 1 = 2FA aktiv & bestaetigt
    # E1 (2026-06-14): Mitarbeiter-Onboarding — erzwungener Passwortwechsel beim
    # ersten Login (von der Provisioning angelegte Accounts mit Initial-Passwort).
    must_change_password = Column(Integer, nullable=False, default=0)
    # E1 (2026-06-14): Invite-Link-Onboarding. Admin legt Account OHNE Passwort an,
    # der Mitarbeiter setzt es selbst per Einladungslink. invite_token_hash =
    # sha256(token) (Token nur einmalig im Klartext zurueckgegeben); invite_expires_at
    # = ISO-Ablauf. Beide nach Annahme geleert. Nullable/BC.
    invite_token_hash = Column(String)
    invite_expires_at = Column(String)

    # Self-Service-Recovery (#25/#27). Laufzeit-Migration bestehender DBs:
    # services.account_recovery.ensure_account_recovery_columns.
    reset_token_hash = Column(String)          # sha256(reset-token); single-use
    reset_token_expires_at = Column(String)
    totp_recovery_codes = Column(String)       # JSON-Liste sha256-Hashes der Backup-Codes

    # AUTH-04 (2026-07-22): pragmatische Token-Revocation ohne jti/Blacklist.
    # Logout setzt diesen Timestamp (ISO, ms-Praezision); get_current_user
    # verweigert jedes Token mit payload['iat'] < token_revoked_before (401).
    # Laufzeit-Migration bestehender DBs: database.ensure_runtime_columns.
    token_revoked_before = Column(String)
    # AUTH-06 (2026-07-22): Anti-Replay fuer TOTP-Login — letzter akzeptierter
    # HOTP-Zeitschritt (int als TEXT). Ein zweiter Login-Versuch mit Code aus
    # demselben oder einem frueheren Zeitschritt wird abgelehnt. services/totp.py
    # bleibt unveraendert; die Speicherung/Pruefung lebt im Login-Flow.
    totp_last_counter = Column(String)
    # SEC-TOTP-REPLAY-WINDOW (2026-09-15): totp_last_counter alleine erkennt
    # keinen Replay, sobald die Server-Uhr in das naechste Zeitfenster
    # weitergerueckt ist — services/totp.py::verify() akzeptiert denselben
    # Code wegen der +/-1-Drift-Toleranz weiterhin, und die reine
    # Zaehler-Monotonie (last < counter) laesst das Update dann zu. Diese
    # Spalte haelt zusaetzlich sha256(zuletzt akzeptierter Code) fest (analog
    # reset_token_hash/invite_token_hash oben — Klartext-Code wird NICHT
    # gespeichert) und blockiert die woertliche Wiederverwendung desselben
    # Codes unabhaengig vom Zeitfenster. Laufzeit-Migration bestehender DBs:
    # database.ensure_runtime_columns.
    totp_last_code_hash = Column(String)
    # REVIEW-CALENDAR-001 (Kontrollrunde 2026-09-24): opaker Feed-Token fuer
    # den persoenlichen .ics-Kalender-Abo-Endpoint (GET /calendar/reviews.ics)
    # -- Outlook kann keine interaktive Anmeldung durchfuehren, deshalb traegt
    # die Abo-URL selbst ein Geheimnis (analog reset_token_hash/
    # invite_token_hash: sha256(token) gespeichert, Klartext nur einmalig bei
    # der Erzeugung zurueckgegeben). Laufzeit-Migration bestehender DBs:
    # database.ensure_runtime_columns.
    calendar_feed_token_hash = Column(String)
    calendar_feed_token_created_at = Column(String)

    @property
    def invite_pending(self) -> bool:
        """True, solange eine Einladung offen ist (Account noch nicht aktiviert)."""
        return bool(getattr(self, "invite_token_hash", None))

    adviser_registration = relationship(
        "AdviserRegistration", back_populates="user", uselist=False
    )
    clients = relationship("Client", back_populates="advisor")


class AdviserRegistration(Base):
    __tablename__ = "adviser_registrations"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    register_body = Column(String, nullable=False, default="FINMA Beraterregister")
    register_number = Column(String)
    register_status = Column(String, nullable=False, default="Aktiv")
    registered_at = Column(String)
    register_valid_until = Column(String)
    ombudsman_body = Column(String)
    ombudsman_affiliated_since = Column(String)
    ombudsman_membership_number = Column(String)
    qualifications_json = Column(String)
    notes = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    user = relationship("User", back_populates="adviser_registration")
