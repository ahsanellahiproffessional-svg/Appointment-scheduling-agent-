# 🗓️ Appointment Scheduling Agent

An AI-powered conversational agent that schedules appointments on **Google Calendar** using natural language, built with **FastAPI**, **OpenAI GPT-4o** (function calling), and the **Google Calendar API**.

---

## ✨ Features

| Feature | Description |
|---|---|
| **Natural Language Understanding** | Uses GPT-4o tool-use to parse messages like *"Book a meeting tomorrow at 3 PM"* |
| **Google Calendar Integration** | Checks availability, finds free slots, and creates events automatically |
| **Multi-Turn Conversations** | Maintains context across turns — asks for missing details intelligently |
| **Conflict Detection** | Detects overlapping events and suggests alternatives |
| **REST API** | Clean `/chat` endpoint for easy frontend integration |
| **Error Handling** | Handles rate limits, API errors, invalid inputs gracefully |

---

## 📁 Project Structure

```
appointment-scheduling-agent/
├── main.py                  # FastAPI entry point & endpoints
├── app/
│   ├── __init__.py
│   ├── config.py            # Environment variables & settings
│   ├── schemas.py           # Pydantic request/response models
│   ├── agent.py             # OpenAI GPT-4o agent with tool-calling
│   ├── calendar_service.py  # Google Calendar API integration
│   └── session_manager.py   # Multi-turn conversation state
├── credentials.json         # Google OAuth client secrets
├── requirements.txt         # Python dependencies
├── .env                     # Environment variables (secrets)
└── .gitignore
```

---

## 🚀 Setup Instructions

### 1. Prerequisites

- Python 3.11+
- An [OpenAI API key](https://platform.openai.com/api-keys) with GPT-4o access
- A [Google Cloud project](https://console.cloud.google.com/) with Calendar API enabled

### 2. Google Calendar API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or select an existing one)
3. Enable the **Google Calendar API**
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Create a **Web application** OAuth client. A Desktop client is not compatible with this FastAPI callback flow.
6. Add this exact authorized redirect URI:
   - `http://127.0.0.1:8001/oauth2callback`
7. Download the Web client JSON and save it as `credentials.json` in the project root, replacing any Desktop client JSON.

Set `GOOGLE_REDIRECT_URI` to the identical URL in `.env`. Start authorization by opening `http://127.0.0.1:8001/auth/google`; Google redirects to the FastAPI `/oauth2callback` route, which validates state, exchanges the authorization code, and stores `token.json`.

The callback-based OAuth flow is implemented in `main.py` using:

```python
flow = Flow.from_client_secrets_file(
    str(CREDENTIALS_PATH),
    scopes=SCOPES,
    redirect_uri=GOOGLE_REDIRECT_URI,
)
authorization_url, state = flow.authorization_url(access_type="offline")
# In /oauth2callback, after validating the saved state:
flow.fetch_token(code=code)
TOKEN_PATH.write_text(flow.credentials.to_json(), encoding="utf-8")
```

OAuth state is kept in memory for ten minutes, so run one application process while authorizing. For a multi-worker or production deployment, store pending OAuth state and PKCE data in shared storage and use HTTPS.

### 3. Install Dependencies

On Windows:

```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 4. Configure Environment

Edit the `.env` file with your credentials:

```env
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o
RESEND_API_KEY=re_your-key-here
RESEND_FROM_EMAIL="ScheduleAI <appointments@your-verified-domain.com>"
APP_ENV=development
OAUTHLIB_INSECURE_TRANSPORT=1
GOOGLE_REDIRECT_URI=http://127.0.0.1:8001/oauth2callback
CALENDAR_TIMEZONE=Asia/Karachi
DEFAULT_EVENT_DURATION_MINUTES=60
```

Google Calendar OAuth credentials are read from `credentials.json`; the client ID and secret do not need to be copied into `.env`.
`OAUTHLIB_INSECURE_TRANSPORT=1` is enabled automatically when `APP_ENV=development` (the default) for local HTTP OAuth testing. Set `APP_ENV=production` when deploying over HTTPS; do not enable insecure transport in production.
After a calendar event is successfully created, the app queues a confirmation email for each attendee; the greeting name is derived from the attendee email address. Email delivery requires a Resend API key and a sender address verified in your Resend account. The email is sent as a FastAPI background task, so delivery does not delay the chat response.
To run the app with the virtual environment on Windows, use `.venv\Scripts\python.exe main.py`.

### 5. Run the Server

```bash
.\.venv\Scripts\python.exe main.py
```

The server starts at `http://localhost:8001`. Open that address to use the chat interface, or visit `/docs` for the API.

If Google Calendar is not authorized, open `http://127.0.0.1:8001/auth/google`. After approving access, the callback saves `token.json` locally for subsequent runs.

---

## 📡 API Reference

### `POST /chat`

Send a message to the scheduling agent.

**Request:**
```json
{
  "session_id": "user-123",
  "message": "Book a meeting with alice@example.com tomorrow at 3 PM"
}
```

**Response:**
```json
{
  "session_id": "user-123",
  "reply": "I've checked your calendar and tomorrow at 3 PM is available! Shall I go ahead and book a 1-hour meeting with alice@example.com?",
  "booking": {
    "event_title": "Meeting with Alice",
    "start_time": "2026-10-24T15:00:00+05:00",
    "end_time": "2026-10-24T16:00:00+05:00",
    "participants": ["alice@example.com"],
    "status": "pending",
    "calendar_event_id": null,
    "calendar_event_link": null
  }
}
```

### `GET /sessions/{session_id}`

Retrieve the current state of a conversation session.

### `DELETE /sessions/{session_id}`

Clear all state for a session.

### `GET /health`

Liveness probe — returns active session count.

---

## 💬 Example Conversations

### Simple Booking
```
User: "Schedule a meeting with bob@company.com tomorrow at 2 PM"
Agent: "Let me check your calendar... ✅ 2 PM tomorrow is free. Shall I book a 1-hour meeting titled 'Meeting' with bob@company.com?"
User: "Yes, title it 'Project Review'"
Agent: "Done! 🎉 'Project Review' booked for Oct 24, 2026, 2:00–3:00 PM. Calendar link: ..."
```

### Multi-Turn (Missing Details)
```
User: "I need to book a meeting"
Agent: "Sure! I need a few details: When would you like to schedule it? And who should be invited?"
User: "Tomorrow afternoon"
Agent: "What time works best? And could you share the attendee's email?"
User: "3 PM with alice@example.com"
Agent: "Checking availability... ✅ 3 PM is open. Shall I create a 1-hour meeting?"
```

### Conflict Handling
```
User: "Book a call at 10 AM on Monday"
Agent: "⚠️ You have 'Team Standup' from 10:00–10:30 AM. Free slots on Monday: 9:00 AM, 11:00 AM, 1:00 PM, 2:00 PM. Which one works?"
```

---

## 📖 Interactive API Docs

Once running, visit:
- **Swagger UI**: [http://localhost:8001/docs](http://localhost:8001/docs)
- **ReDoc**: [http://localhost:8001/redoc](http://localhost:8001/redoc)

---

## 🔒 Security Notes

- All secrets are loaded from `.env` — never hardcode credentials
- `credentials.json` and `token.json` are in `.gitignore`
- CORS is set to `*` for development — restrict in production
- Session state is in-memory — use Redis for production deployments

---

## License

MIT
