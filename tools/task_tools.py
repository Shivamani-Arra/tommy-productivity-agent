from database.superbase_client import supabase
from datetime import datetime
from tools.google_calendar_tools import delete_calendar_event

STUDY_VERBS = {
    "study", "studying", "learn", "learning", "read", "reading",
    "revise", "revising", "practice", "practicing", "prepare", "preparing"
}


def normalize_task_name(task_name: str):
    """Normalize equivalent task phrasings for duplicate checks."""
    words = re_words(task_name)
    words = [word for word in words if word not in STUDY_VERBS]
    return " ".join(words)


def re_words(value: str):
    import re
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", str(value).lower())
    return [word for word in cleaned.split() if word]


def add_task(task_name: str, deadline: str, 
             effort_hours: float, priority: str = "medium", user_id: str = "default"):
    """Add a new task to database"""
    task_name = normalize_task_name(task_name) or task_name
    existing = _find_exact_pending_task(task_name, deadline, effort_hours, user_id)
    if existing:
        return (
            f"Task '{task_name}' already exists with deadline {deadline} "
            f"and {float(effort_hours)} effort hours"
        )

    payload = {
        "task_name": task_name,
        "deadline": deadline,
        "effort_hours": effort_hours,
        "priority": priority or "medium",
        "user_id": str(user_id),
        "status": "pending"
    }
    try:
        result = supabase.table("tasks").insert(payload).execute()
    except Exception:
        payload.pop("user_id", None)
        result = supabase.table("tasks").insert(payload).execute()
    
    return f"Task '{task_name}' added successfully with deadline {deadline}"


def _find_exact_pending_task(task_name: str, deadline: str, effort_hours: float, user_id: str = "default"):
    normalized_name = normalize_task_name(task_name)
    query = supabase.table("tasks")\
        .select("*")\
        .eq("status", "pending")\
        .eq("deadline", deadline)
    if user_id:
        query = query.eq("user_id", str(user_id))

    try:
        rows = query.execute().data or []
    except Exception:
        rows = supabase.table("tasks")\
            .select("*")\
            .eq("status", "pending")\
            .eq("deadline", deadline)\
            .execute().data or []

    for row in rows:
        row_name = normalize_task_name(str(row.get("task_name", "")))
        try:
            row_effort = float(row.get("effort_hours"))
        except (TypeError, ValueError):
            row_effort = None

        if row_name == normalized_name and row_effort == float(effort_hours):
            return row

    return None

def get_all_tasks(user_id: str = "default"):
    """Get all pending tasks"""
    query = supabase.table("tasks")\
        .select("*")\
        .eq("status", "pending")
    if user_id:
        query = query.eq("user_id", str(user_id))
    try:
        result = query.execute()
    except Exception:
        result = supabase.table("tasks")\
            .select("*")\
            .eq("status", "pending")\
            .execute()
    
    if not result.data:
        return "No pending tasks found"
    
    tasks_summary = []
    today = datetime.today().date()
    for task in result.data:
        deadline = datetime.fromisoformat(task['deadline']).date()
        days_left = (deadline - today).days
        tasks_summary.append(
            f"- {task['task_name']} | "
            f"Deadline: {task['deadline']} | "
            f"Days left: {days_left} | "
            f"Effort: {task['effort_hours']} hours | "
            f"Priority: {task['priority']}"
        )
    
    return "\n".join(tasks_summary)

def mark_task_complete(task_name: str, user_id: str = "default"):
    """Mark a task as completed"""
    matched_tasks = _find_pending_tasks(task_name, user_id)
    deleted_events = _delete_future_calendar_events(matched_tasks, user_id)

    query = supabase.table("tasks")\
        .update({"status": "completed"})\
        .ilike("task_name", f"%{task_name}%")
    if user_id:
        query = query.eq("user_id", str(user_id))
    try:
        result = query.execute()
    except Exception:
        result = supabase.table("tasks")\
            .update({"status": "completed"})\
            .ilike("task_name", f"%{task_name}%")\
            .execute()
    
    suffix = f" Deleted {deleted_events} future calendar event(s)." if deleted_events else ""
    return f"Task '{task_name}' marked as complete.{suffix}"


def mark_all_tasks_complete(user_id: str = "default"):
    """Mark every pending task complete and cancel future scheduled calendar sessions."""
    query = supabase.table("tasks").select("*").eq("status", "pending")
    if user_id:
        query = query.eq("user_id", str(user_id))
    try:
        tasks = query.execute().data or []
    except Exception:
        tasks = supabase.table("tasks").select("*").eq("status", "pending").execute().data or []

    if not tasks:
        return "No pending tasks found."

    deleted_events = _delete_future_calendar_events(tasks, user_id)
    task_ids = [str(task.get("id")) for task in tasks if task.get("id")]

    updated = 0
    for task in tasks:
        try:
            query = supabase.table("tasks").update({"status": "completed"}).eq("id", task["id"])
            if user_id:
                query = query.eq("user_id", str(user_id))
            query.execute()
            updated += 1
        except Exception:
            pass

    suffix = f" Deleted {deleted_events} future calendar event(s)." if deleted_events else ""
    return f"Marked {updated} pending task(s) as complete.{suffix}"


def save_task_calendar_event(task_name: str, deadline: str, event_id: str, user_id: str = "default"):
    """Store the deadline calendar event ID on the matching task."""
    if not event_id:
        return "No calendar event ID to save."

    query = supabase.table("tasks")\
        .update({"calendar_event_id": event_id})\
        .ilike("task_name", f"%{task_name}%")\
        .eq("deadline", deadline)
    if user_id:
        query = query.eq("user_id", str(user_id))

    try:
        query.execute()
    except Exception:
        return "Calendar event ID could not be saved. Add tasks.calendar_event_id in Supabase."

    return f"Saved calendar event ID for '{task_name}'."


def _find_pending_tasks(task_name: str, user_id: str = "default"):
    query = supabase.table("tasks")\
        .select("*")\
        .eq("status", "pending")\
        .ilike("task_name", f"%{task_name}%")
    if user_id:
        query = query.eq("user_id", str(user_id))

    try:
        result = query.execute()
    except Exception:
        result = supabase.table("tasks")\
            .select("*")\
            .eq("status", "pending")\
            .ilike("task_name", f"%{task_name}%")\
            .execute()

    return result.data or []


def _delete_future_calendar_events(tasks, user_id: str = "default"):
    deleted = 0
    task_ids = [str(task.get("id")) for task in tasks if task.get("id")]

    for task in tasks:
        event_id = task.get("calendar_event_id")
        if event_id and _try_delete_event(event_id):
            deleted += 1

    for task_id in task_ids:
        query = supabase.table("schedule")\
            .select("*")\
            .eq("task_id", task_id)\
            .eq("completed", False)
        if user_id:
            query = query.eq("user_id", str(user_id))

        try:
            rows = query.execute().data or []
        except Exception:
            rows = supabase.table("schedule")\
                .select("*")\
                .eq("task_id", task_id)\
                .eq("completed", False)\
                .execute().data or []

        for row in rows:
            event_id = row.get("calendar_event_id")
            if event_id and _try_delete_event(event_id):
                deleted += 1
            try:
                supabase.table("schedule")\
                    .update({"completed": True, "status": "cancelled"})\
                    .eq("id", row["id"])\
                    .execute()
            except Exception:
                pass

    return deleted


def _try_delete_event(event_id: str):
    try:
        delete_calendar_event(event_id)
        return True
    except Exception:
        return False
