# bot.py
import os
import random
import asyncio
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
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
    ITEMS_SHOP,
    KAGUNE_TYPES,
    GameDB,
    apply_level_up,
    check_cooldown,
    eat_human,
    format_time,
    pvp_attack,
    render_profile,
    roll_gacha,
    drink_coffee,
    start_raid,
)

UTC = timezone.utc
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Токен бота (BOT_TOKEN) не задан в конфигурационных файлах.")

DB_URI = os.getenv("DATABASE_URL", "game.db")
db = GameDB(DB_URI)

# Внутриигровые сессии и очереди
DUEL_QUEUE = []
ACTIVE_HUNT_SESSIONS = {}
COFFEE_COOLDOWNS = {}

# Инициализируем приложение Telegram Bot
telegram_app = Application.builder().token(BOT_TOKEN).build()


# ================= ПАРСЕР ТЕКСТА КНОПОК И КОМАНД =================

def get_command_type(text: str) -> str | None:
    val = text.lower().strip()
    clean_val = val
    # Очищаем строку от всех возможных эмодзи и пробелов для точного сопоставления
    for char in ["👤", "🏆", "🗡", "🏢", "☕", "🧬", "🛒", "🍖", "💪", "⚔️", "ℹ️", "❌", "🚨", " "]:
        clean_val = clean_val.replace(char, "")
        
    if clean_val in ["профиль", "profile", "персонаж", "stats", "статы"]:
        return "profile"
    if clean_val in ["топигроков", "топ", "top", "лидеры", "рейтинг"]:
        return "top"
    if clean_val in ["наохоту", "охота", "hunt"]:
        return "hunt"
    if clean_val in ["досказаказов", "заказы", "квесты", "доска", "заказ", "контракты"]:
        return "quest"
    if clean_val in ["пожирание", "съесть", "еда", "eat", "человек", "кушать"]:
        return "eat"
    if clean_val in ["кофейня", "кофе", "антейку", "coffee"]:
        return "coffee"
    if clean_val in ["гача", "gacha", "рулетка"]:
        return "gacha"
    if clean_val in ["тренировка", "треня", "спортзал", "качаться", "train"]:
        return "train"
    if clean_val in ["магазин", "рынок", "шоп", "shop"]:
        return "shop"
    if clean_val in ["рейд", "raid", "штурм"]:
        return "raid"
    if clean_val in ["искатьдуэль", "дуэль", "арена", "pvp", "duel", "найтидуэль", "бой"]:
        return "duel_search"
    if clean_val in ["отменадуэли", "отменапоиска", "отменитьдуэль", "отменадуэль", "отмена", "cancel"]:
        return "duel_cancel"
    if clean_val in ["инфо", "информация", "помощь", "help", "info", "справка"]:
        return "info"
    return None


