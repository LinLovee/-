import asyncio
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from game import (
    GameDB,
    KAGUNE_TYPES,
    normalize_kagune_key,
    can_eat_human,
    can_hunt,
    can_raid,
    do_hunt,
    eat_human,
    gacha_pull,
    kagune_help_text,
    pvp_attack,
    raid_district,
    render_profile,
    train,
    upgrade_with_rc,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "/tmp/game.db")


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


async def ensure_player(update: Update):
    user = update.effective_user
    if user is None:
        return None
    return db.get_player(user.id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    existing = db.get_player(user.id)
    if existing:
        await update.message.reply_text(
            "Ты уже в игре. Вот твой текущий профиль:\n\n" + render_profile(existing)
        )
        return

    if not context.args:
        intro = (
            "🩸 Создание персонажа в мире Токийского гуля.\n"
            "Сначала выбери тип кагуне.\n\n"
            f"{kagune_help_text()}"
        )
        await update.message.reply_text(intro, parse_mode="Markdown")
        return

    kagune_key = normalize_kagune_key(context.args[0])
    if not kagune_key or kagune_key not in KAGUNE_TYPES:
        await update.message.reply_text(
            "Неизвестный тип кагуне.\n\n" + kagune_help_text(), parse_mode="Markdown"
        )
        return

    username = user.username or user.full_name
    player = db.create_player(user.id, username, kagune_key)

    text = (
        "✅ Персонаж создан!\n"
        f"Твой тип: {player.kagune}.\n"
        "Команды:\n"
        "/profile\n/hunt\n/eat\n/raid\n/train\n/evolve <strength|stamina|hp>\n"
        "/gacha\n/attack <id>\n/top"
    )
    await update.message.reply_text(text)


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = await ensure_player(update)
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start <тип_кагуне>")
        return
    await update.message.reply_text(render_profile(player))


async def hunt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = await ensure_player(update)
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return

    allowed, cooldown_text = can_hunt(player)
    if not allowed:
        await update.message.reply_text(cooldown_text)
        return

    result = do_hunt(player)
    db.save_player(player)
    await update.message.reply_text(result)


async def eat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    await update.message.reply_text(result)


async def raid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = await ensure_player(update)
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return

    allowed, cooldown_text = can_raid(player)
    if not allowed:
        await update.message.reply_text(cooldown_text)
        return

    result = raid_district(player)
    db.save_player(player)
    await update.message.reply_text(result)


async def do_train(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = await ensure_player(update)
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return

    result = train(player)
    db.save_player(player)
    await update.message.reply_text(result)


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
    await update.message.reply_text(result)


async def gacha(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = await ensure_player(update)
    if not player or update.message is None:
        await update.message.reply_text("Сначала создай персонажа: /start")
        return

    result = gacha_pull(player)
    db.save_player(player)
    await update.message.reply_text(result)


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


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    players = db.top_players(10)
    if not players:
        await update.message.reply_text("Пока нет игроков.")
        return

    lines = ["🏅 Топ игроков:"]
    for i, p in enumerate(players, start=1):
        lines.append(
            f"{i}. {p.username} — lvl {p.level}, RC {p.rc_cells}, EXP {p.exp}, ¥ {p.yen}"
        )

    await update.message.reply_text("\n".join(lines))


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Не найден BOT_TOKEN в переменных окружения")

    run_health_server_if_needed()
    ensure_event_loop()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("hunt", hunt))
    app.add_handler(CommandHandler("eat", eat))
    app.add_handler(CommandHandler("raid", raid))
    app.add_handler(CommandHandler("train", do_train))
    app.add_handler(CommandHandler("evolve", evolve))
    app.add_handler(CommandHandler("gacha", gacha))
    app.add_handler(CommandHandler("attack", attack))
    app.add_handler(CommandHandler("top", top))

    app.run_polling()


if __name__ == "__main__":
    main()
