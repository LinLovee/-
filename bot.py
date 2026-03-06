import asyncio
import os
import random
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

from game import (
    GameDB,
    KAGUNE_TYPES,
    can_eat_human,
    can_hunt,
    can_raid,
    eat_human,
    gacha_pull,
    kagune_help_text,
    normalize_kagune_key,
    pvp_attack,
    render_profile,
    train,
    upgrade_with_rc,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "/tmp/game.db")
DUEL_QUEUE: list[int] = []
HUNT_SESSIONS: dict[int, dict] = {}
RAID_SESSIONS: dict[int, dict] = {}
ZONES = ["head", "body", "legs"]
ZONE_RU = {"head": "голову", "body": "тело", "legs": "ноги"}


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
            ["👤 Профиль", "🏆 Топ"],
            ["🗡 Охота", "🚨 Рейд"],
            ["🍖 Пожирание", "💪 Тренировка", "🎰 Гача"],
            ["⚔️ Дуэль", "❌ Отмена дуэли", "ℹ️ Помощь"],
        ],
        resize_keyboard=True,
    )


def kagune_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, value in KAGUNE_TYPES.items():
        rows.append([InlineKeyboardButton(f"{value['name']} ({key})", callback_data=f"pick:{key}")])
    return InlineKeyboardMarkup(rows)


def attack_keyboard(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👊 Удар в голову", callback_data=f"{kind}:atk:head")],
            [InlineKeyboardButton("👊 Удар в тело", callback_data=f"{kind}:atk:body")],
            [InlineKeyboardButton("👊 Удар в ноги", callback_data=f"{kind}:atk:legs")],
        ]
    )


def defend_keyboard(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛡 Защитить голову", callback_data=f"{kind}:def:head")],
            [InlineKeyboardButton("🛡 Защитить тело", callback_data=f"{kind}:def:body")],
            [InlineKeyboardButton("🛡 Защитить ноги", callback_data=f"{kind}:def:legs")],
        ]
    )


async def ensure_player(update: Update):
    user = update.effective_user
    if user is None:
        return None
    return db.get_player(user.id)


async def create_player_from_choice(update: Update, kagune_key: str) -> str:
    user = update.effective_user
    if user is None:
        return "Ошибка: пользователь не найден."

    existing = db.get_player(user.id)
    if existing:
        return "Ты уже в игре. Нажми «👤 Профиль» и продолжай играть."

    username = user.username or user.full_name
    player = db.create_player(user.id, username, kagune_key)
    return (
        "✅ *Персонаж создан!*\n"
        f"Кагуне: *{player.kagune}*\n"
        "Теперь можешь сразу нажать «🗡 Охота» или «🚨 Рейд»."
    )


def _enemy_title(kind: str) -> str:
    if kind == "hunt":
        return random.choice(["Дикий гуль", "Охотник CCG", "Бешеный полугуль"])
    return random.choice(["Элитный патруль CCG", "Отряд зачистки", "Карательный отряд"])


def _init_combat_session(player, kind: str) -> dict:
    if kind == "hunt":
        hp = random.randint(45, 75)
        attack = (10, 22)
    else:
        hp = random.randint(70, 120)
        attack = (14, 28)
    return {
        "kind": kind,
        "enemy": _enemy_title(kind),
        "enemy_hp": hp,
        "enemy_max_hp": hp,
        "enemy_attack": attack,
        "phase": "attack",
        "turn": 1,
        "pending_enemy_zone": None,
        "log": [],
    }


def _apply_player_attack(player, session: dict, zone: str) -> str:
    base = player.strength + random.randint(2, max(4, player.stamina))
    zone_bonus = {"head": 10, "body": 6, "legs": 4}[zone]
    crit = random.random() < (0.12 if zone == "head" else 0.07)
    damage = base + zone_bonus + (10 if crit else 0)
    session["enemy_hp"] = max(0, session["enemy_hp"] - damage)
    text = f"Ты бьёшь в {ZONE_RU[zone]} и наносишь {damage} урона."
    if crit:
        text += " 💥 Критический удар!"
    return text


