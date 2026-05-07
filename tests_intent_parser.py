from intent_parser import parse_intent


def check(message, intent):
    parsed = parse_intent(message)
    assert parsed["intent"] == intent, f"{message!r} -> {parsed}"
    return parsed


def run_tests():
    assert check("Complete 5 hours of math study before Sunday", "add_task")["task_name"] == "math"
    assert check("I need to study math for 5 hours before Sunday", "add_task")["task_name"] == "math"
    assert check("Before Sundat study 5 hours for math", "add_task")["task_name"] == "math"
    assert check("I studied math for 1 hour", "progress")["hours_completed"] == 1
    assert check("I finished math", "complete")["task_name"] == "math"
    assert check("Remaining work today.", "show_today")
    assert check("What are the remaing tasks today?", "show_today")
    assert check("Give me tasks that I need to complete today.", "show_today")
    assert check("What are todays completed tasks?", "show_today_completed")
    parsed = check("Tomorrow 6 to 8 am I should write screenplay.", "schedule_task_session")
    assert parsed["task_name"] == "write screenplay"
    assert parsed["start_time"] == "06:00"
    assert parsed["duration_hours"] == 2
    parsed = check("I completed math at 9 to 10:30.", "complete_session")
    assert parsed["task_name"] == "math"
    assert parsed["start_time"] == "09:00"
    assert parsed["end_time"] == "10:30"
    assert check("I have a meeting at 1 am on 8th of may", "fixed_event")["start_time"] == "01:00"
    assert check("Schedule a meeting tomorrow at 10 pm.", "fixed_event")["start_time"] == "22:00"
    assert check("meeting tomorrow", "needs_info")["kind"] == "fixed_event_missing_time"
    assert check("Add study science task at 3:15pm.", "schedule_task_session")["start_time"] == "15:15"
    assert check("Postpone todays science schedule to tomorrow", "postpone")["task_name"] == "science"
    assert check("Prepone tomorrow science schedule to today", "prepone")["task_name"] == "science"
    assert check("cancel today science", "cancel_session")["task_name"] == "science"
    parsed = check("Remove the task assigned tomorrow at 10 pm.", "cancel_session_at_time")
    assert parsed["start_time"] == "22:00"
    assert check("make math 30 minutes today", "resize_session")["hours"] == 0.5
    assert check("move science to 6 pm today", "reschedule_session")["new_start_time"] == "18:00"
    assert check("reschedule science from 2 pm to 6 pm today", "reschedule_session")["source_start_time"] == "14:00"
    assert check("swap math and science", "swap_session")["first_task"] == "math"
    assert check("cleanup duplicates", "cleanup")
    print("All intent parser tests passed.")


if __name__ == "__main__":
    run_tests()
