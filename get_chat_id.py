# save as get_chat_id.py
import requests
from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
response = requests.get(url)
data = response.json()

print("Full response:")
print(data)

# Extract chat ID automatically
if data.get("result"):
    for update in data["result"]:
        if "message" in update:
            chat_id = update["message"]["chat"]["id"]
            print(f"\n✅ YOUR CHAT ID IS: {chat_id}")
            print(f"Copy this number to your .env file")
else:
    print("\n❌ No messages found.")
    print("Go to Telegram, send any message to your bot, then run this again.")