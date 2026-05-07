# app/agent/observer.py
from datetime import datetime, timedelta
from typing import List, Dict
from ..tools.supabase_db import SupabaseDB

class Observer:
    def __init__(self, db: SupabaseDB):
        self.db = db
    
    def check_progress(self, tasks: List[Dict]) -> List[Dict]:
        """Check which tasks are falling behind"""
        alerts = []
        
        for task in tasks:
            days_left = (datetime.fromisoformat(task['deadline']) - datetime.now()).days
            if days_left <= 0:
                task['status'] = 'missed'
                self.db.supabase.table("tasks").update({"status": "missed"}).eq("id", task['id']).execute()
                alerts.append({
                    'task': task['name'],
                    'type': 'deadline_missed',
                    'message': f"⚠️ Task '{task['name']}' has missed its deadline!"
                })
                continue
            
            required_daily_hours = task['remaining_hours'] / max(1, days_left)
            
            # Check recent progress (last 3 days)
            recent_progress = self.db.supabase.table("daily_progress")\
                .select("hours_completed")\
                .eq("task_id", task['id'])\
                .gte("date", (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"))\
                .execute()
            
            total_recent = sum(p['hours_completed'] for p in recent_progress.data)
            
            if total_recent < required_daily_hours * 2:  # Falling behind
                alerts.append({
                    'task': task['name'],
                    'type': 'behind_schedule',
                    'message': f"⚠️ You're falling behind on '{task['name']}'. Need {required_daily_hours:.1f} hours/day."
                })
        
        return alerts
    
    def detect_missed_sessions(self, schedule: Dict) -> List[Dict]:
        """Check which scheduled sessions were missed"""
        missed = []
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        if yesterday in schedule:
            for session in schedule[yesterday]:
                # Check if progress was logged for this session
                progress = self.db.supabase.table("daily_progress")\
                    .select("hours_completed")\
                    .eq("task_id", session['task_id'])\
                    .eq("date", yesterday)\
                    .execute()
                
                if not progress.data or progress.data[0]['hours_completed'] < session['hours']:
                    missed.append(session)
        
        return missed