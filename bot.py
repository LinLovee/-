import asyncio
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from game import (
    GameDB,
    KAGUNE_TYPES,
    can_eat_human,
    can_hunt,
    can_raid,
    do_hunt,
    eat_human,
    gacha_pull,
    kagune_help_text,
    normalize_hunt_style,
    normalize_kagune_key,
    normalize_raid_style,
    pvp_attack,
    raid_district,
    render_profile,
    train,
    upgrade_with_rc,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "/tmp/game.db")
DUEL_QUEUE: list[int] = []


def init_db() -> GameDB:
    try:
        return GameDB(DB_PATH)
    except sqlite3.OperationalError as err:
        fallback_path = "/tmp/game.db"
        print(f"Не удалось открыть БД по пути '{DB_PATH}': {err}")
        print(f"Переключаюсь на временную БД: {fallback_path}")
        return GameDB(fallback_path)


db = init_db()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):  # noqa: A003
        return


def run_health_server_if_needed() -> None:
    port_raw = os.getenv("PORT")
    if not port_raw:
        return

    try:
        port = int(port_raw)
    except ValueError:
        print(f"Некорректный PORT: {port_raw}. Healthcheck сервер не запущен.")
        return

    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Healthcheck server started on port {port}")


def ensure_event_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["👤 Профиль", "🏆 Топ игроков"],
            ["🗡 Охота: Агрессия", "🎯 Охота: Стелс", "⚖️ Охота: Баланс"],
            ["🚨 Рейд: Штурм", "🧨 Рейд: Саботаж", "👁 Рейд: Разведка"],
            ["🍖 Пожирание", "💪 Тренировка", "🎰 Гача"],
            ["⚔️ Найти дуэль", "❌ Выйти из дуэли", "ℹ️ Помощь"],
        ],
        resize_keyboard=True,
    )


def actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗡 Агрессия", callback_data="act:hunt:aggressive")],
            [InlineKeyboardButton("🎯 Стелс", callback_data="act:hunt:stealth")],
            [InlineKeyboardButton("⚖️ Баланс", callback_data="act:hunt:balanced")],
            [InlineKeyboardButton("🚨 Штурм", callback_data="act:raid:assault")],
            [InlineKeyboardButton("🧨 Саботаж", callback_data="act:raid:sabotage")],
            [InlineKeyboardButton("👁 Разведка", callback_data="act:raid:scout")],
            [InlineKeyboardButton("🍖 Пожирание", callback_data="act:eat")],
            [InlineKeyboardButton("💪 Тренировка", callback_data="act:train")],
            [InlineKeyboardButton("🎰 Гача", callback_data="act:gacha")],
            [InlineKeyboardButton("⚔️ Дуэль", callback_data="act:duel")],
        ]
    )






db = init_db()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):  # noqa: A003
        return


def run_health_server_if_needed() -> None:
    port_raw = os.getenv("PORT")
    if not port_raw:
        return

    try:
        port = int(port_raw)
    except ValueError:
        print(f"Некорректный PORT: {port_raw}. Healthcheck сервер не запущен.")
        return

    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Healthcheck server started on port {port}")


def ensure_event_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["/profile", "/top"],
            ["/hunt aggressive", "/hunt stealth", "/hunt balanced"],
            ["/raid assault", "/raid sabotage", "/raid scout"],
            ["/eat", "/train", "/gacha"],
            ["/duel", "/duel cancel", "/help"],
        ],
        resize_keyboard=True,
    )


def kagune_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, data in KAGUNE_TYPES.items():
        buttons.append([InlineKeyboardButton(f"{data['name']} ({key})", callback_data=f"pick:{key}")])
    return InlineKeyboardMarkup(buttons)


def init_db() -> GameDB:
    try:
        return GameDB(DB_PATH)
    except sqlite3.OperationalError as err:
        fallback_path = "/tmp/game.db"
        print(f"Не удалось открыть БД по пути '{DB_PATH}': {err}")
        print(f"Переключаюсь на временную БД: {fallback_path}")
        return GameDB(fallback_path)


db = init_db()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):  # noqa: A003
        return


def run_health_server_if_needed() -> None:
    port_raw = os.getenv("PORT")
    if not port_raw:
        return

    try:
        port = int(port_raw)
    except ValueError:
        print(f"Некорректный PORT: {port_raw}. Healthcheck сервер не запущен.")
        return

    port = int(port_raw)
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Healthcheck server started on port {port}")


