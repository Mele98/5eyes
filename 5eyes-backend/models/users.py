from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
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
