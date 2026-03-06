import asyncio
import os
import random
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
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
    eat_human,
    gacha_pull,
    kagune_help_text,
    normalize_kagune_key,
    pvp_attack,
    render_profile,
    train,
    upgrade_with_rc,
)

UTC = timezone.utc

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "/tmp/game.db")
BOT_USERNAME_ENV = os.getenv("BOT_USERNAME")

DUEL_QUEUE: list[int] = []
HUNT_SESSIONS: dict[int, dict] = {}
RAID_LOBBIES: dict[str, dict] = {}
RAID_ACTIVE: dict[int, str] = {}
PENDING_RAID_JOIN: dict[int, str] = {}
BOT_USERNAME_CACHE: str | None = BOT_USERNAME_ENV

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


def gacha_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💴 Гача на ¥", callback_data="gacha:yen")],
            [InlineKeyboardButton("🧬 Гача на RC", callback_data="gacha:rc")],
        ]
    )


def train_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗡 Тренировать силу", callback_data="train:strength")],
            [InlineKeyboardButton("🛡 Тренировать выносливость", callback_data="train:stamina")],
            [InlineKeyboardButton("❤️ Тренировать живучесть", callback_data="train:hp")],
            [InlineKeyboardButton("⚖️ Баланс-тренировка", callback_data="train:balanced")],
        ]
    )


async def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    global BOT_USERNAME_CACHE
    if BOT_USERNAME_CACHE:
        return BOT_USERNAME_CACHE
    try:
        me = await context.bot.get_me()
        BOT_USERNAME_CACHE = me.username
        return BOT_USERNAME_CACHE
    except Exception:
        return None


async def ensure_player(update: Update):
    user = update.effective_user
    if user is None:
        return None

    player = db.get_player(user.id)
    if player and player.username != user.full_name:
        player.username = user.full_name
        db.save_player(player)
    return player


async def create_player_from_choice(update: Update, kagune_key: str) -> str:
    user = update.effective_user
    if user is None:
        return "Ошибка: пользователь не найден."

    existing = db.get_player(user.id)
    if existing:
        return "Ты уже в игре. Нажми «👤 Профиль» и продолжай играть."

    player = db.create_player(user.id, user.full_name, kagune_key)
    return (
        "✅ *Персонаж создан!*\n"
        f"Кагуне: *{player.kagune}*\n"
        "Теперь можешь сразу нажать «🗡 Охота» или «🚨 Рейд»."
    )


def _enemy_title(kind: str) -> str:
    if kind == "hunt":
        return random.choice(["Дикий гуль", "Охотник CCG", "Бешеный полугуль"])
    return random.choice(["Карательный отряд CCG", "Элитный патруль CCG", "Отряд спецзачистки"])


def _new_hunt_session() -> dict:
    hp = random.randint(45, 75)
    return {
        "kind": "hunt",
        "enemy": _enemy_title("hunt"),
        "enemy_hp": hp,
        "enemy_max_hp": hp,
        "enemy_attack": (9, 21),
        "enemy_def_zone": random.choice(ZONES),
        "phase": "attack",
        "turn": 1,
        "pending_enemy_zone": None,
    }


def _new_raid_lobby(host_id: int, host_name: str) -> tuple[str, dict]:
    token = secrets.token_urlsafe(8)
    enemy_name = random.choice([
        "Карательный отряд CCG «Белый Гроб»",
        "Штурмовая группа CCG «Огненный Клык»",
        "Элитный спецотряд «Гидра»",
    ])
    enemy_hp = random.randint(260, 340)
    lobby = {
        "token": token,
        "host_id": host_id,
        "host_name": host_name,
        "ally_id": None,
        "ally_name": None,
        "ready": set(),
        "enemy_name": enemy_name,
        "enemy_hp": enemy_hp,
        "enemy_max_hp": enemy_hp,
        "enemy_attack": (18, 34),
        "started": False,
        "phase_by_player": {},
        "pending_enemy_zone": {},
        "turn": 1,
    }
    return token, lobby


