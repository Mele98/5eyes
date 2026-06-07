"""Bug-#13a (2026-06-07): Beratungsprotokoll-Baustein-Bibliothek.

Modellschicht fuer die Berater-eigene Baustein-Bibliothek (CRUD) und
die N:M-Zuordnung pro Mandat.

- ProtocolBaustein: Bibliotheks-Eintrag. advisor_id nullable -> NULL bedeutet
  'global verfuegbar' (vom Tenant-Admin gepflegt). Soft-delete via deleted_at.
- MandateBausteinSelection: Auswahl + Sort-Order + optionaler Berater-
  Override-Text pro Mandat.

Frontend + PDF-Render kommen separat (PDF ist Codex-Scope).
"""
from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship

from database import Base


class ProtocolBaustein(Base):
    __tablename__ = "protocol_bausteine"

    id = Column(String, primary_key=True)
    # NULL = global (Tenant-/Admin-gepflegt). Sonst = Berater-eigener Baustein.
    advisor_id = Column(String, ForeignKey("users.id"), nullable=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True)
    title = Column(String, nullable=False)
    content_md = Column(String, nullable=False, default="")
    category = Column(String)  # z.B. 'Risikoaufklaerung', 'Anlagestrategie'
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    __table_args__ = (
        Index("ix_protocol_bausteine_advisor", "advisor_id"),
        Index("ix_protocol_bausteine_tenant", "tenant_id"),
    )


class MandateBausteinSelection(Base):
    """N:M zwischen Mandate und Baustein fuer die Protokoll-Komposition.

    sort_order bestimmt die Reihenfolge im gerenderten Protokoll.
    custom_override_md erlaubt fallweise Anpassung des Baustein-Texts
    pro Mandat (z.B. Klienten-spezifische Erlaeuterung) ohne die
    Bibliothek zu mutieren.
    """
    __tablename__ = "mandate_baustein_selections"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    baustein_id = Column(String, ForeignKey("protocol_bausteine.id"), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    custom_override_md = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("mandate_id", "baustein_id", name="uq_mandate_baustein"),
        Index("ix_mandate_baustein_selections_mandate", "mandate_id"),
    )
