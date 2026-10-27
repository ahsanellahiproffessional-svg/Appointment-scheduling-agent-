from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks

import app.email_service as email_service
import main
from app.schemas import BookingInfo, ChatRequest, ChatResponse


class EmailServiceTests(unittest.TestCase):
    def test_sends_html_confirmation_using_resend(self) -> None:
        with (
            patch.object(email_service, "RESEND_API_KEY", "re_test"),
            patch.object(email_service, "RESEND_FROM_EMAIL", "Scheduler <test@example.com>"),
            patch.object(email_service.resend.Emails, "send", return_value={"id": "email-1"}) as send,
        ):
            asyncio.run(
                email_service.send_appointment_email(
                    "alice@example.com",
                    "<Alice>",
                    "Saturday, October 24, 2026",
                    "02:00 PM UTC+05:00",
                )
            )

        params = send.call_args.args[0]
        self.assertEqual(params["to"], ["alice@example.com"])
        self.assertEqual(params["from"], "Scheduler <test@example.com>")
        self.assertIn("&lt;Alice&gt;", params["html"])
        self.assertIn("Saturday, October 24, 2026", params["html"])
        self.assertIn("02:00 PM UTC+05:00", params["html"])

    def test_missing_api_key_is_logged_without_sending(self) -> None:
        with (
            patch.object(email_service, "RESEND_API_KEY", ""),
            patch.object(email_service.resend.Emails, "send") as send,
            self.assertLogs(email_service.logger, level="ERROR"),
        ):
            asyncio.run(
                email_service.send_appointment_email(
                    "alice@example.com", "Alice", "October 24, 2026", "02:00 PM"
                )
            )

        send.assert_not_called()

    def test_delivery_failure_is_logged_and_handled(self) -> None:
        with (
            patch.object(email_service, "RESEND_API_KEY", "re_test"),
            patch.object(email_service.resend.Emails, "send", side_effect=RuntimeError("delivery failed")),
            self.assertLogs(email_service.logger, level="ERROR"),
        ):
            asyncio.run(
                email_service.send_appointment_email(
                    "alice@example.com", "Alice", "October 24, 2026", "02:00 PM"
                )
            )


class ChatEmailNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_queues_one_email_when_a_new_booking_is_confirmed(self) -> None:
        session_id = "email-notification-test"
        booking = BookingInfo(
            event_title="Dental appointment",
            start_time="2026-10-24T14:00:00+05:00",
            participants=["alice@example.com"],
            status="confirmed",
            calendar_event_id="event-1",
        )

        def confirm_booking(session, _message):
            session.booking = booking
            return ChatResponse(
                session_id=session.session_id,
                reply="Your appointment is confirmed.",
                booking=booking,
            )

        with patch.object(main, "run_agent_turn", side_effect=confirm_booking):
            with patch.object(
                main, "send_appointment_email", new_callable=AsyncMock
            ) as send_email:
                background_tasks = BackgroundTasks()
                response = await main.chat(
                    ChatRequest(
                        session_id=session_id,
                        message="Confirm the appointment",
                    ),
                    background_tasks,
                )
                self.assertEqual(len(background_tasks.tasks), 1)
                send_email.assert_not_awaited()
                await background_tasks()

                duplicate_tasks = BackgroundTasks()
                duplicate_response = await main.chat(
                    ChatRequest(session_id=session_id, message="Thanks"),
                    duplicate_tasks,
                )
                self.assertEqual(len(duplicate_tasks.tasks), 0)
                await duplicate_tasks()

        self.assertEqual(response.session_id, session_id)
        self.assertEqual(duplicate_response.session_id, session_id)
        send_email.assert_awaited_once_with(
            "alice@example.com",
            "Alice",
            "Saturday, October 24, 2026",
            "02:00 PM UTC+05:00",
        )


if __name__ == "__main__":
    unittest.main()
