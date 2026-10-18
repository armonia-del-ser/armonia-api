from __future__ import annotations

from pydantic import BaseModel, Field


class ClientBase(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=150)
    phone_whatsapp: str = Field(..., min_length=10, max_length=20)
    email: str | None = None
    notes: str | None = None


class ClientCreate(ClientBase):
    pass


class ClientRead(ClientBase):
    id: str
    created_at: str
