"""Kompatibilitaets-Export: die Override-DDL liegt in
``core/product_eligibility_override_schema.py``.

Das Modell (``models/product_eligibility.py``) liest die DDL aus ``core``,
damit die Modellschicht nicht von ``services`` abhaengt (Architektur-Ratsche,
Schichtung Router -> Service -> Model). Dieser Export haelt die
Alembic-Migration ``f4b8d2a6c1e7`` und bestehende Aufrufer unveraendert.
"""
from __future__ import annotations

from core.product_eligibility_override_schema import (  # noqa: F401
    IMMUTABLE_MESSAGE,
    OVERRIDE_COLUMNS,
    POSTGRES_FUNCTION,
    POSTGRES_FUNCTION_NAME,
    POSTGRES_RUN_FK_NAME,
    POSTGRES_TRIGGER,
    POSTGRES_TRIGGER_NAME,
    RUN_PRODUCT_INDEX,
    SQLITE_TRIGGER_NAMES,
    SQLITE_TRIGGERS,
    TABLE,
    ensure_sqlite_override_append_only,
)
