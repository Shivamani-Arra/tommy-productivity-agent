import inspect
import json
import os
import re
from datetime import date, timedelta

import requests

from intent_parser import parse_intent
from tools.google_calendar_tools import create_calendar_event, create_fixed_calendar_event
from tools.productivity_tools import (
    cancel_schedule,
    cancel_schedule_at_time,
    complete_scheduled_session,
    cleanup_duplicates,
    log_partial_progress,
    extend_task_deadline,
    get_pending_followup,
    clear_pending_followup,
    pending_deadline_extension,
    postpone_schedule,
    prepone_schedule,
    read_calendar_availability,
    recall_conversation_memory,
    remember_conversation,
    replan_missed_work,
    score_deadline_risk,
    schedule_task_session,
    show_today_completed_schedule,
    show_today_schedule,
    resize_schedule,
    reschedule_schedule,
    save_pending_followup,
    set_user_preferences,
    swap_schedule,
    spread_daily_schedule,
)
from tools.task_tools import add_task, get_all_tasks, mark_task_complete, normalize_task_name
from tools.telegram_tools import send_telegram_message


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "llama3.2:3b"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


tool_map = {
    "add_task": add_task,
    "get_all_tasks": get_all_tasks,
    "mark_task_complete": mark_task_complete,
    "cancel_schedule": cancel_schedule,
    "cancel_schedule_at_time": cancel_schedule_at_time,
    "complete_scheduled_session": complete_scheduled_session,
    "cleanup_duplicates": cleanup_duplicates,
    "send_telegram_message": send_telegram_message,
    "create_calendar_event": create_calendar_event,
    "create_fixed_calendar_event": create_fixed_calendar_event,
    "spread_daily_schedule": spread_daily_schedule,
    "replan_missed_work": replan_missed_work,
    "log_partial_progress": log_partial_progress,
    "extend_task_deadline": extend_task_deadline,
    "pending_deadline_extension": pending_deadline_extension,
    "postpone_schedule": postpone_schedule,
    "prepone_schedule": prepone_schedule,
    "score_deadline_risk": score_deadline_risk,
    "schedule_task_session": schedule_task_session,
    "show_today_completed_schedule": show_today_completed_schedule,
    "show_today_schedule": show_today_schedule,
    "resize_schedule": resize_schedule,
    "reschedule_schedule": reschedule_schedule,
    "set_user_preferences": set_user_preferences,
    "swap_schedule": swap_schedule,
    "read_calendar_availability": read_calendar_availability,
    "recall_conversation_memory": recall_conversation_memory,
}


