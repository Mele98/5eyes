"""Bug-#13a (2026-06-07): Pydantic-Schemas fuer Baustein-Bibliothek."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class BausteinCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content_md: str = ""
    category: Optional[str] = Field(default=None, max_length=100)
    sort_order: int = 0


class BausteinUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    content_md: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=100)
    sort_order: Optional[int] = None
    is_active: Optional[int] = None


class BausteinResponse(BaseModel):
    id: str
    advisor_id: Optional[str]
    tenant_id: Optional[str]
    title: str
    content_md: str
    category: Optional[str]
    sort_order: int
    is_active: int
    created_at: str
    updated_at: str


class MandateBausteinSelectionItem(BaseModel):
    baustein_id: str
    sort_order: int = 0
    custom_override_md: Optional[str] = None


class MandateBausteinSelectionUpdate(BaseModel):
    selections: list[MandateBausteinSelectionItem]
    # 2026-07-25 (Generalaudit): custom_override_md ist laut Modell-Docstring
    # explizit fuer "Klienten-spezifische Erlaeuterung" gedacht -- Phase-0-Gate
    # fehlte, obwohl es echten Freitext pro Mandat enthalten kann.
    data_classification: Literal["synthetic", "real"] = "synthetic"


class MandateBausteinSelectionResponse(BaseModel):
    id: str
    mandate_id: str
    baustein_id: str
    sort_order: int
    custom_override_md: Optional[str]
    created_at: str
    updated_at: str
    # Convenience: angereicherter Titel + Content fuers Frontend
    title: Optional[str] = None
    content_md: Optional[str] = None
    category: Optional[str] = None
