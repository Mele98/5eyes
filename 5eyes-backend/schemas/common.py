from pydantic import BaseModel, ConfigDict
from typing import Optional


class BaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str


class PaginatedResponse(BaseModel):
    total: int
    items: list
