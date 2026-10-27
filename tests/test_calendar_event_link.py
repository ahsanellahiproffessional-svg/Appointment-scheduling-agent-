from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.agent import _execute_tool, _update_booking_from_tool
from app.schemas import ChatResponse, EventCreate
from app.session_manager import Session


class CalendarEventLinkTests(unittest.TestCase):
    def test_calendar_html_link_is_included_in_chat_booking_payload(self) -> None:
        event_link = "https://calendar.google.com/calendar/event?eid=event-123"
        event_data = EventCreate(
            summary="Project review",
            start_datetime="2026-10-24T14:00:00+05:00",
            end_datetime="2026-10-24T15:00:00+05:00",
            attendees=["alice@example.com"],
        )
        created_event = {
            "id": "event-123",
            "htmlLink": event_link,
            "summary": "Project review",
            "start": {"dateTime": event_data.start_datetime},
            "end": {"dateTime": event_data.end_datetime},
        }

        with patch("app.agent.create_event", return_value=created_event):
            tool_result = _execute_tool(
                "create_calendar_event",
                {
                    "summary": event_data.summary,
                    "start_datetime": event_data.start_datetime,
                    "end_datetime": event_data.end_datetime,
                    "attendees": event_data.attendees,
                },
            )

        session = Session(session_id="calendar-link-test")
        _update_booking_from_tool(
            session,
            "create_calendar_event",
            {
                "summary": event_data.summary,
                "start_datetime": event_data.start_datetime,
                "end_datetime": event_data.end_datetime,
                "attendees": event_data.attendees,
            },
            tool_result,
        )
        payload = ChatResponse(
            session_id=session.session_id,
            reply="Appointment confirmed.",
            booking=session.booking,
        ).model_dump(mode="json")

        self.assertEqual(json.loads(tool_result)["html_link"], event_link)
        self.assertEqual(payload["booking"]["calendar_event_link"], event_link)


if __name__ == "__main__":
    unittest.main()
