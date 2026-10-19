import uuid
from enum import StrEnum
from typing import Annotated

from pydantic import BeforeValidator, EmailStr
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel
from sqlmodel._compat import SQLModelConfig

from app.services.timestamps import utc_now_iso


class RoleEnum(StrEnum):
    OWNER = "OWNER"
    ASSISTANT = "ASSISTANT"
    ADMIN = "ADMIN"


UserRole = Annotated[RoleEnum, BeforeValidator(lambda v: RoleEnum(v) if isinstance(v, str) else v)]


class AdminAllowlist(SQLModel, table=True):
    model_config = SQLModelConfig(strict=True)
    __tablename__ = "admin_allowlist"  # pyright: ignore[reportAssignmentType]
    email: EmailStr = Field(primary_key=True)
    full_name: str
    role: UserRole = Field(default=RoleEnum.ASSISTANT)
    is_active: bool = Field(default=True)
    created_at: str = Field(default_factory=utc_now_iso)
    last_login_at: str | None = None


class ActionTypeEnum(StrEnum):
    # Should we include DELETE/UPDATE_SERVICE?
    # Do all actions belong to this class?
    CREATE_PACKAGE = "CREATE_PACKAGE"
    UPDATE_PACKAGE = "UPDATE_PACKAGE"
    CREATE_SERVICE = "CREATE_SERVICE"
    ACKNOWLEDGE_PAYMENT = "ACKNOWLEDGE_PAYMENT"
    UPSERT_ALLOWLIST = "UPSERT_ALLOWLIST"
    UPDATE_ALLOWLIST = "UPDATE_ALLOWLIST"
    AUTHORIZE_DELAYED_PAYMENT = "AUTHORIZE_DELAYED_PAYMENT"
    UPDATE_BOOKING_STATUS = "UPDATE_BOOKING_STATUS"
    RELEASE_BOOKING = "RELEASE_BOOKING"
    RETRY_CALENDAR_SYNC = "RETRY_CALENDAR_SYNC"
    ROSTER_CHECKIN = "ROSTER_CHECKIN"
    ROSTER_WALK_IN = "ROSTER_WALK_IN"


ActionType = Annotated[
    ActionTypeEnum, BeforeValidator(lambda v: ActionTypeEnum(v) if isinstance(v, str) else v)
]


class EntityTypeEnum(StrEnum):
    ADMIN_ALLOW_LIST = "admin_allow_list"
    BOOKING = "booking"
    PACKAGE = "package"


EntityType = Annotated[
    EntityTypeEnum, BeforeValidator(lambda v: EntityTypeEnum(v) if isinstance(v, str) else v)
]


class AdminAuditLog(SQLModel, table=True):
    model_config = SQLModelConfig(strict=True)
    __tablename__ = "admin_audit_log"  # pyright: ignore[reportAssignmentType]
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    admin_email: EmailStr = Field(foreign_key="admin_allowlist.email")
    action_type: ActionType
    entity_type: EntityType = Field(
        sa_type=SAEnum(EntityTypeEnum, values_callable=lambda x: [e.value for e in x])
    )
    entity_id: str
    details_json: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
