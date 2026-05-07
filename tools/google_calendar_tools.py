from datetime import datetime, timedelta, time
import json
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from database.superbase_client import supabase

SCOPES = ['https://www.googleapis.com/auth/calendar']
TIMEZONE = 'Asia/Kolkata'


def _calendar_service():
    token_json = os.getenv("GOOGLE_TOKEN_JSON")
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    else:
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    return build('calendar', 'v3', credentials=creds)

def create_calendar_event(
    task_name: str,
    deadline: str,
    start_time: str = "09:00",
    duration_hours: float = 1.0
):
    created_event = create_calendar_event_details(
        task_name=task_name,
        deadline=deadline,
        start_time=start_time,
        duration_hours=duration_hours
    )

    return (
        f"Calendar event created: {task_name} on "
        f"{deadline} at {start_time} IST. "
        f"Event ID: {created_event.get('id')}. "
        f"Link: {created_event.get('htmlLink')}"
    )


def create_calendar_event_details(
    task_name: str,
    deadline: str,
    start_time: str = "09:00",
    duration_hours: float = 1.0
):
    """Create a Google Calendar event and return the raw created event."""
    service = _calendar_service()
    duration_hours = float(duration_hours) if duration_hours else 1.0

    start_datetime = datetime.strptime(
        f"{deadline} {start_time}", "%Y-%m-%d %H:%M"
    )
    end_datetime = start_datetime + timedelta(hours=duration_hours)

    event = {
        'summary': f"Task: {task_name}",
        'description': f"Productivity agent task: {task_name}",
        'start': {
            'dateTime': start_datetime.isoformat(),
            'timeZone': TIMEZONE,
        },
        'end': {
            'dateTime': end_datetime.isoformat(),
            'timeZone': TIMEZONE,
        },
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'popup', 'minutes': 10},
                {'method': 'email', 'minutes': 60},
            ],
        },
    }

    return service.events().insert(
        calendarId='primary',
        body=event
    ).execute()


def create_fixed_calendar_event(
    title: str,
    event_date: str,
    start_time: str,
    duration_hours: float = 1.0,
    description: str = "Fixed event added by productivity agent",
    user_id: str = "default"
):
    """Create a fixed calendar event such as a meeting, call, or appointment."""
    duration_hours = float(duration_hours) if duration_hours else 1.0

    start_datetime = datetime.strptime(
        f"{event_date} {start_time}", "%Y-%m-%d %H:%M"
    )
    end_datetime = start_datetime + timedelta(hours=duration_hours)

    schedule_conflicts = _find_schedule_conflicts(
        event_date,
        start_datetime,
        end_datetime,
        user_id
    )
    if schedule_conflicts:
        conflict_lines = "\n".join(
            f"- {conflict['start_time']}-{conflict['end_time']} | {conflict['task_name']}"
            for conflict in schedule_conflicts[:5]
        )
        return (
            f"I did not create {title} at {start_time} on {event_date} because it overlaps "
            f"with scheduled task work:\n{conflict_lines}\n"
            f"Please postpone, cancel, or resize the conflicting task session first."
        )

    service = _calendar_service()

    existing = service.events().list(
        calendarId='primary',
        timeMin=(start_datetime - timedelta(minutes=1)).isoformat() + '+05:30',
        timeMax=(end_datetime + timedelta(minutes=1)).isoformat() + '+05:30',
        singleEvents=True,
        orderBy='startTime'
    ).execute().get('items', [])

    for event in existing:
        event_start = event.get('start', {}).get('dateTime', '')
        event_end = event.get('end', {}).get('dateTime', '')
        event_summary = event.get('summary', '')
        if (
            event_summary.strip().lower() == title.strip().lower()
            and event_start.startswith(start_datetime.isoformat())
            and event_end.startswith(end_datetime.isoformat())
        ):
            return (
                f"This calendar event already exists: {title} on {event_date} "
                f"at {start_time} IST. Event ID: {event.get('id')}. "
                f"Link: {event.get('htmlLink')}"
            )

    event = {
        'summary': title,
        'description': description,
        'start': {
            'dateTime': start_datetime.isoformat(),
            'timeZone': TIMEZONE,
        },
        'end': {
            'dateTime': end_datetime.isoformat(),
            'timeZone': TIMEZONE,
        },
        'reminders': {
            'useDefault': True,
        },
    }

    created_event = service.events().insert(
        calendarId='primary',
        body=event
    ).execute()

    return (
        f"Calendar event created: {title} on {event_date} at {start_time} IST. "
        f"Event ID: {created_event.get('id')}. "
        f"Link: {created_event.get('htmlLink')}"
    )


