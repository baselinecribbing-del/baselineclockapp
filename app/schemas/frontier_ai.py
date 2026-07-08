from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class FrontierAISelectedRecord(BaseModel):
    record_type: str = Field(min_length=1, max_length=64)
    record_id: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] | None = None

    @field_validator("record_type", "record_id", mode="before")
    @classmethod
    def _strip_required(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value cannot be blank")
        return text


class FrontierAIQueryRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=128)
    page_context: dict[str, Any] | None = None
    surface_context: str | None = Field(default=None, max_length=255)
    selected_record: FrontierAISelectedRecord | None = None

    @field_validator("message", "conversation_id", "surface_context", mode="before")
    @classmethod
    def _strip_optional_strings(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return text


class FrontierAIQueryResponse(BaseModel):
    conversation_id: str
    reply: str
    capability_status: Literal["enabled"]
    company_id: int
    warning: str | None = None
    created_at: datetime
    updated_at: datetime
