# bot.py
import os
import json
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
    KAGUNE_SKILLS,
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
    get_kagune_key_by_name,
    execute_combat_turn,
    get_skill_upgrade_cost,
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
    if clean_val in ["прокачкаrc", "прокачка", "улучшение", "rc", "мутации", "лаборатория"]:
        return "rc_upgrades"
    if clean_val in ["искатьдуэль", "дуэль", "арена", "pvp", "duel", "найтидуэль", "бой"]:
        return "duel_search"
    if clean_val in ["отменадуэли", "отменапоиска", "отменитьдуэль", "отменадуэль", "отмена", "cancel"]:
        return "duel_cancel"
    if clean_val in ["инфо", "информация", "помощь", "help", "info", "справка"]:
        return "info"
    return None


# ================= КНОПКИ УЛУЧШЕНИЙ И БОЯ =================

def rc_upgrades_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧬 Мутации Тела (Характеристики)", callback_data="rc:menu:mutations")],
        [InlineKeyboardButton("🔥 Развитие Умений Кагуне", callback_data="rc:menu:skills")],
        [InlineKeyboardButton("❌ Выход из Лаборатории", callback_data="rc:close")]
    ])

def rc_mutations_keyboard(player: Player) -> InlineKeyboardMarkup:
    cost_str = player.strength * 6
    cost_sta = player.stamina * 6
    cost_hp = player.max_hp // 2
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⚔️ Закалка Кагуне (+2 Силы) | 🧪 {cost_str} RC", callback_data="rc:mutate:strength")],
        [InlineKeyboardButton(f"🛡 Синтез Брони (+2 Защиты) | 🧪 {cost_sta} RC", callback_data="rc:mutate:stamina")],
        [InlineKeyboardButton(f"❤️ Развитие RC-каналов (+15 HP) | 🧪 {cost_hp} RC", callback_data="rc:mutate:max_hp")],
        [InlineKeyboardButton(f"⬅️ Назад в Лабораторию", callback_data="rc:menu:main")]
    ])

def rc_skills_keyboard(player: Player) -> InlineKeyboardMarkup:
    key = get_kagune_key_by_name(player.kagune)
    skills_cfg = KAGUNE_SKILLS[key]
    player_skills = player.get_skills_dict()
    
    s1_lvl = player_skills.get("s1", 1)
    s2_lvl = player_skills.get("s2", 1)
    s3_lvl = player_skills.get("s3", 1)
    
    c1 = get_skill_upgrade_cost(s1_lvl)
    c2 = get_skill_upgrade_cost(s2_lvl)
    c3 = get_skill_upgrade_cost(s3_lvl)
    
    btn1_text = f"1️⃣ Навык 1 ({s1_lvl}/5 Lvl) | 🧪 {c1} RC" if c1 else f"1️⃣ Навык 1 (МАКС. Lvl)"
    btn2_text = f"2️⃣ Навык 2 ({s2_lvl}/5 Lvl) | 🧪 {c2} RC" if c2 else f"2️⃣ Навык 2 (МАКС. Lvl)"
    btn3_text = f"3️⃣ Ультимейт ({s3_lvl}/5 Lvl) | 🧪 {c3} RC" if c3 else f"3️⃣ Ультимейт (МАКС. Lvl)"
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(btn1_text, callback_data="rc:lvlup:s1" if c1 else "rc:lvlup:max")],
        [InlineKeyboardButton(btn2_text, callback_data="rc:lvlup:s2" if c2 else "rc:lvlup:max")],
        [InlineKeyboardButton(btn3_text, callback_data="rc:lvlup:s3" if c3 else "rc:lvlup:max")],
        [InlineKeyboardButton(f"⬅️ Назад в Лабораторию", callback_data="rc:menu:main")]
    ])

