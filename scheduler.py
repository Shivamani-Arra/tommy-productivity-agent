from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import date, datetime, timedelta
from database.superbase_client import supabase
from tools.telegram_tools import send_telegram_message
from agent import run_agent
from tools.productivity_tools import replan_missed_work, score_deadline_risk, spread_daily_schedule
import logging

# Set up logging so you can see what the scheduler is doing
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────

def get_todays_schedule():
    """Get all sessions scheduled for today"""
    today = date.today().isoformat()
    
    query = supabase.table("schedule")\
        .select("*, tasks(task_name, deadline)")\
        .eq("scheduled_date", today)\
        .eq("completed", False)
    try:
        result = query.execute()
    except Exception:
        result = supabase.table("schedule")\
            .select("*")\
            .eq("scheduled_date", today)\
            .eq("completed", False)\
            .execute()
    
    return result.data or []

def get_missed_sessions():
    """Get sessions from yesterday that were not completed"""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    
    query = supabase.table("schedule")\
        .select("*, tasks(task_name, deadline)")\
        .eq("scheduled_date", yesterday)\
        .eq("completed", False)
    try:
        result = query.execute()
    except Exception:
        result = supabase.table("schedule")\
            .select("*")\
            .eq("scheduled_date", yesterday)\
            .eq("completed", False)\
            .execute()
    
    return result.data or []

def get_urgent_tasks():
    """Get tasks with deadlines within next 3 days"""
    today = date.today()
    three_days_later = (today + timedelta(days=3)).isoformat()
    
    result = supabase.table("tasks")\
        .select("*")\
        .eq("status", "pending")\
        .lte("deadline", three_days_later)\
        .execute()
    
    return result.data or []

def get_all_pending_tasks():
    """Get all pending tasks"""
    result = supabase.table("tasks")\
        .select("*")\
        .eq("status", "pending")\
        .order("deadline")\
        .execute()
    
    return result.data or []

def daily_schedule_spreading():
    """
    Runs every morning before the briefing.
    Spreads pending task work across available calendar slots.
    """
    log.info("Spreading daily schedule...")
    result = spread_daily_schedule(days_ahead=7, create_calendar_events=True)
    log.info(result)

def missed_work_replanning():
    """
    Runs daily to move missed sessions back into the upcoming plan.
    """
    log.info("Replanning missed work...")
    result = replan_missed_work()
    log.info(result)

# ─────────────────────────────────────────
# SCHEDULED JOBS
# ─────────────────────────────────────────

def morning_briefing():
    """
    Runs every morning at 8:00 AM
    Sends a full daily briefing to the user
    """
    log.info("Running morning briefing...")
    
    today = date.today().strftime("%B %d, %Y")
    todays_sessions = get_todays_schedule()
    missed_sessions = get_missed_sessions()
    urgent_tasks = get_urgent_tasks()
    risk_summary = score_deadline_risk()
    
    # Build context for the agent
    context = f"""
    Good morning! Today is {today}.
    
    Today's scheduled sessions: 
    {todays_sessions if todays_sessions else 'Nothing scheduled yet'}
    
    Missed sessions from yesterday: 
    {missed_sessions if missed_sessions else 'None - great job!'}
    
    Tasks with deadlines in next 3 days: 
    {urgent_tasks if urgent_tasks else 'None urgent'}

    Deadline risk:
    {risk_summary}
    
    Please:
    1. Write a warm and motivating morning briefing
    2. List today's sessions clearly
    3. Warn about any urgent deadlines
    4. If there are missed sessions, mention they need replanning
    5. Send this briefing via Telegram to the user
    Keep it concise and encouraging.
    """
    
    try:
        response = run_agent(context)
        log.info("Morning briefing sent successfully")
    except Exception as e:
        # If agent fails, send a simple fallback message
        log.error(f"Agent failed: {e}")
        fallback = build_fallback_briefing(
            today, 
            todays_sessions, 
            missed_sessions, 
            urgent_tasks
        )
        send_telegram_message(fallback)

