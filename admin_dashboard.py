from http.server import BaseHTTPRequestHandler, HTTPServer
import html
import json
import os
from urllib.parse import parse_qs, urlparse

import requests

from agent import run_agent
from database.superbase_client import supabase
from scheduler import deadline_warning, evening_checkin, morning_briefing, start_background_scheduler
from tools.productivity_tools import cleanup_duplicates


_scheduler = None


def _rows(table):
    try:
        return supabase.table(table).select("*").limit(50).execute().data or []
    except Exception as exc:
        return [{"error": str(exc)}]


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        user_id = params.get("user_id", ["default"])[0]

        if parsed.path == "/cleanup":
            body = cleanup_duplicates(user_id=user_id)
        elif parsed.path == "/health":
            body = "ok"
        elif parsed.path == "/jobs/morning":
            body = self._run_protected_job(parsed, morning_briefing, "morning briefing")
        elif parsed.path == "/jobs/deadline":
            body = self._run_protected_job(parsed, deadline_warning, "deadline warning")
        elif parsed.path == "/jobs/evening":
            body = self._run_protected_job(parsed, evening_checkin, "evening check-in")
        else:
            body = self._render(user_id, "")

        self._send_html(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length).decode("utf-8")

        if parsed.path == "/telegram":
            self._send_text(self._handle_telegram_webhook(data))
            return

        params = parse_qs(data)
        user_id = params.get("user_id", ["web-demo"])[0]
        message = params.get("message", [""])[0].strip()

        if parsed.path == "/chat" and message:
            try:
                response = run_agent(message, user_id=user_id)
            except Exception as exc:
                response = f"Error: {exc}"
            body = self._render(user_id, response, message)
        else:
            body = self._render(user_id, "Type a message first.")

        self._send_html(body)

    def _send_html(self, body):
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_text(self, body):
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _run_protected_job(self, parsed, job, label):
        secret = os.getenv("CRON_SECRET", "")
        params = parse_qs(parsed.query)
        if secret and params.get("key", [""])[0] != secret:
            return "unauthorized"
        try:
            job()
            return f"ran {label}"
        except Exception as exc:
            return f"failed {label}: {exc}"

    def _handle_telegram_webhook(self, data):
        try:
            update = json.loads(data or "{}")
            message = update.get("message") or update.get("edited_message") or {}
            text = (message.get("text") or "").strip()
            chat = message.get("chat") or {}
            chat_id = chat.get("id")

            if not text or not chat_id:
                return "ignored"

            response = _telegram_command_response(text, chat_id)
            if response is None:
                response = run_agent(text, user_id=str(chat_id))
            _send_telegram_reply(chat_id, response)
            return "ok"
        except Exception as exc:
            return f"error: {exc}"

    def _render(self, user_id, response, last_message=""):
        sections = []
        for table in ("tasks", "schedule", "daily_progress", "pending_followups", "user_preferences"):
            rows = _rows(table)
            sections.append(f"<h2>{html.escape(table)}</h2><pre>{html.escape(str(rows))}</pre>")
        safe_user_id = html.escape(user_id)
        safe_response = html.escape(response or "No message yet.")
        safe_last_message = html.escape(last_message)
        return f"""
        <html>
        <head>
            <title>Productivity Agent Admin</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 32px; max-width: 1100px; }}
                input, textarea {{ width: 100%; padding: 10px; margin: 6px 0 12px; box-sizing: border-box; }}
                button {{ padding: 10px 14px; cursor: pointer; }}
                pre {{ background: #f5f5f5; padding: 12px; overflow: auto; }}
                .chat {{ border: 1px solid #ddd; padding: 16px; margin-bottom: 24px; }}
                .reply {{ white-space: pre-wrap; background: #eef7ff; padding: 12px; }}
            </style>
        </head>
        <body>
            <h1>Productivity Agent Admin</h1>
            <p>User: {safe_user_id}</p>
            <div class="chat">
                <h2>Browser Demo Chat</h2>
                <form method="POST" action="/chat">
                    <label>User ID</label>
                    <input name="user_id" value="{safe_user_id}">
                    <label>Message</label>
                    <textarea name="message" rows="3" placeholder="I need to study math for 5 hours before Sunday">{safe_last_message}</textarea>
                    <button type="submit">Send to Tommy</button>
                </form>
                <h3>Reply</h3>
                <div class="reply">{safe_response}</div>
            </div>
            <p><a href="/cleanup?user_id={safe_user_id}">Cleanup duplicate tasks</a></p>
            {''.join(sections)}
        </body>
        </html>
        """


def _send_telegram_reply(chat_id, text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return

    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
        },
        timeout=15,
    )


def _start_scheduler_if_enabled():
    global _scheduler
    if _scheduler is not None:
        return
    enabled = os.getenv("ENABLE_BACKGROUND_SCHEDULER", "true").lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return
    _scheduler = start_background_scheduler()


def _telegram_command_response(text, chat_id):
    command = text.split()[0].lower()

    if command == "/start":
        return (
            "Hey! I'm Tommy, your productivity agent.\n\n"
            "Tell me things naturally:\n"
            "- I need to study math for 5 hours before Sunday\n"
            "- I studied math for 1 hour\n"
            "- Postpone today's science to tomorrow\n"
            "- What should I work on today?"
        )

    if command == "/help":
        return (
            "Commands:\n"
            "/tasks - show pending tasks\n"
            "/schedule - plan your day\n"
            "/replan - replan missed work\n"
            "/risk - check deadline risk\n"
            "/cleanup - merge duplicate tasks\n\n"
            "You can also just type naturally."
        )

    command_prompts = {
        "/tasks": "Show me all my pending tasks with deadlines",
        "/schedule": "Spread my pending work across my available calendar time",
        "/replan": "Replan my missed work",
        "/risk": "Am I on track for my deadlines? Score the deadline risk.",
        "/cleanup": "cleanup duplicates",
    }

    prompt = command_prompts.get(command)
    if prompt:
        return run_agent(prompt, user_id=str(chat_id))

    return None


if __name__ == "__main__":
    _start_scheduler_if_enabled()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer((host, port), DashboardHandler)
    print(f"Admin dashboard running at http://{host}:{port}")
    server.serve_forever()
