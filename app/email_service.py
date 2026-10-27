"""Resend email delivery for appointment confirmations."""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime

import resend

from app.config import RESEND_API_KEY, RESEND_FROM_EMAIL

logger = logging.getLogger(__name__)


async def send_appointment_email(
    to_email: str,
    user_name: str,
    appointment_date: str,
    appointment_time: str,
) -> None:
    """Send an appointment confirmation without blocking the event loop."""
    if not RESEND_API_KEY:
        logger.error(
            "Appointment confirmation email not sent: RESEND_API_KEY is not configured."
        )
        return

    safe_name = html.escape(user_name)
    safe_date = html.escape(appointment_date)
    safe_time = html.escape(appointment_time)
    params: resend.Emails.SendParams = {
        "from": RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": "Your appointment is confirmed",
        "html": f"""\
<!doctype html>
<html lang="en">
  <body style="margin:0;background:#f4f4f7;font-family:Arial,sans-serif;color:#222;">
    <div style="max-width:560px;margin:32px auto;padding:28px;background:#fff;border-radius:12px;">
      <h1 style="margin-top:0;color:#4338ca;font-size:24px;">Appointment confirmed</h1>
      <p>Hello {safe_name},</p>
      <p>Your appointment has been booked. Here are the details:</p>
      <table role="presentation" style="border-collapse:collapse;width:100%;">
        <tr>
          <th scope="row" style="padding:10px;text-align:left;">Date</th>
          <td style="padding:10px;">{safe_date}</td>
        </tr>
        <tr>
          <th scope="row" style="padding:10px;text-align:left;">Time</th>
          <td style="padding:10px;">{safe_time}</td>
        </tr>
      </table>
      <p style="margin-bottom:0;">Thank you,<br>ScheduleAI</p>
    </div>
  </body>
</html>""",
    }

    try:
        resend.api_key = RESEND_API_KEY
        await asyncio.to_thread(resend.Emails.send, params)
    except Exception:
        logger.exception("Appointment confirmation email delivery failed.")
        return

    logger.info("Appointment confirmation email sent successfully.")


def format_appointment_datetime(start_time: str) -> tuple[str, str]:
    """Format an RFC 3339 event start time for the confirmation email."""
    appointment_start = datetime.fromisoformat(start_time)
    date = appointment_start.strftime("%A, %B %d, %Y")
    time = appointment_start.strftime("%I:%M %p %Z").strip()
    return date, time
