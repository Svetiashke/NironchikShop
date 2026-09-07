import os
import json
import math
import random
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode
from texts import get_text, set_lang, get_lang

load_dotenv()
TOKEN = os.getenv("TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ADMIN_GROUP = int(os.getenv("ADMIN_GROUP", "0"))
CARD_PRIVAT = os.getenv("CARD_PRIVAT")
CARD_MONO = os.getenv("CARD_MONO")
REVIEWS_GROUP = os.getenv("REVIEWS_GROUP")
REVIEWS_CHANNEL = os.getenv("REVIEWS_CHANNEL")

logging.basicConfig(level=logging.INFO)
logging.info(f"ADMIN_ID loaded: {ADMIN_ID} (type: {type(ADMIN_ID).__name__})")
logging.info(f"ADMIN_GROUP loaded: {ADMIN_GROUP}")

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
BALANCES_FILE = os.path.join(os.path.dirname(__file__), "balances.json")
TICKETS_FILE = os.path.join(os.path.dirname(__file__), "tickets.json")
HISTORY_FILE = os.path.join(os.path.dirname(__file__), "history.json")
REVIEWS_FILE = os.path.join(os.path.dirname(__file__), "reviews.json")
STATS_FILE = os.path.join(os.path.dirname(__file__), "stats.json")
GAME_STATS_FILE = os.path.join(os.path.dirname(__file__), "game_stats.json")

TICKET_REPLY_STATE = {}
REVIEW_STATE = {}


def load_reviews():
    if os.path.exists(REVIEWS_FILE):
        with open(REVIEWS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"counter": 0, "reviews": []}


def save_reviews(data):
    with open(REVIEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_review(user_id, username, rating, comment, amount):
    reviews = load_reviews()
    reviews["counter"] += 1
    review_id = reviews["counter"]
    import datetime
    reviews["reviews"].append({
        "id": review_id,
        "user_id": user_id,
        "username": username,
        "rating": rating,
        "comment": comment,
        "amount": amount,
        "time": datetime.datetime.now().strftime("%d.%m.%Y"),
    })
    save_reviews(reviews)
    return review_id


def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_stats(data):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def track_deposit(user_id, amount):
    stats = load_stats()
    uid = str(user_id)
    if uid not in stats:
        stats[uid] = {"deposits": 0, "withdrawals": 0, "turnover": 0, "deposit_count": 0, "withdrawal_count": 0}
    stats[uid]["deposits"] += amount
    stats[uid]["deposit_count"] += 1
    stats[uid]["turnover"] += amount
    save_stats(stats)


def track_withdrawal(user_id, amount):
    stats = load_stats()
    uid = str(user_id)
    if uid not in stats:
        stats[uid] = {"deposits": 0, "withdrawals": 0, "turnover": 0, "deposit_count": 0, "withdrawal_count": 0}
    stats[uid]["withdrawals"] += amount
    stats[uid]["withdrawal_count"] += 1
    stats[uid]["turnover"] += amount
    save_stats(stats)


def load_game_stats():
    if os.path.exists(GAME_STATS_FILE):
        with open(GAME_STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_game_stats(data):
    with open(GAME_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def track_game_result(user_id, game_name, bet, win):
    gs = load_game_stats()
    uid = str(user_id)
    if uid not in gs:
        gs[uid] = {}
    if game_name not in gs[uid]:
        gs[uid][game_name] = {"games": 0, "total_bet": 0, "total_win": 0, "max_win": 0, "max_loss": 0, "max_multiplier": 0}
    g = gs[uid][game_name]
    g["games"] += 1
    g["total_bet"] += bet
    g["total_win"] += win
    if win > g["max_win"]:
        g["max_win"] = win
    loss = bet - win
    if loss > g["max_loss"]:
        g["max_loss"] = loss
    if bet > 0:
        mult = win / bet
        if mult > g["max_multiplier"]:
            g["max_multiplier"] = mult
    save_game_stats(gs)


def get_user_stats(user_id):
    stats = load_stats()
    uid = str(user_id)
    s = stats.get(uid, {"deposits": 0, "withdrawals": 0, "turnover": 0, "deposit_count": 0, "withdrawal_count": 0})
    gs = load_game_stats()
    user_games = gs.get(uid, {})
    total_games = sum(g["games"] for g in user_games.values())
    total_bets = sum(g["total_bet"] for g in user_games.values())
    total_wins = sum(g["total_win"] for g in user_games.values())
    max_win = max((g["max_win"] for g in user_games.values()), default=0)
    max_mult = max((g["max_multiplier"] for g in user_games.values()), default=0)
    max_loss = max((g["max_loss"] for g in user_games.values()), default=0)
    rtp = (total_wins / total_bets * 100) if total_bets > 0 else 0
    avg_bet = (total_bets / total_games) if total_games > 0 else 0
    avg_win = (total_wins / total_games) if total_games > 0 else 0
    all_stats = load_stats()
    turnover_list = [(k, v.get("turnover", 0)) for k, v in all_stats.items()]
    turnover_list.sort(key=lambda x: x[1], reverse=True)
    rank = next((i + 1 for i, (k, _) in enumerate(turnover_list) if k == uid), len(turnover_list) + 1)
    rank_progress = min(100, (rank / max(1, len(turnover_list))) * 100)
    game_list = []
    for name, g in user_games.items():
        game_rtp = (g["total_win"] / g["total_bet"] * 100) if g["total_bet"] > 0 else 0
        game_list.append({
            "name": name,
            "games": g["games"],
            "total_bet": g["total_bet"],
            "win": g["total_win"] - g["total_bet"],
            "rtp": game_rtp,
        })
    return {
        "deposits": s["deposit_count"],
        "withdrawals": s["withdrawal_count"],
        "turnover": s["turnover"],
        "games_played": total_games,
        "total_bets": total_bets,
        "max_win": max_win,
        "max_loss": max_loss,
        "max_multiplier": round(max_mult, 1),
        "rtp": round(rtp, 1),
        "avg_bet": round(avg_bet, 0),
        "avg_win": round(avg_win, 0),
        "rank": rank,
        "rank_progress": round(rank_progress, 1),
        "games": game_list,
    }


def load_balances():
    if os.path.exists(BALANCES_FILE):
        with open(BALANCES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_balances(data):
    with open(BALANCES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_balance(user_id):
    balances = load_balances()
    return balances.get(str(user_id), 0)


def add_balance(user_id, amount):
    balances = load_balances()
    uid = str(user_id)
    balances[uid] = balances.get(uid, 0) + amount
    save_balances(balances)


def load_tickets():
    if os.path.exists(TICKETS_FILE):
        with open(TICKETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"counter": 0, "tickets": {}}


def save_tickets(data):
    with open(TICKETS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def create_ticket(user_id, username, text, photo_id=None):
    tickets = load_tickets()
    tickets["counter"] += 1
    ticket_id = tickets["counter"]
    tickets["tickets"][str(ticket_id)] = {
        "id": ticket_id,
        "user_id": user_id,
        "username": username,
        "text": text,
        "photo_id": photo_id,
        "status": "open",
        "admin_msg_id": None,
        "messages": [{"role": "user", "text": text, "time": __import__("datetime").datetime.now().strftime("%d.%m.%Y %H:%M")}],
    }
    save_tickets(tickets)
    return ticket_id


def add_ticket_message(ticket_id, role, text):
    tickets = load_tickets()
    ticket = tickets["tickets"].get(str(ticket_id))
    if ticket:
        if "messages" not in ticket:
            ticket["messages"] = []
        ticket["messages"].append({
            "role": role,
            "text": text,
            "time": __import__("datetime").datetime.now().strftime("%d.%m.%Y %H:%M"),
        })
        save_tickets(tickets)


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"transactions": []}


def save_history(data):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_history(user_id, action, amount, status="completed", details=""):
    history = load_history()
    import datetime
    history["transactions"].append({
        "user_id": user_id,
        "action": action,
        "amount": amount,
        "status": status,
        "details": details,
        "time": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
    })
    save_history(history)


def get_user_history(user_id):
    history = load_history()
    return [t for t in history["transactions"] if t["user_id"] == user_id]


def get_ticket(ticket_id):
    tickets = load_tickets()
    return tickets["tickets"].get(str(ticket_id))


def update_ticket(ticket_id, data):
    tickets = load_tickets()
    if str(ticket_id) in tickets["tickets"]:
        tickets["tickets"][str(ticket_id)].update(data)
        save_tickets(tickets)


def main_menu_keyboard(uid=None):
    games_btn = KeyboardButton("🎮 Ігри", style="danger")
    if uid and WEBAPP_URL:
        balance = get_balance(uid)
        games_url = WEBAPP_URL
        games_btn = KeyboardButton("🎮 Ігри", web_app=WebAppInfo(url=games_url))
    keyboard = [
        [
            KeyboardButton("💰 Купити", style="success"),
            KeyboardButton("💵 Вивести", style="success"),
            KeyboardButton("🪙 Продати", style="success"),
        ],
        [
            KeyboardButton("🧮 Порахувати", style="primary"),
            KeyboardButton("💬 Підтримка", style="primary"),
            KeyboardButton("👤 Профіль", style="primary"),
        ],
        [
            KeyboardButton("⭐ Відгуки", style="danger"),
            KeyboardButton("⚙️ Налаштування", style="danger"),
        ],
        [
            games_btn,
        ],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = get_text(uid, "menu_title")
    await update.message.reply_text(
        text, reply_markup=main_menu_keyboard(uid), parse_mode=ParseMode.MARKDOWN
    )


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    balance = get_balance(uid)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(uid, "profile_my_tickets"), callback_data="my_tickets")],
        [InlineKeyboardButton(get_text(uid, "profile_my_transactions"), callback_data="my_transactions")],
    ])
    await update.message.reply_text(
        get_text(uid, "profile_title", balance=balance),
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )


async def buy_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_amount"] = True
    photo_path = os.path.join(ASSETS_DIR, "buy.png")
    back_kb = ReplyKeyboardMarkup(
        [[KeyboardButton("🔙 Повернутися", style="primary")]],
        resize_keyboard=True,
    )
    with open(photo_path, "rb") as photo:
        await update.message.reply_photo(
            photo=photo,
            caption=(
                "💰 *Введіть суму покупки в UAH*\n\n"
                "Мінімальна сума поповнення: *52 грн*\n"
                "Комісію гри ми беремо на себе!"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb,
        )


async def support_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_ticket_text"] = True
    uid = update.effective_user.id
    await update.message.reply_text(
        get_text(uid, "support_title"),
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton(get_text(uid, "btn_back"), style="primary")]],
            resize_keyboard=True,
        ),
        parse_mode=ParseMode.MARKDOWN,
    )


def build_amount_text(amount, gold):
    return (
        f"✅ *Супер! до оплати:* {amount:.0f} грн\n"
        f"🪙 *Отримаєш:* {gold} г\n\n"
        f"Комісія гри на нас!\n\n"
        f"Оберіть спосіб оплати:"
    )


def build_amount_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Карта", callback_data="pay_card")],
        [InlineKeyboardButton("🔙 Повернутися", callback_data="back_to_buy")],
    ])