def ensure_event_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["👤 Профиль", "🏆 Топ игроков"],
            ["🗡 Охота: Агрессия", "🎯 Охота: Стелс", "⚖️ Охота: Баланс"],
            ["🚨 Рейд: Штурм", "🧨 Рейд: Саботаж", "👁 Рейд: Разведка"],
            ["🍖 Пожирание", "💪 Тренировка", "🎰 Гача"],
            ["⚔️ Найти дуэль", "❌ Выйти из дуэли", "ℹ️ Помощь"],
        ],
        resize_keyboard=True,
    )


def actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗡 Агрессия", callback_data="act:hunt:aggressive")],
            [InlineKeyboardButton("🎯 Стелс", callback_data="act:hunt:stealth")],
            [InlineKeyboardButton("⚖️ Баланс", callback_data="act:hunt:balanced")],
            [InlineKeyboardButton("🚨 Штурм", callback_data="act:raid:assault")],
            [InlineKeyboardButton("🧨 Саботаж", callback_data="act:raid:sabotage")],
            [InlineKeyboardButton("👁 Разведка", callback_data="act:raid:scout")],
            [InlineKeyboardButton("🍖 Пожирание", callback_data="act:eat")],
            [InlineKeyboardButton("💪 Тренировка", callback_data="act:train")],
            [InlineKeyboardButton("🎰 Гача", callback_data="act:gacha")],
            [InlineKeyboardButton("⚔️ Дуэль", callback_data="act:duel")],
        ]
    )


