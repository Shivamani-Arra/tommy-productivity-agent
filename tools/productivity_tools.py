from datetime import date, datetime, timedelta
import math
import re

from database.superbase_client import supabase
from tools.google_calendar_tools import (
    create_calendar_event_details,
    delete_calendar_event,
    get_free_time_slots,
)
from tools.task_tools import normalize_task_name


DEFAULT_USER_ID = "default"
PRIORITY_WEIGHT = {"high": 1.25, "medium": 1.0, "low": 0.8}


def _today():
    return date.today()


def _safe_execute(builder):
    return builder.execute()


def _select(table, columns="*", user_id=None):
    query = supabase.table(table).select(columns)
    if user_id:
        query = query.eq("user_id", str(user_id))
    try:
        return _safe_execute(query).data or []
    except Exception:
        if user_id:
            return _safe_execute(supabase.table(table).select(columns)).data or []
        raise


def _insert(table, payload):
    unknown_column = re.compile(r"column '([^']+)'|Could not find the '([^']+)' column")
    current = dict(payload)

    while current:
        try:
            return supabase.table(table).insert(current).execute()
        except Exception as exc:
            match = unknown_column.search(str(exc))
            missing = next((group for group in match.groups() if group), None) if match else None
            if not missing or missing not in current:
                raise
            current.pop(missing)

    raise RuntimeError(f"Could not insert into {table}")


def _update(table, values, column, value):
    unknown_column = re.compile(r"column '([^']+)'|Could not find the '([^']+)' column")
    current = dict(values)

    while current:
        try:
            return supabase.table(table).update(current).eq(column, value).execute()
        except Exception as exc:
            match = unknown_column.search(str(exc))
            missing = next((group for group in match.groups() if group), None) if match else None
            if not missing or missing not in current:
                raise
            current.pop(missing)

    return None


def _delete_event_quietly(event_id):
    if not event_id:
        return False
    try:
        delete_calendar_event(event_id)
        return True
    except Exception:
        return False


def _cancel_future_schedule(user_id=DEFAULT_USER_ID, task_id=None, from_date=None):
    """Cancel future incomplete schedule rows before generating a fresh plan."""
    try:
        rows = _select("schedule", "*", user_id)
    except Exception:
        return 0

    cancelled = 0
    from_date = from_date or _today().isoformat()
    for row in rows:
        if row.get("scheduled_date") < from_date or row.get("completed"):
            continue
        if task_id is not None and str(row.get("task_id")) != str(task_id):
            continue

        if _delete_event_quietly(row.get("calendar_event_id")):
            cancelled += 1

        try:
            _update("schedule", {"completed": True, "status": "cancelled"}, "id", row["id"])
        except Exception:
            pass

    return cancelled


def _pending_tasks(user_id=DEFAULT_USER_ID):
    query = supabase.table("tasks").select("*").eq("status", "pending").order("deadline")
    if user_id:
        query = query.eq("user_id", str(user_id))
    try:
        return query.execute().data or []
    except Exception:
        return supabase.table("tasks").select("*").eq("status", "pending").order("deadline").execute().data or []


def _task_by_id(task_id, user_id=DEFAULT_USER_ID):
    if not task_id:
        return None
    query = supabase.table("tasks").select("*").eq("id", str(task_id))
    if user_id:
        query = query.eq("user_id", str(user_id))
    try:
        rows = query.execute().data or []
    except Exception:
        rows = supabase.table("tasks").select("*").eq("id", str(task_id)).execute().data or []
    return rows[0] if rows else None


def _progress_for_task(task_id, user_id=DEFAULT_USER_ID):
    try:
        rows = _select("daily_progress", "*", user_id)
    except Exception:
        return []
    return [row for row in rows if str(row.get("task_id")) == str(task_id)]


def _completed_hours(task, user_id=DEFAULT_USER_ID):
    explicit = task.get("completed_hours")
    if explicit is not None:
        try:
            return float(explicit)
        except (TypeError, ValueError):
            pass

    return sum(float(row.get("hours_completed") or 0) for row in _progress_for_task(task.get("id"), user_id))


def _remaining_hours(task, user_id=DEFAULT_USER_ID):
    effort = float(task.get("effort_hours") or task.get("estimated_hours") or 1)
    return max(0.0, effort - _completed_hours(task, user_id))


def _default_slots(start_day, end_day):
    slots = []
    current = start_day
    while current <= end_day:
        slots.append({
            "date": current.isoformat(),
            "start_time": "00:00",
            "end_time": "23:59",
            "hours": 23.98
        })
        current += timedelta(days=1)
    return slots


def _free_slots_or_default(start_day, end_day):
    if start_day > end_day:
        return []
    try:
        slots = get_free_time_slots(start_day.isoformat(), end_day.isoformat())
    except Exception:
        slots = []
    return slots or _default_slots(start_day, end_day)


