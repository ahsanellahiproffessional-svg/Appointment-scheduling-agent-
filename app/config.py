"""
Configuration module — loads and validates all environment variables and
application-wide settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Load .env from project root ─────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ── Runtime environment ─────────────────────────────────────────────────────
APP_ENV: str = os.getenv("APP_ENV", "development").lower()
if APP_ENV == "development":
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
else:
    os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)

# ── OpenAI ──────────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing from environment variables.")


# ── Google Calendar ─────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_PROJECT_ID: str = os.getenv("GOOGLE_PROJECT_ID", "")
GOOGLE_TOKEN_URI: str = os.getenv("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token")
GOOGLE_AUTH_URI: str = os.getenv("GOOGLE_AUTH_URI", "https://accounts.google.com/o/oauth2/auth")
GOOGLE_REDIRECT_URI: str = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "http://127.0.0.1:8001/oauth2callback",
)

CREDENTIALS_PATH: Path = BASE_DIR / "credentials.json"
TOKEN_PATH: Path = BASE_DIR / "token.json"

SCOPES: list[str] = ["https://www.googleapis.com/auth/calendar"]


# ── Application defaults ───────────────────────────────────────────────────
CALENDAR_TIMEZONE: str = os.getenv("CALENDAR_TIMEZONE", "Asia/Karachi")
DEFAULT_EVENT_DURATION_MINUTES: int = int(
    os.getenv("DEFAULT_EVENT_DURATION_MINUTES", "60")
)


# ── Email notifications ────────────────────────────────────────────────────
RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL: str = os.getenv(
    "RESEND_FROM_EMAIL",
    "ScheduleAI <onboarding@resend.dev>",
)