def build_bank_text():
    return "🏦 *Оберіть зручний банк для вас:*"


def build_bank_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏦 ПриватБанк", callback_data="bank_privat"),
            InlineKeyboardButton("🏦 МоноБанк", callback_data="bank_mono"),
        ],
        [InlineKeyboardButton("🔙 Повернутися", callback_data="back_to_amount")],
    ])


def build_requisites_text(bank_name, card, amount):
    return (
        f"💳 <b>Реквізити для оплати ({bank_name}):</b>\n\n"
        f"Номер картки:\n<code>{card}</code>\n\n"
        f"До оплати: <b>{amount:.0f} грн</b>\n\n"
        f"📩 Після оплати відправте сюди скріншот/квитанцію"
    )


def build_requisites_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Повернутися", callback_data="back_to_bank")],
    ])


async def ask_for_review(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data["user_id"]
    amount = job_data["amount"]

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1⭐", callback_data=f"review_rating_{user_id}_{amount}_1"),
            InlineKeyboardButton("2⭐", callback_data=f"review_rating_{user_id}_{amount}_2"),
            InlineKeyboardButton("3⭐", callback_data=f"review_rating_{user_id}_{amount}_3"),
            InlineKeyboardButton("4⭐", callback_data=f"review_rating_{user_id}_{amount}_4"),
            InlineKeyboardButton("5⭐", callback_data=f"review_rating_{user_id}_{amount}_5"),
        ],
    ])

    await context.bot.send_message(
        chat_id=user_id,
        text=get_text(user_id, "reviews_ask"),
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    uid = user.id

    if text == "🔙 Повернутися":
        context.user_data["awaiting_amount"] = False
        context.user_data["awaiting_ticket_text"] = False
        context.user_data["awaiting_ticket_photo"] = False
        context.user_data["awaiting_calc"] = False
        context.user_data["awaiting_withdraw_amount"] = False
        context.user_data["awaiting_withdraw_skin"] = False
        context.user_data["awaiting_sell_amount"] = False
        context.user_data["awaiting_sell_card"] = False
        context.user_data.pop("awaiting_ticket_reply", None)
        await update.message.reply_text(
            "🏠 *Головне меню*",
            reply_markup=main_menu_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if REVIEW_STATE.get(user.id):
        state = REVIEW_STATE[user.id]

        if state.get("awaiting_screenshot"):
            return

        rating = state["rating"]
        amount = state["amount"]
        state["comment"] = text
        state["awaiting_screenshot"] = True

        await update.message.reply_text(
            get_text(user.id, "review_screenshot_prompt"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if TICKET_REPLY_STATE.get(user.id):
        ticket_id = TICKET_REPLY_STATE[user.id]
        ticket = get_ticket(ticket_id)
        if not ticket or ticket["status"] == "closed":
            TICKET_REPLY_STATE.pop(user.id, None)
            await update.message.reply_text(
                get_text(user.id, "support_ticket_closed_user"),
                reply_markup=main_menu_keyboard(uid),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        admin_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Відповісти", callback_data=f"reply_ticket_{ticket_id}")],
            [InlineKeyboardButton("🔒 Закрити тікет", callback_data=f"close_ticket_{ticket_id}")],
        ])
        try:
            await context.bot.send_message(
                chat_id=ADMIN_GROUP,
                text=(
                    f"📨 *Повідомлення від користувача* (тікет #{ticket_id})\n\n"
                    f"👤 @{user.username or user.first_name} (ID: `{user.id}`)\n"
                    f"📝 {text}"
                ),
                reply_markup=admin_keyboard,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logging.error(f"Failed to forward ticket message to admin: {e}")

        add_ticket_message(ticket_id, "user", text)

        resolved_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Моє питання вирішено", callback_data=f"ticket_resolved_{ticket_id}")],
        ])
        await update.message.reply_text(
            get_text(user.id, "support_reply_sent"),
            reply_markup=resolved_kb,
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == "💰 Купити" or text.lower() == "купити":
        return await buy_entry(update, context)

    if text == "🪙 Продати" or text.lower() == "продати":
        context.user_data["awaiting_sell_amount"] = True
        photo_path = os.path.join(ASSETS_DIR, "sell.png")
        back_kb = ReplyKeyboardMarkup(
            [[KeyboardButton("🔙 Повернутися", style="primary")]],
            resize_keyboard=True,
        )
        try:
            with open(photo_path, "rb") as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=(
                        "🤑 *Введіть потрібну кількість голди, яку ви хочете продати:*\n\n"
                        "💡 Мінімум 500 голди"
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_kb,
                )
        except FileNotFoundError:
            await update.message.reply_text(
                "🤑 *Введіть потрібну кількість голди, яку ви хочете продати:*\n\n"
                "💡 Мінімум 500 голди",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_kb,
            )
        return

    if context.user_data.get("awaiting_sell_amount"):
        context.user_data["awaiting_sell_amount"] = False
        uid = update.effective_user.id
        text_clean = text.replace(" ", "").replace("г", "")
        try:
            amount = int(text_clean)
        except ValueError:
            await update.message.reply_text(get_text(uid, "sell_invalid_amount"))
            context.user_data["awaiting_sell_amount"] = True
            return

        if amount < 500:
            await update.message.reply_text(get_text(uid, "sell_min"))
            context.user_data["awaiting_sell_amount"] = True
            return

        uah = amount / 5
        context.user_data["sell_amount"] = amount
        context.user_data["sell_uah"] = uah
        context.user_data["awaiting_sell_card"] = True

        await update.message.reply_text(
            f"💰 *За продаж своїх {amount} голди ви отримаєте {uah:.2f} грн протягом 5 хвилин!*\n\n"
            f"👨‍💻 Для продажу надішліть реквізити картки — ми обробимо ваше замовлення. "
            f"Ми надішлемо вам скріншот скіна, який потрібно придбати. "
            f"Після того як ви його купите, надішліть нам скріншот покупки. "
            f"Після підтвердження ми відправимо вам кошти.\n\n"
            f"💳 Напишіть реквізити вашої картки:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("🔙 Повернутися", style="primary")]],
                resize_keyboard=True,
            ),
        )
        return

    if context.user_data.get("awaiting_sell_card"):
        context.user_data["awaiting_sell_card"] = False
        card_details = text
        amount = context.user_data.get("sell_amount", 0)
        uah = context.user_data.get("sell_uah", 0)
        user = update.effective_user

        context.user_data["awaiting_sell_skin"] = True

        admin_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "📸 Надіслати скрін користувачу",
                callback_data=f"sell_send_skin_{user.id}_{amount}"
            )],
            [InlineKeyboardButton(
                "✅ Кошти виплачені",
                callback_data=f"sell_paid_{user.id}_{amount}"
            )],
            [InlineKeyboardButton(
                "❌ Відхилити",
                callback_data=f"sell_reject_{user.id}_{amount}"
            )],
        ])

        await context.bot.send_message(
            chat_id=ADMIN_GROUP,
            text=(
                f"💸 *Запит на продаж!*\n\n"
                f"Користувач: @{user.username or user.first_name} (ID: `{user.id}`)\n"
                f"Голда: *{amount} г*\n"
                f"Сума: *{uah:.2f} грн*\n"
                f"Реквізити: `{card_details}`\n\n"
                f"Надішліть скрін скіна для покупки користувачу"
            ),
            reply_markup=admin_keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )

        await update.message.reply_text(
            "✅ *Заявку надіслано!*\n\n"
            "Зачекайте поки адмін надішле скрін скіна для покупки.",
            reply_markup=main_menu_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == "👤 Профіль" or text.lower() == "профіль":
        return await profile(update, context)

    if text == "💬 Підтримка" or text.lower() == "підтримка":
        return await support_entry(update, context)

    if text == "⭐ Відгуки" or text.lower() == "відгуки":
        uid = update.effective_user.id
        photo_path = os.path.join(ASSETS_DIR, "about.png")
        reviews_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(uid, "reviews_button"), url=REVIEWS_GROUP)],
        ])
        try:
            with open(photo_path, "rb") as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=get_text(uid, "reviews_title"),
                    reply_markup=reviews_kb,
                    parse_mode=ParseMode.MARKDOWN,
                )
        except FileNotFoundError:
            await update.message.reply_text(
                get_text(uid, "reviews_title"),
                reply_markup=reviews_kb,
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    if text == "⚙️ Налаштування" or text.lower() == "налаштування":
        uid = update.effective_user.id
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(uid, "settings_guide"), callback_data="settings_guide")],
            [InlineKeyboardButton(get_text(uid, "settings_language"), callback_data="settings_language")],
        ])
        await update.message.reply_text(
            get_text(uid, "settings_title"),
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == "🧮 Порахувати" or text.lower() == "порахувати":
        context.user_data["awaiting_calc"] = True
        uid = update.effective_user.id
        await update.message.reply_text(
            get_text(uid, "calc_title"),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton(get_text(uid, "btn_back"), style="primary")]],
                resize_keyboard=True,
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if context.user_data.get("awaiting_calc"):
        context.user_data["awaiting_calc"] = False
        uid = update.effective_user.id
        text_clean = text.replace(" ", "").replace("грн", "").replace("г", "")
        try:
            amount = float(text_clean.replace(",", "."))
        except ValueError:
            await update.message.reply_text(get_text(uid, "calc_invalid"))
            context.user_data["awaiting_calc"] = True
            return

        gold = math.floor(amount * 2.94)
        await update.message.reply_text(
            get_text(uid, "calc_result", amount=f"{amount:.0f}", gold=gold),
            reply_markup=main_menu_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if text == "💵 Вивести" or text.lower() == "вивести":
        balance = get_balance(update.effective_user.id)
        if balance <= 0:
            await update.message.reply_text(
                "❌ *Недостатньо голди для виводу*\n\n"
                f"Ваш баланс: *{balance} г*\n"
                "Спочатку поповніть баланс.",
                reply_markup=main_menu_keyboard(uid),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        context.user_data["awaiting_withdraw_amount"] = True
        photo_path = os.path.join(ASSETS_DIR, "withdraw.png")
        back_kb = ReplyKeyboardMarkup(
            [[KeyboardButton("🔙 Повернутися", style="primary")]],
            resize_keyboard=True,
        )
        try:
            with open(photo_path, "rb") as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=(
                        f"💵 *Вивід голди*\n\n"
                        f"Ваш баланс: *{balance} г*\n\n"
                        f"Введіть суму голди, яку хочете вивести:"
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_kb,
                )
        except FileNotFoundError:
            await update.message.reply_text(
                f"💵 *Вивід голди*\n\n"
                f"Ваш баланс: *{balance} г*\n\n"
                f"Введіть суму голди, яку хочете вивести:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_kb,
            )
        return

    if context.user_data.get("awaiting_withdraw_amount"):
        context.user_data["awaiting_withdraw_amount"] = False
        uid = update.effective_user.id
        text_clean = text.replace(" ", "").replace("г", "")
        try:
            amount = int(text_clean)
        except ValueError:
            await update.message.reply_text(get_text(uid, "withdraw_invalid"))
            context.user_data["awaiting_withdraw_amount"] = True
            return

        balance = get_balance(uid)
        if amount > balance:
            await update.message.reply_text(
                get_text(uid, "withdraw_insufficient", balance=balance),
                parse_mode=ParseMode.MARKDOWN,
            )
            context.user_data["awaiting_withdraw_amount"] = True
            return

        if amount < 100:
            await update.message.reply_text(
                get_text(uid, "withdraw_min"),
                parse_mode=ParseMode.MARKDOWN,
            )
            context.user_data["awaiting_withdraw_amount"] = True
            return

        if amount <= 0:
            await update.message.reply_text(get_text(uid, "withdraw_zero"))
            context.user_data["awaiting_withdraw_amount"] = True
            return

        skin_price = amount / 0.8
        kopecks = random.randint(1, 99)
        skin_price_int = int(skin_price)
        skin_price_full = f"{skin_price_int}.{kopecks:02d}"
        context.user_data["withdraw_amount"] = amount
        context.user_data["withdraw_skin_price"] = skin_price_full
        context.user_data["awaiting_withdraw_skin"] = True

        photo_path = os.path.join(ASSETS_DIR, "withdraw_example.png")
        try:
            with open(photo_path, "rb") as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=(
                        "🌟 *Чудово!*\n\n"
                        f"🍯 Купуйте та виставляйте Berettas «Damascus» за *{skin_price_full}G* "
                        f"щоб отримати *{amount} г* після комісії ринка\n\n"
                        "⚠️ Скриншот скіна має виглядати як на прикладі вище ☝️\n\n"
                        "✅ Для швидкого виводу ставте скін із наклейками\n"
                        "✅ Надішліть скріншот скіна сюди в чат"
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                )
        except FileNotFoundError:
            await update.message.reply_text(
                "🌟 *Чудово!*\n\n"
                f"🍯 Купуйте та виставляйте Berettas «Damascus» за *{skin_price_full}G* "
                f"щоб отримати *{amount} г* після комісії ринка\n\n"
                "⚠️ Скриншот скіна має виглядати як на прикладі вище ☝️\n\n"
                "✅ Для швидкого виводу ставте скін із наклейками\n"
                "✅ Надішліть скріншот скіна сюди в чат",
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    if context.user_data.get("awaiting_ticket_text"):
        context.user_data["awaiting_ticket_text"] = False
        context.user_data["awaiting_ticket_photo"] = True
        context.user_data["ticket_text"] = text

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Надіслати", callback_data="ticket_send")],
            [InlineKeyboardButton("❌ Скасувати", callback_data="ticket_cancel")],
        ])

        await update.message.reply_text(
            f"📝 *Ваше повідомлення:*\n\n{text}\n\n"
            f"Бажаєте прикріпити фото? Надішліть його або натисніть *\"Надіслати\"*",
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if context.user_data.get("awaiting_ticket_photo"):
        if text.lower() in ("надіслати", "send"):
            context.user_data["awaiting_ticket_photo"] = False
            ticket_text = context.user_data.get("ticket_text", "")
            ticket_id = create_ticket(user.id, user.username, ticket_text)
            context.user_data.pop("ticket_text", None)

            admin_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "💬 Відповісти",
                    callback_data=f"reply_ticket_{ticket_id}"
                )],
            ])

            await context.bot.send_message(
                chat_id=ADMIN_GROUP,
                text=(
                    f"🎫 *Новий тікет #{ticket_id}*\n\n"
                    f"Користувач: @{user.username or user.first_name} (ID: `{user.id}`)\n"
                    f"Повідомлення:\n{ticket_text}"
                ),
                reply_markup=admin_keyboard,
                parse_mode=ParseMode.MARKDOWN,
            )

            await update.message.reply_text(
                get_text(user.id, "support_ticket_created", id=ticket_id),
                reply_markup=main_menu_keyboard(uid),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

    ticket_match = None
    if text.startswith("#"):
        try:
            ticket_match = int(text[1:])
        except ValueError:
            pass

    if ticket_match:
        ticket = get_ticket(ticket_match)
        if ticket:
            status = ticket["status"]
            if status == "open":
                status_text = get_text(user.id, "status_open")
            elif status == "answered":
                status_text = get_text(user.id, "status_answered")
            else:
                status_text = get_text(user.id, "status_closed")

            history_text = ""
            messages = ticket.get("messages", [])
            if messages:
                history_text = "\n\n📜 *Історія повідомлень:*\n\n"
                for msg in messages:
                    role = "👤" if msg["role"] == "user" else "👨‍💼"
                    history_text += f"{role} [{msg.get('time', '?')}]: {msg['text']}\n\n"
            else:
                history_text = f"\n\n📝 Повідомлення: {ticket['text']}"

            await update.message.reply_text(
                f"🎫 *Тікет #{ticket_match}*\n\n"
                f"Статус: {status_text}"
                f"{history_text}",
                reply_markup=main_menu_keyboard(uid),
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            uid = update.effective_user.id
            await update.message.reply_text(
                get_text(uid, "support_not_found"),
                reply_markup=main_menu_keyboard(uid),
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    if context.user_data.get("awaiting_amount"):
        context.user_data["awaiting_amount"] = False
        uid = update.effective_user.id
        text_clean = text.replace(" ", "").replace(" грн", "").replace("г", "")
        try:
            amount = float(text_clean.replace(",", "."))
        except ValueError:
            await update.message.reply_text(get_text(uid, "buy_invalid_amount"))
            context.user_data["awaiting_amount"] = True
            return

        if amount < 52:
            await update.message.reply_text(get_text(uid, "buy_min"))
            context.user_data["awaiting_amount"] = True
            return

        gold = math.floor(amount * 2.94)
        context.user_data["amount"] = amount
        context.user_data["gold"] = gold

        await update.message.reply_text(
            build_amount_text(amount, gold),
            reply_markup=build_amount_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(
        get_text(update.effective_user.id, "menu_fallback"),
        reply_markup=main_menu_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN,
    )


async def forward_user_photo_to_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    ticket_id = TICKET_REPLY_STATE.get(user.id)
    ticket = get_ticket(ticket_id)

    if not ticket or ticket["status"] == "closed":
        TICKET_REPLY_STATE.pop(user.id, None)
        await update.message.reply_text(
            get_text(user.id, "ticket_closed_short"),
            reply_markup=main_menu_keyboard(uid),
        )
        return

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    else:
        file_id = update.message.document.file_id

    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Відповісти", callback_data=f"reply_ticket_{ticket_id}")],
        [InlineKeyboardButton("🔒 Закрити тікет", callback_data=f"close_ticket_{ticket_id}")],
    ])
    await context.bot.send_photo(
        chat_id=ADMIN_GROUP,
        photo=file_id,
        caption=(
            f"📸 *Фото від користувача* (тікет #{ticket_id})\n\n"
            f"👤 @{user.username or user.first_name} (ID: `{user.id}`)"
        ),
        reply_markup=admin_keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )

    resolved_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Моє питання вирішено", callback_data=f"ticket_resolved_{ticket_id}")],
    ])
    await update.message.reply_text(
        "✅ Фото надіслано адміністратору.",
        reply_markup=resolved_kb,
    )