def kagune_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, value in KAGUNE_TYPES.items():
        rows.append(
            [
                InlineKeyboardButton(
                    f"{value['name']} — {value['description'][:34]}…",
                    callback_data=f"pick:{key}",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


async def ensure_player(update: Update):
    user = update.effective_user
    if user is None:
        return None
    return db.get_player(user.id)


async def create_player_from_choice(update: Update, kagune_key: str) -> str:
    user = update.effective_user
    if user is None:
        return "Ошибка: пользователь не найден."
    user = update.effective_user
    if user is None:
        return "Ошибка: пользователь не найден."

    existing = db.get_player(user.id)
    if existing:
        return "Ты уже в игре. Нажми /profile, чтобы открыть профиль."

    username = user.username or user.full_name
    player = db.create_player(user.id, username, kagune_key)
    return (
        "✅ Персонаж создан!\n"
        f"Тип кагуне: {player.kagune}.\n"
        "Тебе доступно меню с кнопками — команды вручную вводить не обязательно.\n"
        "Начни с /hunt balanced или /duel."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return "Ошибка: пользователь не найден."

    if context.args:
        kagune_key = normalize_kagune_key(context.args[0])
        if not kagune_key or kagune_key not in KAGUNE_TYPES:
            await update.message.reply_text(
                "Неизвестный тип кагуне. Выбери кнопкой ниже.",
                reply_markup=kagune_keyboard(),
            )
            return
        text = await create_player_from_choice(update, kagune_key)
        await update.message.reply_text(text, reply_markup=main_keyboard())
        return

    existing = db.get_player(user.id)
    if existing:
        return "Ты уже в игре. Нажми «👤 Профиль» и продолжай прогрессию."

    username = user.username or user.full_name
    player = db.create_player(user.id, username, kagune_key)
    return (
        "✅ *Персонаж создан!*\n"
        f"Кагуне: *{player.kagune}*\n"
        "Тебе открыто главное меню действий.\n"
        "Начни с кнопки охоты или нажми «⚔️ Найти дуэль»."
    )

    username = user.username or user.full_name
    player = db.create_player(user.id, username, kagune_key)
    return (
        "✅ *Персонаж создан!*\n"
        f"Кагуне: *{player.kagune}*\n"
        "Тебе открыто главное меню действий.\n"
        "Начни с кнопки охоты или нажми «⚔️ Найти дуэль»."
    )
        await update.message.reply_text(
            "С возвращением в Токио, гуль.\nИспользуй кнопки ниже для быстрых действий.",
            reply_markup=main_keyboard(),
        )
        await update.message.reply_text(render_profile(existing))
        return

    intro = (
        "🩸 *Добро пожаловать в Tokyo Ghoul RPG*\n\n"
        "Здесь ты прокачиваешь гуля, ходишь в рейды, ешь людей и дерёшься с другими игроками в дуэлях.\n"
        "Выбери тип кагуне кнопкой ниже:"
    )
    await update.message.reply_text(intro, parse_mode="Markdown", reply_markup=kagune_keyboard())


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    if query.data is None:
        return

    if query.data.startswith("pick:"):
        kagune_key = query.data.split(":", maxsplit=1)[1]
        text = await create_player_from_choice(update, kagune_key)
        await query.edit_message_text(text)
        if query.message is not None:
            await query.message.reply_text("Главное меню открыто ⬇️", reply_markup=main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    text = (
        "📘 Основные команды:\n"
        "/profile — профиль\n"
        "/hunt <aggressive|stealth|balanced> — охота по стилю\n"
        "/raid <assault|sabotage|scout> — рейд по стилю\n"
        "/eat, /train, /gacha\n"
        "/evolve <strength|stamina|hp>\n"
        "/duel — встать в очередь на дуэль с живым игроком\n"
        "/duel cancel — выйти из очереди"
    )
    await update.message.reply_text(text, reply_markup=main_keyboard())


async def run_hunt(update: Update, style: str) -> str:
    player = await ensure_player(update)
    if not player:
        return "Сначала создай персонажа: /start"

    allowed, cooldown_text = can_hunt(player)
    if not allowed:
        return cooldown_text
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return
    await update.message.reply_text(render_profile(player), reply_markup=main_keyboard())

    result = do_hunt(player, style)
    db.save_player(player)
    return result


async def run_raid(update: Update, style: str) -> str:
    player = await ensure_player(update)
    if not player:
        return "Сначала создай персонажа: /start"

    allowed, cooldown_text = can_raid(player)
    if not allowed:
        return cooldown_text

    result = raid_district(player, style)
    db.save_player(player)
    return result
    style = normalize_hunt_style(context.args[0] if context.args else None)
    result = do_hunt(player, style)
    db.save_player(player)
    await update.message.reply_text(result, reply_markup=main_keyboard())


async def run_eat(update: Update) -> str:
    player = await ensure_player(update)
    if not player:
        return "Сначала создай персонажа: /start"

    allowed, cooldown_text = can_eat_human(player)
    if not allowed:
        return cooldown_text

    result = eat_human(player)
    db.save_player(player)
    return result
    await update.message.reply_text(result, reply_markup=main_keyboard())


async def run_train(update: Update) -> str:
    player = await ensure_player(update)
    if not player:
        return "Сначала создай персонажа: /start"
    result = train(player)
    db.save_player(player)
    return result


async def run_gacha(update: Update) -> str:
    player = await ensure_player(update)
    if not player:
        return "Сначала создай персонажа: /start"
    result = gacha_pull(player)
    db.save_player(player)
    return result


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    if context.args:
        kagune_key = normalize_kagune_key(context.args[0])
        if kagune_key and kagune_key in KAGUNE_TYPES:
            text = await create_player_from_choice(update, kagune_key)
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())
            await update.message.reply_text("⚡ Быстрые действия:", reply_markup=actions_keyboard())
            return

    existing = db.get_player(user.id)
    if existing:
        await update.message.reply_text(
            "С возвращением в Токио, гуль.\nНиже меню действий и быстрые кнопки.",
            reply_markup=main_keyboard(),
        )
        await update.message.reply_text(render_profile(existing))
        await update.message.reply_text("⚡ Выбери действие кнопкой:", reply_markup=actions_keyboard())
        return

    intro = (
        "🩸 *Добро пожаловать в Tokyo Ghoul RPG*\n\n"
        "Ты — гуль в опасном Токио: охоться, рейдь районы, мутируй, собирай предметы и дерись с живыми игроками.\n\n"
        "*Типы кагуне:*\n"
        f"{kagune_help_text()}\n\n"
        "Нажми кнопку ниже для выбора кагуне:"
    )
    await update.message.reply_text(intro, parse_mode="Markdown", reply_markup=kagune_keyboard())
    style = normalize_raid_style(context.args[0] if context.args else None)
    result = raid_district(player, style)
    db.save_player(player)
    await update.message.reply_text(result, reply_markup=main_keyboard())


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    if query.data is None:
        return

    if query.data.startswith("pick:"):
        kagune_key = query.data.split(":", maxsplit=1)[1]
        text = await create_player_from_choice(update, kagune_key)
        await query.edit_message_text(text, parse_mode="Markdown")
        if query.message is not None:
            await query.message.reply_text("Главное меню открыто ⬇️", reply_markup=main_keyboard())
            await query.message.reply_text("⚡ Быстрые действия:", reply_markup=actions_keyboard())
        return

    if query.data.startswith("act:"):
        parts = query.data.split(":")
        if len(parts) < 2:
            return

        action = parts[1]
        result = ""
        if action == "hunt" and len(parts) >= 3:
            result = await run_hunt(update, parts[2])
        elif action == "raid" and len(parts) >= 3:
        action = parts[1]
        result = ""
        if action == "hunt":
            result = await run_hunt(update, parts[2])
        elif action == "raid":
            result = await run_raid(update, parts[2])
        elif action == "eat":
            result = await run_eat(update)
        elif action == "train":
            result = await run_train(update)
        elif action == "gacha":
            result = await run_gacha(update)
        elif action == "duel":
            await duel(update, context)
            return

        if query.message is not None and result:
            await query.message.reply_text(result, reply_markup=main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    text = (
        "📘 *Команды и кнопки*\n"
        "• 👤 Профиль / /profile\n"
        "• 🗡 Охота с тактикой: агрессия, стелс, баланс\n"
        "• 🚨 Рейд с планом: штурм, саботаж, разведка\n"
        "• 🍖 Пожирание, 💪 тренировка, 🎰 гача\n"
        "• ⚔️ /duel — очередь на дуэль с реальным игроком\n"
        "• /evolve <strength|stamina|hp> — мутация за RC\n"
        "• /attack <id> — ручная PvP атака\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())
    await update.message.reply_text("⚡ Быстрые действия:", reply_markup=actions_keyboard())


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = await ensure_player(update)
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return
    await update.message.reply_text(render_profile(player), reply_markup=main_keyboard())


async def hunt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    style = normalize_hunt_style(context.args[0] if context.args else None)
    result = await run_hunt(update, style)
    await update.message.reply_text(result, reply_markup=main_keyboard())




async def hunt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    style = normalize_hunt_style(context.args[0] if context.args else None)
    result = await run_hunt(update, style)
    await update.message.reply_text(result, reply_markup=main_keyboard())


async def eat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    result = await run_eat(update)
    await update.message.reply_text(result, reply_markup=main_keyboard())


async def raid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    style = normalize_raid_style(context.args[0] if context.args else None)
    result = await run_raid(update, style)
    await update.message.reply_text(result, reply_markup=main_keyboard())


async def do_train(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    result = await run_train(update)
    result = train(player)
    db.save_player(player)
    await update.message.reply_text(result, reply_markup=main_keyboard())


async def evolve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = await ensure_player(update)
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return

    if not context.args:
        await update.message.reply_text("Использование: /evolve <strength|stamina|hp>")
        return

    result = upgrade_with_rc(player, context.args[0])
    db.save_player(player)
    await update.message.reply_text(result, reply_markup=main_keyboard())


async def gacha(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    result = await run_gacha(update)

    result = gacha_pull(player)
    db.save_player(player)
    await update.message.reply_text(result, reply_markup=main_keyboard())


async def attack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    attacker = await ensure_player(update)
    if not attacker or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return

    if not context.args:
        await update.message.reply_text("Использование: /attack <user_id>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    defender = db.get_player(target_id)
    if not defender:
        await update.message.reply_text("Игрок не найден.")
        return

    result = pvp_attack(attacker, defender)
    db.save_player(attacker)
    db.save_player(defender)
    await update.message.reply_text(result)


async def duel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = await ensure_player(update)
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if message is None:
        return
    if not player:
        await message.reply_text("Сначала создай персонажа: /start")
        return

    args = context.args if context.args else []
    if args and args[0].lower() in {"cancel", "отмена"}:
        if player.user_id in DUEL_QUEUE:
            DUEL_QUEUE.remove(player.user_id)
            await message.reply_text("Ты вышел из очереди на дуэль.")
        else:
            await message.reply_text("Ты не в очереди.")
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return

    if context.args and context.args[0].lower() in {"cancel", "отмена"}:
        if player.user_id in DUEL_QUEUE:
            DUEL_QUEUE.remove(player.user_id)
            await update.message.reply_text("Ты вышел из очереди на дуэль.")
        else:
            await update.message.reply_text("Ты не в очереди.")
        return

    if player.user_id not in DUEL_QUEUE:
        DUEL_QUEUE.append(player.user_id)

    opponent_id = next((uid for uid in DUEL_QUEUE if uid != player.user_id), None)
    if opponent_id is None:
        await message.reply_text("⏳ Поиск соперника... Ты в очереди на дуэль.")
        await update.message.reply_text(
            "⏳ Ты в очереди на дуэль. Как только появится соперник — бой начнётся автоматически.",
            reply_markup=main_keyboard(),
        )
        return

    DUEL_QUEUE.remove(player.user_id)
    DUEL_QUEUE.remove(opponent_id)
    opponent = db.get_player(opponent_id)
    if not opponent:
        await message.reply_text("Соперник исчез!Нажми «⚔️ Найти дуэль» ещё раз.")
        await update.message.reply_text("Соперник исчез! Нажми /duel ещё раз.")
        return

    result_for_attacker = pvp_attack(player, opponent)
    result_for_opponent = pvp_attack(opponent, player)
    db.save_player(player)
    db.save_player(opponent)

    await message.reply_text("⚔️ Дуэль найдена!\n" + result_for_attacker, reply_markup=main_keyboard())
    try:
        await context.bot.send_message(
            chat_id=opponent.user_id,
            text=f"⚔️ Тебя вызвал игрок {player.username}!\n{result_for_opponent}",
    await update.message.reply_text("⚔️ Дуэль найдена!\n" + result_for_attacker, reply_markup=main_keyboard())
    try:
        await context.bot.send_message(
            chat_id=opponent.user_id,
            text=f"⚔️ Тебя вызвали на дуэль игроком {player.username}!\n{result_for_opponent}",
            reply_markup=main_keyboard(),
        )
    except Exception as err:
        print(f"Не удалось отправить сообщение сопернику {opponent.user_id}: {err}")


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    players = db.top_players(10)
    if not players:
        await update.message.reply_text("Пока нет игроков.")
        return

    lines = ["🏅 Топ игроков:"]
    for i, p in enumerate(players, start=1):
        lines.append(f"{i}. {p.username} — lvl {p.level}, RC {p.rc_cells}, EXP {p.exp}, ¥ {p.yen}")

    await update.message.reply_text("\n".join(lines), reply_markup=main_keyboard())


BUTTON_ACTIONS = {
    "👤 Профиль": "profile",
    "🏆 Топ игроков": "top",
    "🗡 Охота: Агрессия": "hunt aggressive",
    "🎯 Охота: Стелс": "hunt stealth",
    "⚖️ Охота: Баланс": "hunt balanced",
    "🚨 Рейд: Штурм": "raid assault",
    "🧨 Рейд: Саботаж": "raid sabotage",
    "👁 Рейд: Разведка": "raid scout",
    "🍖 Пожирание": "eat",
    "💪 Тренировка": "train",
    "🎰 Гача": "gacha",
    "⚔️ Найти дуэль": "duel",
    "❌ Выйти из дуэли": "duel cancel",
    "ℹ️ Помощь": "help",
}


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not update.message.text:
        return

    action = BUTTON_ACTIONS.get(update.message.text.strip())
    if not action:
        return

    parts = action.split()
    cmd = parts[0]
    context.args = parts[1:]

    handlers = {
        "profile": profile,
        "top": top,
        "hunt": hunt,
        "raid": raid,
        "eat": eat,
        "train": do_train,
        "gacha": gacha,
        "duel": duel,
        "help": help_command,
    }

    await handlers[cmd](update, context)

    await update.message.reply_text("\n".join(lines), reply_markup=main_keyboard())


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Не найден BOT_TOKEN в переменных окружения")

    run_health_server_if_needed()
    ensure_event_loop()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("hunt", hunt))
    app.add_handler(CommandHandler("eat", eat))
    app.add_handler(CommandHandler("raid", raid))
    app.add_handler(CommandHandler("train", do_train))
    app.add_handler(CommandHandler("evolve", evolve))
    app.add_handler(CommandHandler("gacha", gacha))
    app.add_handler(CommandHandler("attack", attack))
    app.add_handler(CommandHandler("duel", duel))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_router))

    app.run_polling()


if __name__ == "__main__":
    main()