def _combat_status_hunt(player, session: dict) -> str:
    return (
        f"🎯 Раунд {session['turn']}\n"
        f"👹 {session['enemy']}: {session['enemy_hp']}/{session['enemy_max_hp']} HP\n"
        f"❤️ Ты: {player.hp}/{player.max_hp} HP"
    )


def _apply_player_attack(player, session: dict, zone: str) -> str:
    base = player.strength + random.randint(2, max(4, player.stamina))
    zone_bonus = {"head": 10, "body": 6, "legs": 4}[zone]

    enemy_def = session.get("enemy_def_zone", random.choice(ZONES))
    if enemy_def == zone:
        damage = max(1, (base + zone_bonus) // 3)
        text = (
            f"Ты бьёшь в {ZONE_RU[zone]}, но враг защитил эту зону. "
            f"Урон снижен до {damage}."
        )
    else:
        crit = random.random() < (0.12 if zone == "head" else 0.07)
        damage = base + zone_bonus + (10 if crit else 0)
        text = f"Ты бьёшь в {ZONE_RU[zone]} и наносишь {damage} урона."
        if crit:
            text += " 💥 Критический удар!"

    session["enemy_hp"] = max(0, session["enemy_hp"] - damage)
    session["enemy_def_zone"] = random.choice(ZONES)
    return text


def _apply_enemy_attack(player, session: dict, defend_zone: str) -> str:
    enemy_zone = session.get("pending_enemy_zone") or random.choice(ZONES)
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


def _finish_hunt(player) -> str:
    exp = random.randint(28, 56)
    yen = random.randint(26, 96)
    rc = random.randint(7, 18)
    player.exp += exp
    player.yen += yen
    player.rc_cells += rc
    return f"🏁 Охота завершена! +{exp} EXP, +{yen} ¥, +{rc} RC."


def _raid_status(p1, p2, lobby: dict) -> str:
    return (
        f"🚨 Раунд {lobby['turn']}\n"
        f"👹 {lobby['enemy_name']}: {lobby['enemy_hp']}/{lobby['enemy_max_hp']} HP\n"
        f"❤️ {p1.username}: {p1.hp}/{p1.max_hp} HP\n"
        f"❤️ {p2.username}: {p2.hp}/{p2.max_hp} HP"
    )


def _raid_reward(player) -> str:
    exp = random.randint(70, 120)
    yen = random.randint(90, 220)
    rc = random.randint(22, 48)
    player.exp += exp
    player.yen += yen
    player.rc_cells += rc
    return f"+{exp} EXP, +{yen} ¥, +{rc} RC"


async def start_hunt(update: Update) -> str:
    player = await ensure_player(update)
    if not player:
        return "Сначала создай персонажа: /start"

    if player.user_id in HUNT_SESSIONS:
        return "Ты уже в бою охоты. Заверши текущий бой."

    allowed, cooldown_text = can_hunt(player)
    if not allowed:
        return cooldown_text

    player.last_hunt_at = datetime.now(UTC).isoformat()
    session = _new_hunt_session()
    HUNT_SESSIONS[player.user_id] = session
    db.save_player(player)
    return (
        f"🗡 Началась охота! Противник: {session['enemy']}.\n"
        f"{_combat_status_hunt(player, session)}\n"
        "Выбери, куда атаковать:"
    )


async def create_raid_lobby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[str, InlineKeyboardMarkup] | None:
    player = await ensure_player(update)
    if not player:
        return None

    token, lobby = _new_raid_lobby(player.user_id, player.username)
    RAID_LOBBIES[token] = lobby

    bot_username = await get_bot_username(context)
    if bot_username:
        join_url = f"https://t.me/{bot_username}?start=raidjoin_{token}"
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔗 Пригласить в рейд", url=join_url)],
                [InlineKeyboardButton("✅ Я готов(а)", callback_data=f"raidlobby:ready:{token}")],
            ]
        )
    else:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Я готов(а)", callback_data=f"raidlobby:ready:{token}")]]
        )

    return token, keyboard


