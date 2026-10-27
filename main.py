"""
FastAPI application entry point.

Endpoints:
  POST /chat               — Main conversational endpoint
  GET  /sessions/{id}      — Retrieve session state (debug / frontend use)
  DELETE /sessions/{id}    — Clear a session
  GET  /health             — Liveness probe
"""

from __future__ import annotations

import re
import logging
import json
import threading
import time
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
from google.auth.exceptions import GoogleAuthError
from oauthlib.oauth2 import OAuth2Error
from requests.exceptions import RequestException
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas import ChatRequest, ChatResponse, BookingInfo
from app.session_manager import session_store
from app.agent import run_agent_turn
from app.email_service import format_appointment_datetime, send_appointment_email
from app.config import CREDENTIALS_PATH, GOOGLE_REDIRECT_URI, SCOPES, TOKEN_PATH

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
OAUTH_STATE_TTL_SECONDS = 600
_oauth_state_lock = threading.Lock()
_pending_oauth_flows: dict[str, tuple[float, Flow]] = {}


# ── App lifecycle ───────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀  Appointment Scheduling Agent is starting …")
    yield
    logger.info("🛑  Shutting down …")


# ── FastAPI app ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Appointment Scheduling Agent",
    description=(
        "An AI-powered conversational agent that schedules appointments "
        "on Google Calendar using natural language."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Allow CORS for frontend / testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ─────────────────────────────────────────────────────────────────────────────
#  Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.exception_handler(404)
async def not_found(request: Request, exc: StarletteHTTPException):
    """Return browser navigations to the app after a malformed/unknown URL."""
    if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


@app.get("/", include_in_schema=False)
async def index():
    """Serve the scheduling chat interface."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/auth/google", include_in_schema=False)
async def start_google_oauth() -> RedirectResponse:
    """Start the Google Calendar authorization flow."""
    try:
        client_config = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("Unable to read Google OAuth client configuration.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth credentials are missing or invalid.",
        ) from exc

    if "web" not in client_config:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "This callback-based flow requires a Google OAuth Web application "
                "client. Download a Web client and set its redirect URI to "
                f"{GOOGLE_REDIRECT_URI}."
            ),
        )

    try:
        flow = Flow.from_client_secrets_file(
            str(CREDENTIALS_PATH),
            scopes=SCOPES,
            redirect_uri=GOOGLE_REDIRECT_URI,
        )
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
    except (OSError, ValueError, OAuth2Error) as exc:
        logger.exception("Unable to initialize Google OAuth flow.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to start Google Calendar authorization.",
        ) from exc

    now = time.time()
    with _oauth_state_lock:
        expired_states = [
            saved_state
            for saved_state, (created_at, _) in _pending_oauth_flows.items()
            if now - created_at > OAUTH_STATE_TTL_SECONDS
        ]
        for saved_state in expired_states:
            del _pending_oauth_flows[saved_state]
        _pending_oauth_flows[state] = (now, flow)

    return RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)


@app.get("/oauth2callback", include_in_schema=False)
async def google_oauth_callback(request: Request) -> RedirectResponse:
    """Validate OAuth state, exchange the code, and persist Calendar credentials."""
    state = request.query_params.get("state")
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google OAuth callback is missing its state parameter.",
        )

    with _oauth_state_lock:
        pending = _pending_oauth_flows.pop(state, None)

    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google OAuth state is invalid, expired, or already used. Start again at /auth/google.",
        )

    created_at, flow = pending
    if time.time() - created_at > OAUTH_STATE_TTL_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google OAuth state has expired. Start again at /auth/google.",
        )
    if state != flow.oauth2session.state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google OAuth state validation failed. Start again at /auth/google.",
        )

    oauth_error = request.query_params.get("error")
    if oauth_error:
        logger.warning("Google OAuth authorization was denied: %s", oauth_error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar authorization was denied.",
        )

    code = request.query_params.get("code")
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google OAuth callback is missing its authorization code.",
        )

    try:
        flow.fetch_token(code=code)
        credentials = flow.credentials
        if not credentials.has_scopes(SCOPES):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Google Calendar permission was not granted. Please authorize the Calendar scope.",
            )
        TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")
    except HTTPException:
        raise
    except (OAuth2Error, GoogleAuthError, OSError, RequestException, ValueError) as exc:
        logger.exception("Google OAuth token exchange or persistence failed.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google authorization failed. Start again at /auth/google.",
        ) from exc

    logger.info("Google Calendar credentials saved to %s.", TOKEN_PATH)
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@app.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a message to the scheduling agent",
    tags=["Chat"],
)
async def chat(request: ChatRequest, background_tasks: BackgroundTasks) -> ChatResponse:
    """
    Accept a user message, run it through the AI agent, and return the
    agent's reply along with current booking status.
    """
    logger.info(
        "📩  [%s] User: %s",
        request.session_id,
        request.message[:120],
    )

    session = session_store.get_or_create(request.session_id)
    previous_event_id = session.booking.calendar_event_id

    try:
        response = run_agent_turn(session, request.message)
    except Exception as exc:
        logger.exception("Unhandled error in agent turn")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent error: {exc}",
        ) from exc

    booking = response.booking
    if (
        booking
        and booking.status == "confirmed"
        and booking.calendar_event_id
        and booking.calendar_event_id != previous_event_id
        and booking.start_time
    ):
        appointment_date, appointment_time = format_appointment_datetime(
            booking.start_time
        )
        for to_email in booking.participants:
            local_part = to_email.partition("@")[0]
            user_name = re.sub(r"[._+-]+", " ", local_part).strip().title()
            background_tasks.add_task(
                send_appointment_email,
                to_email,
                user_name or "there",
                appointment_date,
                appointment_time,
            )

    logger.info(
        "🤖  [%s] Agent: %s",
        request.session_id,
        response.reply[:120],
    )
    return response


@app.get(
    "/sessions/{session_id}",
    summary="Get current session state",
    tags=["Sessions"],
)
async def get_session(session_id: str):
    """Return the booking state and message count for a session."""
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    return {
        "session_id": session.session_id,
        "message_count": len(session.messages),
        "booking": session.booking.model_dump(),
        "created_at": session.created_at,
        "last_active": session.last_active,
    }


@app.delete(
    "/sessions/{session_id}",
    summary="Delete a session",
    tags=["Sessions"],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_session(session_id: str):
    """Clear all state for a session."""
    session_store.delete(session_id)
    return None


@app.get(
    "/health",
    summary="Health check",
    tags=["System"],
)
async def health():
    """Simple liveness probe."""
    return {
        "status": "healthy",
        "active_sessions": session_store.active_count(),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Run with: python main.py
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info",
    )