def _normalize_free_slots(slots):
    """Sort and merge free slots so the planner never creates overlapping sessions."""
    by_date = {}
    for slot in slots:
        try:
            start_dt = datetime.strptime(f"{slot['date']} {slot['start_time']}", "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(f"{slot['date']} {slot['end_time']}", "%Y-%m-%d %H:%M")
        except (KeyError, ValueError):
            continue
        if end_dt <= start_dt:
            continue
        by_date.setdefault(slot["date"], []).append([start_dt, end_dt])

    normalized = []
    for slot_date, ranges in by_date.items():
        ranges.sort(key=lambda item: item[0])
        merged = []
        for start_dt, end_dt in ranges:
            if not merged or start_dt >= merged[-1][1]:
                merged.append([start_dt, end_dt])
            else:
                merged[-1][1] = max(merged[-1][1], end_dt)

        for start_dt, end_dt in merged:
            normalized.append({
                "date": slot_date,
                "start_time": start_dt.strftime("%H:%M"),
                "end_time": end_dt.strftime("%H:%M"),
                "hours": round((end_dt - start_dt).total_seconds() / 3600, 2)
            })

    return sorted(normalized, key=lambda slot: (slot["date"], slot["start_time"]))


def _find_target_slot(target_date, preferred_start_time, duration_hours, allow_explicit_outside_hours=False):
    """Find a non-conflicting target slot on a date, preferring the original start time."""
    duration = float(duration_hours or 1)
    slots = _normalize_free_slots(_free_slots_or_default(
        datetime.fromisoformat(target_date).date(),
        datetime.fromisoformat(target_date).date()
    ))

    preferred_start = datetime.strptime(f"{target_date} {preferred_start_time}", "%Y-%m-%d %H:%M")
    preferred_end = preferred_start + timedelta(hours=duration)

    for slot in slots:
        slot_start = datetime.strptime(f"{slot['date']} {slot['start_time']}", "%Y-%m-%d %H:%M")
        slot_end = datetime.strptime(f"{slot['date']} {slot['end_time']}", "%Y-%m-%d %H:%M")
        if slot_start <= preferred_start and preferred_end <= slot_end:
            return {
                "date": target_date,
                "start_time": preferred_start_time,
                "end_time": preferred_end.strftime("%H:%M"),
                "changed_time": False,
                "alternatives": slots,
            }

    if allow_explicit_outside_hours:
        try:
            explicit_slots = _normalize_free_slots(get_free_time_slots(
                target_date,
                target_date,
                work_start=preferred_start_time,
                work_end=preferred_end.strftime("%H:%M"),
            ))
        except Exception:
            explicit_slots = [{
                "date": target_date,
                "start_time": preferred_start_time,
                "end_time": preferred_end.strftime("%H:%M"),
                "hours": duration,
            }]

        for slot in explicit_slots:
            slot_start = datetime.strptime(f"{slot['date']} {slot['start_time']}", "%Y-%m-%d %H:%M")
            slot_end = datetime.strptime(f"{slot['date']} {slot['end_time']}", "%Y-%m-%d %H:%M")
            if slot_start <= preferred_start and preferred_end <= slot_end:
                return {
                    "date": target_date,
                    "start_time": preferred_start_time,
                    "end_time": preferred_end.strftime("%H:%M"),
                    "changed_time": False,
                    "alternatives": slots,
                }

    for slot in slots:
        if float(slot.get("hours") or 0) < duration:
            continue
        slot_start = datetime.strptime(f"{slot['date']} {slot['start_time']}", "%Y-%m-%d %H:%M")
        slot_end = slot_start + timedelta(hours=duration)
        return {
            "date": target_date,
            "start_time": slot_start.strftime("%H:%M"),
            "end_time": slot_end.strftime("%H:%M"),
            "changed_time": True,
            "alternatives": slots,
        }

    return {
        "date": target_date,
        "start_time": None,
        "end_time": None,
        "changed_time": True,
        "alternatives": slots,
    }


def _record_deadline_extension_request(task, backlog_hours, suggested_deadline, user_id=DEFAULT_USER_ID):
    payload = {
        "user_id": str(user_id),
        "task_id": str(task.get("id")),
        "task_name": task.get("task_name"),
        "current_deadline": task.get("deadline"),
        "backlog_hours": round(float(backlog_hours), 2),
        "suggested_deadline": suggested_deadline,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }
    try:
        _insert("deadline_extension_requests", payload)
    except Exception:
        pass


def _latest_extension_request(user_id=DEFAULT_USER_ID):
    try:
        rows = _select("deadline_extension_requests", "*", user_id)
    except Exception:
        return None
    pending = [row for row in rows if row.get("status") == "pending"]
    if not pending:
        return None
    return sorted(pending, key=lambda row: row.get("created_at", ""), reverse=True)[0]


def save_pending_followup(kind: str, payload: dict, question: str, user_id=DEFAULT_USER_ID):
    """Remember a half-complete user request until the user provides the missing detail."""
    try:
        _insert("pending_followups", {
            "user_id": str(user_id),
            "kind": kind,
            "payload": payload,
            "question": question,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        })
    except Exception:
        pass
    return question


def get_pending_followup(user_id=DEFAULT_USER_ID):
    try:
        rows = _select("pending_followups", "*", user_id)
    except Exception:
        return None
    pending = [row for row in rows if row.get("status") == "pending"]
    if not pending:
        return None
    return sorted(pending, key=lambda row: row.get("created_at", ""), reverse=True)[0]


def clear_pending_followup(followup_id):
    try:
        _update("pending_followups", {"status": "resolved"}, "id", followup_id)
    except Exception:
        pass


def _risk(task, user_id=DEFAULT_USER_ID):
    deadline = datetime.fromisoformat(task["deadline"]).date()
    days_left = max(0, (deadline - _today()).days)
    remaining = _remaining_hours(task, user_id)
    priority = PRIORITY_WEIGHT.get(str(task.get("priority", "medium")).lower(), 1.0)
    available_days = max(1, days_left + 1)
    daily_load = remaining / available_days
    score = min(100, round((daily_load / 2.5) * 70 * priority + (25 if days_left <= 1 else 0)))

    if deadline < _today():
        label = "overdue"
        score = 100
    elif score >= 80:
        label = "critical"
    elif score >= 55:
        label = "high"
    elif score >= 30:
        label = "medium"
    else:
        label = "low"

    return {
        "score": score,
        "label": label,
        "days_left": days_left,
        "remaining_hours": round(remaining, 2),
        "required_hours_per_day": round(daily_load, 2)
    }


def score_deadline_risk(user_id=DEFAULT_USER_ID):
    """Score every pending task by deadline risk."""
    tasks = _pending_tasks(user_id)
    if not tasks:
        return "No pending tasks to score."

    lines = []
    for task in tasks:
        risk = _risk(task, user_id)
        try:
            _update("tasks", {"risk_score": risk["score"], "risk_label": risk["label"]}, "id", task["id"])
        except Exception:
            pass
        lines.append(
            f"{task['task_name']} | {risk['label']} risk ({risk['score']}/100) | "
            f"{risk['remaining_hours']}h left | {risk['days_left']} days left | "
            f"needs {risk['required_hours_per_day']}h/day"
        )

    return "\n".join(lines)


def read_calendar_availability(start_date=None, end_date=None, user_id=DEFAULT_USER_ID):
    """Read free calendar time for scheduling."""
    start_date = start_date or _today().isoformat()
    end_date = end_date or (_today() + timedelta(days=7)).isoformat()

    try:
        slots = get_free_time_slots(start_date, end_date)
    except Exception as exc:
        return f"Could not read calendar availability: {exc}"

    if not slots:
        return f"No free work slots found from {start_date} to {end_date}."

    return "\n".join(
        f"{slot['date']} {slot['start_time']}-{slot['end_time']} ({slot['hours']}h)"
        for slot in slots[:30]
    )


def show_today_schedule(user_id=DEFAULT_USER_ID):
    """Show only today's incomplete schedule sessions."""
    today = _today().isoformat()
    try:
        rows = _select("schedule", "*", user_id)
    except Exception as exc:
        return f"Could not read today's schedule: {exc}"

    todays_rows = [
        row for row in rows
        if row.get("scheduled_date") == today and not row.get("completed")
    ]
    if not todays_rows:
        return "No scheduled tasks for today."

    lines = []
    for row in sorted(todays_rows, key=lambda item: item.get("start_time") or ""):
        task = _task_by_id(row.get("task_id"), user_id)
        task_name = task.get("task_name") if task else row.get("task_name", "Task")
        lines.append(
            f"{row.get('start_time', '09:00')}-{row.get('end_time', '')} | "
            f"{task_name} ({float(row.get('hours_planned') or 0):g}h)"
        )

    return f"Today's schedule ({today}):\n" + "\n".join(lines)


def show_today_completed_schedule(user_id=DEFAULT_USER_ID):
    """Show today's completed schedule sessions."""
    today = _today().isoformat()
    try:
        rows = _select("schedule", "*", user_id)
    except Exception as exc:
        return f"Could not read today's completed schedule: {exc}"

    completed_rows = [
        row for row in rows
        if row.get("scheduled_date") == today and row.get("completed")
        and str(row.get("status", "")).lower() != "cancelled"
    ]
    if not completed_rows:
        return "No completed tasks found for today."

    lines = []
    for row in sorted(completed_rows, key=lambda item: item.get("start_time") or ""):
        task = _task_by_id(row.get("task_id"), user_id)
        display_name = task.get("task_name") if task else row.get("task_name", "Scheduled task")
        lines.append(
            f"- {row.get('start_time', '')}-{row.get('end_time', '')} | "
            f"{display_name} ({row.get('hours_planned', '?')}h)"
        )

    return f"Completed today ({today}):\n" + "\n".join(lines)


def complete_scheduled_session(
    task_name: str,
    start_time: str,
    end_time: str = None,
    schedule_date: str = None,
    user_id=DEFAULT_USER_ID
):
    """Mark one scheduled session complete and log its planned hours as progress."""
    target_date = schedule_date or _today().isoformat()
    wanted = normalize_task_name(task_name)
    try:
        rows = _select("schedule", "*", user_id)
    except Exception as exc:
        return f"Could not read schedule: {exc}"

    matches = []
    for row in rows:
        if row.get("scheduled_date") != target_date or row.get("completed"):
            continue
        if row.get("start_time") != start_time:
            continue
        if end_time and row.get("end_time") != end_time:
            continue
        task = _task_by_id(row.get("task_id"), user_id)
        display_name = task.get("task_name") if task else row.get("task_name", "")
        normalized = normalize_task_name(display_name)
        if wanted and wanted not in normalized and normalized not in wanted:
            continue
        matches.append((row, task, display_name))

    if not matches:
        time_range = f"{start_time}-{end_time}" if end_time else start_time
        return f"No incomplete {task_name} session found on {target_date} at {time_range}."
    if len(matches) > 1:
        return f"I found multiple {task_name} sessions at {start_time}. Please include the end time too."

    row, task, display_name = matches[0]
    hours = float(row.get("hours_planned") or 0)
    try:
        _update("schedule", {"completed": True, "status": "completed"}, "id", row["id"])
    except Exception as exc:
        return f"Could not mark the session complete: {exc}"

    if task and task.get("id") and hours:
        try:
            _insert("daily_progress", {
                "task_id": str(task.get("id")),
                "user_id": str(user_id),
                "date": target_date,
                "hours_completed": hours,
                "note": f"Completed scheduled session {start_time}-{row.get('end_time', end_time or '')}",
            })
        except Exception:
            pass

        if _remaining_hours(task, user_id) <= 0:
            try:
                supabase.table("tasks").update({"status": "completed"}).eq("id", task["id"]).execute()
            except Exception:
                pass

    return (
        f"Marked {display_name or task_name} complete for {target_date} "
        f"{start_time}-{row.get('end_time', end_time or '')}."
    )


def schedule_task_session(
    task_name: str,
    start_time: str,
    schedule_date: str = None,
    duration_hours: float = 1.0,
    user_id=DEFAULT_USER_ID
):
    """Create a one-off scheduled task session at an exact time."""
    target_date = schedule_date or _today().isoformat()
    display_name = normalize_task_name(task_name) or task_name
    hours = float(duration_hours or 1.0)
    start_dt = datetime.strptime(f"{target_date} {start_time}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(hours=hours)
    end_time = end_dt.strftime("%H:%M")

    try:
        rows = _select("schedule", "*", user_id)
    except Exception as exc:
        return f"Could not read schedule: {exc}"

    conflicts = _schedule_conflicts(rows, target_date, start_dt, end_dt, user_id=user_id)
    if conflicts:
        conflict_lines = "\n".join(
            f"- {conflict['start_time']}-{conflict['end_time']} | {conflict['task_name']}"
            for conflict in conflicts[:5]
        )
        return (
            f"I could not schedule {display_name} at {start_time}-{end_time} on {target_date} "
            f"because it overlaps another scheduled task:\n{conflict_lines}"
        )

    target_slot = _find_target_slot(target_date, start_time, hours, allow_explicit_outside_hours=True)
    if target_slot.get("changed_time"):
        alternatives = target_slot.get("alternatives") or []
        available = "\n".join(
            f"{slot['start_time']}-{slot['end_time']} ({slot['hours']}h)"
            for slot in alternatives[:6]
        )
        suffix = f"\nAvailable slots:\n{available}" if available else ""
        return (
            f"I could not schedule {display_name} at {start_time}-{end_time} on {target_date}; "
            f"that time is busy on your calendar.{suffix}"
        )

    task_id = None
    try:
        task_result = _insert("tasks", {
            "task_name": display_name,
            "deadline": target_date,
            "effort_hours": hours,
            "priority": "medium",
            "user_id": str(user_id),
            "status": "pending"
        })
        task_rows = getattr(task_result, "data", None) or []
        if task_rows:
            task_id = task_rows[0].get("id")
    except Exception:
        pass

    calendar_event_id = None
    calendar_link = None
    try:
        created_event = create_calendar_event_details(display_name, target_date, start_time, hours)
        calendar_event_id = created_event.get("id")
        calendar_link = created_event.get("htmlLink")
    except Exception:
        pass

    try:
        _insert("schedule", {
            "task_id": str(task_id) if task_id else None,
            "task_name": display_name,
            "user_id": str(user_id),
            "scheduled_date": target_date,
            "start_time": start_time,
            "end_time": end_time,
            "hours_planned": round(hours, 2),
            "completed": False,
            "status": "planned",
            "calendar_event_id": calendar_event_id,
            "calendar_link": calendar_link
        })
    except Exception as exc:
        return f"Could not save scheduled task session: {exc}"

    calendar_note = " Calendar event created." if calendar_event_id else " Calendar event could not be created, but the app schedule was saved."
    return f"Scheduled {display_name} on {target_date} at {start_time}-{end_time}.{calendar_note}"


def set_user_preferences(
    study_start: str = "",
    study_end: str = "",
    sleep_start: str = "23:00",
    sleep_end: str = "07:00",
    max_session_hours: float = 2.0,
    break_minutes: int = 10,
    no_study_days: str = "",
    preferred_subjects: str = "",
    user_id=DEFAULT_USER_ID
):
    """Store planning preferences for a user."""
    payload = {
        "user_id": str(user_id),
        "study_start": study_start,
        "study_end": study_end,
        "sleep_start": sleep_start,
        "sleep_end": sleep_end,
        "max_session_hours": float(max_session_hours),
        "break_minutes": int(break_minutes),
        "no_study_days": no_study_days,
        "preferred_subjects": preferred_subjects,
        "updated_at": datetime.utcnow().isoformat()
    }
    try:
        rows = _select("user_preferences", "*", user_id)
        if rows:
            _update("user_preferences", payload, "id", rows[0]["id"])
        else:
            _insert("user_preferences", payload)
    except Exception as exc:
        return f"Could not save preferences: {exc}"
    return "Saved your planning preferences."


def get_user_preferences(user_id=DEFAULT_USER_ID):
    try:
        rows = _select("user_preferences", "*", user_id)
    except Exception:
        return {}
    return rows[0] if rows else {}


def spread_daily_schedule(days_ahead=7, user_id=DEFAULT_USER_ID, create_calendar_events=True, cancel_from_date=None):
    """Spread pending task work across free calendar slots before deadlines."""
    tasks = _pending_tasks(user_id)
    if not tasks:
        return "No pending tasks to schedule."

    cancelled_events = _cancel_future_schedule(user_id, from_date=cancel_from_date)

    start = _today()
    end = start + timedelta(days=int(days_ahead))
    latest_deadline = max(datetime.fromisoformat(t["deadline"]).date() for t in tasks)
    end = min(end, latest_deadline)

    prefs = get_user_preferences(user_id)
    free_slots = _normalize_free_slots(_free_slots_or_default(start, end))
    if prefs.get("study_start") and prefs.get("study_end"):
        free_slots = [
            slot for slot in free_slots
            if slot["start_time"] >= prefs["study_start"] and slot["end_time"] <= prefs["study_end"]
        ] or free_slots
    max_session_hours = float(prefs.get("max_session_hours") or 2.0)

    planned = []
    backlog_lines = []
    tasks_by_risk = sorted(tasks, key=lambda task: (-_risk(task, user_id)["score"], task["deadline"]))

    for task in tasks_by_risk:
        remaining = _remaining_hours(task, user_id)
        deadline = datetime.fromisoformat(task["deadline"]).date()
        task_slots = [
            slot for slot in free_slots
            if start <= datetime.fromisoformat(slot["date"]).date() <= deadline
        ]
        schedule_dates = sorted({slot["date"] for slot in task_slots})
        if not schedule_dates:
            continue

        for schedule_date in schedule_dates:
            if remaining <= 0:
                break

            days_left_in_plan = len([d for d in schedule_dates if d >= schedule_date])
            day_target = math.ceil((remaining / max(1, days_left_in_plan)) * 4) / 4
            day_target = min(remaining, day_target)
            day_planned = 0.0

            for slot in [s for s in free_slots if s["date"] == schedule_date]:
                if remaining <= 0 or day_planned >= day_target:
                    break
                if slot["hours"] < 0.5:
                    continue

                hours = min(remaining, slot["hours"], day_target - day_planned, max_session_hours)
                if hours < 0.5 and remaining > hours:
                    continue

                start_time = slot["start_time"]
                start_dt = datetime.strptime(f"{slot['date']} {start_time}", "%Y-%m-%d %H:%M")
                end_dt = start_dt + timedelta(hours=hours)

                calendar_event_id = None
                calendar_link = None
                if create_calendar_events:
                    try:
                        created_event = create_calendar_event_details(task["task_name"], slot["date"], start_time, hours)
                        calendar_event_id = created_event.get("id")
                        calendar_link = created_event.get("htmlLink")
                    except Exception:
                        pass

                payload = {
                    "task_id": str(task.get("id")),
                    "user_id": str(user_id),
                    "scheduled_date": slot["date"],
                    "start_time": start_time,
                    "end_time": end_dt.strftime("%H:%M"),
                    "hours_planned": round(hours, 2),
                    "completed": False,
                    "status": "planned",
                    "calendar_event_id": calendar_event_id,
                    "calendar_link": calendar_link
                }
                try:
                    _insert("schedule", payload)
                except Exception:
                    pass

                planned.append(f"{slot['date']} {start_time}-{end_dt.strftime('%H:%M')} | {task['task_name']} ({round(hours, 2)}h)")
                remaining -= hours
                day_planned += hours
                slot["hours"] = round(slot["hours"] - hours, 2)
                slot["start_time"] = end_dt.strftime("%H:%M")

        if remaining > 0:
            backlog_hours = remaining
            overflow_start = max(deadline + timedelta(days=1), start)
            overflow_end = overflow_start + timedelta(days=14)
            overflow_slots = _normalize_free_slots(_free_slots_or_default(overflow_start, overflow_end))
            last_backlog_date = None

            for slot in overflow_slots:
                if remaining <= 0:
                    break
                if slot["hours"] < 0.5:
                    continue

                hours = min(remaining, slot["hours"], max_session_hours)
                start_time = slot["start_time"]
                start_dt = datetime.strptime(f"{slot['date']} {start_time}", "%Y-%m-%d %H:%M")
                end_dt = start_dt + timedelta(hours=hours)

                calendar_event_id = None
                calendar_link = None
                if create_calendar_events:
                    try:
                        created_event = create_calendar_event_details(task["task_name"], slot["date"], start_time, hours)
                        calendar_event_id = created_event.get("id")
                        calendar_link = created_event.get("htmlLink")
                    except Exception:
                        pass

                payload = {
                    "task_id": str(task.get("id")),
                    "user_id": str(user_id),
                    "scheduled_date": slot["date"],
                    "start_time": start_time,
                    "end_time": end_dt.strftime("%H:%M"),
                    "hours_planned": round(hours, 2),
                    "completed": False,
                    "status": "backlog",
                    "calendar_event_id": calendar_event_id,
                    "calendar_link": calendar_link
                }
                try:
                    _insert("schedule", payload)
                except Exception:
                    pass

                planned.append(f"{slot['date']} {start_time}-{end_dt.strftime('%H:%M')} | {task['task_name']} backlog ({round(hours, 2)}h)")
                remaining -= hours
                slot["hours"] = round(slot["hours"] - hours, 2)
                slot["start_time"] = end_dt.strftime("%H:%M")
                last_backlog_date = slot["date"]

            suggested_deadline = last_backlog_date or overflow_end.isoformat()
            _record_deadline_extension_request(task, backlog_hours, suggested_deadline, user_id)
            backlog_lines.append(
                f"{task['task_name']} has {round(backlog_hours, 2)}h backlog beyond {task['deadline']}. "
                f"I tentatively scheduled it through {suggested_deadline}. "
                f"Do you want to extend the deadline to {suggested_deadline}, or tell me another date?"
            )

    if not planned:
        return "I could not find enough free time before the pending deadlines."

    prefix = f"Cancelled {cancelled_events} old future calendar event(s).\n" if cancelled_events else ""
    warning = ""
    if backlog_lines:
        warning = "\n\nBacklog warning:\n" + "\n".join(backlog_lines)

    return prefix + "Planned schedule:\n" + "\n".join(planned[:40]) + warning


def log_partial_progress(task_name: str, hours_completed: float, note: str = "", user_id=DEFAULT_USER_ID):
    """Log partial progress for a task without marking it complete."""
    tasks = _pending_tasks(user_id)
    matches = [task for task in tasks if task_name.lower() in task["task_name"].lower()]
    if not matches:
        return f"No pending task matched '{task_name}'."

    task = matches[0]
    hours = float(hours_completed)
    payload = {
        "task_id": str(task.get("id")),
        "user_id": str(user_id),
        "date": _today().isoformat(),
        "hours_completed": hours,
        "note": note
    }
    try:
        _insert("daily_progress", payload)
    except Exception as exc:
        return f"Could not log progress: {exc}"

    remaining = max(0.0, _remaining_hours(task, user_id))
    if remaining <= 0:
        try:
            supabase.table("tasks").update({"status": "completed"}).eq("id", task["id"]).execute()
        except Exception:
            pass
        _cancel_future_schedule(user_id, task_id=task.get("id"))
        return f"Logged {hours} hours for {task['task_name']}. It now looks complete."

    tomorrow = (_today() + timedelta(days=1)).isoformat()
    schedule_result = spread_daily_schedule(
        days_ahead=14,
        user_id=user_id,
        create_calendar_events=True,
        cancel_from_date=tomorrow
    )
    return (
        f"Logged {hours} hours for {task['task_name']}. "
        f"About {round(remaining, 2)} hours remain.\n{schedule_result}"
    )


def replan_missed_work(user_id=DEFAULT_USER_ID):
    """Move missed incomplete schedule sessions back into the planning pool."""
    yesterday = (_today() - timedelta(days=1)).isoformat()
    try:
        rows = _select("schedule", "*", user_id)
    except Exception as exc:
        return f"Could not read schedule for replanning: {exc}"

    missed = [
        row for row in rows
        if row.get("scheduled_date") <= yesterday and not row.get("completed")
    ]
    if not missed:
        return "No missed scheduled work found."

    for row in missed:
        try:
            _update("schedule", {"completed": True, "status": "missed"}, "id", row["id"])
        except Exception:
            pass

    schedule_result = spread_daily_schedule(days_ahead=7, user_id=user_id, create_calendar_events=False)
    return f"Found {len(missed)} missed session(s) and replanned upcoming work.\n{schedule_result}"


def postpone_schedule(
    task_name: str,
    from_date: str = None,
    to_date: str = None,
    user_id=DEFAULT_USER_ID
):
    """Move matching scheduled sessions from one day to another without replanning unrelated tasks."""
    source_date = from_date or _today().isoformat()
    target_date = to_date or (_today() + timedelta(days=1)).isoformat()
    wanted = normalize_task_name(task_name)

    try:
        rows = _select("schedule", "*", user_id)
    except Exception as exc:
        return f"Could not read schedule: {exc}"

    matches = []
    for row in rows:
        if row.get("scheduled_date") != source_date or row.get("completed"):
            continue
        task = _task_by_id(row.get("task_id"), user_id)
        row_task_name = task.get("task_name") if task else row.get("task_name", "")
        if wanted and wanted not in normalize_task_name(row_task_name):
            continue
        matches.append((row, task))

    if not matches:
        return f"No {task_name} schedule found on {source_date}."

    moved = []
    deleted_events = 0
    conflict_notes = []
    for row, task in matches:
        calendar_event_id = None
        calendar_link = None
        display_name = task.get("task_name") if task else task_name
        hours = float(row.get("hours_planned") or 1)
        original_start_time = row.get("start_time") or "09:00"
        target_slot = _find_target_slot(target_date, original_start_time, hours)
        if not target_slot.get("start_time"):
            alternatives = target_slot.get("alternatives") or []
            if alternatives:
                available = "\n".join(
                    f"{slot['start_time']}-{slot['end_time']} ({slot['hours']}h)"
                    for slot in alternatives[:6]
                )
                return (
                    f"I could not move {display_name} to {target_date}; no free slot can fit {hours:g}h.\n"
                    f"Available slots:\n{available}"
                )
            return f"I could not move {display_name} to {target_date}; your calendar looks full that day."

        if _delete_event_quietly(row.get("calendar_event_id")):
            deleted_events += 1

        start_time = target_slot["start_time"]
        end_time = target_slot["end_time"]
        if target_slot["changed_time"]:
            conflict_notes.append(
                f"{display_name} could not stay at {original_start_time} on {target_date}, "
                f"so I moved it to {start_time}-{end_time}."
            )

        try:
            created_event = create_calendar_event_details(display_name, target_date, start_time, hours)
            calendar_event_id = created_event.get("id")
            calendar_link = created_event.get("htmlLink")
        except Exception:
            pass

        values = {
            "scheduled_date": target_date,
            "start_time": start_time,
            "end_time": end_time,
            "status": "postponed",
            "calendar_event_id": calendar_event_id,
            "calendar_link": calendar_link
        }
        try:
            _update("schedule", values, "id", row["id"])
        except Exception as exc:
            return f"Could not update postponed schedule: {exc}"

        moved.append(
            f"{target_date} {start_time}-{end_time} | {display_name} ({hours:g}h)"
        )

    event_note = f" Deleted {deleted_events} old calendar event(s)." if deleted_events else ""
    note = ("\n" + "\n".join(conflict_notes)) if conflict_notes else ""
    return (
        f"Postponed {len(moved)} {task_name} session(s) from {source_date} to {target_date}."
        f"{event_note}\n" + "\n".join(moved) + note
    )


def prepone_schedule(
    task_name: str,
    from_date: str = None,
    to_date: str = None,
    user_id=DEFAULT_USER_ID
):
    """Move matching scheduled sessions to an earlier day without replanning unrelated tasks."""
    source_date = from_date or (_today() + timedelta(days=1)).isoformat()
    target_date = to_date or _today().isoformat()
    result = postpone_schedule(
        task_name=task_name,
        from_date=source_date,
        to_date=target_date,
        user_id=user_id
    )
    if result.startswith("Postponed"):
        return result.replace("Postponed", "Preponed", 1)
    return result


def cancel_schedule(task_name: str, schedule_date: str = None, user_id=DEFAULT_USER_ID):
    """Cancel matching incomplete sessions on a date."""
    target_date = schedule_date or _today().isoformat()
    wanted = normalize_task_name(task_name)
    rows = _select("schedule", "*", user_id)
    cancelled = []
    for row in rows:
        if row.get("scheduled_date") != target_date or row.get("completed"):
            continue
        task = _task_by_id(row.get("task_id"), user_id)
        display_name = task.get("task_name") if task else row.get("task_name", "")
        if wanted and wanted not in normalize_task_name(display_name):
            continue
        _delete_event_quietly(row.get("calendar_event_id"))
        _update("schedule", {"completed": True, "status": "cancelled"}, "id", row["id"])
        cancelled.append(display_name or task_name)
    if not cancelled:
        return f"No {task_name} session found on {target_date}."
    return f"Cancelled {len(cancelled)} {task_name} session(s) on {target_date}."


def resize_schedule(task_name: str, hours: float, schedule_date: str = None, user_id=DEFAULT_USER_ID):
    """Change today's matching session duration and update its calendar event."""
    target_date = schedule_date or _today().isoformat()
    wanted = normalize_task_name(task_name)
    rows = _select("schedule", "*", user_id)
    for row in rows:
        if row.get("scheduled_date") != target_date or row.get("completed"):
            continue
        task = _task_by_id(row.get("task_id"), user_id)
        display_name = task.get("task_name") if task else row.get("task_name", "")
        if wanted and wanted not in normalize_task_name(display_name):
            continue
        start_time = row.get("start_time") or "09:00"
        start_dt = datetime.strptime(f"{target_date} {start_time}", "%Y-%m-%d %H:%M")
        end_time = (start_dt + timedelta(hours=float(hours))).strftime("%H:%M")
        _delete_event_quietly(row.get("calendar_event_id"))
        event_id = link = None
        try:
            event = create_calendar_event_details(display_name or task_name, target_date, start_time, float(hours))
            event_id = event.get("id")
            link = event.get("htmlLink")
        except Exception:
            pass
        _update("schedule", {
            "hours_planned": float(hours),
            "end_time": end_time,
            "calendar_event_id": event_id,
            "calendar_link": link,
            "status": "resized"
        }, "id", row["id"])
        return f"Changed {display_name or task_name} on {target_date} to {float(hours):g}h ({start_time}-{end_time})."
    return f"No {task_name} session found on {target_date}."


def reschedule_schedule(
    task_name: str,
    new_start_time: str,
    schedule_date: str = None,
    source_start_time: str = None,
    user_id=DEFAULT_USER_ID
):
    """Move a matching session to an exact time on the same date."""
    target_date = schedule_date or _today().isoformat()
    wanted = normalize_task_name(task_name)
    rows = _select("schedule", "*", user_id)
    matches = []

    for row in rows:
        if row.get("scheduled_date") != target_date or row.get("completed"):
            continue
        task = _task_by_id(row.get("task_id"), user_id)
        display_name = task.get("task_name") if task else row.get("task_name", "")
        if wanted and wanted not in normalize_task_name(display_name):
            continue
        if source_start_time and row.get("start_time") != source_start_time:
            continue
        matches.append((row, task, display_name or task_name))

    if not matches:
        source_note = f" at {source_start_time}" if source_start_time else ""
        return f"No {task_name} session found on {target_date}{source_note}."

    if len(matches) > 1 and not source_start_time:
        options = "\n".join(
            f"- {row.get('start_time', '09:00')}-{row.get('end_time', '')} | {display_name}"
            for row, _task, display_name in matches[:6]
        )
        return (
            f"I found multiple {task_name} sessions on {target_date}. "
            f"Please include the original start time.\n{options}"
        )

    row, _task, display_name = matches[0]
    hours = float(row.get("hours_planned") or 1)
    new_start_dt = datetime.strptime(f"{target_date} {new_start_time}", "%Y-%m-%d %H:%M")
    new_end_dt = new_start_dt + timedelta(hours=hours)
    new_end_time = new_end_dt.strftime("%H:%M")

    conflicts = _schedule_conflicts(
        rows,
        target_date,
        new_start_dt,
        new_end_dt,
        exclude_id=row.get("id"),
        user_id=user_id
    )
    if conflicts:
        conflict_lines = "\n".join(
            f"- {conflict['start_time']}-{conflict['end_time']} | {conflict['task_name']}"
            for conflict in conflicts[:5]
        )
        return (
            f"I could not move {display_name} to {new_start_time}-{new_end_time} on {target_date} "
            f"because it overlaps another scheduled task:\n{conflict_lines}"
        )

    target_slot = _find_target_slot(target_date, new_start_time, hours)
    if target_slot.get("changed_time"):
        alternatives = target_slot.get("alternatives") or []
        available = "\n".join(
            f"{slot['start_time']}-{slot['end_time']} ({slot['hours']}h)"
            for slot in alternatives[:6]
        )
        suffix = f"\nAvailable slots:\n{available}" if available else ""
        return (
            f"I could not move {display_name} to {new_start_time}-{new_end_time} on {target_date}; "
            f"that time is busy on your calendar.{suffix}"
        )

    old_start_time = row.get("start_time") or "09:00"
    old_end_time = row.get("end_time") or ""
    _delete_event_quietly(row.get("calendar_event_id"))

    calendar_event_id = None
    calendar_link = None
    try:
        created_event = create_calendar_event_details(display_name, target_date, new_start_time, hours)
        calendar_event_id = created_event.get("id")
        calendar_link = created_event.get("htmlLink")
    except Exception:
        pass

    values = {
        "start_time": new_start_time,
        "end_time": new_end_time,
        "status": "rescheduled",
        "calendar_event_id": calendar_event_id,
        "calendar_link": calendar_link
    }
    try:
        _update("schedule", values, "id", row["id"])
    except Exception as exc:
        return f"Could not update rescheduled session: {exc}"

    calendar_note = " Calendar event updated." if calendar_event_id else " Calendar event could not be recreated, but the app schedule was updated."
    return (
        f"Moved {display_name} on {target_date} from {old_start_time}-{old_end_time} "
        f"to {new_start_time}-{new_end_time}.{calendar_note}"
    )


def _schedule_conflicts(rows, target_date, start_datetime, end_datetime, exclude_id=None, user_id=DEFAULT_USER_ID):
    conflicts = []
    for row in rows:
        if row.get("scheduled_date") != target_date or row.get("completed"):
            continue
        if exclude_id is not None and str(row.get("id")) == str(exclude_id):
            continue
        if user_id and str(row.get("user_id", user_id)) != str(user_id):
            continue
        row_start_time = row.get("start_time")
        if not row_start_time:
            continue
        try:
            row_start = datetime.strptime(f"{target_date} {row_start_time}", "%Y-%m-%d %H:%M")
            if row.get("end_time"):
                row_end = datetime.strptime(f"{target_date} {row['end_time']}", "%Y-%m-%d %H:%M")
            else:
                row_end = row_start + timedelta(hours=float(row.get("hours_planned") or 1))
        except (TypeError, ValueError):
            continue
        if row_start < end_datetime and start_datetime < row_end:
            task = _task_by_id(row.get("task_id"), user_id)
            conflicts.append({
                "start_time": row_start.strftime("%H:%M"),
                "end_time": row_end.strftime("%H:%M"),
                "task_name": task.get("task_name") if task else row.get("task_name", "Scheduled task"),
            })
    return sorted(conflicts, key=lambda conflict: conflict["start_time"])


def swap_schedule(first_task: str, second_task: str, schedule_date: str = None, user_id=DEFAULT_USER_ID):
    """Swap times for two task sessions on the same date."""
    target_date = schedule_date or _today().isoformat()
    first = normalize_task_name(first_task)
    second = normalize_task_name(second_task)
    rows = [row for row in _select("schedule", "*", user_id) if row.get("scheduled_date") == target_date and not row.get("completed")]
    first_row = second_row = None
    for row in rows:
        task = _task_by_id(row.get("task_id"), user_id)
        name = normalize_task_name(task.get("task_name") if task else row.get("task_name", ""))
        if first in name:
            first_row = row
        if second in name:
            second_row = row
    if not first_row or not second_row:
        return f"I could not find both {first_task} and {second_task} on {target_date}."
    first_times = {"start_time": first_row.get("start_time"), "end_time": first_row.get("end_time")}
    second_times = {"start_time": second_row.get("start_time"), "end_time": second_row.get("end_time")}
    _update("schedule", {**second_times, "status": "swapped"}, "id", first_row["id"])
    _update("schedule", {**first_times, "status": "swapped"}, "id", second_row["id"])
    return f"Swapped {first_task} and {second_task} on {target_date}. Run /schedule if you want calendar events regenerated."


def cleanup_duplicates(user_id=DEFAULT_USER_ID):
    """Mark duplicate pending tasks cancelled and cancel their future schedule events."""
    tasks = _pending_tasks(user_id)
    seen = {}
    removed = 0
    for task in tasks:
        key = (
            normalize_task_name(task.get("task_name", "")),
            str(task.get("deadline")),
            float(task.get("effort_hours") or 0),
        )
        if key not in seen:
            seen[key] = task
            continue
        _cancel_future_schedule(user_id, task_id=task.get("id"))
        _update("tasks", {"status": "cancelled"}, "id", task["id"])
        removed += 1
    return f"Cleanup complete. Cancelled {removed} duplicate pending task(s)."


def extend_task_deadline(
    task_name: str = "",
    new_deadline: str = "",
    extra_days: int = None,
    user_id=DEFAULT_USER_ID
):
    """Extend a task deadline, using the latest pending extension request when task is omitted."""
    request = _latest_extension_request(user_id)
    tasks = _pending_tasks(user_id)

    if task_name:
        matches = [task for task in tasks if task_name.lower() in task["task_name"].lower()]
    elif request:
        matches = [task for task in tasks if str(task.get("id")) == str(request.get("task_id"))]
    else:
        matches = []

    if not matches:
        return "I could not find a pending task to extend."

    task = matches[0]
    current_deadline = datetime.fromisoformat(task["deadline"]).date()

    if new_deadline:
        target_deadline = datetime.fromisoformat(new_deadline).date()
    elif extra_days is not None:
        target_deadline = current_deadline + timedelta(days=int(extra_days))
    elif request and request.get("suggested_deadline"):
        target_deadline = datetime.fromisoformat(request["suggested_deadline"]).date()
    else:
        return f"What new deadline should I use for {task['task_name']}?"

    try:
        _update("tasks", {"deadline": target_deadline.isoformat()}, "id", task["id"])
    except Exception as exc:
        return f"Could not update deadline: {exc}"

    if request:
        try:
            _update("deadline_extension_requests", {"status": "resolved"}, "id", request["id"])
        except Exception:
            pass

    schedule_result = spread_daily_schedule(days_ahead=14, user_id=user_id, create_calendar_events=True)
    return (
        f"Updated {task['task_name']} deadline from {current_deadline.isoformat()} "
        f"to {target_deadline.isoformat()}.\n{schedule_result}"
    )


def pending_deadline_extension(user_id=DEFAULT_USER_ID):
    """Show the latest pending deadline extension question."""
    request = _latest_extension_request(user_id)
    if not request:
        return "No pending deadline extension question."
    return (
        f"{request.get('task_name')} has {request.get('backlog_hours')}h backlog beyond "
        f"{request.get('current_deadline')}. Suggested new deadline: "
        f"{request.get('suggested_deadline')}."
    )


def remember_conversation(user_message: str, assistant_response: str = "", user_id=DEFAULT_USER_ID):
    """Store a compact conversation memory."""
    payload = {
        "user_id": str(user_id),
        "message": user_message,
        "assistant_response": assistant_response,
        "created_at": datetime.utcnow().isoformat()
    }
    try:
        _insert("conversation_memory", payload)
        return "Conversation memory saved."
    except Exception:
        return "Conversation memory table is not available yet."


def recall_conversation_memory(limit=5, user_id=DEFAULT_USER_ID):
    """Recall recent conversation memory for personalization."""
    try:
        rows = _select("conversation_memory", "*", user_id)
    except Exception:
        return "No conversation memory available yet."

    rows = sorted(rows, key=lambda row: row.get("created_at", ""), reverse=True)[:int(limit)]
    if not rows:
        return "No conversation memory available yet."

    return "\n".join(
        f"{row.get('created_at', '')}: user said '{row.get('message', '')}'"
        for row in rows
    )
