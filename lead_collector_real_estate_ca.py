import os
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import threading

BOT_TOKEN = os.environ.get("BOT_TOKEN")
PAYPAL_EMAIL = os.environ.get("PAYPAL_EMAIL")

app = Flask(__name__)

# Telegram Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to the Lead Shop Bot! Use /buy to see available leads.")

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"To buy leads, send payment to PayPal: {PAYPAL_EMAIL}\n"
        "After payment, you’ll receive your lead file automatically!"
    )

# Flask route (optional if used for PayPal IPN)
@app.route('/')
def index():
    return "Telegram Lead Bot is running."

# Run Flask in a separate thread
def run_flask():
    app.run(host='0.0.0.0', port=10000)

# Main bot
def run_telegram_bot():
    telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("buy", buy))
    telegram_app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    run_telegram_bot()
