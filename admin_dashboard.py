from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from database.superbase_client import supabase
from tools.productivity_tools import cleanup_duplicates


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
        else:
            body = self._render(user_id)

        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _render(self, user_id):
        sections = []
        for table in ("tasks", "schedule", "daily_progress", "pending_followups", "user_preferences"):
            rows = _rows(table)
            sections.append(f"<h2>{table}</h2><pre>{rows}</pre>")
        return f"""
        <html>
        <head><title>Productivity Agent Admin</title></head>
        <body style="font-family: Arial; margin: 32px;">
            <h1>Productivity Agent Admin</h1>
            <p>User: {user_id}</p>
            <p><a href="/cleanup?user_id={user_id}">Cleanup duplicate tasks</a></p>
            {''.join(sections)}
        </body>
        </html>
        """


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 8080), DashboardHandler)
    print("Admin dashboard running at http://127.0.0.1:8080")
    server.serve_forever()
