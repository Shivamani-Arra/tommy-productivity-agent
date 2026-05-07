# app/agent/core.py
import asyncio
import os
from datetime import datetime
from typing import Dict, List
from ..tools.supabase_db import SupabaseDB
from ..tools.calendar import CalendarTool
from ..tools.telegram import TelegramBot
from ..tools.gemini_client import GeminiClient
from .planner import Planner
from .observer import Observer
from .replanner import Replanner

class ProductivityAgent:
    def __init__(self):
        self.db = SupabaseDB()
        self.calendar = CalendarTool()
        self.gemini = GeminiClient()
        self.planner = Planner(self.calendar, self.gemini)
        self.observer = Observer(self.db)
        self.replanner = Replanner(self.calendar, self.db, self.gemini)
        self.telegram = TelegramBot(self.process_user_input)
    
    async def run_daily_loop(self):
        """Main agent loop - called daily by scheduler"""
        print(f"🤖 Agent waking up - {datetime.now()}")
        
        # Step 1: Observe - Check all tasks
        tasks = self.db.get_pending_tasks()
        alerts = self.observer.check_progress(tasks)
        
        # Step 2: Detect missed work
        schedule = self._load_schedule()
        missed_sessions = self.observer.detect_missed_sessions(schedule)
        
        # Step 3: Replan if needed
        if missed_sessions:
            print(f"🔄 Replanning for {len(missed_sessions)} missed sessions")
            schedule = self.replanner.replan(missed_sessions, schedule)
        
        # Step 4: Create new schedule if needed
        if not schedule or self._schedule_outdated(schedule):
            print(f"📅 Generating new schedule for {len(tasks)} tasks")
            schedule = self.planner.generate_schedule(tasks)
            self._save_schedule(schedule)
            
            # Create calendar events
            for date, sessions in schedule.items():
                for session in sessions:
                    self.calendar.create_event(
                        f"📝 {session['task_name']}",
                        session['start'],
                        session['end']
                    )
        
        # Step 5: Send morning briefing
        await self._send_morning_briefing(tasks, alerts, schedule)
        
        # Log agent action
        self.db.log_agent_action("daily_loop", {
            "tasks_count": len(tasks),
            "alerts": alerts,
            "schedule_length": len(schedule)
        })
    
    async def process_user_input(self, user_input: str, chat_id: int) -> str:
        """Process user commands and tasks"""
        
        # Check if adding a new task
        if any(word in user_input.lower() for word in ["complete", "finish", "study", "by", "before"]):
            task_info = self.gemini.extract_task_info(user_input)
            task = self.db.add_task({
                "name": task_info["name"],
                "deadline": task_info["deadline"],
                "estimated_hours": task_info["estimated_hours"],
                "priority": task_info.get("priority", 2)
            })
            
            # Regenerate schedule with new task
            all_tasks = self.db.get_pending_tasks()
            schedule = self.planner.generate_schedule(all_tasks)
            self._save_schedule(schedule)
            
            return f"✅ Task added: {task_info['name']}\nDeadline: {task_info['deadline']}\nEstimated: {task_info['estimated_hours']} hours\n\nI've updated your schedule!"
        
        elif "progress" in user_input.lower():
            tasks = self.db.get_pending_tasks()
            report = f"📊 Your Progress:\n"
            for task in tasks:
                report += f"\n📌 {task['name']}: {task['completed_hours']}/{task['estimated_hours']} hours ({task['status']})"
            return report
        
        elif "schedule" in user_input.lower():
            schedule = self._load_schedule()
            today = datetime.now().strftime("%Y-%m-%d")
            if today in schedule:
                report = f"📅 Today's Schedule:\n"
                for session in schedule[today]:
                    report += f"\n⏰ {session['start'].strftime('%H:%M')}: {session['task_name']} ({session['hours']} hrs)"
                return report
            return "No schedule for today. Add some tasks first!"
        
        return "I can help you add tasks, check progress, or view your schedule. What would you like to do?"
    
    async def _send_morning_briefing(self, tasks: List[Dict], alerts: List[Dict], schedule: Dict):
        """Send daily briefing via Telegram"""
        today = datetime.now().strftime("%Y-%m-%d")
        message = f"🌅 Good morning! Here's your briefing for {today}\n\n"
        
        # Task summary
        active_tasks = [t for t in tasks if t['status'] == 'pending']
        message += f"📋 Active tasks: {len(active_tasks)}\n"
        message += f"⏰ Upcoming deadlines: {len([t for t in tasks if (datetime.fromisoformat(t['deadline']) - datetime.now()).days <= 2])}\n\n"
        
        # Today's schedule
        if today in schedule:
            message += "📅 Today's plan:\n"
            for session in schedule[today]:
                message += f"  • {session['task_name']}: {session['hours']} hours\n"
        
        # Alerts
        if alerts:
            message += "\n⚠️ Alerts:\n"
            for alert in alerts[:3]:  # Max 3 alerts
                message += f"  • {alert['message']}\n"
        
        # Send to user (you'll need to store user's chat ID)
        user_chat_id = os.getenv("USER_CHAT_ID")
        if user_chat_id:
            await self.telegram.send_message(user_chat_id, message)
    
    def _load_schedule(self) -> Dict:
        # Load from Supabase or local storage
        try:
            result = self.db.supabase.table("agent_state").select("schedule").eq("key", "current_schedule").execute()
            if result.data:
                import json
                return json.loads(result.data[0]['schedule'])
        except:
            pass
        return {}
    
    def _save_schedule(self, schedule: Dict):
        # Save to Supabase
        try:
            import json
            # Create table agent_state if not exists
            self.db.supabase.table("agent_state").upsert({
                "key": "current_schedule",
                "schedule": json.dumps(schedule, default=str)
            }).execute()
        except:
            pass
    
    def _schedule_outdated(self, schedule: Dict) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        return today not in schedule
    
    async def start(self):
        """Start the agent"""
        print("🚀 Starting AI Productivity Assistant...")
        # Start Telegram bot in background
        asyncio.create_task(self._run_telegram())
        # Run initial loop
        await self.run_daily_loop()
    
    async def _run_telegram(self):
        await self.telegram.run()