def evening_checkin():
    """
    Runs every evening at 8:00 PM
    Asks user to update their progress
    """
    log.info("Running evening check-in...")
    
    todays_sessions = get_todays_schedule()
    
    if not todays_sessions:
        send_telegram_message(
            "🌙 *Evening Check-in*\n\n"
            "No sessions were scheduled today.\n"
            "Reply with any tasks you worked on today!"
        )
        return
    
    # Build task list for check-in message
    task_list = []
    for session in todays_sessions:
        task_name = session.get('tasks', {}).get('task_name', 'Unknown')
        hours = session.get('hours_planned', 0)
        task_list.append(f"• {task_name} ({hours} hrs)")
    
    task_text = "\n".join(task_list)
    
    message = (
        f"🌙 *Evening Check-in*\n\n"
        f"Today's sessions:\n{task_text}\n\n"
        f"Reply with what you completed today.\n"
        f"Example: *'Completed DP study'* or *'Skipped ML project'*"
    )
    
    send_telegram_message(message)
    log.info("Evening check-in sent")

def deadline_warning():
    """
    Runs every day at 12:00 PM (noon)
    Sends warnings for approaching deadlines
    """
    log.info("Checking for deadline warnings...")
    
    urgent_tasks = get_urgent_tasks()
    
    if not urgent_tasks:
        log.info("No urgent deadlines today")
        return
    
    today = date.today()
    warnings = []
    
    for task in urgent_tasks:
        deadline = date.fromisoformat(task['deadline'])
        days_left = (deadline - today).days
        
        if days_left == 0:
            emoji = "🚨"
            urgency = "DUE TODAY"
        elif days_left == 1:
            emoji = "⚠️"
            urgency = "due TOMORROW"
        else:
            emoji = "📅"
            urgency = f"due in {days_left} days"
        
        warnings.append(
            f"{emoji} *{task['task_name']}* — {urgency}\n"
            f"   Effort remaining: {task['effort_hours']} hours"
        )
    
    if warnings:
        warning_text = "\n\n".join(warnings)
        message = f"⏰ *Deadline Alert*\n\n{warning_text}"
        send_telegram_message(message)
        log.info(f"Sent warnings for {len(warnings)} tasks")

def weekly_summary():
    """
    Runs every Sunday at 7:00 PM
    Sends a weekly progress summary
    """
    log.info("Running weekly summary...")
    
    # Get all tasks
    all_tasks = get_all_pending_tasks()
    
    # Get completed tasks this week
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    
    completed = supabase.table("tasks")\
        .select("*")\
        .eq("status", "completed")\
        .gte("created_at", week_ago)\
        .execute()
    
    completed_tasks = completed.data or []
    
    context = f"""
    It's Sunday evening. Please create a weekly summary for the user.
    
    Pending tasks: {all_tasks}
    Completed this week: {completed_tasks}
    
    Please:
    1. Celebrate what was completed this week
    2. Summarise what's still pending
    3. Highlight the most important tasks for next week
    4. Give one motivating thought for the week ahead
    5. Send this via Telegram
    Keep it warm, honest, and motivating.
    """
    
    try:
        run_agent(context)
        log.info("Weekly summary sent")
    except Exception as e:
        log.error(f"Weekly summary failed: {e}")
        send_telegram_message(
            f"📊 *Weekly Summary*\n\n"
            f"Completed this week: {len(completed_tasks)} tasks\n"
            f"Still pending: {len(all_tasks)} tasks\n\n"
            f"Keep going! 💪"
        )

# ─────────────────────────────────────────
# FALLBACK MESSAGE BUILDER
# ─────────────────────────────────────────

