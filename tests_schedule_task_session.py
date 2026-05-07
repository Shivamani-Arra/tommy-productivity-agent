import sys
import types

calendar_calls = {"created": []}

database_module = types.ModuleType("database")
superbase_client_module = types.ModuleType("database.superbase_client")
calendar_module = types.ModuleType("tools.google_calendar_tools")


def create_calendar_event_details(task_name, deadline, start_time, duration_hours):
    calendar_calls["created"].append((task_name, deadline, start_time, duration_hours))
    return {"id": "calendar-event", "htmlLink": "https://calendar.example/event"}


def delete_calendar_event(_event_id):
    return None


def get_free_time_slots(*_args, **_kwargs):
    return [{"date": "2026-05-06", "start_time": "09:00", "end_time": "21:00", "hours": 12}]


calendar_module.create_calendar_event_details = create_calendar_event_details
calendar_module.delete_calendar_event = delete_calendar_event
calendar_module.get_free_time_slots = get_free_time_slots
sys.modules.setdefault("database", database_module)
sys.modules.setdefault("database.superbase_client", superbase_client_module)
sys.modules.setdefault("tools.google_calendar_tools", calendar_module)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table_name, rows):
        self.table_name = table_name
        self.rows = rows
        self.filters = []
        self.insert_payload = None

    def select(self, _columns):
        return self

    def insert(self, payload):
        self.insert_payload = payload
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self.insert_payload is not None:
            row = dict(self.insert_payload)
            row.setdefault("id", f"{self.table_name}-1")
            self.rows.append(row)
            return FakeResult([row])

        matched = self.rows
        for column, value in self.filters:
            matched = [row for row in matched if str(row.get(column)) == str(value)]
        return FakeResult(matched)


class FakeSupabase:
    def __init__(self):
        self.tables = {"schedule": [], "tasks": []}

    def table(self, name):
        return FakeQuery(name, self.tables[name])


superbase_client_module.supabase = FakeSupabase()

from tools import productivity_tools


def test_schedule_task_session_creates_calendar_and_schedule_row():
    result = productivity_tools.schedule_task_session(
        "study science",
        "15:15",
        "2026-05-06",
        user_id="default",
    )

    schedule_row = productivity_tools.supabase.tables["schedule"][0]
    assert schedule_row["task_name"] == "science"
    assert schedule_row["start_time"] == "15:15"
    assert schedule_row["end_time"] == "16:15"
    assert schedule_row["calendar_event_id"] == "calendar-event"
    assert calendar_calls["created"] == [("science", "2026-05-06", "15:15", 1.0)]
    assert "Scheduled science" in result


if __name__ == "__main__":
    test_schedule_task_session_creates_calendar_and_schedule_row()
    print("Schedule task session tests passed.")
