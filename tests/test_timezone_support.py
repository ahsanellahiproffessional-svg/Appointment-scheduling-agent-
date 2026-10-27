from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.agent import run_agent_turn
from app.config import CALENDAR_TIMEZONE
from app.session_manager import Session


class TimezoneSupportTests(unittest.TestCase):
    def test_agent_can_start_a_turn_in_configured_timezone(self) -> None:
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(tool_calls=None, content="How can I help?")
                )
            ]
        )
        with patch("app.agent.client.chat.completions.create", return_value=response):
            result = run_agent_turn(Session(session_id="timezone-test"), "Hello")

        self.assertEqual(result.reply, "How can I help?")
        self.assertIsNotNone(ZoneInfo(CALENDAR_TIMEZONE))


if __name__ == "__main__":
    unittest.main()
