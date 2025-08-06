import os
import threading
from flask import Flask, request
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
PAYPAL_EMAIL = os.getenv("PAYPAL_EMAIL")
LEAD_FILES = {
    "law": "law_leads.csv",
    "real_estate": "real_estate_leads.csv",
    "healthcare": "healthcare_leads.csv",
    "accounting": "accounting_leads.csv",
    "tech": "it_leads.csv"
}

# Telegram bot setup
app = Flask(__name__)
telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

# Store payment verification status
paid_users = {}

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📄 Buy Law Leads", callback_data="buy_law")],
        [InlineKeyboardButton("🏠 Buy Real Estate Leads", callback_data="buy_real_estate")],
        [InlineKeyboardButton("🏥 Buy Healthcare Leads", callback_data="buy_healthcare")],
        [InlineKeyboardButton("📊 Buy Accounting Leads", callback_data="buy_accounting")],
        [InlineKeyboardButton("💻 Buy Tech Leads", callback_data="buy_tech")]
    ]
    await update.message.reply_text("Welcome! Choose a lead category to buy:", reply_markup=InlineKeyboardMarkup(keyboard))

# Handle button presses
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lead_type = query.data.replace("buy_", "")

    # Send mock payment instructions
    await query.message.reply_text(
        f"💰 Please send $5 to PayPal: {PAYPAL_EMAIL}\n"
        f"After payment, you'll automatically receive the {lead_type.replace('_', ' ').title()} leads."
    )

    # Mark as paid for testing (in real app, wait for PayPal IPN)
    paid_users[user_id] = lead_type

# Endpoint PayPal calls after payment
@app.route('/paypal-ipn', methods=['POST'])
def paypal_ipn():
    # Simulate IPN validation (you'd verify with PayPal here)
    data = request.form
    if data.get("payment_status") == "Completed":
        email = data.get("payer_email")
        custom = data.get("custom")
        telegram_id = int(custom)
        lead_type = data.get("item_name").lower().replace(" ", "_")

        file_path = LEAD_FILES.get(lead_type)
        if file_path:
            # Send the file in the background
            telegram_app.create_task(
                telegram_app.bot.send_document(chat_id=telegram_id, document=open(file_path, "rb"))
            )
    return "OK", 200

# Periodic check or manual trigger
async def check_payments(context: ContextTypes.DEFAULT_TYPE):
    for user_id, lead_type in paid_users.items():
        file_path = LEAD_FILES.get(lead_type)
        if file_path:
            await context.bot.send_document(chat_id=user_id, document=open(file_path, "rb"))
    paid_users.clear()

# Set up handlers
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CallbackQueryHandler(button_handler))

# Run both Flask and Telegram bot together
def run_flask():
    app.run(host='0.0.0.0', port=10000)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    telegram_app.run_polling()