def build_fallback_briefing(today, sessions, missed, urgent):
    """
    If the AI agent fails, send a simple
    text-based briefing instead
    """
    lines = [f"🌅 *Good Morning!*\n📅 {today}\n"]
    
    if sessions:
        lines.append("*Today's Sessions:*")
        for s in sessions:
            task = s.get('tasks', {}).get('task_name', 'Task')
            hours = s.get('hours_planned', 0)
            lines.append(f"• {task} — {hours} hrs")
    else:
        lines.append("No sessions scheduled today.")
    
    if missed:
        lines.append("\n⚠️ *Missed Yesterday:*")
        for m in missed:
            task = m.get('tasks', {}).get('task_name', 'Task')
            lines.append(f"• {task} — needs replanning")
    
    if urgent:
        lines.append("\n🚨 *Urgent Deadlines:*")
        for u in urgent:
            lines.append(
                f"• {u['task_name']} — "
                f"due {u['deadline']}"
            )
    
    lines.append("\nYou've got this! 💪")
    return "\n".join(lines)

# ─────────────────────────────────────────
# SCHEDULER SETUP
# ─────────────────────────────────────────

def start_scheduler():
    """
    Start the scheduler with all jobs
    This runs continuously in the background
    """
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    scheduler.add_job(
        missed_work_replanning,
        trigger='cron',
        hour=7,
        minute=30,
        id='missed_work_replanning',
        name='Missed Work Replanning'
    )

    scheduler.add_job(
        daily_schedule_spreading,
        trigger='cron',
        hour=7,
        minute=45,
        id='daily_schedule_spreading',
        name='Daily Schedule Spreading'
    )
    
    # Morning briefing — every day at 8:00 AM
    scheduler.add_job(
        morning_briefing,
        trigger='cron',
        hour=8,
        minute=0,
        id='morning_briefing',
        name='Morning Briefing'
    )
    
    # Deadline warning — every day at 12:00 PM
    scheduler.add_job(
        deadline_warning,
        trigger='cron',
        hour=12,
        minute=0,
        id='deadline_warning',
        name='Deadline Warning'
    )
    
    # Evening check-in — every day at 8:00 PM
    scheduler.add_job(
        evening_checkin,
        trigger='cron',
        hour=20,
        minute=0,
        id='evening_checkin',
        name='Evening Check-in'
    )
    
    # Weekly summary — every Sunday at 7:00 PM
    scheduler.add_job(
        weekly_summary,
        trigger='cron',
        day_of_week='sun',
        hour=19,
        minute=0,
        id='weekly_summary',
        name='Weekly Summary'
    )
    
    log.info("Scheduler started with these jobs:")
    log.info("  7:30 AM - Missed work replanning")
    log.info("  7:45 AM - Daily schedule spreading")
    log.info("  8:00 AM — Morning Briefing")
    log.info("  12:00 PM — Deadline Warning")
    log.info("  8:00 PM — Evening Check-in")
    log.info("  Sunday 7PM — Weekly Summary")
    
    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Scheduler stopped")
        scheduler.shutdown()

def start_background_scheduler():
    """
    Use this when running scheduler
    alongside your FastAPI server
    """
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    scheduler.add_job(
        missed_work_replanning, 'cron',
        hour=7, minute=30
    )
    scheduler.add_job(
        daily_schedule_spreading, 'cron',
        hour=7, minute=45
    )
    
    scheduler.add_job(
        morning_briefing, 'cron',
        hour=8, minute=0
    )
    scheduler.add_job(
        deadline_warning, 'cron',
        hour=12, minute=0
    )
    scheduler.add_job(
        evening_checkin, 'cron',
        hour=20, minute=0
    )
    scheduler.add_job(
        weekly_summary, 'cron',
        day_of_week='sun', hour=19, minute=0
    )
    
    scheduler.start()
    log.info("Background scheduler started")
    return scheduler

# ─────────────────────────────────────────
# TEST FUNCTION
# ─────────────────────────────────────────

def test_all_jobs():
    """
    Run all jobs immediately to test them
    Call this before deploying to make sure
    everything works
    """
    print("Testing morning briefing...")
    morning_briefing()
    
    print("\nTesting deadline warning...")
    deadline_warning()
    
    print("\nTesting evening check-in...")
    evening_checkin()
    
    print("\nAll tests complete. Check your Telegram!")

# ─────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Run: python scheduler.py test
        test_all_jobs()
    else:
        # Run: python scheduler.py
        start_scheduler()
