import os
import logging
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")  # Make sure to set this environment variable correctly

app = Flask(__name__)

telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! Bot is working.")

telegram_app.add_handler(CommandHandler("start", start))

@app.route("/")
def index():
    return "Flask server running!"

def run_telegram_bot():
    telegram_app.run_polling()

if __name__ == "__main__":
    from threading import Thread

    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))).start()
    run_telegram_bot()