async def handle_review_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    state = REVIEW_STATE[user.id]
    rating = state["rating"]
    amount = state["amount"]
    comment = state["comment"]

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    else:
        file_id = update.message.document.file_id

    stars = "⭐️" * rating
    review_id = add_review(user.id, user.username, rating, comment, amount)
    username_display = f"@{user.username}" if user.username else user.first_name

    review_text = (
        f"📊№{review_id}\n\n"
        f"🆔Клієнт: {username_display}\n"
        f"📝Коментар:\n{comment}\n\n"
        f"Оцінка: {stars}\n\n"
        f"Виведено: {amount}G. {__import__('datetime').datetime.now().strftime('%d.%m.%Y')}"
    )

    try:
        await context.bot.send_photo(
            chat_id=REVIEWS_CHANNEL,
            photo=file_id,
            caption=review_text,
        )
    except Exception as e:
        logging.error(f"Failed to send review to channel: {e}")

    REVIEW_STATE.pop(user.id, None)

    reward = random.randint(1, 100)
    if reward > 10:
        reward = random.randint(1, 10)

    reward_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user.id, "review_reward_button"), callback_data=f"review_reward_{user.id}_{reward}")],
    ])

    await update.message.reply_text(
        get_text(user.id, "review_thanks_with_reward", stars=stars),
        reply_markup=reward_kb,
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_ticket_photo_or_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if REVIEW_STATE.get(user.id) and REVIEW_STATE[user.id].get("awaiting_screenshot"):
        return await handle_review_screenshot(update, context)

    if context.user_data.get("awaiting_ticket_photo"):
        return await handle_ticket_photo(update, context)

    if TICKET_REPLY_STATE.get(update.effective_user.id):
        return await forward_user_photo_to_ticket(update, context)

    if context.user_data.get("awaiting_withdraw_skin"):
        return await handle_withdraw_skin(update, context)

    if context.user_data.get("awaiting_sell_buy_screenshot"):
        return await handle_sell_buy_screenshot(update, context)

    if context.user_data.get("amount") and context.user_data.get("gold"):
        return await handle_check(update, context)


async def handle_sell_buy_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_sell_buy_screenshot"):
        return

    user = update.effective_user
    uid = user.id
    amount = context.user_data.get("sell_buy_amount", 0)

    context.user_data["awaiting_sell_buy_screenshot"] = False
    context.user_data.pop("sell_buy_amount", None)

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    else:
        file_id = update.message.document.file_id

    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Кошти виплачені",
            callback_data=f"sell_paid_{user.id}_{amount}"
        )],
        [InlineKeyboardButton(
            "❌ Відхилити",
            callback_data=f"sell_reject_{user.id}_{amount}"
        )],
    ])

    try:
        await context.bot.send_message(
            chat_id=ADMIN_GROUP,
            text=(
                f"🔔 *Користувач надіслав скрін покупки!*\n\n"
                f"Користувач: @{user.username or user.first_name} (ID: `{user.id}`)\n"
                f"Голда: *{amount} г*\n\n"
                f"Перевірте скрін та підтвердіть виплату"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        await context.bot.send_photo(
            chat_id=ADMIN_GROUP,
            photo=file_id,
            reply_markup=admin_keyboard,
        )
    except Exception as e:
        logging.error(f"Failed to send buy screenshot to admin: {e}")

    await update.message.reply_text(
        "✅ *Скріншот надіслано!*\n\n"
        "Чекайте на підтвердження від адміна.",
        reply_markup=main_menu_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_withdraw_skin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_withdraw_skin"):
        return

    user = update.effective_user
    uid = user.id
    amount = context.user_data.get("withdraw_amount", 0)
    skin_price = context.user_data.get("withdraw_skin_price", 0)

    context.user_data["awaiting_withdraw_skin"] = False
    context.user_data.pop("withdraw_amount", None)
    context.user_data.pop("withdraw_skin_price", None)

    add_balance(user.id, -amount)
    track_withdrawal(user.id, amount)

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    else:
        file_id = update.message.document.file_id

    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Виведено",
            callback_data=f"withdraw_done_{user.id}_{amount}"
        )],
        [InlineKeyboardButton(
            "❌ Відхилити",
            callback_data=f"withdraw_reject_{user.id}_{amount}"
        )],
    ])

    await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=(
            f"💸 *Запит на вивід!*\n\n"
            f"Користувач: @{user.username or user.first_name} (ID: `{user.id}`)\n"
            f"Сума виводу: *{amount} г*\n"
            f"Ціна скіна: *{skin_price} г*"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )
    await context.bot.send_photo(
        chat_id=ADMIN_GROUP,
        photo=file_id,
        reply_markup=admin_keyboard,
    )

    await update.message.reply_text(
        "🚀 *Ви зробили вивід!*\n\n"
        "✅ Вам не потрібно нічого робити, голда сама прийде на ваш баланс через 5-60 хвилин!\n\n"
        "⚠️ Не скасовуйте/не переставляйте скін і не змінюйте аватарку під час виведення.\n\n"
        "⚠️ Якщо Ви помилилися з копійками і вже надіслали скрін – нічого не робіть!",
        reply_markup=main_menu_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_ticket_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_ticket_photo"):
        return

    user = update.effective_user
    uid = user.id
    ticket_text = context.user_data.get("ticket_text", "")

    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
    else:
        photo_id = update.message.document.file_id

    ticket_id = create_ticket(user.id, user.username, ticket_text, photo_id)
    context.user_data["awaiting_ticket_photo"] = False
    context.user_data.pop("ticket_text", None)

    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "💬 Відповісти",
            callback_data=f"reply_ticket_{ticket_id}"
        )],
    ])

    await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=(
            f"🎫 *Новий тікет #{ticket_id}*\n\n"
            f"Користувач: @{user.username or user.first_name} (ID: `{user.id}`)\n"
            f"Повідомлення:\n{ticket_text}"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )
    await context.bot.send_photo(
        chat_id=ADMIN_GROUP,
        photo=photo_id,
        reply_markup=admin_keyboard,
    )

    await update.message.reply_text(
        f"✅ *Тікет #{ticket_id} створено!*\n\n"
        f"Номер вашого тікета: *#{ticket_id}*\n"
        f"Збережіть його для перевірки статусу.\n\n"
        f"Наші співробітники зв'яжуться з вами найближчим часом.",
        reply_markup=main_menu_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN,
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    msg = query.message
    uid = update.effective_user.id
    logging.info(f"Callback received: data={data}, user={uid}, chat={msg.chat_id}")

    if data == "back_to_buy":
        try:
            photo_path = os.path.join(ASSETS_DIR, "buy.png")
            with open(photo_path, "rb") as photo:
                await msg.delete()
                context.user_data["awaiting_amount"] = True
                back_kb = ReplyKeyboardMarkup(
                    [[KeyboardButton("🔙 Повернутися", style="primary")]],
                    resize_keyboard=True,
                )
                await context.bot.send_photo(
                    chat_id=msg.chat_id,
                    photo=photo,
                    caption=(
                        "💰 *Введіть суму покупки в UAH*\n\n"
                        "Мінімальна сума поповнення: *52 грн*\n"
                        "Комісію гри ми беремо на себе!"
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_kb,
                )
        except Exception as e:
            logging.error(f"Error in back_to_buy: {e}")

    elif data == "pay_card":
        try:
            await msg.edit_text(
                build_bank_text(),
                reply_markup=build_bank_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logging.error(f"Error in pay_card: {e}")

    elif data == "back_to_amount":
        try:
            amount = context.user_data.get("amount", 0)
            gold = context.user_data.get("gold", 0)
            await msg.edit_text(
                build_amount_text(amount, gold),
                reply_markup=build_amount_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logging.error(f"Error in back_to_amount: {e}")

    elif data in ("bank_privat", "bank_mono"):
        try:
            if data == "bank_privat":
                card = CARD_PRIVAT
                bank_name = "ПриватБанк"
            else:
                card = CARD_MONO
                bank_name = "МоноБанк"

            await msg.edit_text(
                build_requisites_text(bank_name, card, context.user_data.get("amount", 0)),
                reply_markup=build_requisites_keyboard(),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logging.error(f"Error in bank selection: {e}")

    elif data == "back_to_bank":
        try:
            await msg.edit_text(
                build_bank_text(),
                reply_markup=build_bank_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logging.error(f"Error in back_to_bank: {e}")

    elif data.startswith("approve_"):
        logging.info(f"Admin {update.effective_user.id} clicked approve. Data: {data}")
        if update.effective_user.id != ADMIN_ID:
            logging.warning(f"Non-admin {update.effective_user.id} tried to approve")
            return

        parts = data.split("_")
        user_id = int(parts[1])
        gold = int(parts[2])

        add_balance(user_id, gold)
        track_deposit(user_id, gold)
        balance = get_balance(user_id)
        add_history(user_id, "Покупка голди", gold, "completed", f"Нараховано {gold}г")

        try:
            photo_path = os.path.join(ASSETS_DIR, "accept.png")
            with open(photo_path, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=(
                        f"🎉 *Оплату підтверджено!*\n\n"
                        f"Вам нараховано *{gold} г*!\n"
                        f"Поточний баланс: *{balance} г*\n\n"
                        f"Дякуємо за покупку!"
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_menu_keyboard(uid),
                )
            logging.info(f"Approval message sent to user {user_id}")
        except Exception as e:
            logging.error(f"Failed to send message to user {user_id}: {e}")

        await msg.delete()
        await context.bot.send_message(
            chat_id=ADMIN_GROUP,
            text=(
                f"✅ *Чек закрито*\n\n"
                f"Статус: ✅ Підтверджено\n"
                f"Користувач: {user_id}\n"
                f"Нараховано: {gold}г\n"
                f"Баланс користувача: {balance}г"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("reject_"):
        logging.info(f"Admin {update.effective_user.id} clicked reject. Data: {data}")
        if update.effective_user.id != ADMIN_ID:
            logging.warning(f"Non-admin {update.effective_user.id} tried to reject")
            return

        parts = data.split("_")
        user_id = int(parts[1])

        try:
            photo_path = os.path.join(ASSETS_DIR, "cancell.png")
            with open(photo_path, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=(
                        "❌ *Оплату не підтверджено*\n\n"
                        "Якщо ви вважаєте, що це помилка — зверніться до підтримки."
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_menu_keyboard(uid),
                )
            logging.info(f"Rejection message sent to user {user_id}")
        except Exception as e:
            logging.error(f"Failed to send message to user {user_id}: {e}")

        await msg.delete()
        await context.bot.send_message(
            chat_id=ADMIN_GROUP,
            text=(
                f"❌ *Чек закрито*\n\n"
                f"Статус: ❌ Відхилено\n"
                f"Користувач: {user_id}"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "ticket_send":
        if context.user_data.get("awaiting_ticket_photo"):
            context.user_data["awaiting_ticket_photo"] = False
            ticket_text = context.user_data.get("ticket_text", "")
            user = update.effective_user
            ticket_id = create_ticket(user.id, user.username, ticket_text)
            context.user_data.pop("ticket_text", None)

            admin_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "💬 Відповісти",
                    callback_data=f"reply_ticket_{ticket_id}"
                )],
            ])

            await context.bot.send_message(
                chat_id=ADMIN_GROUP,
                text=(
                    f"🎫 *Новий тікет #{ticket_id}*\n\n"
                    f"Користувач: @{user.username or user.first_name} (ID: `{user.id}`)\n"
                    f"Повідомлення:\n{ticket_text}"
                ),
                reply_markup=admin_keyboard,
                parse_mode=ParseMode.MARKDOWN,
            )

            await msg.edit_text(
                f"✅ *Тікет #{ticket_id} створено!*\n\n"
                f"Номер вашого тікета: *#{ticket_id}*\n"
                f"Збережіть його для перевірки статусу.",
                reply_markup=None,
                parse_mode=ParseMode.MARKDOWN,
            )
            await context.bot.send_message(
                chat_id=msg.chat_id,
                text="🏠 *Головне меню*",
                reply_markup=main_menu_keyboard(uid),
                parse_mode=ParseMode.MARKDOWN,
            )

    elif data == "ticket_cancel":
        context.user_data["awaiting_ticket_photo"] = False
        context.user_data.pop("ticket_text", None)
        await msg.edit_text("❌ Створення тікета скасовано.", reply_markup=None)
        await context.bot.send_message(
            chat_id=msg.chat_id,
            text="🏠 *Головне меню*",
            reply_markup=main_menu_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("reply_ticket_"):
        if update.effective_user.id != ADMIN_ID:
            return

        ticket_id = int(data.split("_")[2])
        ticket = get_ticket(ticket_id)

        if not ticket:
            try:
                await msg.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=ADMIN_GROUP,
                text="❌ Тікет не знайдено.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        context.user_data["replying_to_ticket"] = ticket_id
        try:
            await msg.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=ADMIN_GROUP,
            text=(
                f"💬 *Відповідь на тікет #{ticket_id}*\n\n"
                f"Напишіть повідомлення користувачу:"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("close_ticket_"):
        if update.effective_user.id != ADMIN_ID:
            return

        ticket_id = int(data.split("_")[2])
        ticket = get_ticket(ticket_id)

        if not ticket:
            return

        if ticket["status"] == "closed":
            try:
                await msg.edit_text(
                    f"🔒 *Тікет #{ticket_id} вже закрито*",
                    reply_markup=None,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            return

        update_ticket(ticket_id, {"status": "closed"})
        user_id = ticket["user_id"]
        TICKET_REPLY_STATE.pop(user_id, None)

        await msg.edit_text(
            f"🔒 *Тікет #{ticket_id} закрито*",
            reply_markup=None,
            parse_mode=ParseMode.MARKDOWN,
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"🔒 *Тікет #{ticket_id} закрито*\n\n"
                    f"Дякуємо за звернення!"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_keyboard(uid),
            )
        except Exception as e:
            logging.error(f"Failed to close ticket message: {e}")

    elif data.startswith("ticket_resolved_"):
        ticket_id = int(data.split("_")[2])
        user_id = update.effective_user.id
        ticket = get_ticket(ticket_id)

        if not ticket or ticket["user_id"] != user_id:
            return

        if ticket["status"] == "closed":
            try:
                await msg.edit_text(
                    get_text(user_id, "support_ticket_already_closed", id=ticket_id),
                    reply_markup=None,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            return

        update_ticket(ticket_id, {"status": "closed"})
        TICKET_REPLY_STATE.pop(user_id, None)

        try:
            await msg.edit_text(
                get_text(user_id, "support_resolved", id=ticket_id),
                reply_markup=None,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

        admin_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔒 Закрити тікет", callback_data=f"close_ticket_{ticket_id}")],
        ])
        try:
            await context.bot.send_message(
                chat_id=ADMIN_GROUP,
                text=(
                    f"🔒 *Тікет #{ticket_id} закрито користувачем*\n\n"
                    f"👤 @{ticket.get('username') or user_id}"
                ),
                reply_markup=admin_keyboard,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logging.error(f"Failed to notify admin about ticket close: {e}")

    elif data.startswith("review_rating_"):
        parts = data.split("_")
        user_id = int(parts[2])
        amount = int(parts[3])
        rating = int(parts[4])

        if update.effective_user.id != user_id:
            return

        REVIEW_STATE[user_id] = {"rating": rating, "amount": amount}

        stars = "⭐️" * rating
        try:
            await msg.edit_text(
                f"Оцінка: {stars}\n\n"
                + get_text(user_id, "review_comment_prompt"),
                reply_markup=None,
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"Оцінка: {stars}\n\n"
                    + get_text(user_id, "review_comment_prompt")
                ),
            )

    elif data.startswith("review_reward_"):
        parts = data.split("_")
        user_id = int(parts[2])
        reward = int(parts[3])

        if update.effective_user.id != user_id:
            return

        add_balance(user_id, reward)
        balance = get_balance(user_id)

        try:
            await msg.edit_text(
                get_text(user_id, "review_reward_received", amount=reward, balance=balance),
                reply_markup=None,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user_id,
                text=get_text(user_id, "review_reward_received", amount=reward, balance=balance),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_keyboard(uid),
            )

    elif data.startswith("withdraw_done_"):
        if update.effective_user.id != ADMIN_ID:
            return

        parts = data.split("_")
        user_id = int(parts[2])
        amount = int(parts[3])

        add_history(user_id, "Виведення", amount, "completed", f"Виведено {amount}г")

        await msg.delete()
        await context.bot.send_message(
            chat_id=ADMIN_GROUP,
            text=(
                f"✅ *Вивід виконано*\n\n"
                f"Користувач: {user_id}\n"
                f"Сума: {amount}г"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ *Вивід виконано!*\n\n"
                    f"Вам виведено *{amount} г*.\n"
                    "Дякуємо за користування нашим сервісом!"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_keyboard(uid),
            )
            context.job_queue.run_once(
                ask_for_review,
                when=60,
                data={"user_id": user_id, "amount": amount},
                name=f"review_{user_id}",
            )
        except Exception as e:
            logging.error(f"Failed to send withdraw done: {e}")

    elif data.startswith("withdraw_reject_"):
        if update.effective_user.id != ADMIN_ID:
            return

        parts = data.split("_")
        user_id = int(parts[2])
        amount = int(parts[3])

        add_balance(user_id, amount)

        await msg.delete()
        await context.bot.send_message(
            chat_id=ADMIN_GROUP,
            text=(
                f"❌ *Вивід відхилено*\n\n"
                f"Користувач: {user_id}\n"
                f"Сума повернено: {amount}г"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "❌ *Вивід відхилено*\n\n"
                    f"Ваш вивід *{amount} г* було відхилено.\n"
                    "Кошти повернено на баланс.\n"
                    "Якщо виникли питання — зверніться до підтримки."
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_keyboard(uid),
            )
        except Exception as e:
            logging.error(f"Failed to send withdraw reject: {e}")

    elif data.startswith("sell_paid_"):
        if update.effective_user.id != ADMIN_ID:
            return

        parts = data.split("_")
        user_id = int(parts[2])
        amount = int(parts[3])
        uah = amount / 5

        add_history(user_id, "Продажа скіна", amount, "completed", f"Виплачено {uah:.2f} грн за {amount}г")

        await msg.delete()
        await context.bot.send_message(
            chat_id=ADMIN_GROUP,
            text=(
                f"✅ *Кошти виплачено!*\n\n"
                f"Користувач: {user_id}\n"
                f"Сума: {uah:.2f} грн"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ *Кошти виплачено!*\n\n"
                    f"Вам виплачено *{uah:.2f} грн* за *{amount} г*.\n"
                    "Дякуємо за користування нашим сервісом!"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_keyboard(uid),
            )
        except Exception as e:
            logging.error(f"Failed to send sell paid: {e}")

    elif data.startswith("sell_reject_"):
        if update.effective_user.id != ADMIN_ID:
            return

        parts = data.split("_")
        user_id = int(parts[2])
        amount = int(parts[3])

        await msg.delete()
        await context.bot.send_message(
            chat_id=ADMIN_GROUP,
            text=(
                f"❌ *Продаж відхилено*\n\n"
                f"Користувач: {user_id}\n"
                f"Сума: {amount}г"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "❌ *Продаж відхилено*\n\n"
                    f"Ваш продаж *{amount} г* було відхилено.\n"
                    "Якщо виникли питання — зверніться до підтримки."
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_keyboard(uid),
            )
        except Exception as e:
            logging.error(f"Failed to send sell reject: {e}")

    elif data.startswith("sell_send_skin_"):
        if update.effective_user.id != ADMIN_ID:
            return

        parts = data.split("_")
        user_id = int(parts[3])
        amount = int(parts[4])

        context.user_data["admin_sending_skin_to"] = user_id
        context.user_data["admin_selling_amount"] = amount

        await msg.edit_text(
            f"📸 *Надішліть скрін скіна для користувача {user_id}*\n\n"
            f"Надішліть фото в цей чат, і воно буде переслано користувачу.",
            reply_markup=None,
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("sell_confirm_buy_"):
        parts = data.split("_")
        user_id = int(parts[3])
        amount = int(parts[4])

        if update.effective_user.id != user_id:
            return

        context.user_data["awaiting_sell_buy_screenshot"] = True
        context.user_data["sell_buy_amount"] = amount

        try:
            await msg.delete()
        except Exception:
            pass

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "📸 *Надішліть скріншот покупки*\n\n"
                "Зробіть скріншот того, що ви придбали скін, та надішліть його сюди."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "my_tickets":
        user_id = update.effective_user.id
        tickets = load_tickets()
        user_tickets = [t for t in tickets["tickets"].values() if t["user_id"] == user_id]

        if not user_tickets:
            await msg.edit_text(
                get_text(user_id, "profile_no_tickets"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(get_text(user_id, "profile_back"), callback_data="back_to_profile")]
                ]),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        text_lines = ""
        for t in user_tickets[-10:]:
            status = t["status"]
            if status == "open":
                status_text = "🟢"
            elif status == "answered":
                status_text = "🔵"
            else:
                status_text = "🔴"
            text_lines += f"{status_text} #{t['id']} — {t['text'][:30]}...\n"

        await msg.edit_text(
            get_text(user_id, "profile_tickets_list", text=text_lines),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(get_text(user_id, "profile_back"), callback_data="back_to_profile")]
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "my_transactions":
        user_id = update.effective_user.id
        history = get_user_history(user_id)

        if not history:
            await msg.edit_text(
                get_text(user_id, "profile_no_transactions"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(get_text(user_id, "profile_back"), callback_data="back_to_profile")]
                ]),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        text_lines = ""
        for t in history[-10:]:
            text_lines += f"📅 {t['time']}\n"
            text_lines += f"📌 {t['action']}\n"
            text_lines += f"🪙 {t['amount']} г — {t['status']}\n\n"

        await msg.edit_text(
            get_text(user_id, "profile_transactions_list", text=text_lines),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(get_text(user_id, "profile_back"), callback_data="back_to_profile")]
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "back_to_profile":
        user = update.effective_user
        uid = user.id
        balance = get_balance(uid)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(uid, "profile_my_tickets"), callback_data="my_tickets")],
            [InlineKeyboardButton(get_text(uid, "profile_my_transactions"), callback_data="my_transactions")],
        ])
        await msg.edit_text(
            get_text(uid, "profile_title", balance=balance),
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "settings_guide":
        uid = update.effective_user.id
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(uid, "settings_back"), callback_data="settings_back")],
        ])
        await msg.edit_text(
            get_text(uid, "settings_guide_text"),
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "settings_language":
        uid = update.effective_user.id
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(uid, "settings_lang_uk"), callback_data="lang_uk")],
            [InlineKeyboardButton(get_text(uid, "settings_lang_ru"), callback_data="lang_ru")],
            [InlineKeyboardButton(get_text(uid, "settings_back"), callback_data="settings_back")],
        ])
        await msg.edit_text(
            get_text(uid, "settings_lang_select"),
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("lang_"):
        lang = data.split("_")[1]
        user_id = update.effective_user.id
        set_lang(user_id, lang)

        if lang == "uk":
            lang_name = "🇺🇦 Українська"
        else:
            lang_name = "🇷🇺 Російська"

        await msg.edit_text(
            get_text(user_id, "settings_lang_changed", lang=lang_name),
            reply_markup=None,
            parse_mode=ParseMode.MARKDOWN,
        )
        await context.bot.send_message(
            chat_id=user_id,
            text="🏠 *Головне меню*",
            reply_markup=main_menu_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "settings_back":
        uid = update.effective_user.id
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(uid, "settings_guide"), callback_data="settings_guide")],
            [InlineKeyboardButton(get_text(uid, "settings_language"), callback_data="settings_language")],
        ])
        await msg.edit_text(
            get_text(uid, "settings_title"),
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo and not update.message.document:
        await update.message.reply_text(get_text(update.effective_user.id, "check_photo_required"))
        return

    uid = update.effective_user.id
    photo_path = os.path.join(ASSETS_DIR, "check.png")
    with open(photo_path, "rb") as photo:
        await update.message.reply_photo(
            photo=photo,
            caption=(
                "✅ *Супер!*\n\n"
                "Зараз наші співробітники перевіряють ваш чек.\n"
                "Зазвичай це займає до 3 годин.\n\n"
                "Ми перевіряємо чеки в робочий час — з 11:00 до 00:00 по Києву."
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(uid),
        )

    amount = context.user_data.get("amount", 0)
    gold = context.user_data.get("gold", 0)
    user = update.effective_user

    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✅ Нарахувати {gold}г",
            callback_data=f"approve_{user.id}_{gold}"
        )],
        [InlineKeyboardButton(
            "❌ Відхилити",
            callback_data=f"reject_{user.id}"
        )],
    ])

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    else:
        file_id = update.message.document.file_id

    await context.bot.send_message(
        chat_id=ADMIN_GROUP,
        text=(
            f"🧾 *Новий чек!*\n\n"
            f"Користувач: @{user.username or user.first_name} (ID: `{user.id}`)\n"
            f"Сума: *{amount:.0f} грн*\n"
            f"Голд: *{gold} г*"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )
    await context.bot.send_photo(
        chat_id=ADMIN_GROUP,
        photo=file_id,
        reply_markup=admin_keyboard,
    )


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP:
        return
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.user_data.get("replying_to_ticket"):
        return

    ticket_id = context.user_data["replying_to_ticket"]
    context.user_data["replying_to_ticket"] = None

    ticket = get_ticket(ticket_id)
    if not ticket:
        return

    user_id = ticket["user_id"]
    reply_text = update.message.text

    update_ticket(ticket_id, {
        "status": "answered",
        "admin_reply": reply_text,
    })
    add_ticket_message(ticket_id, "admin", reply_text)

    try:
        resolved_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Моє питання вирішено", callback_data=f"ticket_resolved_{ticket_id}")],
        ])
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"💬 *Відповідь на тікет #{ticket_id}*\n\n"
                f"{reply_text}\n\n"
                f"📝 Ви можете продовжити розмову, надіславши повідомлення сюди.\n"
                f"Якщо питання вирішене — натисніть кнопку нижче."
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=resolved_kb,
        )
        TICKET_REPLY_STATE[user_id] = ticket_id
    except Exception as e:
        logging.error(f"Failed to send reply to user: {e}")

    close_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔒 Закрити тікет",
            callback_data=f"close_ticket_{ticket_id}"
        )],
    ])

    await update.message.reply_text(
        f"✅ *Відповідь надіслано користувачу {user_id}*",
        reply_markup=close_keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_admin_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP:
        return
    if update.effective_user.id != ADMIN_ID:
        return

    user_id = context.user_data.get("admin_sending_skin_to")
    amount = context.user_data.get("admin_selling_amount")

    if not user_id:
        return

    context.user_data["admin_sending_skin_to"] = None
    context.user_data["admin_selling_amount"] = None

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    else:
        file_id = update.message.document.file_id

    user_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🛒 Я купив",
            callback_data=f"sell_confirm_buy_{user_id}_{amount}"
        )],
    ])

    try:
        await context.bot.send_photo(
            chat_id=user_id,
            photo=file_id,
            caption=(
                "🛒 *Скрін скіна для покупки*\n\n"
                "Придбайте цей скін та надішліть нам скріншот покупки.\n"
                "Натисніть кнопку нижче коли купите:"
            ),
            reply_markup=user_keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
        await update.message.reply_text(
            f"✅ *Скрін надіслано користувачу {user_id}*",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logging.error(f"Failed to forward skin to user: {e}")
        await update.message.reply_text(
            f"❌ *Помилка при відправці користувачу {user_id}*",
            parse_mode=ParseMode.MARKDOWN,
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Exception while handling an update: {context.error}")


class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logging.info(f"API: {format % args}")

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            self._send_json({"status": "ok"})
            return

        if path.startswith("/api/"):
            api_path = path[5:]
            if api_path.startswith("balance/"):
                try:
                    uid = api_path.split("balance/")[1]
                    balance = get_balance(int(uid))
                    self._send_json({"balance": balance})
                except Exception as e:
                    self._send_json({"error": str(e)}, 500)
            elif api_path.startswith("stats/"):
                try:
                    uid = api_path.split("stats/")[1]
                    stats = get_user_stats(int(uid))
                    self._send_json(stats)
                except Exception as e:
                    self._send_json({"error": str(e)}, 500)
            elif api_path.startswith("game-stats/"):
                try:
                    uid = api_path.split("game-stats/")[1]
                    gs = load_game_stats()
                    user_games = gs.get(uid, {})
                    game_list = []
                    for name, g in user_games.items():
                        rtp = (g["total_win"] / g["total_bet"] * 100) if g["total_bet"] > 0 else 0
                        game_list.append({
                            "name": name, "games": g["games"],
                            "total_bet": g["total_bet"],
                            "win": g["total_win"] - g["total_bet"],
                            "rtp": rtp,
                        })
                    self._send_json({"games": game_list})
                except Exception as e:
                    self._send_json({"error": str(e)}, 500)
            else:
                self._send_json({"error": "not found"}, 404)
        else:
            self._serve_static(path)

    def _serve_static(self, path):
        WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")
        if path == "/": path = "/index.html"
        file_path = os.path.join(WEBAPP_DIR, path.lstrip("/"))
        file_path = os.path.normpath(file_path)
        if not file_path.startswith(WEBAPP_DIR):
            self._send_json({"error": "forbidden"}, 403); return
        MIME = {".html":"text/html",".css":"text/css",".js":"application/javascript",
                ".json":"application/json",".png":"image/png",".jpg":"image/jpeg",
                ".webp":"image/webp",".svg":"image/svg+xml",".ico":"image/x-icon"}
        ext = os.path.splitext(file_path)[1].lower()
        if os.path.isfile(file_path):
            ct = MIME.get(ext, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            with open(file_path, "rb") as f:
                self.wfile.write(f.read())
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            path = path[5:]

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        if path == "game-result":
            try:
                data = json.loads(body)
                uid = int(data.get("uid", 0))
                game = data.get("game", "unknown")
                bet = float(data.get("bet", 0))
                profit = float(data.get("profit", 0))
                win = bet + profit
                track_game_result(uid, game, bet, win)
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
        else:
            self._send_json({"error": "not found"}, 404)


def run_api_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), APIHandler)
    logging.info(f"API server running on port {port}")
    server.serve_forever()


def main():
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(
        filters.Chat(ADMIN_GROUP) & filters.TEXT & ~filters.COMMAND,
        handle_admin_reply
    ))
    app.add_handler(MessageHandler(
        filters.Chat(ADMIN_GROUP) & (filters.PHOTO | filters.Document.ALL),
        handle_admin_photo
    ))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_ticket_photo_or_check))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()


if __name__ == "__main__":
    main()
