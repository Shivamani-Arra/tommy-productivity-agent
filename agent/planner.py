# app/agent/planner.py
from datetime import datetime, timedelta
from typing import List, Dict
from ..tools.calendar import CalendarTool
from ..tools.gemini_client import GeminiClient

class Planner:
    def __init__(self, calendar_tool: CalendarTool, gemini: GeminiClient):
        self.calendar = calendar_tool
        self.gemini = gemini
    
    def generate_schedule(self, tasks: List[Dict], working_hours_start=9, working_hours_end=18) -> Dict:
        """Generate optimized schedule for all tasks"""
        
        # Sort tasks by urgency
        sorted_tasks = sorted(tasks, key=lambda t: self._calculate_urgency(t))
        
        schedule = {}
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        for task in sorted_tasks:
            days_until_deadline = (datetime.fromisoformat(task['deadline']) - today).days
            if days_until_deadline <= 0:
                continue
            
            hours_per_day = task['remaining_hours'] / max(1, days_until_deadline)
            
            # Get free slots for each day
            for day in range(min(days_until_deadline, 7)):  # Look ahead 1 week
                current_day = today + timedelta(days=day)
                date_str = current_day.strftime("%Y-%m-%d")
                
                if date_str not in schedule:
                    schedule[date_str] = []
                
                # Find free slots in calendar
                free_slots = self.calendar.get_free_slots(
                    current_day.replace(hour=working_hours_start),
                    current_day.replace(hour=working_hours_end)
                )
                
                allocated_hours = 0
                for slot in free_slots:
                    slot_duration = (slot['end'] - slot['start']).seconds / 3600
                    hours_to_add = min(hours_per_day - allocated_hours, slot_duration)
                    
                    if hours_to_add > 0.5:  # Only schedule if at least 30 mins
                        schedule[date_str].append({
                            'task_id': task['id'],
                            'task_name': task['name'],
                            'start': slot['start'],
                            'end': slot['start'] + timedelta(hours=hours_to_add),
                            'hours': hours_to_add
                        })
                        allocated_hours += hours_to_add
                    
                    if allocated_hours >= hours_per_day:
                        break
        
        return schedule
    
    def _calculate_urgency(self, task: Dict) -> float:
        days_left = max(1, (datetime.fromisoformat(task['deadline']) - datetime.now()).days)
        return (task['remaining_hours'] / days_left) * task['priority']