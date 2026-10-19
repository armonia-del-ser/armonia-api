from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AdminRole = Literal["OWNER", "ASSISTANT", "ADMIN"]


class AdminPrincipal(BaseModel):
    email: str
    full_name: str
    role: AdminRole
    is_active: bool = True
    last_login_at: str | None = None


class AdminAllowlistCreate(BaseModel):
    email: str = Field(..., min_length=5)
    full_name: str = Field(..., min_length=2)
    role: AdminRole = "ASSISTANT"
    is_active: bool = True


class AdminAllowlistUpdate(BaseModel):
    full_name: str | None = None
    role: AdminRole | None = None
    is_active: bool | None = None


class AuditLogRead(BaseModel):
    id: str
    admin_email: str
    action_type: str
    entity_type: str
    entity_id: str
    details_json: str | None = None
    created_at: str
