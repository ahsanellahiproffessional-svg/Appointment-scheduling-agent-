"""
Scheduling Agent — the brain of the system.

Uses OpenAI GPT-4o with function-calling (tool use) to:
  • Parse natural language into structured appointment data
  • Decide when to check calendar availability
  • Decide when to create a calendar event
  • Carry on multi-turn conversations to collect missing details
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from openai import OpenAI, RateLimitError, APIError

from app.config import OPENAI_API_KEY, OPENAI_MODEL, CALENDAR_TIMEZONE, DEFAULT_EVENT_DURATION_MINUTES
from app.schemas import BookingInfo, ChatResponse, EventCreate
from app.session_manager import Session
from app.calendar_service import check_availability, create_event, get_free_slots

logger = logging.getLogger(__name__)

# ── OpenAI client ───────────────────────────────────────────────────────────
client = OpenAI(api_key=OPENAI_API_KEY)


# ─────────────────────────────────────────────────────────────────────────────
#  System prompt — instructs the model how to behave
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""\
You are an intelligent appointment scheduling assistant.  Your job is to help
users book meetings on their Google Calendar.

Today's date and time: {{now}}
Timezone: {CALENDAR_TIMEZONE}
Default meeting length: {DEFAULT_EVENT_DURATION_MINUTES} minutes

─── RULES ────────────────────────────────────────────────────────────────────
1. Extract: event title, date, start time, duration, and participant email(s).
2. If ANY required detail is missing, ask the user for it — do NOT guess.
3. Before confirming a booking, ALWAYS call `check_availability` first.
4. If the slot has conflicts, inform the user and suggest running `get_free_slots`
   to show alternatives.
5. Once the user confirms, call `create_calendar_event` to finalize.
6. After creating the event, provide a summary with the calendar link.
7. Be concise, friendly, and professional.
8. All date/time values you produce MUST be in RFC 3339 format with timezone offset.
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Tool (function) definitions sent to the model
# ─────────────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": (
                "Check whether a specific time window is free on the user's "
                "Google Calendar.  Returns availability status and any "
                "conflicting events."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_datetime": {
                        "type": "string",
                        "description": "Start of the window in RFC 3339 format, e.g. 2026-10-24T15:00:00+05:00",
                    },
                    "end_datetime": {
                        "type": "string",
                        "description": "End of the window in RFC 3339 format.",
                    },
                },
                "required": ["start_datetime", "end_datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_free_slots",
            "description": (
                "Return a list of free time slots for a given date within "
                "working hours (09:00–17:00).  Useful when the requested "
                "slot is busy and alternatives are needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "ISO date, e.g. 2026-10-24",
                    },
                    "slot_duration_minutes": {
                        "type": "integer",
                        "description": "Length of each slot in minutes.  Default 60.",
                        "default": 60,
                    },
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": (
                "Create a new event on the user's Google Calendar once the "
                "user has confirmed the booking details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Title / subject of the meeting.",
                    },
                    "start_datetime": {
                        "type": "string",
                        "description": "RFC 3339 start datetime.",
                    },
                    "end_datetime": {
                        "type": "string",
                        "description": "RFC 3339 end datetime.",
                    },
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of attendee email addresses.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional event description / notes.",
                        "default": "",
                    },
                },
                "required": ["summary", "start_datetime", "end_datetime"],
            },
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
#  Tool execution dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def _execute_tool(name: str, arguments: dict) -> str:
    """
    Route a tool call to the appropriate service function and return a
    JSON-encoded result string to feed back into the model.
    """
    try:
        if name == "check_availability":
            result = check_availability(
                start_datetime=arguments["start_datetime"],
                end_datetime=arguments["end_datetime"],
            )
            return json.dumps(result, default=str)

        elif name == "get_free_slots":
            slots = get_free_slots(
                date=arguments["date"],
                slot_duration_minutes=arguments.get("slot_duration_minutes", DEFAULT_EVENT_DURATION_MINUTES),
            )
            return json.dumps(
                [{"start": s.start.isoformat(), "end": s.end.isoformat()} for s in slots],
                default=str,
            )

        elif name == "create_calendar_event":
            event_data = EventCreate(
                summary=arguments["summary"],
                start_datetime=arguments["start_datetime"],
                end_datetime=arguments["end_datetime"],
                timezone=CALENDAR_TIMEZONE,
                attendees=arguments.get("attendees", []),
                description=arguments.get("description", ""),
            )
            created = create_event(event_data)
            return json.dumps({
                "status": "confirmed",
                "event_id": created.get("id"),
                "html_link": created.get("htmlLink"),
                "summary": created.get("summary"),
                "start": created["start"].get("dateTime"),
                "end": created["end"].get("dateTime"),
            })

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as exc:
        logger.exception("Tool execution failed: %s", name)
        return json.dumps({"error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
#  Agent turn — the main conversation loop
# ─────────────────────────────────────────────────────────────────────────────

MAX_TOOL_ROUNDS = 5  # safety cap to avoid infinite loops


def run_agent_turn(session: Session, user_message: str) -> ChatResponse:
    """
    Process one user message through the agent.

    Steps:
      1. Append the user message to session history.
      2. Call the model (with tools).
      3. If the model requests tool calls, execute them and feed results back.
      4. Repeat until the model produces a final text reply (or we hit the cap).
      5. Return the response + any extracted booking info.
    """

    # Inject the system prompt on first turn
    now_str = datetime.now(ZoneInfo(CALENDAR_TIMEZONE)).strftime("%A, %B %d, %Y at %I:%M %p %Z")
    if not session.messages:
        session.messages.append({
            "role": "system",
            "content": SYSTEM_PROMPT.replace("{now}", now_str),
        })

    # Append user turn
    session.messages.append({"role": "user", "content": user_message})

    for _round in range(MAX_TOOL_ROUNDS):
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=session.messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.3,
            )
        except RateLimitError:
            logger.warning("OpenAI rate-limit hit — asking user to retry.")
            return ChatResponse(
                session_id=session.session_id,
                reply="⏳ I'm currently rate-limited by OpenAI. Please try again in a few seconds.",
                booking=session.booking,
            )
        except APIError as exc:
            logger.error("OpenAI API error: %s", exc)
            return ChatResponse(
                session_id=session.session_id,
                reply="❌ Something went wrong while contacting the AI service. Please try again.",
                booking=session.booking,
            )

        choice = response.choices[0]
        message = choice.message

        # ── Case 1: model wants to call one or more tools ────────────────
        if message.tool_calls:
            # Append the assistant message (contains tool_call metadata)
            session.messages.append(message.model_dump())

            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)
                logger.info("Tool call: %s(%s)", fn_name, fn_args)

                result_str = _execute_tool(fn_name, fn_args)

                # Feed the tool result back
                session.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                })

                # Update session booking from tool results
                _update_booking_from_tool(session, fn_name, fn_args, result_str)

            # Loop again so the model can process the tool results
            continue

        # ── Case 2: model produced a final text response ─────────────────
        assistant_text = message.content or ""
        session.messages.append({"role": "assistant", "content": assistant_text})

        return ChatResponse(
            session_id=session.session_id,
            reply=assistant_text,
            booking=session.booking,
        )

    # If we exhausted all rounds (shouldn't happen), return what we have
    return ChatResponse(
        session_id=session.session_id,
        reply="I seem to be going in circles — could you rephrase your request?",
        booking=session.booking,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Booking state updater
# ─────────────────────────────────────────────────────────────────────────────

def _update_booking_from_tool(
    session: Session,
    tool_name: str,
    tool_args: dict,
    result_str: str,
) -> None:
    """
    After a tool executes, merge its data into the session's BookingInfo so
    the API response always reflects the latest known state.
    """
    try:
        result = json.loads(result_str)
    except json.JSONDecodeError:
        return

    b = session.booking

    if tool_name == "check_availability":
        b.start_time = tool_args.get("start_datetime", b.start_time)
        b.end_time = tool_args.get("end_datetime", b.end_time)
        if result.get("available"):
            b.status = "pending"  # still needs user confirmation
        else:
            b.status = "conflict"

    elif tool_name == "create_calendar_event":
        if result.get("status") == "confirmed":
            b.event_title = result.get("summary", b.event_title)
            b.start_time = result.get("start", b.start_time)
            b.end_time = result.get("end", b.end_time)
            b.calendar_event_id = result.get("event_id")
            b.calendar_event_link = result.get("html_link")
            b.status = "confirmed"
            b.participants = tool_args.get("attendees", b.participants)
        else:
            b.status = "pending"
