"""H10 (DSG-Technikaudit 2026-11-11): Fassade der Datenschutz-Governance fuer
``routers/privacy.py``.

Der Router importiert nur dieses Modul (eine Kante statt je Fachmodul eine):

* Bearbeitungsverzeichnis und Angaben des Verantwortlichen (C-DSG-01,
  services/privacy_owner_values.py, services/processing_activity_register.py).
"""
from __future__ import annotations

from services import privacy_erasure_inventory as erasure_inventory
from services.privacy_owner_values import (
    OWNER_VALUE_MAX_LENGTH,
    open_blocking_fields,
    owner_field_definitions,
    owner_field_status,
    owner_values,
    register_export,
    register_view,
    set_owner_value,
)

EVIDENCE_TYPES = erasure_inventory.EVIDENCE_TYPES
ERASURE_INVENTORY_VERSION = erasure_inventory.INVENTORY_VERSION

__all__ = [
    "ERASURE_INVENTORY_VERSION",
    "EVIDENCE_TYPES",
    "OWNER_VALUE_MAX_LENGTH",
    "open_blocking_fields",
    "owner_field_definitions",
    "owner_field_status",
    "owner_values",
    "register_export",
    "register_view",
    "set_owner_value",
]
