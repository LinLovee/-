# bot.py
import os
import random
import asyncio
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

# Веб-сервер для интеграции с хостингом Render
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
)

UTC = timezone.utc
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Токен бота (BOT_TOKEN) не задан в конфигурационных файлах.")

# Приоритетно берем строку подключения Postgres из переменной DATABASE_URL, иначе используем локальный файл
DB_URI = os.getenv("DATABASE_URL", "game.db")
db = GameDB(DB_URI)

# Внутриигровые сессии и очереди
DUEL_QUEUE = []
ACTIVE_HUNT_SESSIONS = {}

# Инициализируем приложение Telegram Bot
telegram_app = Application.builder().token(BOT_TOKEN).build()


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

    if text == "👤 Профиль":
        await update.message.reply_text(render_profile(player), parse_mode="Markdown")

    elif text == "🗡 На Охоту":
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

    elif text == "🏢 Доска Заказов":
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

    elif text == "🍖 Пожирание":
        is_ready, seconds = check_cooldown(player.last_eat_at, timedelta(hours=2))
        if not is_ready:
            await update.message.reply_text(f"⏳ Вы еще не проголодались настолько сильно. Кулдаун: {format_time(seconds)}")
            return
        res = eat_human(player)
        db.save_player(player)
        await update.message.reply_text(res, parse_mode="Markdown")

    elif text == "☕ Кофейня":
        is_ready, seconds = check_cooldown(player.last_raid_at, timedelta(minutes=10))
        if not is_ready:
            await update.message.reply_text(f"⏳ Кофеин ещё действует. Вы сможете посетить заведение снова через: {format_time(seconds)}")
            return
        res = drink_coffee(player)
        db.save_player(player)
        await update.message.reply_text(res, parse_mode="Markdown")

    elif text == "🧬 Гача":
        res = roll_gacha(player)
        db.save_player(player)
        await update.message.reply_text(res, parse_mode="Markdown")

    elif text == "💪 Тренировка":
        cost = 40 + (player.level * 5)
        if player.yen < cost:
            await update.message.reply_text(f"❌ Недостаточно средств. Стоимость тренировки для твоего уровня: {cost} ¥")
            return
        player.yen -= cost
        player.strength += random.randint(1, 3)
        player.stamina += random.randint(1, 3)
        db.save_player(player)
        await update.message.reply_text(f"🏋️‍♂️ Вы провели изнурительную тренировку в спортзале.\nХарактеристики Силы и Выносливости выросли! Списано: {cost} ¥")

    elif text == "🛒 Магазин":
        buttons = [
            [InlineKeyboardButton(f"{v['name']} ({v['cost']} ¥)", callback_data=f"buy:{k}")]
            for k, v in ITEMS_SHOP.items()
        ]
        await update.message.reply_text("🛒 *Черный рынок Токио.*\nЗдесь вы можете приобрести постоянные улучшения за наличные йены:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif text == "🏆 Топ Игроков":
        leaders = db.top_players(10)
        msg = "🏆 *Рейтинг сильнейших гулей города:*\n\n"
        for idx, p in enumerate(leaders, 1):
            msg += f"{idx}. *{p.username}* — Уровень: {p.level} | RC-клетки: {p.rc_cells}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif text == "⚔️ Искать Дуэль":
        if user.id in DUEL_QUEUE:
            await update.message.reply_text("Вы уже находитесь в поиске оппонента для PvP.")
            return
            
        if player.hp < int(player.max_hp * 0.4):
            await update.message.reply_text("❌ У вас слишком мало здоровья для аренных боев! Подлечитесь на Охоте, Пожирании или в Кофейне.")
            return

        DUEL_QUEUE.append(user.id)
        if len(DUEL_QUEUE) < 2:
            await update.message.reply_text("🔍 Поиск достойного соперника по всему Токио... Ожидайте.")
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

    elif text == "ℹ️ Инфо":
        await update.message.reply_text(
            "🩸 *Tokyo Ghoul RPG Bot* 🩸\n\n"
            "Выживайте на улицах, сражайтесь с агентами CCG и другими игроками, улучшайте свой Кагуне.\n\n"
            "💡 _Совет: stamina уменьшает входящий урон и дает пассивный шанс увернуться от атак в PvP!_",
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
            ["🗡 На Охоту", "🏢 Доска Заказов"],
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
    # Этот блок срабатывает строго при старте веб-сервера Uvicorn
    # Бот инициализируется внутри активного Event Loop'а веб-сервера
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    print("🤖 Telegram-бот успешно запущен в общем цикле с FastAPI!")
    
    yield  # В этой точке веб-сервер принимает входящие запросы
    
    # Этот блок срабатывает при выключении сервера на Render
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
