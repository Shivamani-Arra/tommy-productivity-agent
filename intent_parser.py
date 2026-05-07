import re
from datetime import date, timedelta


WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

MONTHS = {
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

EVENT_WORDS = "meeting|call|appointment|class|interview|doctor|event"
STUDY_VERBS = {
    "study", "studying", "learn", "learning", "read", "reading",
    "revise", "revising", "practice", "practicing", "prepare", "preparing"
}


def normalize_task_name(task_name: str):
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", str(task_name).lower())
    words = [word for word in cleaned.split() if word and word not in STUDY_VERBS]
    return " ".join(words)


def parse_intent(message: str):
    """Parse common productivity messages into a structured intent."""
    text = " ".join(str(message).strip().split())
    lowered = text.lower()

    if not lowered:
        return {"intent": "unknown"}

    if re.fullmatch(r"/?tasks|show tasks|show my tasks|pending tasks", lowered):
        return {"intent": "show_tasks"}

    if _asks_today_completed(lowered):
        return {"intent": "show_today_completed"}

    if _asks_today_schedule(lowered):
        return {"intent": "show_today"}

    time_block = _parse_time_block(lowered)
    if time_block:
        return time_block

    if re.search(r"\b(on track|risk|risky|danger|deadline pressure)\b", lowered):
        return {"intent": "risk"}

    if re.fullmatch(r"/?cleanup|cleanup duplicates|clean duplicates", lowered):
        return {"intent": "cleanup"}

    fixed_event = _parse_fixed_event(lowered, text)
    if fixed_event:
        return fixed_event

    session = _parse_session_command(lowered)
    if session:
        return session

    move_intent = _parse_move(lowered)
    if move_intent:
        return move_intent

    session_complete = _parse_session_completion(lowered)
    if session_complete:
        return session_complete

    progress = _parse_progress(lowered)
    if progress:
        return progress

    complete = _parse_complete(lowered)
    if complete:
        return complete

    task = _parse_task(lowered)
    if task:
        return task

    deadline_extension = _parse_deadline_extension(lowered)
    if deadline_extension:
        return deadline_extension

    return {"intent": "unknown"}


def _parse_task(text: str):
    patterns = [
        r"(?:i\s+need\s+to|i\s+have\s+to|need\s+to|have\s+to|please\s+)?(.+?)\s+for\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s+(?:before|by)\s+(.+)",
        r"(?:before|by)\s+(.+?)\s+(.+?)\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s+for\s+(.+)",
        r"(?:complete|finish|do)\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s+of\s+(.+?)\s+(?:before|by)\s+(.+)",
        r"(.+?)\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s+(?:before|by)\s+(.+)",
    ]

    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text)
        if not match:
            continue

        if index == 1:
            deadline_text = match.group(1)
            raw_name = f"{match.group(2)} {match.group(4)}"
            hours = float(match.group(3))
        elif index == 2:
            hours = float(match.group(1))
            raw_name = match.group(2)
            deadline_text = match.group(3)
        else:
            raw_name = match.group(1)
            hours = float(match.group(2))
            deadline_text = match.group(3)

        deadline = parse_date(deadline_text)
        task_name = normalize_task_name(_clean_task_name(raw_name))
        if not deadline or not task_name:
            continue

        return {
            "intent": "add_task",
            "task_name": task_name,
            "effort_hours": hours,
            "deadline": deadline,
            "priority": _parse_priority(text),
        }

    return None


def _parse_time_block(text: str):
    range_info = _parse_time_range(text)
    if not range_info:
        return None

    action_match = re.search(
        r"\b(?:i\s+)?(?:should|need\s+to|have\s+to|will|want\s+to|am\s+going\s+to|i'll)\s+(.+)$",
        text,
    )
    if not action_match:
        return None

    task_name = normalize_task_name(_clean_task_name(action_match.group(1)))
    if not task_name:
        return None

    return {
        "intent": "schedule_task_session",
        "task_name": task_name,
        "start_time": range_info["start_time"],
        "schedule_date": parse_relative_day(text, default_today=True),
        "duration_hours": range_info["duration_hours"],
    }


def _asks_today_completed(text: str):
    if not re.search(r"\btoday'?s?\b", text):
        return False
    if not re.search(r"\b(completed|done|finished)\b", text):
        return False
    return bool(re.search(r"\b(what|show|give|list|which|are|were|tasks?|work|schedule)\b", text))