def combat_keyboard_for_player(player: Player) -> InlineKeyboardMarkup:
    key = get_kagune_key_by_name(player.kagune)
    skills = KAGUNE_SKILLS[key]
    player_skills = player.get_skills_dict()
    
    s1_lvl = player_skills.get("s1", 1)
    s2_lvl = player_skills.get("s2", 1)
    s3_lvl = player_skills.get("s3", 1)
    
    btn_1 = InlineKeyboardButton(f"⚔️ Атака ({player.strength} DMG)", callback_data="fight:hit:basic")
    btn_2 = InlineKeyboardButton(f"🌀 {skills[0]['name']} [Lvl {s1_lvl}] ({skills[0]['cost_rc']}🧪)", callback_data="fight:hit:skill1")
    btn_3 = InlineKeyboardButton(f"🛡 {skills[1]['name']} [Lvl {s2_lvl}] ({skills[1]['cost_rc']}🧪)", callback_data="fight:hit:skill2")
    btn_4 = InlineKeyboardButton(f"💀 {skills[2]['name']} [Lvl {s3_lvl}] ({skills[2]['cost_rc']}🧪)", callback_data="fight:hit:ult")
    btn_run = InlineKeyboardButton("🏃 Попытка Отхода", callback_data="fight:run")
    
    return InlineKeyboardMarkup([
        [btn_1],
        [btn_2, btn_3],
        [btn_4],
        [btn_run]
    ])


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

    buttons = [
        [InlineKeyboardButton(f"🧬 {v['name'].split(' ')[0]}", callback_data=f"setup_info:{k}")]
        for k, v in KAGUNE_TYPES.items()
    ]
    await update.message.reply_text(
        "🩸 *Добро пожаловать в Токийский подпольный мир.*\n\n"
        "Чтобы выжить на улицах города, вы должны активировать свои RC-клетки и выпустить Кагуне.\n"
        "Выберите интересующий Кагуне ниже для подробного изучения характеристик, лора и боевых навыков:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    data = query.data
    await query.answer()

    # Показ лора и навыков конкретного кагуне
    if data.startswith("setup_info:"):
        choice = data.split(":")[1]
        info = KAGUNE_TYPES[choice]
        skills = KAGUNE_SKILLS[choice]
        
        text = (
            f"🧬 *{info['name']}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📖 *Лор-описание:* {info['description']}\n\n"
            f"📊 *Стартовые бонусы пробуждения:*\n"
            f"⚔️ Сила (Базовый урон): +{info['bonus']['strength']}\n"
            f"🛡 Выносливость (Броня): +{info['bonus']['stamina']}\n"
            f"❤️ Макс. Здоровье: +{info['bonus']['max_hp']} HP\n\n"
            f"🌀 *Доступный боевой арсенал умений:*\n"
            f"1️⃣ *{skills[0]['name']}* (Расход: {skills[0]['cost_rc']}🧪)\n"
            f"   _— {skills[0]['desc']}_\n"
            f"2️⃣ *{skills[1]['name']}* (Расход: {skills[1]['cost_rc']}🧪)\n"
            f"   _— {skills[1]['desc']}_\n"
            f"3️⃣ *{skills[2]['name']}* (Расход: {skills[2]['cost_rc']}🧪)\n"
            f"   _— {skills[2]['desc']}_\n\n"
            f"Вы уверены, что хотите пробудить эти RC-каналы?"
        )
        buttons = [
            [InlineKeyboardButton("✅ Пробудить этот Кагуне", callback_data=f"setup_select:{choice}")],
            [InlineKeyboardButton("⬅️ Вернуться назад", callback_data="setup_back")]
        ]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
        return

    # Возврат к списку кагуне
    if data == "setup_back":
        buttons = [
            [InlineKeyboardButton(f"🧬 {v['name'].split(' ')[0]}", callback_data=f"setup_info:{k}")]
            for k, v in KAGUNE_TYPES.items()
        ]
        await query.edit_message_text(
            "🩸 *Добро пожаловать в Токийский подпольный мир.*\n\n"
            "Чтобы выжить на улицах города, вы должны активировать свои RC-клетки и выпустить Кагуне.\n"
            "Выберите интересующий Кагуне ниже для подробного изучения характеристик, лора и боевых навыков:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # Окончательный выбор и пробуждение
    if data.startswith("setup_select:"):
        choice = data.split(":")[1]
        if db.get_player(user.id):
            await query.edit_message_text("Кагуне у вашего персонажа уже выбран.")
            return
        player = db.create_player(user.id, user.full_name or f"User_{user.id}", choice)
        await query.edit_message_text(
            f"🧬 *Ваш Кагуне успешно пробужден: {player.kagune}!*\n\n"
            f"Вам выдано 50 ¥ в дорогу. Пожирайте людей и следователей CCG, чтобы расти в пищевой цепочке Токио!",
            parse_mode="Markdown"
        )
        await context.bot.send_message(
            chat_id=user.id,
            text="🎮 Основное игровое меню успешно активировано:",
            reply_markup=main_keyboard()
        )
        return

    # Логика работы «Лаборатории RC-улучшений»
    if data.startswith("rc:"):
        player = db.get_player(user.id)
        if not player:
            return
            
        action = data.split(":")[1]
        
        if action == "close":
            await query.edit_message_text("🧬 Вы закрыли интерфейс биолаборатории RC.")
            return

        if action == "menu":
            menu_type = data.split(":")[2]
            if menu_type == "main":
                await query.edit_message_text(
                    f"🧬 *Секретная Лаборатория RC-структур*\n\n"
                    f"Приветствуем, *{player.username}*. Здесь вы можете вкладывать избыточную биомассу в развитие физических возможностей вашего тела.\n\n"
                    f"🧪 Ваш свободный резервуар: *{player.rc_cells}* RC-клеток.\n"
                    f"Выберите направление развития:",
                    parse_mode="Markdown",
                    reply_markup=rc_upgrades_main_keyboard()
                )
            elif menu_type == "mutations":
                await query.edit_message_text(
                    f"🧬 *Физиологические RC-Мутации Тела*\n\n"
                    f"Перманентные физические изменения. Действуют всегда, повышая базовый потенциал во всех боевых режимах!\n\n"
                    f"🧪 Свободных RC-клеток: *{player.rc_cells}*\n"
                    f"⚔️ Сила (Атака): *{player.strength}*\n"
                    f"🛡 Выносливость (Защита): *{player.stamina}*\n"
                    f"❤️ Макс. Здоровье: *{player.max_hp} HP*",
                    parse_mode="Markdown",
                    reply_markup=rc_mutations_keyboard(player)
                )
            elif menu_type == "skills":
                await query.edit_message_text(
                    f"🧬 *Усовершенствование Боевых Умений Кагуне*\n\n"
                    f"Повышение уровня навыков увеличивает их урон, показатели брони или объем лечения в бою на *+15%* за уровень.\n\n"
                    f"🧪 Свободных RC-клеток: *{player.rc_cells}*",
                    parse_mode="Markdown",
                    reply_markup=rc_skills_keyboard(player)
                )
            return

        if action == "mutate":
            stat = data.split(":")[2]
            cost_str = player.strength * 6
            cost_sta = player.stamina * 6
            cost_hp = player.max_hp // 2
            
            if stat == "strength":
                if player.rc_cells < cost_str:
                    await query.answer("❌ Недостаточно RC-клеток!", show_alert=True)
                    return
                player.rc_cells -= cost_str
                player.strength += 2
                await query.answer("🔺 Сила увеличена на +2!", show_alert=True)
                
            elif stat == "stamina":
                if player.rc_cells < cost_sta:
                    await query.answer("❌ Недостаточно RC-клеток!", show_alert=True)
                    return
                player.rc_cells -= cost_sta
                player.stamina += 2
                await query.answer("🔺 Выносливость увеличена на +2!", show_alert=True)
                
            elif stat == "max_hp":
                if player.rc_cells < cost_hp:
                    await query.answer("❌ Недостаточно RC-клеток!", show_alert=True)
                    return
                player.rc_cells -= cost_hp
                player.max_hp += 15
                player.hp = player.max_hp
                await query.answer("🔺 Макс. HP увеличено на +15!", show_alert=True)
                
            db.save_player(player)
            # Обновляем меню мутаций
            await query.edit_message_text(
                f"🧬 *Физиологические RC-Мутации Тела*\n\n"
                f"Перманентные физические изменения. Действуют всегда, повышая базовый потенциал во всех боевых режимах!\n\n"
                f"🧪 Свободных RC-клеток: *{player.rc_cells}*\n"
                f"⚔️ Сила (Атака): *{player.strength}*\n"
                f"🛡 Выносливость (Защита): *{player.stamina}*\n"
                f"❤️ Макс. Здоровье: *{player.max_hp} HP*",
                parse_mode="Markdown",
                reply_markup=rc_mutations_keyboard(player)
            )
            return

        if action == "lvlup":
            skill_slot = data.split(":")[2]
            if skill_slot == "max":
                await query.answer("🔥 Навык уже развит до максимального 5-го уровня!", show_alert=True)
                return
                
            skills_dict = player.get_skills_dict()
            curr_lvl = skills_dict.get(skill_slot, 1)
            cost = get_skill_upgrade_cost(curr_lvl)
            
            if not cost:
                await query.answer("🔥 Навык уже развит до максимального уровня!", show_alert=True)
                return
                
            if player.rc_cells < cost:
                await query.answer(f"❌ Требуется {cost} RC-клеток!", show_alert=True)
                return
                
            player.rc_cells -= cost
            skills_dict[skill_slot] = curr_lvl + 1
            player.skills_json = json.dumps(skills_dict)
            db.save_player(player)
            
            await query.answer(f"🔺 Навык повышен до Lvl {curr_lvl + 1}!", show_alert=True)
            
            # Обновляем меню навыков
            await query.edit_message_text(
                f"🧬 *Усовершенствование Боевых Умений Кагуне*\n\n"
                f"Повышение уровня навыков увеличивает их урон, показатели брони или объем лечения в бою на *+15%* за уровень.\n\n"
                f"🧪 Свободных RC-клеток: *{player.rc_cells}*",
                parse_mode="Markdown",
                reply_markup=rc_skills_keyboard(player)
            )
            return

    # Обработка ходов в бою на Охоте
    if data.startswith("fight:"):
        player = db.get_player(user.id)
        session = ACTIVE_HUNT_SESSIONS.get(user.id)
        
        if not session or not player:
            await query.edit_message_text("❌ Бой уже завершен.")
            return

        action = data.split(":")[1]
        
        if action == "run":
            ACTIVE_HUNT_SESSIONS.pop(user.id, None)
            await query.edit_message_text("🏃 Вы оперативно отступили во тьму переулков, сохранив свои пожитки.")
            return

        hit_type = data.split(":")[2]
        result = execute_combat_turn(player, session, hit_type)
        
        if isinstance(result, str):
            await query.answer(result, show_alert=True)
            return

        db.save_player(player)

        # Проверка смерти моба
        if session["mob_hp"] <= 0:
            yen_reward = random.randint(40, 90)
            exp_reward = random.randint(20, 40)
            rc_reward = random.randint(15, 30)
            
            player.yen += yen_reward
            player.exp += exp_reward
            player.rc_cells += rc_reward
            
            lvl_msg = apply_level_up(player)
            db.save_player(player)
            ACTIVE_HUNT_SESSIONS.pop(user.id, None)
            
            await query.edit_message_text(
                f"⚔️ *Победа над следователем!*\nВы уничтожили `{session['mob_name']}`.\n\n"
                f"🧬 Собрано биоматериала: +{rc_reward} 🧪 RC-клеток\n"
                f"💰 Добыча: +{yen_reward} ¥\n"
                f"📈 Опыт: +{exp_reward} EXP\n\n"
                f"{lvl_msg}",
                parse_mode="Markdown"
            )
            return

        # Проверка смерти игрока
        if player.hp <= 0:
            ACTIVE_HUNT_SESSIONS.pop(user.id, None)
            player.hp = int(player.max_hp * 0.3)  
            player.yen = max(0, player.yen - 30)
            db.save_player(player)
            await query.edit_message_text(
                "💀 *Вы потеряли сознание!*\n"
                "Группа следователей CCG загнала вас в тупик. При поспешном отступлении потеряно 30 ¥."
            )
            return

        # Продолжение боя
        db.save_player(player)
        await query.edit_message_text(
            f"⚔️ *Идет ожесточенная битва!*\n\n"
            f"{result['msg']}\n"
            f"👹 `{session['mob_name']}` наносит ответный удар: -{result['mob_dmg']} HP.\n\n"
            f"🩸 Твое здоровье: {player.hp}/{player.max_hp} HP\n"
            f"🧪 Запас RC-клеток: {player.rc_cells}\n"
            f"🖤 Здоровье врага: {session['mob_hp']} HP",
            parse_mode="Markdown",
            reply_markup=combat_keyboard_for_player(player)
        )
        return

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
            await update.message.reply_text("Вы уже находитесь в состоянии боя!", reply_markup=combat_keyboard_for_player(player))
            return
            
        is_ready, seconds = check_cooldown(player.last_hunt_at, timedelta(minutes=2))
        if not is_ready:
            await update.message.reply_text(f"⏳ Ваши рецепторы перегружены. Охота будет доступна через: {format_time(seconds)}")
            return

        mob_names = ["Следователь CCG третьего класса", "Территориальный Дикий Гуль", "Разведчик Древа Аогири"]
        mob_name = random.choice(mob_names)
        ACTIVE_HUNT_SESSIONS[user.id] = {
            "mob_name": mob_name,
            "mob_hp": random.randint(40, 80),
            "mob_atk": random.randint(12, 22)
        }
        player.last_hunt_at = datetime.now(UTC).isoformat()
        db.save_player(player)

        await update.message.reply_text(
            f"🕵️‍♂️ Вы углубились в переулки и наткнулись на: *{mob_name}*!\nПриготовьтесь к бою.",
            parse_mode="Markdown",
            reply_markup=combat_keyboard_for_player(player)
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

    elif cmd == "rc_upgrades":
        await update.message.reply_text(
            f"🧬 *Секретная Лаборатория RC-структур*\n\n"
            f"Приветствуем, *{player.username}*. Здесь вы можете вкладывать избыточную биомассу в развитие физических возможностей вашего тела.\n\n"
            f"🧪 Ваш свободный резервуар: *{player.rc_cells}* RC-клеток.\n"
            f"Выберите направление развития:",
            parse_mode="Markdown",
            reply_markup=rc_upgrades_main_keyboard()
        )

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
            ["☕ Кофейня", "🧬 Прокачка RC", "🧬 Гача"],
            ["🍖 Пожирание", "💪 Тренировка", "🛒 Магазин"],
            ["⚔️ Искать Дуэль", "ℹ️ Инфо"]
        ],
        resize_keyboard=True
    )


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
