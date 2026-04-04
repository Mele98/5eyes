from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class Client(Base):
    __tablename__ = "clients"

    id = Column(String, primary_key=True)
    client_number = Column(String, nullable=False, unique=True)
    salutation = Column(String)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    date_of_birth = Column(String)
    investment_horizon_start = Column(String)
    investment_horizon_end = Column(String)
    country_of_residence = Column(String, nullable=False, default="CH")
    canton = Column(String)
    civil_status = Column(String)
    profession = Column(String)
    employer = Column(String)
    language = Column(String, nullable=False, default="DE")
    partner_salutation = Column(String)
    partner_first_name = Column(String)
    partner_last_name = Column(String)
    partner_date_of_birth = Column(String)
    partner_profession = Column(String)
    household_type = Column(String, nullable=False, default="Einzelperson")
    client_classification = Column(String, nullable=False, default="Privatkunde")
    is_professional_opt_out = Column(Integer, nullable=False, default=0)
    is_qualified_investor = Column(Integer, nullable=False, default=0)
    advisor_id = Column(String, ForeignKey("users.id"), nullable=False)
    notes = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    advisor = relationship("User", back_populates="clients")
    nationalities = relationship("ClientNationality", back_populates="client")
    opt_history = relationship("ClientOptHistory", back_populates="client")
    mandates = relationship("Mandate", back_populates="client")
    wealth_positions = relationship("WealthPosition", back_populates="client")
    cashflows = relationship("Cashflow", back_populates="client")


class ClientNationality(Base):
    __tablename__ = "client_nationalities"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    country_code = Column(String, nullable=False)
    is_primary = Column(Integer, nullable=False, default=0)
    created_at = Column(String, nullable=False)

    client = relationship("Client", back_populates="nationalities")


class ClientOptHistory(Base):
    __tablename__ = "client_opt_history"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    event_type = Column(String, nullable=False)
    from_classification = Column(String, nullable=False)
    to_classification = Column(String, nullable=False)
    client_requested = Column(Integer, nullable=False, default=1)
    documented_by = Column(String, ForeignKey("users.id"), nullable=False)
    documented_at = Column(String, nullable=False)
    document_id = Column(String)
    notes = Column(String)
    created_at = Column(String, nullable=False)

    client = relationship("Client", back_populates="opt_history")
