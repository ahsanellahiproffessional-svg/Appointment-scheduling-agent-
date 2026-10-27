from __future__ import annotations

import asyncio
import unittest

from fastapi import HTTPException
from starlette.requests import Request

import main


def make_request(path: str, accept: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"accept", accept.encode())],
            "server": ("127.0.0.1", 8001),
            "client": ("127.0.0.1", 50000),
        }
    )


class NotFoundRouteTests(unittest.TestCase):
    def test_unknown_browser_url_redirects_to_app_home(self) -> None:
        response = asyncio.run(
            main.not_found(
                make_request("/<a href=", "text/html,application/xhtml+xml"),
                HTTPException(status_code=404, detail="Not Found"),
            )
        )

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/")

    def test_unknown_api_url_keeps_json_404(self) -> None:
        response = asyncio.run(
            main.not_found(
                make_request("/unknown-api", "application/json"),
                HTTPException(status_code=404, detail="Not Found"),
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.body, b'{"detail":"Not Found"}')


if __name__ == "__main__":
    unittest.main()
