import os
print("🔍 ENV DUMP:", dict(os.environ))
print("BOT_TOKEN:", os.environ.get("BOT_TOKEN"))
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

# Telegram bot token from env variable
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set.")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7352016327"))  # Your Telegram user ID
PAYPAL_EMAIL = os.getenv("PAYPAL_EMAIL", "premiumrays01@gmail.com")
BASE_URL = os.getenv("https://telegram-lead-shop.onrender.com")  # Your Render app URL e.g. https://yourapp.onrender.com

# Lead categories: label, price, filename
LEAD_CATEGORIES = {
    "law": {"label": "Law Leads", "price": 10.00, "file": "law_leads.csv"},
    "realestate": {"label": "Real Estate Leads", "price": 12.00, "file": "real_estate_leads.csv"},
    "healthcare": {"label": "Healthcare Leads", "price": 15.00, "file": "healthcare_leads.csv"},
    "finance": {"label": "Finance Leads", "price": 13.00, "file": "finance_leads.csv"},
    "it": {"label": "IT Leads", "price": 14.00, "file": "it_leads.csv"},
}

app = Flask(__name__)

# Store user orders: chat_id -> {categories: set, total: float, paid: bool, txn_id: str}
user_orders = {}

# Telegram bot setup
telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

# ===== Telegram Handlers =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Welcome to the Lead Shop Bot!\n"
        "Use /buy to select and purchase leads.\n"
        "Available categories:\n"
    )
    for key, cat in LEAD_CATEGORIES.items():
        text += f"- {cat['label']} — ${cat['price']:.2f}\n"
    await update.message.reply_text(text)


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_orders[chat_id] = {"categories": set(), "total": 0.0, "paid": False, "txn_id": None}
    await send_category_selection(update, context, chat_id)


async def send_category_selection(update, context, chat_id):
    keyboard = []
    for key, cat in LEAD_CATEGORIES.items():
        keyboard.append([InlineKeyboardButton(f"{cat['label']} (${cat['price']})", callback_data=key)])
    keyboard.append([InlineKeyboardButton("✅ Confirm Selection", callback_data="confirm")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "Select lead categories to buy (tap to toggle):", reply_markup=reply_markup
        )
    else:
        await context.bot.send_message(chat_id, "Select lead categories to buy (tap to toggle):", reply_markup=reply_markup)


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
        # Calculate total
        total = sum(LEAD_CATEGORIES[c]["price"] for c in user_orders[chat_id]["categories"])
        user_orders[chat_id]["total"] = total

        # Generate PayPal payment link
        payment_link = generate_paypal_link(chat_id, total)
        await query.edit_message_text(
            f"You selected: {', '.join([LEAD_CATEGORIES[c]['label'] for c in user_orders[chat_id]['categories']])}\n"
            f"Total price: ${total:.2f}\n\n"
            f"Please pay using the link below:\n{payment_link}\n\n"
            "After payment, your leads will be sent automatically."
        )
        return

    # Toggle selection
    if category in user_orders[chat_id]["categories"]:
        user_orders[chat_id]["categories"].remove(category)
    else:
        user_orders[chat_id]["categories"].add(category)

    # Update keyboard buttons to show selection status
    keyboard = []
    for key, cat in LEAD_CATEGORIES.items():
        selected = "✅ " if key in user_orders[chat_id]["categories"] else ""
        keyboard.append([InlineKeyboardButton(f"{selected}{cat['label']} (${cat['price']})", callback_data=key)])
    keyboard.append([InlineKeyboardButton("✅ Confirm Selection", callback_data="confirm")])

    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    await query.answer()


def generate_paypal_link(chat_id, total):
    # PayPal payment link using "Buy Now" button parameters
    # 'item_name' encodes the chat_id for tracking, you can improve this with unique order IDs
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
    # PayPal IPN message validation and order processing
    ipn_data = request.form.to_dict()
    logger.info(f"Received IPN: {ipn_data}")

    # Prepare 'cmd' param to validate IPN with PayPal
    verify_params = {"cmd": "_notify-validate"}
    verify_params.update(ipn_data)

    # Verify IPN with PayPal
    resp = requests.post("https://ipnpb.paypal.com/cgi-bin/webscr", data=verify_params)
    if resp.text != "VERIFIED":
        logger.warning("IPN Verification failed")
        return Response("IPN Verification failed", status=400)

    # Check payment status
    payment_status = ipn_data.get("payment_status")
    if payment_status != "Completed":
        logger.info(f"Payment not completed: {payment_status}")
        return Response("Payment not completed", status=200)

    # Extract buyer info
    item_name = ipn_data.get("item_name", "")
    txn_id = ipn_data.get("txn_id", "")
    payer_email = ipn_data.get("payer_email", "")
    mc_gross = ipn_data.get("mc_gross", "")
    custom = ipn_data.get("custom", "")  # if you use custom

    # Extract chat_id from item_name (expects format leads_purchase_<chat_id>)
    if not item_name.startswith("leads_purchase_"):
        logger.warning("Invalid item_name format")
        return Response("Invalid item_name format", status=400)

    try:
        chat_id = int(item_name.split("_")[-1])
    except Exception as e:
        logger.error(f"Invalid chat_id in item_name: {e}")
        return Response("Invalid chat_id", status=400)

    # Verify total amount
    if chat_id not in user_orders:
        logger.warning(f"No order found for chat_id {chat_id}")
        return Response("Order not found", status=404)

    order = user_orders[chat_id]
    if float(mc_gross) != order["total"]:
        logger.warning(f"Payment amount mismatch: {mc_gross} vs {order['total']}")
        return Response("Amount mismatch", status=400)

    # Check if this txn_id was already processed (avoid duplicates)
    if order.get("txn_id") == txn_id:
        logger.info(f"Duplicate txn_id {txn_id} ignored")
        return Response("Duplicate txn", status=200)

    # Mark order as paid
    order["paid"] = True
    order["txn_id"] = txn_id

    # Send lead files to buyer in a new thread (to avoid blocking IPN)
    Thread(target=send_leads_to_buyer, args=(chat_id,)).start()

    logger.info(f"Payment verified for chat_id {chat_id}, txn_id {txn_id}")
    return Response("OK", status=200)


def send_leads_to_buyer(chat_id):
    import asyncio

    async def send_files():
        bot = telegram_app.bot
        order = user_orders.get(chat_id)
        if not order or not order.get("paid"):
            logger.error(f"Order not paid or not found for chat_id {chat_id}")
            return

        categories = order["categories"]
        if not categories:
            logger.error(f"No categories found in order for chat_id {chat_id}")
            return

        for cat_key in categories:
            cat = LEAD_CATEGORIES[cat_key]
            filename = cat["file"]
            if not os.path.isfile(filename):
                await bot.send_message(chat_id, f"⚠️ Lead file not found: {filename}")
                continue
            try:
                with open(filename, "rb") as f:
                    await bot.send_document(
                        chat_id=chat_id,
                        document=InputFile(f),
                        caption=f"Here is your {cat['label']} leads file. Thank you for your purchase!"
                    )
            except Exception as e:
                logger.error(f"Error sending file {filename} to {chat_id}: {e}")

    asyncio.run(send_files())


@telegram_app.command("start")
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

@telegram_app.command("buy")
async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy(update, context)

@telegram_app.callback_query_handler()
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await category_toggle(update, context)

def run_telegram_bot():
    telegram_app.run_polling()

# Run Flask and Telegram bot in parallel
if __name__ == "__main__":
    from threading import Thread

    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))).start()
    run_telegram_bot()