tools = [
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Create a Google Calendar event for a task",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "Name of the task"},
                    "deadline": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                    "start_time": {"type": "string", "description": "Time in HH:MM 24hr format"},
                    "duration_hours": {"type": "number", "description": "Duration in hours"},
                },
                "required": ["task_name", "deadline"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_fixed_calendar_event",
            "description": "Create a fixed Google Calendar event such as a meeting, call, class, interview, or appointment. Do not save it as a task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Calendar event title"},
                    "event_date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                    "start_time": {"type": "string", "description": "Time in HH:MM 24hr format"},
                    "duration_hours": {"type": "number", "description": "Duration in hours, default 1"},
                    "description": {"type": "string", "description": "Optional event description"},
                },
                "required": ["title", "event_date", "start_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Add a new task with deadline and effort hours to database",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "Name of the task"},
                    "deadline": {"type": "string", "description": "Deadline in YYYY-MM-DD format"},
                    "effort_hours": {"type": "number", "description": "Estimated hours needed"},
                    "priority": {"type": "string", "description": "high, medium, or low"},
                },
                "required": ["task_name", "deadline", "effort_hours"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_all_tasks",
            "description": "Get all pending tasks from database. Do not pass arguments.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_task_complete",
            "description": "Mark a task as completed when user reports finishing it",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "Name of task to mark complete"},
                },
                "required": ["task_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_telegram_message",
            "description": "Send a message to the user via Telegram",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Message to send to user"},
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spread_daily_schedule",
            "description": "Spread pending task work across available calendar time before deadlines",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {"type": "number", "description": "How many days ahead to plan"},
                    "create_calendar_events": {
                        "type": "boolean",
                        "description": "Whether to create calendar events for schedule sessions",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replan_missed_work",
            "description": "Detect missed scheduled sessions and replan remaining work",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_partial_progress",
            "description": "Log partial progress when a user worked on a task but did not finish it",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "Name or partial name of the task"},
                    "hours_completed": {"type": "number", "description": "Hours completed"},
                    "note": {"type": "string", "description": "Optional progress note"},
                },
                "required": ["task_name", "hours_completed"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extend_task_deadline",
            "description": "Extend a task deadline after backlog cannot fit before the current deadline",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "Task name. Can be omitted to use the latest pending extension question."},
                    "new_deadline": {"type": "string", "description": "New deadline in YYYY-MM-DD format"},
                    "extra_days": {"type": "number", "description": "Number of days to add to the current deadline"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pending_deadline_extension",
            "description": "Show the latest pending deadline extension question",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "postpone_schedule",
            "description": "Move only the matching scheduled sessions from one date to another without replanning unrelated tasks",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "Task name to postpone"},
                    "from_date": {"type": "string", "description": "Original schedule date in YYYY-MM-DD format"},
                    "to_date": {"type": "string", "description": "New schedule date in YYYY-MM-DD format"},
                },
                "required": ["task_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepone_schedule",
            "description": "Move only the matching scheduled sessions to an earlier date without replanning unrelated tasks",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "Task name to prepone"},
                    "from_date": {"type": "string", "description": "Original schedule date in YYYY-MM-DD format"},
                    "to_date": {"type": "string", "description": "Earlier schedule date in YYYY-MM-DD format"},
                },
                "required": ["task_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_deadline_risk",
            "description": "Score deadline risk for pending tasks and show whether user is on track",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_today_schedule",
            "description": "Show today's incomplete scheduled sessions only",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_task_session",
            "description": "Create a one-off scheduled task session at an exact time and add its calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "Task name to schedule"},
                    "start_time": {"type": "string", "description": "Start time in HH:MM 24hr format"},
                    "schedule_date": {"type": "string", "description": "Schedule date in YYYY-MM-DD format"},
                    "duration_hours": {"type": "number", "description": "Duration in hours, default 1"},
                },
                "required": ["task_name", "start_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_schedule",
            "description": "Move one scheduled task session to an exact time on the same date, updating its calendar event and freeing the old slot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "Task name to reschedule"},
                    "new_start_time": {"type": "string", "description": "New start time in HH:MM 24hr format"},
                    "schedule_date": {"type": "string", "description": "Schedule date in YYYY-MM-DD format"},
                    "source_start_time": {"type": "string", "description": "Optional original start time in HH:MM 24hr format when multiple sessions match"},
                },
                "required": ["task_name", "new_start_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_calendar_availability",
            "description": "Read Google Calendar availability and free work slots",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format"},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_conversation_memory",
            "description": "Recall recent conversation memory for the current user",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "number", "description": "Maximum memories to recall"},
                },
            },
        },
    },
]


def extract_time_from_message(user_message: str) -> str:
    """Extract time from natural language. Returns HH:MM in 24hr format."""
    msg = user_message.lower()
    time_patterns = [
        (r"(\d{1,2}):(\d{2})\s*pm", lambda m: f"{(int(m.group(1)) % 12) + 12:02d}:{m.group(2)}"),
        (r"(\d{1,2}):(\d{2})\s*am", lambda m: f"{int(m.group(1)) % 12:02d}:{m.group(2)}"),
        (r"(\d{1,2})\s*pm", lambda m: f"{(int(m.group(1)) % 12) + 12:02d}:00"),
        (r"(\d{1,2})\s*am", lambda m: f"{int(m.group(1)) % 12:02d}:00"),
        (r"\b([01]?\d|2[0-3]):([0-5]\d)\b", lambda m: f"{int(m.group(1)):02d}:{m.group(2)}"),
    ]

    for pattern, formatter in time_patterns:
        match = re.search(pattern, msg)
        if match:
            return formatter(match)

    return "09:00"


