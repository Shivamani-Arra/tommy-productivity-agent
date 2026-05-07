import sys
import types

calendar_calls = {"created": [], "deleted": []}

database_module = types.ModuleType("database")
superbase_client_module = types.ModuleType("database.superbase_client")
calendar_module = types.ModuleType("tools.google_calendar_tools")


def create_calendar_event_details(task_name, deadline, start_time, duration_hours):
    calendar_calls["created"].append((task_name, deadline, start_time, duration_hours))
    return {"id": "new-event", "htmlLink": "https://calendar.example/new-event"}


def delete_calendar_event(event_id):
    calendar_calls["deleted"].append(event_id)


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
        self.update_values = None

    def select(self, _columns):
        return self

    def update(self, values):
        self.update_values = values
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        matched = self.rows
        for column, value in self.filters:
            matched = [row for row in matched if str(row.get(column)) == str(value)]

        if self.update_values is not None:
            for row in matched:
                row.update(self.update_values)

        return FakeResult(matched)


class FakeSupabase:
    def __init__(self):
        self.tables = {
            "schedule": [
                {
                    "id": "schedule-1",
                    "task_id": "task-1",
                    "user_id": "default",
                    "scheduled_date": "2026-05-06",
                    "start_time": "14:00",
                    "end_time": "15:00",
                    "hours_planned": 1,
                    "completed": False,
                    "calendar_event_id": "old-event",
                }
            ],
            "tasks": [{"id": "task-1", "user_id": "default", "task_name": "Study science"}],
        }

    def table(self, name):
        return FakeQuery(name, self.tables[name])


superbase_client_module.supabase = FakeSupabase()

from tools import productivity_tools


def test_reschedule_updates_schedule_and_calendar():
    result = productivity_tools.reschedule_schedule(
        task_name="science",
        schedule_date="2026-05-06",
        source_start_time="14:00",
        new_start_time="18:00",
        user_id="default",
    )

    row = productivity_tools.supabase.tables["schedule"][0]
    assert row["start_time"] == "18:00"
    assert row["end_time"] == "19:00"
    assert row["calendar_event_id"] == "new-event"
    assert row["status"] == "rescheduled"
    assert calendar_calls["deleted"] == ["old-event"]
    assert calendar_calls["created"] == [("Study science", "2026-05-06", "18:00", 1.0)]
    assert "Moved Study science" in result


if __name__ == "__main__":
    test_reschedule_updates_schedule_and_calendar()
    print("Reschedule schedule tests passed.")
