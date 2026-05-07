# Tommy Productivity Agent

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

Tommy is a Telegram-based AI productivity assistant that turns natural messages into tasks, calendar sessions, progress tracking, reminders, and schedule changes.

It is designed for simple, everyday language:

```text
I need to study math for 5 hours before Sunday
I studied math for 1 hour
I have a meeting at 1 am on 8th of May
Postpone today's science schedule to tomorrow
Prepone tomorrow's math schedule to today
```

## What It Does

- Adds tasks from natural language.
- Splits work across available days before the deadline.
- Creates Google Calendar work sessions.
- Adds fixed calendar events such as meetings, calls, appointments, and classes.
- Tracks partial progress.
- Replans future sessions after progress or missed work.
- Marks tasks complete and cancels future calendar sessions.
- Scores deadline risk.
- Detects backlog and asks whether to extend deadlines.
- Supports targeted postpone and prepone commands.
- Checks calendar conflicts when moving sessions.
- Supports pending follow-ups, such as asking for a missing meeting time.
- Stores per-user data using Telegram chat IDs.
- Includes daily reminders and an optional local admin dashboard.

## Project Structure

```text
agent.py                  Main agent loop and tool execution
intent_parser.py          Deterministic natural-language intent parser
bot.py                    Telegram bot entrypoint
scheduler.py              Daily reminders and background jobs
admin_dashboard.py        Optional local dashboard
supabase_schema.sql       Supabase schema upgrades
tools/
  google_calendar_tools.py
  productivity_tools.py
  task_tools.py
  telegram_tools.py
database/
  superbase_client.py
```

## Setup

1. Install dependencies:

```powershell
pip install -r requirements.txt
```

2. Create `.env` from `.env.example`:

```powershell
copy .env.example .env
```

Fill in:

```text
SUPABASE_URL
SUPABASE_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

3. Add Google OAuth credentials:

Put `credentials.json` in the project root.

4. Generate Google Calendar token:

```powershell
python auth.py
```

This creates `token.json`.

5. Run the Supabase schema:

Open Supabase SQL Editor and run:

```text
supabase_schema.sql
```

## Running The Bot

```powershell
python bot.py
```

The Telegram bot and background scheduler start together.

## Optional Admin Dashboard

```powershell
python admin_dashboard.py
```

Open:

```text
http://127.0.0.1:8080
```

The dashboard shows recent tasks, schedule rows, progress, follow-ups, preferences, and a cleanup link.

## Commands And Examples

Tasks:

```text
I need to study math for 5 hours before Sunday
Complete 5 hours of math study before Sunday
Before Sunday study 5 hours for math
```

Progress:

```text
I studied math for 1 hour
I worked on science for 30 minutes
```

Completion:

```text
I finished math
I completed science
```

Meetings and fixed events:

```text
I have a meeting at 1 am on 8th of May
Call with Rahul tomorrow at 3 pm
```

Schedule movement:

```text
Postpone today's science schedule to tomorrow
Prepone tomorrow's math schedule to today
Cancel today science
Make math 30 minutes today
Swap math and science
```

Bot commands:

```text
/tasks
/schedule
/replan
/risk
/cleanup
```

## Reliable Background Jobs

The scheduler runs only while `bot.py` is running. For daily reminders to be reliable, run the bot using Windows Task Scheduler, a process manager, or a hosted worker.

See:

```text
DEPLOYMENT.md
```

## Testing

Parser tests:

```powershell
python tests_intent_parser.py
```

Additional tests:

```powershell
python tests_calendar_conflicts.py
python tests_reschedule_schedule.py
python tests_schedule_task_session.py
```

## Security Notes

Do not commit:

```text
.env
credentials.json
token.json
```

These files are ignored by `.gitignore`.

## Current Limitations

- Daily reminders require the bot process to be running.
- Google Calendar cleanup works best for events created after calendar event ID tracking was added.
- The admin dashboard is local and intentionally simple.
- Hosted deployment is recommended for production reliability.
