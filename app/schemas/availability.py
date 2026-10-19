from __future__ import annotations

from pydantic import BaseModel


class SlotRead(BaseModel):
    start: str
    end: str


class DayAvailabilityRead(BaseModel):
    date: str
    slots: list[SlotRead]


class AvailabilityResponse(BaseModel):
    service_id: str
    service_name: str
    duration_minutes: int
    buffer_minutes: int
    timezone: str
    days: list[DayAvailabilityRead]