# ================= ХЭНДЛЕРЫ КОМАНД И КНОПОК =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
        
    player = db.get_player(user.id)
    
    if player:
        await update.message.reply_text(
            f"Привет, {player.username}! Твой кагуне: {player.kagune}. Ты уже в игре!",
            reply_markup=main_keyboard()
        )
        return

    if context.args:
        choice = context.args[0].lower()
        if choice in KAGUNE_TYPES:
            player = db.create_player(user.id, user.full_name or f"User_{user.id}", choice)
            await update.message.reply_text(
                f"🎉 Персонаж успешно создан!\n\nТвой выбор: *{player.kagune}*\n"
                f"Мы выдали тебе стартовые 50 ¥. Пора заявить о себе на улицах Токио!",
                parse_mode="Markdown", reply_markup=main_keyboard()
            )
            return

    buttons = [
        [InlineKeyboardButton(f"🧬 {v['name']}", callback_data=f"setup:{k}")]
        for k, v in KAGUNE_TYPES.items()
    ]
    await update.message.reply_text(
        "🩸 *Добро пожаловать в Токийский подпольный мир.*\n\n"
        "Чтобы выжить здесь, тебе нужно активировать свои RC-клетки и выпустить Кагуне. "
        "Выбери свой врожденный тип боевого органа:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    data = query.data
    await query.answer()

    if data.startswith("setup:"):
        choice = data.split(":")[1]
        if db.get_player(user.id):
            await query.edit_message_text("У тебя уже есть персонаж!")
            return
        player = db.create_player(user.id, user.full_name or f"User_{user.id}", choice)
        await query.edit_message_text(
            f"🧬 *Выбран кагуне: {player.kagune}*\nВы готовы к своей первой охоте! Используйте меню ниже.",
            parse_mode="Markdown"
        )
        return

    if data.startswith("fight:"):
        player = db.get_player(user.id)
        session = ACTIVE_HUNT_SESSIONS.get(user.id)
        
        if not session or not player:
            await query.edit_message_text("❌ Бой уже завершен или не найден.")
            return

        action = data.split(":")[1]
        
        if action == "run":
            ACTIVE_HUNT_SESSIONS.pop(user.id, None)
            await query.edit_message_text("🏃 Вы тактически отступили вглубь переулков, сохранив свои пожитки.")
            return

        dmg_to_mob = max(5, player.strength + random.randint(-3, 5))
        session["mob_hp"] -= dmg_to_mob
        
        if session["mob_hp"] <= 0:
            yen_reward = random.randint(40, 90)
            exp_reward = random.randint(20, 40)
            player.yen += yen_reward
            player.exp += exp_reward
            lvl_msg = apply_level_up(player)
            db.save_player(player)
            ACTIVE_HUNT_SESSIONS.pop(user.id, None)
            
            await query.edit_message_text(
                f"⚔️ *Победа!*\nВы уничтожили `{session['mob_name']}`.\n\n"
                f"💰 Награда: +{yen_reward} ¥\n📈 Опыт: +{exp_reward} EXP\n{lvl_msg}",
                parse_mode="Markdown"
            )
            return

        dmg_to_player = max(2, session["mob_atk"] - (player.stamina // 2))
        player.hp = max(0, player.hp - dmg_to_player)
        
        if player.hp <= 0:
            ACTIVE_HUNT_SESSIONS.pop(user.id, None)
            player.hp = int(player.max_hp * 0.3)  
            player.yen = max(0, player.yen - 30)
            db.save_player(player)
            await query.edit_message_text(
                "💀 *Вы потеряли сознание!*\nПатруль CCG оказался сильнее. Вас обобрали на 30 ¥ и бросили в канаве."
            )
            return

        db.save_player(player)
        await query.edit_message_text(
            f"⚔️ *Бой продолжается!*\nВы нанесли врагу {dmg_to_mob} урона.\n"
            f"👹 `{session['mob_name']}` бьет в ответ: -{dmg_to_player} HP.\n\n"
            f"🩸 Твое здоровье: {player.hp}/{player.max_hp} HP\n"
            f"🖤 Здоровье врага: {session['mob_hp']} HP",
            parse_mode="Markdown",
            reply_markup=combat_keyboard()
        )

    if data.startswith("buy:"):
        item_id = data.split(":")[1]
        player = db.get_player(user.id)
        item = ITEMS_SHOP.get(item_id)
        
        if player.yen < item["cost"]:
            await query.message.reply_text("❌ Недостаточно йен для покупки данного предмета.")
            return
            
        player.yen -= item["cost"]
        if item["stat"] == "strength": player.strength += item["val"]
        elif item["stat"] == "stamina": player.stamina += item["val"]
        elif item["stat"] == "max_hp": 
            player.max_hp += item["val"]
            player.hp = player.max_hp
            
        db.save_player(player)
        await query.edit_message_text(f"🛍 Вы успешно приобрели *{item['name']}* за {item['cost']} ¥!")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not update.message or not update.message.text:
        return
        
    text = update.message.text
    player = db.get_player(user.id)

    if not player:
        await update.message.reply_text("Используй /start для инициализации персонажа.")
        return

    cmd = get_command_type(text)

    if not cmd:
        await update.message.reply_text("❌ Команда не распознана. Воспользуйтесь кнопками меню или напишите «помощь».")
        return

    if cmd == "profile":
        await update.message.reply_text(render_profile(player), parse_mode="Markdown")

    elif cmd == "top":
        leaders = db.top_players(10)
        msg = "🏆 *Рейтинг сильнейших гулей города:*\n\n"
        for idx, p in enumerate(leaders, 1):
            msg += f"{idx}. *{p.username}* — Уровень: {p.level} | RC-клетки: {p.rc_cells}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif cmd == "hunt":
        if user.id in ACTIVE_HUNT_SESSIONS:
            await update.message.reply_text("Вы уже находитесь в состоянии боя!", reply_markup=combat_keyboard())
            return
            
        is_ready, seconds = check_cooldown(player.last_hunt_at, timedelta(minutes=2))
        if not is_ready:
            await update.message.reply_text(f"⏳ Ваши рецепторы перегружены. Охота будет доступна через: {format_time(seconds)}")
            return

        mob_names = ["Следователь третьего класса", "Голодный Гуль", "Член Древа Аогири"]
        mob_name = random.choice(mob_names)
        ACTIVE_HUNT_SESSIONS[user.id] = {
            "mob_name": mob_name,
            "mob_hp": random.randint(40, 80),
            "mob_atk": random.randint(12, 22)
        }
        player.last_hunt_at = datetime.now(UTC).isoformat()
        db.save_player(player)

        await update.message.reply_text(
            f"🕵️‍♂️ Вы углубились в 20-й район и наткнулись на: *{mob_name}*!\nПриготовьтесь к бою.",
            parse_mode="Markdown",
            reply_markup=combat_keyboard()
        )

    elif cmd == "quest":
        is_ready, seconds = check_cooldown(player.last_quest_at, timedelta(minutes=10))
        if not is_ready:
            await update.message.reply_text(f"⏳ Доступных контрактов пока нет. Зайдите через: {format_time(seconds)}")
            return
            
        player.last_quest_at = datetime.now(UTC).isoformat()
        reward_yen = random.randint(60, 140)
        player.yen += reward_yen
        db.save_player(player)
        
        quests = [
            "Доставили посылку для куратора Антейку.",
            "Собрали ценные сведения о перемещениях CCG в районе.",
            "Помогли скрыть следы недавней стычки фракций."
        ]
        await update.message.reply_text(f"📋 *Выполнение контракта:*\n\n{random.choice(quests)}\n💰 Вы получили оплату: +{reward_yen} ¥", parse_mode="Markdown")

    elif cmd == "raid":
        is_ready, seconds = check_cooldown(player.last_raid_at, timedelta(hours=4))
        if not is_ready:
            await update.message.reply_text(f"⏳ Слишком высокая активность патрулей в районе CCG. Рейд будет доступен через: {format_time(seconds)}")
            return
        if player.hp < 55:
            await update.message.reply_text("❌ Вы слишком слабы для штурма штаба! Сначала восстановите здоровье в Кофейне.")
            return
            
        res = start_raid(player)
        db.save_player(player)
        await update.message.reply_text(res, parse_mode="Markdown")

    elif cmd == "eat":
        is_ready, seconds = check_cooldown(player.last_eat_at, timedelta(hours=2))
        if not is_ready:
            await update.message.reply_text(f"⏳ Вы еще не проголодались настолько сильно. Кулдаун: {format_time(seconds)}")
            return
        res = eat_human(player)
        db.save_player(player)
        await update.message.reply_text(res, parse_mode="Markdown")

    elif cmd == "coffee":
        now = datetime.now(UTC)
        last_coffee = COFFEE_COOLDOWNS.get(user.id)
        if last_coffee and now < last_coffee + timedelta(minutes=10):
            seconds = int((last_coffee + timedelta(minutes=10) - now).total_seconds())
            await update.message.reply_text(f"⏳ Кофеин ещё действует. Вы сможете посетить заведение повторно через: {format_time(seconds)}")
            return
            
        res = drink_coffee(player)
        if "❌" not in res:
            COFFEE_COOLDOWNS[user.id] = now
        db.save_player(player)
        await update.message.reply_text(res, parse_mode="Markdown")

    elif cmd == "gacha":
        res = roll_gacha(player)
        db.save_player(player)
        await update.message.reply_text(res, parse_mode="Markdown")

    elif cmd == "train":
        cost = 40 + (player.level * 5)
        if player.yen < cost:
            await update.message.reply_text(f"❌ Недостаточно средств. Стоимость тренировки для твоего уровня: {cost} ¥")
            return
        player.yen -= cost
        player.strength += random.randint(1, 3)
        player.stamina += random.randint(1, 3)
        db.save_player(player)
        await update.message.reply_text(f"🏋️‍♂️ Вы провели изнурительную тренировку в спортзале.\nХарактеристики Силы и Выносливости выросли! Списано: {cost} ¥")

    elif cmd == "shop":
        buttons = [
            [InlineKeyboardButton(f"{v['name']} ({v['cost']} ¥)", callback_data=f"buy:{k}")]
            for k, v in ITEMS_SHOP.items()
        ]
        await update.message.reply_text("🛒 *Черный рынок Токио.*\nЗдесь вы можете приобрести постоянные улучшения за наличные йены:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif cmd == "duel_search":
        if user.id in DUEL_QUEUE:
            await update.message.reply_text("Вы уже находитесь в очереди. Для отмены отправьте команду «отмена».")
            return
            
        if player.hp < int(player.max_hp * 0.4):
            await update.message.reply_text("❌ У вас слишком мало здоровья для аренных боев! Подлечитесь на Охоте, в Кофейне или на Пожирании.")
            return

        DUEL_QUEUE.append(user.id)
        if len(DUEL_QUEUE) < 2:
            await update.message.reply_text("🔍 Поиск достойного соперника по всему Токио...\nВы можете отменить поиск в любой момент, отправив слово «отмена».")
            return

        p1_id = DUEL_QUEUE.pop(0)
        p2_id = DUEL_QUEUE.pop(0)

        p1 = db.get_player(p1_id)
        p2 = db.get_player(p2_id)

        battle_report = pvp_attack(p1, p2)
        db.save_player(p1)
        db.save_player(p2)

        for uid, report in [(p1_id, f"⚔️ *Арена дуэлей!*\n\n{battle_report}"), (p2_id, f"⚔️ *На вас совершено нападение на Арене!*\n\n{battle_report}")]:
            try:
                await context.bot.send_message(chat_id=uid, text=report, parse_mode="Markdown", reply_markup=main_keyboard())
            except Exception:
                pass

    elif cmd == "duel_cancel":
        if user.id in DUEL_QUEUE:
            DUEL_QUEUE.remove(user.id)
            await update.message.reply_text("❌ Поиск оппонента для дуэли успешно отменен. Вы вышли из очереди.")
        else:
            await update.message.reply_text("Вы не находились в очереди поиска дуэлей.")

    elif cmd == "info":
        await update.message.reply_text(
            "🩸 *Tokyo Ghoul RPG Bot* 🩸\n\n"
            "Выживайте на улицах Токио, сражайтесь с агентами CCG и другими игроками, улучшайте свой Кагуне.\n\n"
            "💡 *Полезные подсказки:*\n"
            "• `Выносливость` снижает входящий урон и дает пассивный шанс увернуться от атак в PvP.\n"
            "• При критическом HP воспользуйтесь *Кофейней «Антейку»* (всего за 15 ¥ восстановит 40 HP).\n"
            "• Участвуйте в опасных *Рейдах* раз в 4 часа за ценные трофеи, но помните о рисках!\n"
            "• Вы можете отменить поиск арены в любой момент, написав в чат слово *«отмена»*.\n\n"
            "🎮 *Текстовые команды (можно писать текстом в чат):*\n"
            "➔ `профиль`, `топ`, `охота`, `заказы`, `рейд`, `кофейня`, `гача`, `магазин`, `пожирание`, `тренировка`, `дуэль`, `отмена`, `помощь`",
            parse_mode="Markdown"
        )


# Регистрируем хэндлеры
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CallbackQueryHandler(handle_callback))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))


# ================= КЛАВИАТУРЫ И ИНТЕРФЕЙС =================

def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["👤 Профиль", "🏆 Топ Игроков"],
            ["🗡 На Охоту", "🏢 Доска Заказов", "🚨 Рейд"],
            ["☕ Кофейня", "🧬 Гача", "🛒 Магазин"],
            ["🍖 Пожирание", "💪 Тренировка", "⚔️ Искать Дуэль"],
            ["ℹ️ Инфо"]
        ],
        resize_keyboard=True
    )

def combat_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💥 Атака в Голову", callback_data="fight:hit:head")],
        [InlineKeyboardButton("🛡 Защита Корпуса", callback_data="fight:hit:body")],
        [InlineKeyboardButton("🏃 Попытка Отхода", callback_data="fight:run")]
    ])


# ================= FASTAPI С LIFESPAN ДЛЯ ОБЩЕГО EVENT LOOP =================

@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    print("🤖 Telegram-бот успешно запущен в общем цикле с FastAPI!")
    
    yield
    
    await telegram_app.updater.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()
    print("🛑 Telegram-бот успешно остановлен.")


api = FastAPI(lifespan=lifespan)

@api.get("/")
def read_root():
    return {"status": "Бот активен, база данных подключена, веб-сервер отвечает!"}


def main() -> None:
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Инициализация FastAPI на порту {port}...")
    uvicorn.run(api, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
