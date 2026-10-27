"""
Conversation State Manager — provides per-session, thread-safe context for
multi-turn conversations between the user and the scheduling agent.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Optional

from app.schemas import BookingInfo


# ── Single session container ────────────────────────────────────────────────

@dataclass
class Session:
    """Holds the entire state for one conversation session."""

    session_id: str

    # OpenAI message history (system + user + assistant + tool messages)
    messages: list[dict] = field(default_factory=list)

    # Extracted booking details accumulated across turns
    booking: BookingInfo = field(default_factory=BookingInfo)

    # Timestamps
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    def touch(self) -> None:
        """Update the last-active timestamp."""
        self.last_active = time.time()


# ── Session store ───────────────────────────────────────────────────────────

class SessionStore:
    """
    In-memory session store.  Thread-safe for concurrent FastAPI requests.

    For production, swap this out for Redis / a database-backed store.
    """

    _TTL_SECONDS: int = 3600  # auto-expire sessions after 1 hour of inactivity

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    # ── public API ──────────────────────────────────────────────────────────

    def get_or_create(self, session_id: str) -> Session:
        """Retrieve an existing session or create a new one."""
        with self._lock:
            self._purge_expired()
            if session_id not in self._sessions:
                self._sessions[session_id] = Session(session_id=session_id)
            session = self._sessions[session_id]
            session.touch()
            return session

    def get(self, session_id: str) -> Optional[Session]:
        """Return the session or ``None`` if it doesn't exist / has expired."""
        with self._lock:
            self._purge_expired()
            session = self._sessions.get(session_id)
            if session:
                session.touch()
            return session

    def delete(self, session_id: str) -> None:
        """Explicitly remove a session."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def active_count(self) -> int:
        with self._lock:
            self._purge_expired()
            return len(self._sessions)

    # ── housekeeping ────────────────────────────────────────────────────────

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [
            sid
            for sid, sess in self._sessions.items()
            if now - sess.last_active > self._TTL_SECONDS
        ]
        for sid in expired:
            del self._sessions[sid]


# ── Module-level singleton ──────────────────────────────────────────────────
session_store = SessionStore()
