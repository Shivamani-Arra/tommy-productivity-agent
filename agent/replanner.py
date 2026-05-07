# app/agent/replanner.py
from datetime import datetime, timedelta
from typing import List, Dict
from ..tools.calendar import CalendarTool
from ..tools.supabase_db import SupabaseDB
from ..tools.gemini_client import GeminiClient

class Replanner:
    def __init__(self, calendar: CalendarTool, db: SupabaseDB, gemini: GeminiClient):
        self.calendar = calendar
        self.db = db
        self.gemini = gemini
    
    def replan(self, missed_tasks: List[Dict], current_schedule: Dict) -> Dict:
        """Re-plan schedule after missed work"""
        
        for missed in missed_tasks:
            task_id = missed['task_id']
            
            # Get task details
            task = self.db.supabase.table("tasks").select("*").eq("id", task_id).execute()
            if not task.data:
                continue
            
            task = task.data[0]
            remaining_hours = task['remaining_hours'] + missed['hours']
            days_left = (datetime.fromisoformat(task['deadline']) - datetime.now()).days
            
            if days_left <= 0:
                # Generate warning message
                warning = self.gemini.chat(
                    f"Task '{task['name']}' is overdue by {abs(days_left)} days. "
                    f"Write a brief, urgent warning message to the user suggesting they reprioritize or extend deadline."
                )
                self._send_warning(warning, task)
            else:
                # Increase daily allocation
                new_daily_hours = remaining_hours / days_left
                self._adjust_schedule(task, new_daily_hours, current_schedule)
        
        return current_schedule
    
    def _adjust_schedule(self, task: Dict, new_daily_hours: float, schedule: Dict):
        """Adjust schedule to accommodate increased daily hours"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        for date in schedule:
            if date >= today:
                for session in schedule[date]:
                    if session['task_id'] == task['id']:
                        # Increase session duration
                        session['hours'] = new_daily_hours
                        session['end'] = session['start'] + timedelta(hours=new_daily_hours)
    
    def _send_warning(self, message: str, task: Dict):
        """Send warning to user"""
        # Will be implemented with Telegram
        pass