def execute_tool(tool_name: str, tool_args: dict, user_id: str = "default") -> str:
    """Execute a tool and return the result as string."""
    print(f"  -> Tool: {tool_name}")
    print(f"  -> Args: {tool_args}")

    try:
        tool_args = dict(tool_args or {})
        signature = inspect.signature(tool_map[tool_name])
        if "user_id" in signature.parameters and "user_id" not in tool_args:
            tool_args["user_id"] = str(user_id)

        if tool_name == "get_all_tasks":
            result = tool_map[tool_name](user_id=str(user_id))
        else:
            result = tool_map[tool_name](**tool_args)

        print(f"  -> Result: {result}")
        return str(result)
    except Exception as e:
        error = f"Tool error: {str(e)}"
        print(f"  -> Error: {error}")
        return error


def _parse_deadline(text: str):
    msg = re.sub(r"[,.]", " ", text.lower())
    iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", msg)
    if iso_match:
        return iso_match.group(1)

    month_numbers = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    month_patterns = [
        r"\b(?:on\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]+)(?:\s+(20\d{2}))?\b",
        r"\b([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(20\d{2}))?\b",
    ]
    for pattern in month_patterns:
        for month_match in re.finditer(pattern, msg):
            first = month_match.group(1)
            second = month_match.group(2)
            year = int(month_match.group(3) or date.today().year)
            if first.isdigit() and second in month_numbers:
                return date(year, month_numbers[second], int(first)).isoformat()
            if first in month_numbers and second.isdigit():
                return date(year, month_numbers[first], int(second)).isoformat()

    numeric_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](20\d{2}))?\b", msg)
    if numeric_match:
        day = int(numeric_match.group(1))
        month = int(numeric_match.group(2))
        year = int(numeric_match.group(3) or date.today().year)
        return date(year, month, day).isoformat()

    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", msg) or _looks_like_weekday(msg, name):
            today = date.today()
            days_ahead = (weekday - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return (today + timedelta(days=days_ahead)).isoformat()

    return None


def _looks_like_weekday(text: str, weekday_name: str):
    """Catch common one-character typos such as 'Sundat'."""
    for word in re.findall(r"\b[a-z]{5,9}\b", text.lower()):
        if abs(len(word) - len(weekday_name)) > 1:
            continue
        mismatches = sum(1 for a, b in zip(word, weekday_name) if a != b)
        mismatches += abs(len(word) - len(weekday_name))
        if mismatches <= 1:
            return True
    return False


def _extract_time(text: str):
    msg = text.lower()
    patterns = [
        (r"\b(\d{1,2}):(\d{2})\s*pm\b", lambda m: f"{(int(m.group(1)) % 12) + 12:02d}:{m.group(2)}"),
        (r"\b(\d{1,2}):(\d{2})\s*am\b", lambda m: f"{int(m.group(1)) % 12:02d}:{m.group(2)}"),
        (r"\b(\d{1,2})\s*pm\b", lambda m: f"{(int(m.group(1)) % 12) + 12:02d}:00"),
        (r"\b(\d{1,2})\s*am\b", lambda m: f"{int(m.group(1)) % 12:02d}:00"),
        (r"\b([01]?\d|2[0-3]):([0-5]\d)\b", lambda m: f"{int(m.group(1)):02d}:{m.group(2)}"),
    ]
    for pattern, formatter in patterns:
        match = re.search(pattern, msg)
        if match:
            return formatter(match)
    return None


def _parse_relative_day(text: str, default_today=True):
    lowered = text.lower()
    if re.search(r"\btoday'?s?\b", lowered):
        return date.today().isoformat()
    if re.search(r"\btomorrow\b", lowered):
        return (date.today() + timedelta(days=1)).isoformat()
    parsed = _parse_deadline(lowered)
    if parsed:
        return parsed
    return date.today().isoformat() if default_today else None


def _execute_structured_intent(intent: dict, user_message: str, user_id: str):
    name = intent.get("intent")

    if name == "needs_info":
        payload = intent.get("payload") or {}
        if payload:
            save_pending_followup(intent.get("kind", "unknown"), payload, intent.get("question", "I need one more detail."), user_id=user_id)
        return intent.get("question", "I need one more detail.")

    if name == "show_tasks":
        return execute_tool("get_all_tasks", {}, user_id=user_id)

    if name == "show_today":
        return execute_tool("show_today_schedule", {}, user_id=user_id)

    if name == "show_today_completed":
        return execute_tool("show_today_completed_schedule", {}, user_id=user_id)

    if name == "risk":
        return execute_tool("score_deadline_risk", {}, user_id=user_id)

    if name == "cleanup":
        return execute_tool("cleanup_duplicates", {}, user_id=user_id)

    if name == "fixed_event":
        return execute_tool(
            "create_fixed_calendar_event",
            {
                "title": intent["title"],
                "event_date": intent["event_date"],
                "start_time": intent["start_time"],
                "duration_hours": intent.get("duration_hours", 1.0),
                "description": intent.get("description", user_message),
            },
            user_id=user_id,
        )

    if name == "add_task":
        add_result = execute_tool(
            "add_task",
            {
                "task_name": intent["task_name"],
                "deadline": intent["deadline"],
                "effort_hours": intent["effort_hours"],
                "priority": intent.get("priority", "medium"),
            },
            user_id=user_id,
        )
        if "already exists" in add_result:
            return add_result
        schedule_result = execute_tool(
            "spread_daily_schedule",
            {"days_ahead": 14, "create_calendar_events": True},
            user_id=user_id,
        )
        return f"{add_result}\n{schedule_result}"

    if name == "progress":
        return execute_tool(
            "log_partial_progress",
            {
                "task_name": intent["task_name"],
                "hours_completed": intent["hours_completed"],
            },
            user_id=user_id,
        )

    if name == "complete_session":
        return execute_tool(
            "complete_scheduled_session",
            {
                "task_name": intent["task_name"],
                "start_time": intent["start_time"],
                "end_time": intent.get("end_time"),
                "schedule_date": intent.get("schedule_date"),
            },
            user_id=user_id,
        )

    if name == "complete":
        return execute_tool(
            "mark_task_complete",
            {"task_name": intent["task_name"]},
            user_id=user_id,
        )

    if name == "postpone":
        return execute_tool(
            "postpone_schedule",
            {
                "task_name": intent["task_name"],
                "from_date": intent["from_date"],
                "to_date": intent["to_date"],
            },
            user_id=user_id,
        )

    if name == "prepone":
        return execute_tool(
            "prepone_schedule",
            {
                "task_name": intent["task_name"],
                "from_date": intent["from_date"],
                "to_date": intent["to_date"],
            },
            user_id=user_id,
        )

    if name == "cancel_session":
        return execute_tool("cancel_schedule", {
            "task_name": intent["task_name"],
            "schedule_date": intent.get("schedule_date"),
        }, user_id=user_id)

    if name == "cancel_session_at_time":
        return execute_tool("cancel_schedule_at_time", {
            "start_time": intent["start_time"],
            "schedule_date": intent.get("schedule_date"),
        }, user_id=user_id)

    if name == "schedule_task_session":
        return execute_tool("schedule_task_session", {
            "task_name": intent["task_name"],
            "start_time": intent["start_time"],
            "schedule_date": intent.get("schedule_date"),
            "duration_hours": intent.get("duration_hours", 1.0),
        }, user_id=user_id)

    if name == "resize_session":
        return execute_tool("resize_schedule", {
            "task_name": intent["task_name"],
            "hours": intent["hours"],
            "schedule_date": intent.get("schedule_date"),
        }, user_id=user_id)

    if name == "reschedule_session":
        return execute_tool("reschedule_schedule", {
            "task_name": intent["task_name"],
            "new_start_time": intent["new_start_time"],
            "schedule_date": intent.get("schedule_date"),
            "source_start_time": intent.get("source_start_time"),
        }, user_id=user_id)

    if name == "swap_session":
        return execute_tool("swap_schedule", {
            "first_task": intent["first_task"],
            "second_task": intent["second_task"],
            "schedule_date": intent.get("schedule_date"),
        }, user_id=user_id)

    if name == "move_session":
        period_time = {
            "morning": "09:00",
            "afternoon": "14:00",
            "evening": "18:00",
            "night": "20:00",
        }.get(intent.get("period"), "18:00")
        return execute_tool("reschedule_schedule", {
            "task_name": intent["task_name"],
            "new_start_time": period_time,
            "schedule_date": intent.get("schedule_date"),
        }, user_id=user_id)

    if name == "extend_deadline":
        return execute_tool(
            "extend_task_deadline",
            {
                "new_deadline": intent.get("new_deadline", ""),
                "extra_days": intent.get("extra_days"),
            },
            user_id=user_id,
        )

    return None


def _handle_pending_followup(user_message: str, user_id: str):
    followup = get_pending_followup(user_id)
    if not followup:
        return None
    from intent_parser import parse_time, parse_date
    payload = followup.get("payload") or {}
    if followup.get("kind") == "fixed_event_missing_time":
        start_time = parse_time(user_message)
        if not start_time:
            return None
        payload["start_time"] = start_time
        clear_pending_followup(followup["id"])
        return execute_tool("create_fixed_calendar_event", payload, user_id=user_id)
    if followup.get("kind") == "fixed_event_missing_date":
        event_date = parse_date(user_message)
        if not event_date:
            return None
        payload["event_date"] = event_date
        clear_pending_followup(followup["id"])
        if not payload.get("start_time"):
            save_pending_followup("fixed_event_missing_time", payload, "What time should I put this event on the calendar?", user_id=user_id)
            return "What time should I put this event on the calendar?"
        return execute_tool("create_fixed_calendar_event", payload, user_id=user_id)
    return None


def _handle_common_message(user_message: str, user_id: str):
    """Handle high-confidence productivity commands without relying on the LLM."""
    followup_response = _handle_pending_followup(user_message, user_id)
    if followup_response:
        remember_conversation(user_message, followup_response, user_id=user_id)
        return followup_response

    parsed = parse_intent(user_message)
    structured_response = _execute_structured_intent(parsed, user_message, user_id)
    if structured_response:
        remember_conversation(user_message, structured_response, user_id=user_id)
        return structured_response

    msg = user_message.strip()
    lowered = msg.lower()

    event_words = r"meeting|call|appointment|class|interview|doctor|event"
    if re.search(rf"\b({event_words})\b", lowered):
        event_date = _parse_deadline(lowered)
        start_time = _extract_time(lowered)
        if not event_date:
            return "What date is this event on? Please send it like 2026-05-07."
        if not start_time:
            return "What time should I put this event on the calendar?"

        event_word = re.search(rf"\b({event_words})\b", lowered).group(1)
        title = event_word.capitalize()
        response = execute_tool(
            "create_fixed_calendar_event",
            {
                "title": title,
                "event_date": event_date,
                "start_time": start_time,
                "duration_hours": 1.0,
                "description": user_message,
            },
            user_id=user_id,
        )
        remember_conversation(user_message, response, user_id=user_id)
        return response

    postpone_match = re.search(
        r"\bpostpone\s+(.+?)\s+schedule\s+to\s+(.+)",
        lowered,
    )
    if postpone_match:
        task_text = postpone_match.group(1)
        to_text = postpone_match.group(2)
        from_date = _parse_relative_day(task_text, default_today=True)
        to_date = _parse_relative_day(to_text, default_today=False)
        task_name = re.sub(r"\btoday'?s?\b|\btomorrow\b", " ", task_text)
        task_name = normalize_task_name(task_name.replace("schedule", "")).strip()
        if not task_name:
            return "Which task schedule should I postpone?"
        if not to_date:
            return "What date should I postpone it to?"

        response = execute_tool(
            "postpone_schedule",
            {
                "task_name": task_name,
                "from_date": from_date,
                "to_date": to_date,
            },
            user_id=user_id,
        )
        remember_conversation(user_message, response, user_id=user_id)
        return response

    prepone_match = re.search(
        r"\bprepone\s+(.+?)\s+schedule\s+to\s+(.+)",
        lowered,
    )
    if prepone_match:
        task_text = prepone_match.group(1)
        to_text = prepone_match.group(2)
        from_date = _parse_relative_day(task_text, default_today=False)
        to_date = _parse_relative_day(to_text, default_today=False)
        task_name = re.sub(r"\btoday'?s?\b|\btomorrow\b", " ", task_text)
        task_name = normalize_task_name(task_name.replace("schedule", "")).strip()
        if not task_name:
            return "Which task schedule should I prepone?"
        if not from_date:
            return "Which day's schedule should I prepone?"
        if not to_date:
            return "What earlier date should I prepone it to?"

        response = execute_tool(
            "prepone_schedule",
            {
                "task_name": task_name,
                "from_date": from_date,
                "to_date": to_date,
            },
            user_id=user_id,
        )
        remember_conversation(user_message, response, user_id=user_id)
        return response

    task_match = re.search(
        r"(?:i\s+need\s+to|i\s+have\s+to|need\s+to|have\s+to)\s+(.+?)\s+for\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s+(?:before|by)\s+(.+)",
        lowered,
    )
    if not task_match:
        task_match = re.search(
            r"(?:before|by)\s+(.+?)\s+(.+?)\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s+for\s+(.+)",
            lowered,
        )
        if task_match:
            deadline_text = task_match.group(1)
            task_name = f"{task_match.group(2)} {task_match.group(4)}"
            effort_hours = float(task_match.group(3))
            task_match = None
        else:
            task_name = effort_hours = deadline_text = None
    else:
        task_name = task_match.group(1).strip(" .")
        effort_hours = float(task_match.group(2))
        deadline_text = task_match.group(3)

    if task_name and effort_hours and deadline_text:
        task_name = normalize_task_name(task_name) or task_name
        deadline = _parse_deadline(deadline_text)
        if not deadline:
            return "What deadline date should I use? Please send it like 2026-05-10."

        add_result = execute_tool(
            "add_task",
            {
                "task_name": task_name,
                "deadline": deadline,
                "effort_hours": effort_hours,
                "priority": "medium",
            },
            user_id=user_id,
        )
        if "already exists" in add_result:
            response = add_result
        else:
            schedule_result = execute_tool(
                "spread_daily_schedule",
                {
                    "days_ahead": 14,
                    "create_calendar_events": True,
                },
                user_id=user_id,
            )
            response = f"{add_result}\n{schedule_result}"
        remember_conversation(user_message, response, user_id=user_id)
        return response

    progress_match = re.search(
        r"(?:i\s+)?(?:studied|worked\s+on|worked|did|completed)\s+(.+?)\s+for\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b",
        lowered,
    )
    if progress_match and "completed" not in lowered:
        task_name = progress_match.group(1).strip(" .")
        hours = float(progress_match.group(2))
        response = execute_tool(
            "log_partial_progress",
            {
                "task_name": task_name,
                "hours_completed": hours,
            },
            user_id=user_id,
        )
        remember_conversation(user_message, response, user_id=user_id)
        return response

    return None


def run_agent(user_message: str, user_id: str = "default") -> str:
    """Main agent loop. Receives a user message, calls tools, and returns a response."""
    deterministic_response = _handle_common_message(user_message, str(user_id))
    if deterministic_response:
        return deterministic_response

    today = date.today().strftime("%Y-%m-%d")
    memory = recall_conversation_memory(limit=5, user_id=user_id)

    system_prompt = f"""You are a personal productivity agent. Today is {today}.

The user is chatting with you via Telegram.
Your reply will be sent directly as a Telegram message.

Your responsibilities:
1. Parse tasks from natural language and save to database
2. Automatically spread new tasks into smaller Google Calendar work sessions
3. Show pending tasks with deadlines and days remaining when asked
4. Mark tasks complete when user says they finished something
5. Send reminders with real task names and deadlines when asked
6. Warn about approaching deadlines
7. Encourage and motivate the user
8. Spread work across days when the user asks for a plan or schedule
9. Replan missed work when the user skipped or missed sessions
10. Track partial progress when the user reports hours worked
11. Score deadline risk when the user asks if they are on track
12. Use calendar availability before scheduling when possible
13. Use conversation memory to personalize replies
14. If work cannot fit before a deadline, tell the user the backlog and ask whether to extend the deadline
15. Treat meetings, calls, appointments, classes, interviews, doctor visits, and events as fixed calendar events, not tasks
16. If the user asks to postpone or prepone a specific schedule, move only that task's matching schedule rows

Critical rules:
- Always extract deadlines in YYYY-MM-DD format
- Always use tools to take real action; never pretend
- When showing tasks, include task name, deadline, and days remaining
- If the user adds a task or asks what to do today, schedule, plan my day, or spread work, call spread_daily_schedule
- If the user says they worked X hours on a task, call log_partial_progress
- If the user says they missed, skipped, or fell behind, call replan_missed_work
- If the user asks am I on track, risk, danger, or deadline pressure, call score_deadline_risk
- If the user agrees to extend a deadline, says add X days, or gives a new date after a backlog warning, call extend_task_deadline
- If the user asks what deadline extension is pending, call pending_deadline_extension
- If the user mentions a meeting, call, appointment, class, interview, doctor visit, or event with date and time, call create_fixed_calendar_event
- If the user asks to add or schedule a study/task session at a specific time, call schedule_task_session
- If the user says postpone today's X schedule to tomorrow or another date, call postpone_schedule, not spread_daily_schedule
- If the user says prepone tomorrow's X schedule to today or another earlier date, call prepone_schedule, not spread_daily_schedule
- If the user asks to move or reschedule a task session to a specific time on the same date, call reschedule_schedule
- Current user id is {user_id}; tools will store data for this user
- Keep replies concise and friendly
- Use plain text only
- Always mention specific task names and actual dates
- Never give generic responses like "check your deadlines"
- If user says "I finished X" or "I completed X", mark it complete immediately

Recent memory:
{memory}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    if os.getenv("GEMINI_API_KEY"):
        return _run_gemini_agent(user_message, system_prompt, user_id)

    for iteration in range(10):
        try:
            print(f"\n[Iteration {iteration + 1}]")

            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": MODEL_NAME,
                    "messages": messages,
                    "tools": tools,
                    "stream": False,
                },
                timeout=120,
            )

            if response.status_code != 200:
                return f"Ollama error {response.status_code}: {response.text}"

            data = response.json()
            message = data.get("message", {})
            tool_calls = message.get("tool_calls", [])

            if tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": message.get("content", ""),
                    "tool_calls": tool_calls,
                })

                for tool_call in tool_calls:
                    tool_name = tool_call["function"]["name"]
                    tool_args = tool_call["function"]["arguments"]

                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except json.JSONDecodeError:
                            tool_args = {}

                    result = execute_tool(tool_name, tool_args, user_id=user_id)

                    if (
                        tool_name == "add_task"
                        and "Tool error" not in result
                        and "already exists" not in result
                    ):
                        print("  -> Spreading task across available calendar time...")
                        schedule_result = execute_tool(
                            "spread_daily_schedule",
                            {
                                "days_ahead": 14,
                                "create_calendar_events": True,
                            },
                            user_id=user_id,
                        )
                        result += f"\n{schedule_result}"

                    messages.append({"role": "tool", "content": result})
            else:
                final_response = message.get("content", "").strip() or "Done."
                remember_conversation(user_message, final_response, user_id=user_id)
                return final_response

        except requests.exceptions.ConnectionError:
            return "Cannot connect to Ollama.\nPlease start Ollama by running: ollama serve"
        except requests.exceptions.Timeout:
            return "The model is taking too long.\nPlease try again in a moment."
        except Exception as e:
            return f"Unexpected error: {str(e)}"

    return "I have completed all the actions for your request."


def _run_gemini_agent(user_message: str, system_prompt: str, user_id: str):
    """Cloud LLM fallback. Gemini chooses tools using a strict JSON protocol."""
    transcript = [
        f"User message: {user_message}",
        "Decide the best next action. Use a tool when real work is needed.",
    ]

    for iteration in range(6):
        payload = {
            "systemInstruction": {
                "parts": [{"text": _gemini_system_prompt(system_prompt)}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "\n\n".join(transcript)}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

        try:
            response = requests.post(
                GEMINI_URL.format(model=os.getenv("GEMINI_MODEL", GEMINI_MODEL)),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": os.getenv("GEMINI_API_KEY", ""),
                },
                json=payload,
                timeout=60,
            )
        except requests.exceptions.Timeout:
            return "The cloud AI model is taking too long. Please try again in a moment."
        except requests.exceptions.RequestException as exc:
            return f"Cloud AI connection error: {exc}"

        if response.status_code != 200:
            return f"Cloud AI error {response.status_code}: {response.text}"

        decision = _parse_gemini_decision(response.json())
        if not decision:
            return "I could not understand that yet. Please say it with a task, time, or deadline."

        if decision.get("reply"):
            final_response = str(decision["reply"]).strip()
            remember_conversation(user_message, final_response, user_id=user_id)
            return final_response

        tool_name = decision.get("tool")
        tool_args = decision.get("arguments") or {}
        if tool_name not in tool_map:
            return "I understood you, but I do not have the right tool for that yet."
        if not isinstance(tool_args, dict):
            tool_args = {}

        result = execute_tool(tool_name, tool_args, user_id=user_id)
        if (
            tool_name == "add_task"
            and "Tool error" not in result
            and "already exists" not in result
        ):
            schedule_result = execute_tool(
                "spread_daily_schedule",
                {
                    "days_ahead": 14,
                    "create_calendar_events": True,
                },
                user_id=user_id,
            )
            result += f"\n{schedule_result}"

        transcript.append(
            f"Tool used: {tool_name}\nArguments: {json.dumps(tool_args)}\nResult: {result}\n"
            "Now either call another needed tool or return a concise final reply."
        )

    return "I took the action, but the cloud AI needed too many steps to summarize it."


def _gemini_system_prompt(system_prompt: str):
    tool_lines = []
    for tool in tools:
        function = tool.get("function", {})
        name = function.get("name", "")
        description = function.get("description", "")
        properties = function.get("parameters", {}).get("properties", {})
        args = ", ".join(properties.keys())
        tool_lines.append(f"- {name}({args}): {description}")

    return f"""{system_prompt}

You are running in cloud mode with access to real tools.

Available tools:
{chr(10).join(tool_lines)}

Return exactly one JSON object. No markdown.

To call a tool:
{{"tool":"tool_name","arguments":{{"arg":"value"}}}}

To reply without a tool:
{{"reply":"message to user"}}

Rules:
- Use tools for tasks, calendar events, scheduling, progress, completion, reminders, risk, and cleanup.
- Dates must be YYYY-MM-DD.
- Times must be HH:MM 24-hour format.
- Do not invent that something was saved or scheduled; call a tool first.
- After a tool result is shown in the transcript, return a concise final reply unless another tool is truly needed.
"""


def _parse_gemini_decision(data):
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts).strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
        return json.loads(text)
    except Exception:
        return None
