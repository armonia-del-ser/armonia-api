import re
import uuid

from pydantic import EmailStr, field_validator
from sqlmodel import Field, SQLModel
from sqlmodel._compat import SQLModelConfig

from app.services.timestamps import utc_now_iso


class Client(SQLModel, table=True):
    model_config = SQLModelConfig(strict=True)
    __tablename__ = "clients"  # pyright: ignore[reportAssignmentType]
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    full_name: str
    phone_whatsapp: str = Field(index=True)
    email: EmailStr | None = None
    notes: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)

    @field_validator("phone_whatsapp")
    @classmethod
    def validate_phone_number(cls, v: str) -> str:
        PHONE_WITH_EXT_REGEX = re.compile(
            r"^((?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?){2,4}\d{3,4})(?:[-.\s]*(?:ext|ext\.|x|#|extension)[-.\s]*(\d+))?$",
            re.IGNORECASE,
        )

        clean_value = v.strip()

        match_value = PHONE_WITH_EXT_REGEX.match(clean_value)
        if not match_value:
            raise ValueError(
                "Invalid phone number format. Examples of valid formats: "
                "'+1 (555) 019-2834', '555-019-2834 ext 123', or '5550192834x12'"
            )
        return clean_value
