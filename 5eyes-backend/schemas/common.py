from pydantic import BaseModel, ConfigDict
from typing import Optional


class BaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str


class PaginatedResponse(BaseModel):
    total: int
    items: list


# MONEY-COLUMN-WIDTH-001: Betragsspalten sind BIGINT (SQLite INTEGER / Postgres
# bigint), also vorzeichenbehaftet 64 Bit. Ein Python-int ausserhalb dieses
# Bereichs ist auf keiner Plattform speicherbar und endete sonst als HTTP 500
# beim Schreiben; am API-Rand wird er mit 422 abgelehnt.
PERSISTABLE_INT_MAX = 2**63 - 1
PERSISTABLE_INT_MIN = -(2**63)
