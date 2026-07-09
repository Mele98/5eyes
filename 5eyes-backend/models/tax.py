"""Tax reference data models.

Tax parameter sets are global reference data, not tenant data. They contain no
client information and can be shared across tenants safely.
"""
from __future__ import annotations

from sqlalchemy import Column, Integer, String

from database import Base


class TaxParameterSet(Base):
    __tablename__ = "tax_parameter_sets"

    id = Column(String, primary_key=True)
    country_code = Column(String, nullable=False, server_default="", index=True)
    region = Column(String, index=True)
    year = Column(Integer, nullable=False, server_default="2026", index=True)
    params_json = Column(String, nullable=False, server_default="{}")
    is_current = Column(Integer, nullable=False, default=1, server_default="1", index=True)
    version = Column(String, nullable=False, server_default="")
    source = Column(String, nullable=False, server_default="")
    created_at = Column(String, nullable=False, server_default="")
    updated_at = Column(String, nullable=False, server_default="")