def _apply_enemy_attack(player, session: dict, defend_zone: str) -> str:
    enemy_zone = session["pending_enemy_zone"] or random.choice(ZONES)
    raw = random.randint(*session["enemy_attack"])
    blocked = defend_zone == enemy_zone
    damage = max(1, raw // 3) if blocked else raw
    player.hp = max(1, player.hp - damage)

    text = f"{session['enemy']} атакует в {ZONE_RU[enemy_zone]}. "
    if blocked:
        text += f"Ты угадал с блоком! Получено {damage} урона вместо {raw}."
    else:
        text += f"Блок мимо. Получено {damage} урона."
    return text


def _combat_status(player, session: dict) -> str:
    return (
        f"🎯 Раунд {session['turn']}\n"
        f"👹 {session['enemy']}: {session['enemy_hp']}/{session['enemy_max_hp']} HP\n"
        f"❤️ Ты: {player.hp}/{player.max_hp} HP"
    )


def _finish_hunt(player, session: dict) -> str:
    exp = random.randint(32, 62)
    yen = random.randint(30, 110)
    rc = random.randint(8, 22)
    player.exp += exp
    player.yen += yen
    player.rc_cells += rc
    return f"🏁 Охота завершена! +{exp} EXP, +{yen} ¥, +{rc} RC."


def _finish_raid(player, session: dict) -> str:
    exp = random.randint(52, 95)
    yen = random.randint(70, 180)
    rc = random.randint(16, 38)
    player.exp += exp
    player.yen += yen
    player.rc_cells += rc
    return f"🏁 Рейд завершен! +{exp} EXP, +{yen} ¥, +{rc} RC."


async def start_hunt(update: Update) -> str:
    player = await ensure_player(update)
    if not player:
        return "Сначала создай персонажа: /start"

    if player.user_id in HUNT_SESSIONS:
        return "Ты уже в бою охоты. Заверши текущий бой."

    allowed, cooldown_text = can_hunt(player)
    if not allowed:
        return cooldown_text

    player.last_hunt_at = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    session = _init_combat_session(player, "hunt")
    HUNT_SESSIONS[player.user_id] = session
    db.save_player(player)
    return (
        f"🗡 Началась охота! Найден противник: {session['enemy']}.\n"
        f"{_combat_status(player, session)}\n"
        "Выбери, куда атаковать:"
    )


async def start_raid(update: Update) -> str:
    player = await ensure_player(update)
    if not player:
        return "Сначала создай персонажа: /start"

    if player.user_id in RAID_SESSIONS:
        return "Ты уже в рейде. Заверши текущий бой."

    allowed, cooldown_text = can_raid(player)
    if not allowed:
        return cooldown_text

    player.last_raid_at = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    session = _init_combat_session(player, "raid")
    RAID_SESSIONS[player.user_id] = session
    db.save_player(player)
    return (
        f"🚨 Начался рейд! Цель: {session['enemy']}.\n"
        f"{_combat_status(player, session)}\n"
        "Выбери удар:"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    if context.args:
        kagune_key = normalize_kagune_key(context.args[0])
        if kagune_key and kagune_key in KAGUNE_TYPES:
            text = await create_player_from_choice(update, kagune_key)
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())
            return

    existing = db.get_player(user.id)
    if existing:
        await update.message.reply_text("С возвращением. Меню ниже.", reply_markup=main_keyboard())
        await update.message.reply_text(render_profile(existing))
        return

    intro = (
        "🩸 *Добро пожаловать в Tokyo Ghoul RPG*\n\n"
        "*Типы кагуне:*\n"
        f"{kagune_help_text()}\n\n"
        "Выбери кагуне кнопкой ниже:"
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
        await query.edit_message_text(text, parse_mode="Markdown")
        if query.message is not None:
            await query.message.reply_text("Главное меню открыто ⬇️", reply_markup=main_keyboard())
        return

    parts = query.data.split(":")
    if len(parts) != 3:
        return

    mode, action, zone = parts
    player = await ensure_player(update)
    if not player:
        if query.message is not None:
            await query.message.reply_text("Сначала создай персонажа: /start")
        return

    sessions = HUNT_SESSIONS if mode == "hunt" else RAID_SESSIONS
    session = sessions.get(player.user_id)
    if not session:
        if query.message is not None:
            await query.message.reply_text("Бой не найден. Запусти заново через меню.")
        return

    if action == "atk" and session["phase"] == "attack":
        attack_text = _apply_player_attack(player, session, zone)
        if session["enemy_hp"] <= 0:
            reward = _finish_hunt(player, session) if mode == "hunt" else _finish_raid(player, session)
            sessions.pop(player.user_id, None)
            db.save_player(player)
            if query.message is not None:
                await query.message.reply_text(f"{attack_text}\n\n✅ Враг повержен!\n{reward}")
            return

        session["pending_enemy_zone"] = random.choice(ZONES)
        session["phase"] = "defense"
        if query.message is not None:
            await query.message.reply_text(
                f"{attack_text}\n\n{_combat_status(player, session)}\n"
                "Противник контратакует. Выбери, что защищать:",
                reply_markup=defend_keyboard(mode),
            )
        return

    if action == "def" and session["phase"] == "defense":
        defend_text = _apply_enemy_attack(player, session, zone)
        session["phase"] = "attack"
        session["turn"] += 1

        if player.hp <= 1:
            sessions.pop(player.user_id, None)
            db.save_player(player)
            if query.message is not None:
                await query.message.reply_text(
                    f"{defend_text}\n\n💀 Ты еле выжил и отступил. Бой завершен.",
                    reply_markup=main_keyboard(),
                )
            return

        db.save_player(player)
        if query.message is not None:
            await query.message.reply_text(
                f"{defend_text}\n\n{_combat_status(player, session)}\n"
                "Твой ход — выбери удар:",
                reply_markup=attack_keyboard(mode),
            )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    text = (
        "📘 Команды:\n"
        "• 👤 Профиль\n"
        "• 🗡 Охота — пошаговый бой с NPC\n"
        "• 🚨 Рейд — тяжелый пошаговый бой\n"
        "• 🍖 Пожирание, 💪 тренировка, 🎰 гача\n"
        "• ⚔️ Дуэль — очередь на PvP"
    )
    await update.message.reply_text(text, reply_markup=main_keyboard())


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = await ensure_player(update)
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return
    await update.message.reply_text(render_profile(player), reply_markup=main_keyboard())


async def hunt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    text = await start_hunt(update)
    await update.message.reply_text(text, reply_markup=attack_keyboard("hunt"))


async def eat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = await ensure_player(update)
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return

    allowed, cooldown_text = can_eat_human(player)
    if not allowed:
        await update.message.reply_text(cooldown_text)
        return

    result = eat_human(player)
    db.save_player(player)
    await update.message.reply_text(result, reply_markup=main_keyboard())


# Backward-compatible alias for old references
eat = eat_command


async def raid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    text = await start_raid(update)
    await update.message.reply_text(text, reply_markup=attack_keyboard("raid"))


async def train_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = await ensure_player(update)
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return
    result = train(player)
    db.save_player(player)
    await update.message.reply_text(result, reply_markup=main_keyboard())


# Backward-compatible alias for old references
do_train = train_command


async def evolve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    player = await ensure_player(update)
    if not player:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return

    if not context.args:
        await update.message.reply_text("Использование: /evolve <strength|stamina|hp>")
        return

    result = upgrade_with_rc(player, context.args[0])
    db.save_player(player)
    await update.message.reply_text(result, reply_markup=main_keyboard())


async def gacha(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = await ensure_player(update)
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return

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
        return

    if player.user_id not in DUEL_QUEUE:
        DUEL_QUEUE.append(player.user_id)

    opponent_id = next((uid for uid in DUEL_QUEUE if uid != player.user_id), None)
    if opponent_id is None:
        await message.reply_text("⏳ Поиск соперника...")
        return

    DUEL_QUEUE.remove(player.user_id)
    DUEL_QUEUE.remove(opponent_id)
    opponent = db.get_player(opponent_id)
    if not opponent:
        await message.reply_text("Соперник исчез. Нажми «⚔️ Дуэль» ещё раз.")
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
    "🏆 Топ": "top",
    "🗡 Охота": "hunt",
    "🚨 Рейд": "raid",
    "🍖 Пожирание": "eat",
    "💪 Тренировка": "train",
    "🎰 Гача": "gacha",
    "⚔️ Дуэль": "duel",
    "❌ Отмена дуэли": "duel cancel",
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
        "eat": eat_command,
        "train": train_command,
        "gacha": gacha,
        "duel": duel,
        "help": help_command,
    }
    await handlers[cmd](update, context)


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
    app.add_handler(CommandHandler("eat", eat_command))
    app.add_handler(CommandHandler("raid", raid))
    app.add_handler(CommandHandler("train", train_command))
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
