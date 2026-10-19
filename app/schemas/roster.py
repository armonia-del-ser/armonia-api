from __future__ import annotations

from pydantic import BaseModel, model_validator


class RosterAttendeeRead(BaseModel):
    booking_id: str
    booking_code: str
    client_id: str
    client_name: str
    client_phone: str
    client_email: str | None = None
    booking_status: str
    payment_arrangement: str
    payment_status: str
    amount_mxn: int
    attended: bool


class RosterSessionRead(BaseModel):
    service_id: str
    service_name: str
    scheduled_at: str
    max_capacity: int
    occupied_count: int
    attended_count: int
    attendees: list[RosterAttendeeRead]


class QuickCheckinRequest(BaseModel):
    # Mode 1: existing booking check-in
    booking_id: str | None = None

    # Mode 2: walk-in check-in
    service_id: str | None = None
    scheduled_at: str | None = None
    client_name: str | None = None
    client_phone: str | None = None
    client_email: str | None = None

    paid_cash: bool = False
    notes: str | None = None

    @model_validator(mode="after")
    def validate_exactly_one_mode(self) -> QuickCheckinRequest:
        has_booking_id = bool(self.booking_id)
        has_any_walk_in = any(
            [self.service_id, self.scheduled_at, self.client_name, self.client_phone]
        )
        is_complete_walk_in = bool(
            self.service_id and self.scheduled_at and self.client_name and self.client_phone
        )

        if has_booking_id:
            if has_any_walk_in:
                raise ValueError("Cannot combine 'booking_id' with walk-in fields.")
            return self

        if is_complete_walk_in:
            return self

        raise ValueError(
            "Must provide either 'booking_id' for an existing booking, "
            "or ('service_id', 'scheduled_at', 'client_name', 'client_phone') for a walk-in."
        )


class QuickCheckinResponse(BaseModel):
    walk_in: bool
    attendee: RosterAttendeeRead
    payment_id: str | None = None
