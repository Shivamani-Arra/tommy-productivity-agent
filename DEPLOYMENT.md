# Deployment

The bot's reminders run only while `bot.py` is alive. For production, run it under a process manager.

## Render Free Web Service

Render free web services can host the admin dashboard and Telegram webhook from `admin_dashboard.py`.

Use this setup:

```text
Build command: pip install -r requirements.txt
Start command: python admin_dashboard.py
Health check path: /health
```

Environment variables:

```text
SUPABASE_URL
SUPABASE_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
GOOGLE_TOKEN_JSON
GEMINI_API_KEY
GEMINI_MODEL=gemini-2.5-flash
ENABLE_BACKGROUND_SCHEDULER=true
CRON_SECRET
HOST=0.0.0.0
```

`GOOGLE_TOKEN_JSON` should be the full contents of local `token.json` pasted as one environment variable. Do not commit `token.json`.

`GEMINI_API_KEY` is used by the cloud AI fallback. Without it, the deployed app still handles known productivity patterns, but unknown messages cannot use LLM reasoning.

The reminder scheduler runs at 8 AM, 12 PM, and 8 PM Asia/Kolkata while the service is awake. On Render free tier, use `/jobs/morning`, `/jobs/deadline`, and `/jobs/evening` with `CRON_SECRET` from an external cron service for reliable wakeups.

After Render gives you a URL, connect Telegram to the webhook:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://YOUR-RENDER-APP.onrender.com/telegram
```

Then test in Telegram:

```text
/start
I need to study math for 5 hours before Sunday
```

The public dashboard URL will be:

```text
https://YOUR-RENDER-APP.onrender.com/
```

Note: Render free web services may sleep after inactivity. The first request after sleep can be slow. For daily reminders that must run at exact times, keep using the Windows Task Scheduler option or use a paid always-on worker.

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
