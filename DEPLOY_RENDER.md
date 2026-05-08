# Deploy Tommy on Render

## What Render Will Run

Render runs:

```text
python admin_dashboard.py
```

This provides:

```text
/          Admin dashboard and browser demo
/chat      Browser demo message endpoint
/telegram  Telegram webhook endpoint
/health    Render health check
```

## Required Environment Variables

Set these in Render:

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

For `GOOGLE_TOKEN_JSON`, open local `token.json`, copy the full JSON content, and paste it into Render as the variable value.

For `GEMINI_API_KEY`, create a key in Google AI Studio and paste it into Render. This makes the deployed bot a cloud AI agent instead of relying on local Ollama.

`ENABLE_BACKGROUND_SCHEDULER=true` starts the 8 AM, 12 PM, and 8 PM reminder jobs inside the Render web service. Render free services may sleep, so for more reliable reminders create external cron pings to:

```text
https://YOUR-RENDER-APP.onrender.com/jobs/morning?key=CRON_SECRET
https://YOUR-RENDER-APP.onrender.com/jobs/deadline?key=CRON_SECRET
https://YOUR-RENDER-APP.onrender.com/jobs/evening?key=CRON_SECRET
```

## Render Settings

```text
Runtime: Python
Build Command: pip install -r requirements.txt
Start Command: python admin_dashboard.py
Health Check Path: /health
Plan: Free
```

The included `render.yaml` already contains the important defaults.

## Connect Telegram

After Render deploys, open this URL in your browser:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://YOUR-RENDER-APP.onrender.com/telegram
```

Replace:

```text
<TELEGRAM_BOT_TOKEN>
YOUR-RENDER-APP
```

Then message the bot in Telegram.

## Test Script

Try:

```text
I need to study math for 5 hours before Sunday
I studied math for 1 hour
Postpone today's math to tomorrow
What should I work on today?
```

## Important Limitation

Render free web services can sleep. This is fine for a recruiter demo, but exact daily reminders are more reliable on your PC with Windows Task Scheduler or on a paid always-on worker.
