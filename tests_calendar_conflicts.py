from datetime import datetime
import sys
import types

google_module = types.ModuleType("google")
oauth2_module = types.ModuleType("google.oauth2")
credentials_module = types.ModuleType("google.oauth2.credentials")
googleapiclient_module = types.ModuleType("googleapiclient")
discovery_module = types.ModuleType("googleapiclient.discovery")
database_module = types.ModuleType("database")
superbase_client_module = types.ModuleType("database.superbase_client")


class Credentials:
    @staticmethod
    def from_authorized_user_file(*_args, **_kwargs):
        return None


def build(*_args, **_kwargs):
    return None


credentials_module.Credentials = Credentials
discovery_module.build = build
superbase_client_module.supabase = None
sys.modules.setdefault("google", google_module)
sys.modules.setdefault("google.oauth2", oauth2_module)
sys.modules.setdefault("google.oauth2.credentials", credentials_module)
sys.modules.setdefault("googleapiclient", googleapiclient_module)
sys.modules.setdefault("googleapiclient.discovery", discovery_module)
sys.modules.setdefault("database", database_module)
sys.modules.setdefault("database.superbase_client", superbase_client_module)

from tools import google_calendar_tools


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        rows = self.rows
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        return FakeResult(rows)


class FakeSupabase:
    def __init__(self):
        self.tables = {
            "schedule": [
                {
                    "task_id": "task-1",
                    "user_id": "default",
                    "scheduled_date": "2026-05-06",
                    "start_time": "16:00",
                    "end_time": "17:00",
                    "completed": False,
                }
            ],
            "tasks": [{"id": "task-1", "task_name": "Study math"}],
        }

    def table(self, name):
        return FakeQuery(self.tables[name])


def test_fixed_event_detects_scheduled_task_overlap():
    original_supabase = google_calendar_tools.supabase
    google_calendar_tools.supabase = FakeSupabase()
    try:
        conflicts = google_calendar_tools._find_schedule_conflicts(
            "2026-05-06",
            datetime.strptime("2026-05-06 16:00", "%Y-%m-%d %H:%M"),
            datetime.strptime("2026-05-06 17:00", "%Y-%m-%d %H:%M"),
        )
    finally:
        google_calendar_tools.supabase = original_supabase

    assert conflicts == [
        {
            "start_time": "16:00",
            "end_time": "17:00",
            "task_name": "Study math",
        }
    ]


def test_fixed_event_returns_conflict_without_calendar_insert():
    original_supabase = google_calendar_tools.supabase
    original_calendar_service = google_calendar_tools._calendar_service
    google_calendar_tools.supabase = FakeSupabase()
    google_calendar_tools._calendar_service = lambda: (_ for _ in ()).throw(
        AssertionError("calendar service should not be called")
    )
    try:
        message = google_calendar_tools.create_fixed_calendar_event(
            "Meeting",
            "2026-05-06",
            "16:00",
            user_id="default",
        )
    finally:
        google_calendar_tools.supabase = original_supabase
        google_calendar_tools._calendar_service = original_calendar_service

    assert "I did not create Meeting" in message
    assert "16:00-17:00 | Study math" in message


if __name__ == "__main__":
    test_fixed_event_detects_scheduled_task_overlap()
    test_fixed_event_returns_conflict_without_calendar_insert()
    print("Calendar conflict tests passed.")