def _asks_today_schedule(text: str):
    if re.fullmatch(r"/?today|today schedule|show today|what today|what should i do today", text):
        return True
    if not re.search(r"\btoday'?s?\b", text):
        return False
    if re.search(r"\b(completed|done|finished)\b", text):
        return False
    return bool(
        re.search(r"\b(remaining|remaing|left|pending|incomplete|scheduled|schedule|tasks?|work|complete)\b", text)
        and re.search(r"\b(what|show|give|list|need|needs?|remaining|remaing)\b", text)
    )


def _parse_fixed_event(lowered: str, original: str):
    if not re.search(rf"\b({EVENT_WORDS})\b", lowered):
        return None

    event_date = parse_date(lowered)
    start_time = parse_time(lowered)
    event_word = re.search(rf"\b({EVENT_WORDS})\b", lowered).group(1)

    if not event_date:
        return {
            "intent": "needs_info",
            "kind": "fixed_event_missing_date",
            "question": "What date is this event on? Please send it like 2026-05-07.",
            "payload": {
                "title": title if 'title' in locals() else event_word.capitalize(),
                "start_time": start_time,
                "duration_hours": _parse_duration(lowered) or 1.0,
                "description": original,
            },
        }
    if not start_time:
        return {
            "intent": "needs_info",
            "kind": "fixed_event_missing_time",
            "question": "What time should I put this event on the calendar?",
            "payload": {
                "title": event_word.capitalize(),
                "event_date": event_date,
                "duration_hours": _parse_duration(lowered) or 1.0,
                "description": original,
            },
        }

    title = event_word.capitalize()
    named = re.search(rf"\b(?:{EVENT_WORDS})\s+(?:with|about|for)\s+(.+?)(?:\s+(?:at|on|tomorrow|today)\b|$)", lowered)
    if named:
        title = f"{title} with {named.group(1).strip()}"

    return {
        "intent": "fixed_event",
        "title": title,
        "event_date": event_date,
        "start_time": start_time,
        "duration_hours": _parse_duration(lowered) or 1.0,
        "description": original,
    }


def _parse_progress(text: str):
    patterns = [
        r"(?:i\s+)?(?:studied|worked\s+on|worked|did|practiced|revised)\s+(.+?)\s+for\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b",
        r"(?:i\s+)?(?:studied|worked|did|practiced|revised)\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s+of\s+(.+)",
        r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s+(?:done|completed|finished)\s+(?:for|of)?\s*(.+)",
    ]
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text)
        if not match:
            continue
        if index == 0:
            task_name = match.group(1)
            hours = float(match.group(2))
        else:
            hours = float(match.group(1))
            task_name = match.group(2)
        task_name = normalize_task_name(_clean_task_name(task_name))
        if task_name:
            return {"intent": "progress", "task_name": task_name, "hours_completed": hours}
    return None


def _parse_session_completion(text: str):
    match = re.search(
        r"(?:i\s+)?(?:finished|completed|done)\s+(.+?)\s+(?:at|from)\s+(.+?)\s+(?:to|-)\s+(.+?)(?:\s+today)?$",
        text,
    )
    if not match:
        return None

    task_name = normalize_task_name(_clean_task_name(match.group(1)))
    start_time = parse_time(match.group(2))
    end_time = parse_time(match.group(3))
    if not task_name or not start_time or not end_time:
        return None

    return {
        "intent": "complete_session",
        "task_name": task_name,
        "start_time": start_time,
        "end_time": end_time,
        "schedule_date": parse_relative_day(text, default_today=True),
    }


def _parse_complete(text: str):
    if re.search(r"\b(?:mark|complete|finish|done)\b", text) and re.search(r"\ball\b", text) and re.search(r"\bpending\s+tasks?\b|\btasks?\b", text):
        return {"intent": "complete_all"}

    match = re.search(r"(?:i\s+)?(?:finished|completed|done|complete)\s+(.+)", text)
    if not match:
        return None
    task_name = normalize_task_name(_clean_task_name(match.group(1)))
    if not task_name or re.search(r"\d+(?:\.\d+)?\s*(?:hours?|hrs?)", text):
        return None
    return {"intent": "complete", "task_name": task_name}


def _parse_move(text: str):
    match = re.search(r"\b(postpone|prepone)\s+(.+?)\s+schedule\s+to\s+(.+)", text)
    if not match:
        return None

    direction = match.group(1)
    task_text = match.group(2)
    target_text = match.group(3)
    task_name = normalize_task_name(re.sub(r"\btoday'?s?\b|\btomorrow'?s?\b", " ", task_text))

    if direction == "postpone":
        from_date = parse_relative_day(task_text, default_today=True)
        to_date = parse_relative_day(target_text, default_today=False)
    else:
        from_date = parse_relative_day(task_text, default_today=False)
        to_date = parse_relative_day(target_text, default_today=False)

    if not task_name:
        return {"intent": "needs_info", "question": f"Which task schedule should I {direction}?"}
    if not from_date:
        return {"intent": "needs_info", "question": f"Which day's {task_name} schedule should I {direction}?"}
    if not to_date:
        return {"intent": "needs_info", "question": f"What date should I {direction} it to?"}

    return {
        "intent": direction,
        "task_name": task_name,
        "from_date": from_date,
        "to_date": to_date,
    }


