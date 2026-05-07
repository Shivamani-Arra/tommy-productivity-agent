import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from dotenv import load_dotenv
import os
from agent import run_agent
from scheduler import start_background_scheduler

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# BOT COMMAND HANDLERS
# ─────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    name = update.effective_user.first_name
    
    await update.message.reply_text(
        f"Hey {name}! I'm your Personal Productivity Agent.\n\n"
        f"Here's what you can tell me:\n"
        f"• 'Study DP for 10 hours before May 15'\n"
        f"• 'Show my tasks'\n"
        f"• 'I finished ML project'\n"
        f"• 'Send me a reminder'\n"
        f"• 'What's due this week'\n\n"
        f"Just talk to me naturally — I'll handle the rest!"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    await update.message.reply_text(
        "Commands you can use:\n\n"
        "/start — Welcome message\n"
        "/tasks — Show all pending tasks\n"
        "/reminder — Send yourself a reminder now\n"
        "/help — Show this message\n\n"
        "Or just type naturally:\n"
        "• 'Add task: finish report by May 10'\n"
        "• 'I completed the ML project'\n"
        "• 'What should I work on today'\n"
        "• 'Am I on track for my deadlines'"
    )

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tasks command"""
    await update.message.reply_text("Fetching your tasks...")
    response = run_agent(
        "Show me all my pending tasks with deadlines",
        user_id=str(update.effective_chat.id)
    )
    await update.message.reply_text(response)

async def reminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reminder command"""
    await update.message.reply_text("Generating your reminder...")
    response = run_agent(
        "Send me a detailed reminder about all my pending tasks and deadlines",
        user_id=str(update.effective_chat.id)
    )
    await update.message.reply_text(response)

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /schedule command"""
    await update.message.reply_text("Planning your schedule...")
    response = run_agent(
        "Spread my pending work across my available calendar time",
        user_id=str(update.effective_chat.id)
    )
    await update.message.reply_text(response)

async def replan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /replan command"""
    await update.message.reply_text("Checking missed work and replanning...")
    response = run_agent(
        "Replan my missed work",
        user_id=str(update.effective_chat.id)
    )
    await update.message.reply_text(response)

async def risk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /risk command"""
    await update.message.reply_text("Scoring deadline risk...")
    response = run_agent(
        "Am I on track for my deadlines? Score the deadline risk.",
        user_id=str(update.effective_chat.id)
    )
    await update.message.reply_text(response)

async def cleanup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cleanup command"""
    await update.message.reply_text("Cleaning duplicate tasks...")
    response = run_agent(
        "cleanup duplicates",
        user_id=str(update.effective_chat.id)
    )
    await update.message.reply_text(response)

# ─────────────────────────────────────────
# MAIN MESSAGE HANDLER
# ─────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all natural language messages"""
    
    user_message = update.message.text
    user_name = update.effective_user.first_name
    
    log.info(f"Message from {user_name}: {user_message}")
    
    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )
    
    # Run agent
    try:
        response = run_agent(user_message, user_id=str(update.effective_chat.id))
        await update.message.reply_text(response)
        
    except Exception as e:
        log.error(f"Agent error: {e}")
        await update.message.reply_text(
            "Sorry, something went wrong. Please try again."
        )

# ─────────────────────────────────────────
# ERROR HANDLER
# ─────────────────────────────────────────

async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    log.error(f"Error: {context.error}")

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

def main():
    print("=" * 50)
    print("🤖 Productivity Agent Bot Starting...")
    print("=" * 50)
    
    # Start background scheduler (daily reminders)
    scheduler = start_background_scheduler()
    print("✓ Scheduler started")
    print("  • 8:00 AM — Morning briefing")
    print("  • 12:00 PM — Deadline warnings")
    print("  • 8:00 PM — Evening check-in")
    print("  • Sunday 7PM — Weekly summary")
    
    # Build Telegram bot
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("reminder", reminder_command))
    app.add_handler(CommandHandler("schedule", schedule_command))
    app.add_handler(CommandHandler("replan", replan_command))
    app.add_handler(CommandHandler("risk", risk_command))
    app.add_handler(CommandHandler("cleanup", cleanup_command))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))
    app.add_error_handler(error_handler)
    
    print("✓ Bot is running!")
    print("  Open Telegram and chat with your bot now.")
    print("  Press Ctrl+C to stop.\n")
    
    # Start polling
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
