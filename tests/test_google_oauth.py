from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

from fastapi import HTTPException
from starlette.requests import Request

import main


def make_callback_request(query: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/oauth2callback",
            "raw_path": b"/oauth2callback",
            "query_string": query.encode(),
            "headers": [],
            "server": ("127.0.0.1", 8001),
            "client": ("127.0.0.1", 50000),
        }
    )


class GoogleOAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        main._pending_oauth_flows.clear()

    def tearDown(self) -> None:
        main._pending_oauth_flows.clear()

    def test_callback_flow_exchanges_code_and_persists_scoped_credentials(self) -> None:
        flow = Mock()
        flow.authorization_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth?state=test-state",
            "test-state",
        )
        flow.oauth2session.state = "test-state"
        flow.credentials.has_scopes.return_value = True
        flow.credentials.to_json.return_value = '{"token":"test"}'

        with tempfile.TemporaryDirectory() as temp_dir:
            client_path = Path(temp_dir) / "client.json"
            client_path.write_text(json.dumps({"web": {}}), encoding="utf-8")
            token_path = Path(temp_dir) / "token.json"
            with (
                patch.object(main, "CREDENTIALS_PATH", client_path),
                patch.object(main, "TOKEN_PATH", token_path),
                patch.object(main.Flow, "from_client_secrets_file", return_value=flow) as create_flow,
            ):
                start_response = asyncio.run(main.start_google_oauth())
                callback_response = asyncio.run(
                    main.google_oauth_callback(
                        make_callback_request("state=test-state&code=authorization-code")
                    )
                )

            self.assertEqual(start_response.status_code, 302)
            self.assertEqual(
                parse_qs(urlparse(start_response.headers["location"]).query)["state"],
                ["test-state"],
            )
            create_flow.assert_called_once_with(
                str(client_path),
                scopes=main.SCOPES,
                redirect_uri=main.GOOGLE_REDIRECT_URI,
            )
            flow.fetch_token.assert_called_once_with(code="authorization-code")
            flow.credentials.has_scopes.assert_called_once_with(main.SCOPES)
            self.assertEqual(token_path.read_text(encoding="utf-8"), '{"token":"test"}')
            self.assertEqual(callback_response.status_code, 303)
            self.assertEqual(callback_response.headers["location"], "/")

    def test_callback_rejects_unknown_state(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                main.google_oauth_callback(
                    make_callback_request("state=invalid&code=authorization-code")
                )
            )

        self.assertEqual(raised.exception.status_code, 400)

    def test_callback_rejects_missing_calendar_scope(self) -> None:
        flow = Mock()
        flow.oauth2session.state = "test-state"
        flow.credentials.has_scopes.return_value = False
        main._pending_oauth_flows["test-state"] = (main.time.time(), flow)

        with tempfile.TemporaryDirectory() as temp_dir:
            token_path = Path(temp_dir) / "token.json"
            with patch.object(main, "TOKEN_PATH", token_path):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(
                        main.google_oauth_callback(
                            make_callback_request("state=test-state&code=authorization-code")
                        )
                    )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertFalse(token_path.exists())

    def test_start_rejects_desktop_client_for_fastapi_callback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client_path = Path(temp_dir) / "client.json"
            client_path.write_text(json.dumps({"installed": {}}), encoding="utf-8")
            with patch.object(main, "CREDENTIALS_PATH", client_path):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(main.start_google_oauth())

        self.assertEqual(raised.exception.status_code, 500)
        self.assertIn("Web application client", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
