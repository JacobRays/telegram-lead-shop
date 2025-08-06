import sys
print("Running Python version:", sys.version)
import os
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ContextTypes,
)
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PAYPAL_EMAIL = os.getenv("PAYPAL_EMAIL")
LEAD_FILES = os.getenv("LEAD_FILES", "").split(",")

# Confirm environment variables are loaded
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing. Check your .env on Render.")

# Flask app
app = Flask(__name__)

# Telegram bot application
telegram_app = Application.builder().token(BOT_TOKEN).build()

# /start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Buy Leads", callback_data="buy")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome to Lead Shop Bot!", reply_markup=reply_markup)

# /buy command handler
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for lead_file in LEAD_FILES:
        name = lead_file.replace("_", " ").replace(".csv", "").title()
        keyboard.append([
            InlineKeyboardButton(f"Buy {name}", callback_data=f"buy_{lead_file}")
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Choose a lead category to buy:", reply_markup=reply_markup)

# Callback query handler
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("buy_"):
        file_key = query.data.replace("buy_", "")
        price = "5.00"  # Adjust as needed
        paypal_url = f"https://www.paypal.com/paypalme/{PAYPAL_EMAIL}/{price}"
        await query.edit_message_text(
            f"To buy **{file_key}**, pay ${price} via PayPal:\n\n{paypal_url}",
            parse_mode="Markdown"
        )

# Flask route for webhook
@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
async def webhook():
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    await telegram_app.process_update(update)
    return "OK", 200

# Health check root route
@app.route("/", methods=["GET"])
def home():
    return "🤖 Lead Shop Bot is running!"

# Set webhook on startup
async def set_webhook():
    webhook_url = f"https://telegram-lead-shop.onrender.com/webhook/{BOT_TOKEN}"
    await telegram_app.bot.set_webhook(url=webhook_url)

# Start Flask + Telegram
if __name__ == "__main__":
    import asyncio

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("buy", buy))
    telegram_app.add_handler(CallbackQueryHandler(handle_callback))

    # Set webhook and start Flask
    asyncio.run(set_webhook())
    app.run(host="0.0.0.0", port=10000)
