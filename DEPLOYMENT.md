# Reliable Background Jobs

The bot's reminders run only while `bot.py` is alive. For production, run it under a process manager.

## Simple Windows Option

Use Task Scheduler:

1. Create a task named `Tommy Productivity Bot`.
2. Trigger: At log on.
3. Action:
   - Program: your Python executable.
   - Arguments: `bot.py`
   - Start in: `C:\Users\dell\OneDrive\Desktop\Personal Project\app`
4. Enable "Restart on failure" if available.

## Cloud Option

Deploy the app to a small VPS or service that supports long-running Python processes.

Run:

```powershell
python bot.py
```

Keep environment files and Google `token.json` on that machine.

## Admin Dashboard

Run:

```powershell
python admin_dashboard.py
```

Open:

```text
http://127.0.0.1:8080
```
