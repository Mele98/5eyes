"""Sprint U-36 (2026-06-06): Client-Login-Linkage zwischen User und Client.

Stellt die 1:1-Verbindung her: ein User mit role='client' ist genau einem
Client zugeordnet (= seine eigene Berater-Akte). Der Advisor erstellt diese
Linkage einmalig pro Kunde via Admin-Endpoint.

Schema-Trennung von User: KEIN neuer Column auf User-Tabelle (vermeidet
Migration-Risiko bei bestehenden Produktiv-DBs ohne alembic).
"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base


class ClientLogin(Base):
    """1:1 Linkage User <-> Client fuer role='client'.

    Erzeugt durch den Advisor via Admin-Endpoint. Wenn ein Client-User
    sich einloggt, fetcht require_client() die zugehoerige Client-ID
    aus dieser Tabelle.
    """
    __tablename__ = "client_logins"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_client_logins_user_id"),
        UniqueConstraint("client_id", name="uq_client_logins_client_id"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    is_active = Column(Integer, nullable=False, default=1)

    user = relationship("User", foreign_keys=[user_id])
    client = relationship("Client", foreign_keys=[client_id])
    creator = relationship("User", foreign_keys=[created_by])
