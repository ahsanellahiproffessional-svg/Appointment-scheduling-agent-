"""
Pydantic schemas for API request / response models and internal data transfer.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ─── Chat API ───────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """Incoming user message."""
    session_id: str = Field(
        ...,
        description="Unique session identifier for multi-turn context.",
        examples=["sess_abc123"],
    )
    message: str = Field(
        ...,
        description="The user's natural-language message.",
        examples=["Book a meeting tomorrow at 3 PM with alice@example.com"],
    )


class BookingInfo(BaseModel):
    """Structured booking details extracted by the agent."""
    event_title: Optional[str] = None
    date: Optional[str] = None          # ISO-8601 date string
    start_time: Optional[str] = None    # ISO-8601 datetime string
    end_time: Optional[str] = None      # ISO-8601 datetime string
    participants: list[str] = Field(default_factory=list)
    status: str = Field(
        default="pending",
        description="One of: pending | confirmed | conflict | cancelled",
    )
    calendar_event_id: Optional[str] = None
    calendar_event_link: Optional[str] = None


class ChatResponse(BaseModel):
    """Response returned to the client."""
    session_id: str
    reply: str
    booking: Optional[BookingInfo] = None


# ─── Calendar helpers ───────────────────────────────────────────────────────

class TimeSlot(BaseModel):
    """A free / busy window on the calendar."""
    start: datetime
    end: datetime


class EventCreate(BaseModel):
    """Parameters required to create a Google Calendar event."""
    summary: str
    start_datetime: str          # RFC 3339
    end_datetime: str            # RFC 3339
    timezone: str = "Asia/Karachi"
    attendees: list[str] = Field(default_factory=list)
    description: str = ""
