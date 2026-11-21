"""Schemas der Vertragsschicht (H-179, L2/L3)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class OwnerContentCreate(BaseModel):
    """Neue Version eines Owner-Inhalts. Text (``body_text``) oder typisierter
    Wert (``value``) je nach Katalogart; der Server vergibt die Version."""

    content_key: str = Field(min_length=3, max_length=200)
    body_text: Optional[str] = Field(default=None, max_length=20000)
    value: Optional[Any] = None
    source_reference: str = Field(min_length=1, max_length=500)


class OwnerContentApprove(BaseModel):
    content_hash: str = Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")
    approval_reference: str = Field(min_length=1, max_length=500)


class AdviceRationaleCreate(BaseModel):
    client_needs: str = Field(min_length=1, max_length=10000)
    recommendation_reasons: str = Field(min_length=1, max_length=10000)


class W033DeclarationCreate(BaseModel):
    declaration_kind: Literal["angaben_wahr_meldepflicht", "horizont_abraten"]
    capture_channel: Literal["persoenlich_papier", "vor_ort", "kundenportal"]
    confirmed_at: str = Field(min_length=10, max_length=40)
    content_hash: str = Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")
