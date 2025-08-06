import os
import json
import logging
from flask import Flask, request, Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from threading import Thread
import requests

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Telegram bot token and environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")  # ✅ CORRECTED
ADMIN_ID = int(os.getenv("ADMIN_ID", "7352016327"))
PAYPAL_EMAIL = os.getenv("PAYPAL_EMAIL", "premiumrays01@gmail.com")
BASE_URL = os.getenv("BASE_URL", "https://telegram-lead-shop.onrender.com")  # ✅ CORRECTED

# Lead categories
LEAD_CATEGORIES = {
    "law": {"label": "Law Leads", "price": 10.00, "file": "law_leads.csv"},
    "realestate": {"label": "Real Estate Leads", "price": 12.00, "file": "real_estate_leads.csv"},
    "healthcare": {"label": "Healthcare Leads", "price": 15.00, "file": "healthcare_leads.csv"},
    "finance": {"label": "Finance Leads", "price": 13.00, "file": "finance_leads.csv"},
    "it": {"label": "IT Leads", "price": 14.00, "file": "it_leads.csv"},
}

app = Flask(__name__)
user_orders = {}

telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

# ===== Handlers =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Welcome to the Lead Shop Bot!\n"
        "Use /buy to select and purchase leads.\n\n"
        "Available categories:\n"
    )
    for cat in LEAD_CATEGORIES.values():
        text += f"- {cat['label']} — ${cat['price']:.2f}\n"
    await update.message.reply_text(text)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_orders[chat_id] = {"categories": set(), "total": 0.0, "paid": False, "txn_id": None}
    await send_category_selection(update, context, chat_id)

async def send_category_selection(update, context, chat_id):
    keyboard = [[InlineKeyboardButton(f"{cat['label']} (${cat['price']})", callback_data=key)] for key, cat in LEAD_CATEGORIES.items()]
    keyboard.append([InlineKeyboardButton("✅ Confirm Selection", callback_data="confirm")])
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text("Select lead categories to buy (tap to toggle):", reply_markup=markup)
    else:
        await context.bot.send_message(chat_id, "Select lead categories to buy (tap to toggle):", reply_markup=markup)

async def category_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat.id
    category = query.data

    if chat_id not in user_orders:
        user_orders[chat_id] = {"categories": set(), "total": 0.0, "paid": False, "txn_id": None}

    if category == "confirm":
        if not user_orders[chat_id]["categories"]:
            await query.answer("Please select at least one category before confirming.", show_alert=True)
            return
        total = sum(LEAD_CATEGORIES[c]["price"] for c in user_orders[chat_id]["categories"])
        user_orders[chat_id]["total"] = total
        payment_link = generate_paypal_link(chat_id, total)
        await query.edit_message_text(
            f"You selected: {', '.join(LEAD_CATEGORIES[c]['label'] for c in user_orders[chat_id]['categories'])}\n"
            f"Total: ${total:.2f}\n\n"
            f"Pay with PayPal: {payment_link}\n\n"
            "After payment, your leads will be sent automatically."
        )
        return

    if category in user_orders[chat_id]["categories"]:
        user_orders[chat_id]["categories"].remove(category)
    else:
        user_orders[chat_id]["categories"].add(category)

    keyboard = []
    for key, cat in LEAD_CATEGORIES.items():
        selected = "✅ " if key in user_orders[chat_id]["categories"] else ""
        keyboard.append([InlineKeyboardButton(f"{selected}{cat['label']} (${cat['price']})", callback_data=key)])
    keyboard.append([InlineKeyboardButton("✅ Confirm Selection", callback_data="confirm")])
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    await query.answer()

def generate_paypal_link(chat_id, total):
    base = "https://www.paypal.com/cgi-bin/webscr"
    params = {
        "cmd": "_xclick",
        "business": PAYPAL_EMAIL,
        "currency_code": "USD",
        "amount": f"{total:.2f}",
        "item_name": f"leads_purchase_{chat_id}",
        "no_shipping": "1",
        "return": f"{BASE_URL}/payment_success?chat_id={chat_id}",
        "cancel_return": f"{BASE_URL}/payment_cancel?chat_id={chat_id}",
        "notify_url": f"{BASE_URL}/paypal_ipn",
    }
    from urllib.parse import urlencode
    return f"{base}?{urlencode(params)}"

@app.route("/paypal_ipn", methods=["POST"])
def paypal_ipn():
    ipn_data = request.form.to_dict()
    logger.info(f"Received IPN: {ipn_data}")
    verify_params = {"cmd": "_notify-validate", **ipn_data}
    resp = requests.post("https://ipnpb.paypal.com/cgi-bin/webscr", data=verify_params)
    if resp.text != "VERIFIED":
        logger.warning("IPN verification failed")
        return Response("IPN failed", status=400)

    item_name = ipn_data.get("item_name", "")
    txn_id = ipn_data.get("txn_id", "")
    mc_gross = ipn_data.get("mc_gross", "")

    if not item_name.startswith("leads_purchase_"):
        return Response("Invalid item_name", status=400)

    try:
        chat_id = int(item_name.split("_")[-1])
    except:
        return Response("Invalid chat_id", status=400)

    order = user_orders.get(chat_id)
    if not order or float(mc_gross) != order["total"]:
        return Response("Invalid order or amount mismatch", status=400)

    if order.get("txn_id") == txn_id:
        return Response("Duplicate txn", status=200)

    order["paid"] = True
    order["txn_id"] = txn_id
    Thread(target=send_leads_to_buyer, args=(chat_id,)).start()
    return Response("OK", status=200)

def send_leads_to_buyer(chat_id):
    import asyncio

    async def send_files():
        bot = telegram_app.bot
        order = user_orders.get(chat_id)
        if not order or not order.get("paid"):
            return

        for cat_key in order["categories"]:
            cat = LEAD_CATEGORIES[cat_key]
            file_path = cat["file"]
            if not os.path.isfile(file_path):
                await bot.send_message(chat_id, f"⚠️ File not found: {file_path}")
                continue
            try:
                with open(file_path, "rb") as f:
                    await bot.send_document(
                        chat_id=chat_id,
                        document=InputFile(f),
                        caption=f"Here is your {cat['label']} leads file. Thank you!"
                    )
            except Exception as e:
                logger.error(f"Failed to send {file_path}: {e}")

    asyncio.run(send_files())

# Register handlers
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("buy", buy))
telegram_app.add_handler(CallbackQueryHandler(category_toggle))

def run_telegram_bot():
    telegram_app.run_polling()

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))).start()
    run_telegram_bot()
