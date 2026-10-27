"""
Google Calendar Service — handles OAuth2 authentication, availability checks,
and event creation via the Google Calendar API v3.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.config import (
    TOKEN_PATH,
    SCOPES,
    CALENDAR_TIMEZONE,
    DEFAULT_EVENT_DURATION_MINUTES,
)

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.schemas import EventCreate, TimeSlot

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Authentication
# ─────────────────────────────────────────────────────────────────────────────

def _get_credentials() -> Credentials:
    """
    Load cached credentials from *token.json*.  If expired, refresh them.
    If no cached credentials exist, direct the user to the FastAPI OAuth flow.
    """
    creds: Optional[Credentials] = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Google OAuth token …")
            creds.refresh(Request())
        else:
            raise RuntimeError(
                "Google Calendar is not authorized. Open "
                "http://127.0.0.1:8001/auth/google to connect your calendar."
            )

        # Persist for next run
        TOKEN_PATH.write_text(creds.to_json())
        logger.info("Token saved to %s", TOKEN_PATH)

    return creds


def get_calendar_service():
    """Return an authorised Google Calendar API service object."""
    creds = _get_credentials()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


# ─────────────────────────────────────────────────────────────────────────────
#  Availability Check
# ─────────────────────────────────────────────────────────────────────────────

def check_availability(
    start_datetime: str,
    end_datetime: str,
    calendar_id: str = "primary",
) -> dict:
    """
    Check whether the requested window is free on the user's calendar.

    Parameters
    ----------
    start_datetime : str   – RFC 3339 datetime  (e.g. "2026-10-24T15:00:00+05:00")
    end_datetime   : str   – RFC 3339 datetime
    calendar_id    : str   – Calendar to query (default: ``"primary"``)

    Returns
    -------
    dict with keys:
        available : bool
        conflicts : list[dict]   – overlapping events (summary + start/end)
    """
    service = get_calendar_service()

    try:
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_datetime,
            timeMax=end_datetime,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = events_result.get("items", [])
        conflicts = [
            {
                "summary": ev.get("summary", "(No title)"),
                "start": ev["start"].get("dateTime", ev["start"].get("date")),
                "end": ev["end"].get("dateTime", ev["end"].get("date")),
            }
            for ev in events
        ]

        return {"available": len(conflicts) == 0, "conflicts": conflicts}

    except HttpError as exc:
        logger.error("Calendar API error during availability check: %s", exc)
        raise RuntimeError(f"Google Calendar API error: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
#  Free-Slot Finder
# ─────────────────────────────────────────────────────────────────────────────

def get_free_slots(
    date: str,
    slot_duration_minutes: int = DEFAULT_EVENT_DURATION_MINUTES,
    working_hours: tuple[int, int] = (9, 17),
    calendar_id: str = "primary",
) -> list[TimeSlot]:
    """
    Return a list of free slots for a given *date* within working hours.

    Parameters
    ----------
    date                 : str   – ISO date  (e.g. "2026-10-24")
    slot_duration_minutes: int   – length of each candidate slot
    working_hours        : tuple – (start_hour, end_hour) in 24-h format
    calendar_id          : str

    Returns
    -------
    list[TimeSlot]
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(CALENDAR_TIMEZONE)
    day = datetime.fromisoformat(date).date()
    work_start = datetime(day.year, day.month, day.day, working_hours[0], tzinfo=tz)
    work_end = datetime(day.year, day.month, day.day, working_hours[1], tzinfo=tz)

    service = get_calendar_service()

    body = {
        "timeMin": work_start.isoformat(),
        "timeMax": work_end.isoformat(),
        "timeZone": CALENDAR_TIMEZONE,
        "items": [{"id": calendar_id}],
    }

    try:
        freebusy = service.freebusy().query(body=body).execute()
    except HttpError as exc:
        logger.error("Calendar freebusy error: %s", exc)
        raise RuntimeError(f"Google Calendar API error: {exc}") from exc

    busy_periods = freebusy["calendars"][calendar_id]["busy"]

    # Parse busy intervals
    busy_intervals: list[tuple[datetime, datetime]] = []
    for period in busy_periods:
        bs = datetime.fromisoformat(period["start"])
        be = datetime.fromisoformat(period["end"])
        busy_intervals.append((bs, be))

    # Walk through the day in slot_duration_minutes increments
    free_slots: list[TimeSlot] = []
    cursor = work_start
    delta = timedelta(minutes=slot_duration_minutes)

    while cursor + delta <= work_end:
        slot_end = cursor + delta
        is_free = all(
            slot_end <= bs or cursor >= be for bs, be in busy_intervals
        )
        if is_free:
            free_slots.append(TimeSlot(start=cursor, end=slot_end))
        cursor += delta

    return free_slots


# ─────────────────────────────────────────────────────────────────────────────
#  Event Creation
# ─────────────────────────────────────────────────────────────────────────────

def create_event(event: EventCreate, calendar_id: str = "primary") -> dict:
    """
    Create a new event on Google Calendar.

    Returns
    -------
    dict  – the created event resource (contains ``id``, ``htmlLink``, etc.)
    """
    service = get_calendar_service()

    body = {
        "summary": event.summary,
        "description": event.description,
        "start": {
            "dateTime": event.start_datetime,
            "timeZone": event.timezone,
        },
        "end": {
            "dateTime": event.end_datetime,
            "timeZone": event.timezone,
        },
        "attendees": [{"email": email} for email in event.attendees],
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 30},
                {"method": "popup", "minutes": 10},
            ],
        },
    }

    try:
        created = (
            service.events()
            .insert(calendarId=calendar_id, body=body, sendUpdates="all")
            .execute()
        )
        logger.info(
            "Event created: %s  (%s)", created["id"], created.get("htmlLink")
        )
        return created

    except HttpError as exc:
        logger.error("Calendar API error creating event: %s", exc)
        raise RuntimeError(f"Failed to create calendar event: {exc}") from exc