def _parse_session_command(text: str):
    cancel_at_time = re.search(
        r"\b(?:cancel|remove|delete)\b.+?\b(?:at|from)\s+(.+?)(?:\s+(today|tomorrow))?$",
        text,
    )
    if cancel_at_time:
        start_time = parse_time(cancel_at_time.group(1))
        if start_time:
            return {
                "intent": "cancel_session_at_time",
                "start_time": start_time,
                "schedule_date": parse_relative_day(text, default_today=True),
            }

    timed_task = re.search(
        r"\b(?:add|schedule)\s+(.+?)\s+(?:task\s+)?at\s+(.+?)(?:\s+(today|tomorrow))?$",
        text
    )
    if timed_task:
        task_name = normalize_task_name(_clean_task_name(timed_task.group(1)))
        start_time = parse_time(timed_task.group(2))
        day_text = timed_task.group(3) or text
        if task_name and start_time:
            return {
                "intent": "schedule_task_session",
                "task_name": task_name,
                "start_time": start_time,
                "schedule_date": parse_relative_day(day_text, default_today=True),
                "duration_hours": _parse_duration(text) or 1.0,
            }

    cancel = re.search(r"\bcancel\s+(.+)", text)
    if cancel:
        raw = cancel.group(1)
        return {
            "intent": "cancel_session",
            "task_name": normalize_task_name(re.sub(r"\btoday'?s?\b|\btomorrow'?s?\b", " ", raw)),
            "schedule_date": parse_relative_day(raw, default_today=True),
        }

    resize = re.search(r"\bmake\s+(.+?)\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\s*(?:today|tomorrow)?", text)
    if resize:
        amount = float(resize.group(2))
        unit = resize.group(3)
        hours = amount / 60 if unit.startswith("min") else amount
        return {
            "intent": "resize_session",
            "task_name": normalize_task_name(resize.group(1)),
            "hours": hours,
            "schedule_date": parse_relative_day(text, default_today=True),
        }

    reschedule = re.search(
        r"\b(?:move|reschedule)\s+(.+?)(?:\s+from\s+(.+?))?\s+to\s+(.+?)(?:\s+(today|tomorrow))?$",
        text
    )
    if reschedule:
        task_name = normalize_task_name(reschedule.group(1))
        source_text = reschedule.group(2) or ""
        target_text = reschedule.group(3)
        day_text = reschedule.group(4) or text
        new_start_time = parse_time(target_text)
        source_start_time = parse_time(source_text) if source_text else None
        if new_start_time:
            return {
                "intent": "reschedule_session",
                "task_name": task_name,
                "new_start_time": new_start_time,
                "source_start_time": source_start_time,
                "schedule_date": parse_relative_day(day_text, default_today=True),
            }

    move_evening = re.search(r"\bmove\s+(.+?)\s+to\s+(morning|afternoon|evening|night|today|tomorrow)\b", text)
    if move_evening:
        # Store broad time-of-day moves as targeted postpone/prepone to the same date for now.
        return {
            "intent": "move_session",
            "task_name": normalize_task_name(move_evening.group(1)),
            "period": move_evening.group(2),
            "schedule_date": parse_relative_day(text, default_today=True),
        }

    swap = re.search(r"\bswap\s+(.+?)\s+and\s+(.+?)(?:\s+today|\s+tomorrow)?$", text)
    if swap:
        return {
            "intent": "swap_session",
            "first_task": normalize_task_name(swap.group(1)),
            "second_task": normalize_task_name(swap.group(2)),
            "schedule_date": parse_relative_day(text, default_today=True),
        }

    return None


def _parse_deadline_extension(text: str):
    if re.search(r"\b(add|extend|increase|move)\b", text) and re.search(r"\bdeadline\b", text):
        parsed = parse_date(text)
        days = re.search(r"\b(\d+)\s+days?\b", text)
        return {
            "intent": "extend_deadline",
            "new_deadline": parsed or "",
            "extra_days": int(days.group(1)) if days else None,
        }
    if re.fullmatch(r"yes|yes extend|extend it|ok extend|okay extend", text):
        return {"intent": "extend_deadline", "new_deadline": "", "extra_days": None}
    return None