async def try_join_raid(player_id: int, token: str) -> tuple[bool, str]:
    player = db.get_player(player_id)
    if not player:
        return False, "Сначала создай персонажа: /start"

    lobby = RAID_LOBBIES.get(token)
    if not lobby:
        return False, "Этот рейд уже неактивен или не найден."

    if lobby["ally_id"] is None and player_id != lobby["host_id"]:
        lobby["ally_id"] = player_id
        lobby["ally_name"] = player.username
        return True, f"Ты присоединился к рейду с игроком {lobby['host_name']}!"

    if player_id in {lobby["host_id"], lobby["ally_id"]}:
        return True, "Ты уже в этом рейде."

    return False, "В этом рейде уже есть 2 участника."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    if context.args:
        arg = context.args[0]
        if arg.startswith("raidjoin_"):
            token = arg.split("_", 1)[1]
            existing = db.get_player(user.id)
            if not existing:
                PENDING_RAID_JOIN[user.id] = token
                intro = (
                    "Чтобы вступить в рейд, сначала создай персонажа.\n\n"
                    "Выбери кагуне кнопкой ниже:"
                )
                await update.message.reply_text(intro, reply_markup=kagune_keyboard())
                return

            ok, msg = await try_join_raid(user.id, token)
            await update.message.reply_text(msg, reply_markup=main_keyboard())
            if ok:
                await update.message.reply_text(
                    "Нажми «✅ Я готов(а)» в сообщении рейда, когда будете готовы.",
                )
            return

        kagune_key = normalize_kagune_key(arg)
        if kagune_key and kagune_key in KAGUNE_TYPES:
            text = await create_player_from_choice(update, kagune_key)
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())
            return

    existing = await ensure_player(update)
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

    if query.message is not None and query.message.reply_markup is not None:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

    if query.data.startswith("pick:"):
        kagune_key = query.data.split(":", maxsplit=1)[1]
        text = await create_player_from_choice(update, kagune_key)
        await query.edit_message_text(text, parse_mode="Markdown")
        if query.message is not None:
            await query.message.reply_text("Главное меню открыто ⬇️", reply_markup=main_keyboard())

        user = update.effective_user
        if user and user.id in PENDING_RAID_JOIN:
            token = PENDING_RAID_JOIN.pop(user.id)
            ok, msg = await try_join_raid(user.id, token)
            if query.message is not None:
                await query.message.reply_text(msg, reply_markup=main_keyboard())
                if ok:
                    await query.message.reply_text("Вернись в сообщение рейда и нажми «✅ Я готов(а)». ")
        return

    if query.data.startswith("gacha:"):
        pool = query.data.split(":", 1)[1]
        player = await ensure_player(update)
        if not player:
            await query.message.reply_text("Сначала создай персонажа: /start")
            return
        result = gacha_pull(player, pool)
        db.save_player(player)
        await query.message.reply_text(result, reply_markup=main_keyboard())
        return

    if query.data.startswith("train:"):
        focus = query.data.split(":", 1)[1]
        player = await ensure_player(update)
        if not player:
            await query.message.reply_text("Сначала создай персонажа: /start")
            return
        result = train(player, focus)
        db.save_player(player)
        await query.message.reply_text(result, reply_markup=main_keyboard())
        return

    if query.data.startswith("raidlobby:"):
        _, action, token = query.data.split(":")
        lobby = RAID_LOBBIES.get(token)
        user = update.effective_user
        if lobby is None or user is None:
            await query.message.reply_text("Рейд не найден.")
            return

        player = db.get_player(user.id)
        if not player:
            PENDING_RAID_JOIN[user.id] = token
            await query.message.reply_text("Сначала создай персонажа: /start")
            return

        if action == "ready":
            if user.id not in {lobby['host_id'], lobby.get('ally_id')}:
                ok, msg = await try_join_raid(user.id, token)
                await query.message.reply_text(msg)
                if not ok:
                    return

            lobby["ready"].add(user.id)
            if lobby.get("ally_id") and lobby["ready"] == {lobby['host_id'], lobby['ally_id']}:
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔥 Начать рейд", callback_data=f"raidlobby:start:{token}")]]
                )
                await query.message.reply_text("Оба игрока готовы. Можно начинать рейд.", reply_markup=kb)
            else:
                await query.message.reply_text("Готовность отмечена. Ждём второго игрока.")
            return

        if action == "start":
            if user.id != lobby['host_id']:
                await query.message.reply_text("Только создатель рейда может начать бой.")
                return
            if not lobby.get("ally_id"):
                await query.message.reply_text("Нужен союзник для старта рейда.")
                return
            if lobby["ready"] != {lobby['host_id'], lobby['ally_id']}:
                await query.message.reply_text("Оба игрока должны нажать «Я готов(а)». ")
                return

            lobby["started"] = True
            for uid in (lobby['host_id'], lobby['ally_id']):
                RAID_ACTIVE[uid] = token
                lobby["phase_by_player"][uid] = "attack"
                lobby["pending_enemy_zone"][uid] = None

            p1 = db.get_player(lobby['host_id'])
            p2 = db.get_player(lobby['ally_id'])
            if p1 and p2:
                status = _raid_status(p1, p2, lobby)
                await context.bot.send_message(p1.user_id, f"🚨 Рейд начался!\n{status}\nТвой ход: выбери удар.", reply_markup=attack_keyboard("raid"))
                await context.bot.send_message(p2.user_id, f"🚨 Рейд начался!\n{status}\nТвой ход: выбери удар.", reply_markup=attack_keyboard("raid"))
            return

    parts = query.data.split(":")
    if len(parts) != 3:
        return

    mode, action, zone = parts
    player = await ensure_player(update)
    if not player:
        await query.message.reply_text("Сначала создай персонажа: /start")
        return

    if mode == "hunt":
        session = HUNT_SESSIONS.get(player.user_id)
        if not session:
            await query.message.reply_text("Бой не найден. Запусти охоту заново.")
            return

        if action == "atk" and session["phase"] == "attack":
            attack_text = _apply_player_attack(player, session, zone)
            if session["enemy_hp"] <= 0:
                reward = _finish_hunt(player)
                HUNT_SESSIONS.pop(player.user_id, None)
                db.save_player(player)
                await query.message.reply_text(f"{attack_text}\n\n✅ Враг повержен!\n{reward}", reply_markup=main_keyboard())
                return

            session["pending_enemy_zone"] = random.choice(ZONES)
            session["phase"] = "defense"
            await query.message.reply_text(
                f"{attack_text}\n\n{_combat_status_hunt(player, session)}\n"
                "Противник контратакует. Выбери, что защищать:",
                reply_markup=defend_keyboard("hunt"),
            )
            return

        if action == "def" and session["phase"] == "defense":
            defend_text = _apply_enemy_attack(player, session, zone)
            session["phase"] = "attack"
            session["turn"] += 1

            if player.hp <= 1:
                HUNT_SESSIONS.pop(player.user_id, None)
                db.save_player(player)
                await query.message.reply_text(
                    f"{defend_text}\n\n💀 Ты еле выжил и отступил. Бой завершен.",
                    reply_markup=main_keyboard(),
                )
                return

            db.save_player(player)
            await query.message.reply_text(
                f"{defend_text}\n\n{_combat_status_hunt(player, session)}\n"
                "Твой ход — выбери удар:",
                reply_markup=attack_keyboard("hunt"),
            )
            return

    if mode == "raid":
        token = RAID_ACTIVE.get(player.user_id)
        if not token:
            await query.message.reply_text("Ты не в активном рейде.")
            return
        lobby = RAID_LOBBIES.get(token)
        if not lobby:
            RAID_ACTIVE.pop(player.user_id, None)
            await query.message.reply_text("Рейд не найден.")
            return

        ally_id = lobby['ally_id'] if player.user_id == lobby['host_id'] else lobby['host_id']
        ally = db.get_player(ally_id)
        if not ally:
            await query.message.reply_text("Союзник потерян. Рейд остановлен.")
            return

        phase = lobby['phase_by_player'].get(player.user_id, 'attack')
        if action == 'atk' and phase == 'attack':
            attack_text = _apply_player_attack(player, lobby, zone)
            lobby['phase_by_player'][player.user_id] = 'defense'
            lobby['pending_enemy_zone'][player.user_id] = random.choice(ZONES)

            if lobby['enemy_hp'] <= 0:
                p1 = db.get_player(lobby['host_id'])
                p2 = db.get_player(lobby['ally_id'])
                if p1 and p2:
                    r1 = _raid_reward(p1)
                    r2 = _raid_reward(p2)
                    db.save_player(p1)
                    db.save_player(p2)
                    await context.bot.send_message(p1.user_id, f"✅ Рейд завершен! Твои награды: {r1}", reply_markup=main_keyboard())
                    await context.bot.send_message(p2.user_id, f"✅ Рейд завершен! Твои награды: {r2}", reply_markup=main_keyboard())
                RAID_ACTIVE.pop(lobby['host_id'], None)
                RAID_ACTIVE.pop(lobby['ally_id'], None)
                RAID_LOBBIES.pop(token, None)
                return

            await query.message.reply_text(
                f"{attack_text}\nПротивник готовит ответ. Выбери защиту:",
                reply_markup=defend_keyboard('raid'),
            )
            return

        if action == 'def' and phase == 'defense':
            defend_text = _apply_enemy_attack(player, {"enemy": lobby['enemy_name'], "enemy_attack": lobby['enemy_attack'], "pending_enemy_zone": lobby['pending_enemy_zone'][player.user_id]}, zone)
            lobby['phase_by_player'][player.user_id] = 'attack'
            if all(v == 'attack' for v in lobby['phase_by_player'].values()):
                lobby['turn'] += 1

            db.save_player(player)
            db.save_player(ally)

            if player.hp <= 1 and ally.hp <= 1:
                await context.bot.send_message(player.user_id, "💀 Вы оба выбиты. Рейд провален.", reply_markup=main_keyboard())
                await context.bot.send_message(ally.user_id, "💀 Вы оба выбиты. Рейд провален.", reply_markup=main_keyboard())
                RAID_ACTIVE.pop(player.user_id, None)
                RAID_ACTIVE.pop(ally.user_id, None)
                RAID_LOBBIES.pop(token, None)
                return

            status = _raid_status(player, ally, lobby) if player.user_id == lobby['host_id'] else _raid_status(ally, player, lobby)
            await query.message.reply_text(f"{defend_text}\n\n{status}\nТвой ход: выбери удар.", reply_markup=attack_keyboard('raid'))
            return


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    text = (
        "📘 Команды:\n"
        "• 👤 Профиль\n"
        "• 🗡 Охота — бой с NPC (кд 3 минуты)\n"
        "• 🚨 Рейд — только с союзником через invite-link\n"
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


eat = eat_command


async def raid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    player = await ensure_player(update)
    if not player:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return

    lobby_data = await create_raid_lobby(update, context)
    if lobby_data is None:
        await update.message.reply_text("Не удалось создать рейд.")
        return

    token, kb = lobby_data
    lobby = RAID_LOBBIES[token]
    text = (
        "🚨 В рейд можно ходить только с союзным гулем.\n"
        f"👹 Предстоящий враг: {lobby['enemy_name']}\n"
        f"❤️ HP врага: {lobby['enemy_max_hp']}\n\n"
        "Нажми кнопку приглашения, отправь ссылку союзнику и отметь готовность."
    )
    await update.message.reply_text(text, reply_markup=kb)


async def train_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = await ensure_player(update)
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return

    if context.args:
        result = train(player, context.args[0])
        db.save_player(player)
        await update.message.reply_text(result, reply_markup=main_keyboard())
        return

    await update.message.reply_text("Выбери тип тренировки:", reply_markup=train_keyboard())


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

    if context.args:
        result = gacha_pull(player, context.args[0])
        db.save_player(player)
        await update.message.reply_text(result, reply_markup=main_keyboard())
        return

    await update.message.reply_text("Выбери тип гачи:", reply_markup=gacha_keyboard())


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
