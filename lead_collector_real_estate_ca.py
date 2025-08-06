import os
import json
import logging
from flask import Flask, request, Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
import requests
import asyncio
from urllib.parse import urlencode

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Telegram bot token from env variable
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7352016327"))  # Your Telegram user ID as fallback
PAYPAL_EMAIL = os.getenv("PAYPAL_EMAIL", "premiumrays01@gmail.com")
BASE_URL = os.getenv("BASE_URL", "https://telegram-lead-shop.onrender.com")  # Your Render app URL

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
    return f"{base}?{urlencode(params)}"


@app.route("/paypal_ipn", methods=["POST"])
def paypal_ipn():
    ipn_data = request.form.to_dict()
    logger.info(f"Received IPN: {ipn_data}")

    verify_params = {"cmd": "_notify-validate"}
    verify_params.update(ipn_data)

    resp = requests.post("https://ipnpb.paypal.com/cgi-bin/webscr", data=verify_params)
    if resp.text != "VERIFIED":
        logger.warning("IPN Verification failed")
        return Response("IPN Verification failed", status=400)

    payment_status = ipn_data.get("payment_status")
    if payment_status != "Completed":
        logger.info(f"Payment not completed: {payment_status}")
        return Response("Payment not completed", status=200)

    item_name = ipn_data.get("item_name", "")
    txn_id = ipn_data.get("txn_id", "")
    mc_gross = ipn_data.get("mc_gross", "")

    if not item_name.startswith("leads_purchase_"):
        logger.warning("Invalid item_name format")
        return Response("Invalid item_name format", status=400)

    try:
        chat_id = int(item_name.split("_")[-1])
    except Exception as e:
        logger.error(f"Invalid chat_id in item_name: {e}")
        return Response("Invalid chat_id", status=400)

    if chat_id not in user_orders:
        logger.warning(f"No order found for chat_id {chat_id}")
        return Response("Order not found", status=404)

    order = user_orders[chat_id]
    if float(mc_gross) != order["total"]:
        logger.warning(f"Payment amount mismatch: {mc_gross} vs {order['total']}")
        return Response("Amount mismatch", status=400)

    if order.get("txn_id") == txn_id:
        logger.info(f"Duplicate txn_id {txn_id} ignored")
        return Response("Duplicate txn", status=200)

    order["paid"] = True
    order["txn_id"] = txn_id

    # Send leads asynchronously
    asyncio.run(send_leads_to_buyer(chat_id))

    logger.info(f"Payment verified for chat_id {chat_id}, txn_id {txn_id}")
    return Response("OK", status=200)


async def send_leads_to_buyer(chat_id):
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


# Register handlers
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("buy", buy))
telegram_app.add_handler(CallbackQueryHandler(category_toggle))


@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
async def webhook_handler():
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    await telegram_app.process_update(update)
    return "OK"


if __name__ == "__main__":
    import asyncio

    webhook_url = f"{BASE_URL}/webhook/{BOT_TOKEN}"

    async def setup_webhook():
        await telegram_app.bot.delete_webhook()
        await telegram_app.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to: {webhook_url}")

    asyncio.run(setup_webhook())

    # Run Flask app (Render will use PORT environment variable)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