def parse_date(text: str):
    msg = re.sub(r"[,.]", " ", text.lower())
    iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", msg)
    if iso_match:
        return iso_match.group(1)

    for pattern in [
        r"\b(?:on\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]+)(?:\s+(20\d{2}))?\b",
        r"\b([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(20\d{2}))?\b",
    ]:
        for match in re.finditer(pattern, msg):
            first = match.group(1)
            second = match.group(2)
            year = int(match.group(3) or date.today().year)
            if first.isdigit() and second in MONTHS:
                return date(year, MONTHS[second], int(first)).isoformat()
            if first in MONTHS and second.isdigit():
                return date(year, MONTHS[first], int(second)).isoformat()

    numeric = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](20\d{2}))?\b", msg)
    if numeric:
        return date(int(numeric.group(3) or date.today().year), int(numeric.group(2)), int(numeric.group(1))).isoformat()

    return parse_relative_day(msg, default_today=False)


def parse_relative_day(text: str, default_today=True):
    lowered = text.lower()
    if re.search(r"\btoday'?s?\b", lowered):
        return date.today().isoformat()
    if re.search(r"\btomorrow'?s?\b", lowered):
        return (date.today() + timedelta(days=1)).isoformat()

    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", lowered) or _looks_like_weekday(lowered, name):
            today = date.today()
            days_ahead = (weekday - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return (today + timedelta(days=days_ahead)).isoformat()

    return date.today().isoformat() if default_today else None


def parse_time(text: str):
    msg = text.lower()
    patterns = [
        (r"\b(\d{1,2}):(\d{2})\s*pm\b", lambda m: f"{(int(m.group(1)) % 12) + 12:02d}:{m.group(2)}"),
        (r"\b(\d{1,2}):(\d{2})\s*am\b", lambda m: f"{int(m.group(1)) % 12:02d}:{m.group(2)}"),
        (r"\b(\d{1,2})\s*pm\b", lambda m: f"{(int(m.group(1)) % 12) + 12:02d}:00"),
        (r"\b(\d{1,2})\s*am\b", lambda m: f"{int(m.group(1)) % 12:02d}:00"),
        (r"\b([01]?\d|2[0-3]):([0-5]\d)\b", lambda m: f"{int(m.group(1)):02d}:{m.group(2)}"),
        (r"^\s*([01]?\d|2[0-3])\s*$", lambda m: f"{int(m.group(1)):02d}:00"),
    ]
    for pattern, formatter in patterns:
        match = re.search(pattern, msg)
        if match:
            return formatter(match)
    return None


def _parse_time_range(text: str):
    match = re.search(
        r"\b(\d{1,2}(?::\d{2})?)\s*(am|pm)?\s*(?:to|-)\s*(\d{1,2}(?::\d{2})?)\s*(am|pm)\b",
        text,
    )
    if not match:
        return None

    start_raw = match.group(1)
    start_meridiem = match.group(2) or match.group(4)
    end_raw = match.group(3)
    end_meridiem = match.group(4)
    start_time = parse_time(f"{start_raw} {start_meridiem}")
    end_time = parse_time(f"{end_raw} {end_meridiem}")
    if not start_time or not end_time:
        return None

    start_hour, start_minute = [int(part) for part in start_time.split(":")]
    end_hour, end_minute = [int(part) for part in end_time.split(":")]
    start_minutes = start_hour * 60 + start_minute
    end_minutes = end_hour * 60 + end_minute
    if end_minutes <= start_minutes:
        end_minutes += 24 * 60

    return {
        "start_time": start_time,
        "duration_hours": round((end_minutes - start_minutes) / 60, 2),
    }


def _parse_duration(text: str):
    match = re.search(r"\bfor\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b", text)
    return float(match.group(1)) if match else None


def _parse_priority(text: str):
    for priority in ("high", "medium", "low"):
        if re.search(rf"\b{priority}\b", text):
            return priority
    return "medium"


def _clean_task_name(value: str):
    cleaned = re.sub(r"\b(study|studying|task|please|complete|finish|do|of|for|before|by)\b", " ", value)
    cleaned = re.sub(r"\b\d+(?:\.\d+)?\s*(?:hours?|hrs?)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned


def _looks_like_weekday(text: str, weekday_name: str):
    for word in re.findall(r"\b[a-z]{5,9}\b", text.lower()):
        if abs(len(word) - len(weekday_name)) > 1:
            continue
        mismatches = sum(1 for a, b in zip(word, weekday_name) if a != b)
        mismatches += abs(len(word) - len(weekday_name))
        if mismatches <= 1:
            return True
    return False