def _find_schedule_conflicts(event_date: str, start_datetime: datetime, end_datetime: datetime, user_id: str = "default"):
    """Find incomplete app-planned task sessions that overlap a fixed event."""
    try:
        query = supabase.table("schedule")\
            .select("*")\
            .eq("scheduled_date", event_date)\
            .eq("completed", False)
        if user_id:
            query = query.eq("user_id", str(user_id))
        rows = query.execute().data or []
    except Exception:
        try:
            rows = supabase.table("schedule")\
                .select("*")\
                .eq("scheduled_date", event_date)\
                .eq("completed", False)\
                .execute().data or []
        except Exception:
            return []

    conflicts = []
    for row in rows:
        row_start_time = row.get("start_time")
        if not row_start_time:
            continue

        try:
            row_start = datetime.strptime(f"{event_date} {row_start_time}", "%Y-%m-%d %H:%M")
            if row.get("end_time"):
                row_end = datetime.strptime(f"{event_date} {row['end_time']}", "%Y-%m-%d %H:%M")
            else:
                row_end = row_start + timedelta(hours=float(row.get("hours_planned") or 1))
        except (TypeError, ValueError):
            continue

        if row_start < end_datetime and start_datetime < row_end:
            conflicts.append({
                "start_time": row_start.strftime("%H:%M"),
                "end_time": row_end.strftime("%H:%M"),
                "task_name": _schedule_task_name(row),
            })

    return sorted(conflicts, key=lambda conflict: conflict["start_time"])


def _schedule_task_name(row):
    if row.get("task_name"):
        return row["task_name"]
    task_id = row.get("task_id")
    if not task_id:
        return "Scheduled task"
    try:
        rows = supabase.table("tasks").select("task_name").eq("id", str(task_id)).execute().data or []
    except Exception:
        return "Scheduled task"
    return rows[0].get("task_name", "Scheduled task") if rows else "Scheduled task"


def delete_calendar_event(event_id: str):
    """Delete a Google Calendar event by ID."""
    if not event_id:
        return "No calendar event ID provided."

    service = _calendar_service()
    service.events().delete(calendarId='primary', eventId=event_id).execute()
    return f"Calendar event deleted: {event_id}"


def get_calendar_events(start_date: str, end_date: str):
    """Read Google Calendar events between two YYYY-MM-DD dates."""
    service = _calendar_service()
    start = datetime.combine(
        datetime.strptime(start_date, "%Y-%m-%d").date(),
        time.min
    )
    end = datetime.combine(
        datetime.strptime(end_date, "%Y-%m-%d").date(),
        time.max
    )

    result = service.events().list(
        calendarId='primary',
        timeMin=start.isoformat() + '+05:30',
        timeMax=end.isoformat() + '+05:30',
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    return result.get('items', [])


def get_busy_blocks(start_date: str, end_date: str):
    """Return calendar busy blocks in a compact shape for planning."""
    blocks = []
    for event in get_calendar_events(start_date, end_date):
        start = event.get('start', {}).get('dateTime')
        end = event.get('end', {}).get('dateTime')
        if not start or not end:
            continue

        blocks.append({
            "summary": event.get('summary', 'Busy'),
            "start": start,
            "end": end
        })

    return blocks


def get_free_time_slots(
    start_date: str,
    end_date: str,
    work_start: str = "09:00",
    work_end: str = "18:00",
    min_slot_minutes: int = 30
):
    """Find free workday slots after subtracting Google Calendar events."""
    busy_blocks = get_busy_blocks(start_date, end_date)
    busy_by_date = {}

    for block in busy_blocks:
        start = datetime.fromisoformat(block["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(block["end"].replace("Z", "+00:00"))
        day = start.date().isoformat()
        busy_by_date.setdefault(day, []).append((start.replace(tzinfo=None), end.replace(tzinfo=None)))

    slots = []
    current = datetime.strptime(start_date, "%Y-%m-%d").date()
    final = datetime.strptime(end_date, "%Y-%m-%d").date()

    while current <= final:
        day_start = datetime.strptime(f"{current.isoformat()} {work_start}", "%Y-%m-%d %H:%M")
        day_end = datetime.strptime(f"{current.isoformat()} {work_end}", "%Y-%m-%d %H:%M")
        cursor = day_start

        for busy_start, busy_end in sorted(busy_by_date.get(current.isoformat(), [])):
            if busy_start > cursor:
                minutes = (busy_start - cursor).total_seconds() / 60
                if minutes >= min_slot_minutes:
                    slots.append({
                        "date": current.isoformat(),
                        "start_time": cursor.strftime("%H:%M"),
                        "end_time": busy_start.strftime("%H:%M"),
                        "hours": round(minutes / 60, 2)
                    })
            cursor = max(cursor, busy_end)

        if cursor < day_end:
            minutes = (day_end - cursor).total_seconds() / 60
            if minutes >= min_slot_minutes:
                slots.append({
                    "date": current.isoformat(),
                    "start_time": cursor.strftime("%H:%M"),
                    "end_time": day_end.strftime("%H:%M"),
                    "hours": round(minutes / 60, 2)
                })

        current += timedelta(days=1)

    return slots
