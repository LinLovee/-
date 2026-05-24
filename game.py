# game.py
import os
import json
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

try:
    import psycopg2
except ImportError:
    psycopg2 = None

UTC = timezone.utc

KAGUNE_TYPES = {
    "rinkaku": {
        "name": "Ринкаку (Чешуйчатые щупальца)",
        "description": "Свирепый тип кагуне в виде чешуйчатых щупалец. Отличается невероятной взрывной силой, пробивающей даже самую плотную броню, и высочайшей скоростью регенерации клеток. Однако связи между RC-клетками у этого типа крайне хрупкие, что делает его носителя уязвимым.",
        "bonus": {"strength": 4, "stamina": 1, "max_hp": 15},
    },
    "ukaku": {
        "name": "Укаку (Кристаллические крылья)",
        "description": "Высокоскоростной тип, напоминающий яркие кристаллизованные крылья. Позволяет вести непрерывный обстрел шипами на дистанции и мгновенно уворачиваться от выпадов врага. Основной недостаток — колоссальный расход энергии и быстрая утомляемость.",
        "bonus": {"strength": 2, "stamina": 4, "max_hp": 10},
    },
    "koukaku": {
        "name": "Коукаку (Тяжелый доспех)",
        "description": "Чрезвычайно плотный металлический кагуне, формирующийся в виде щита, бура или тяжелого доспеха. Гарантирует абсолютную защиту от холодного и огнестрельного оружия. Повышает выносливость и живучесть, но сильно сковывает движения.",
        "bonus": {"strength": 2, "stamina": 5, "max_hp": 25},
    },
    "bikaku": {
        "name": "Бикаку (Тактический хвост)",
        "description": "Сбалансированный кагуне в форме мощного хвоста. Универсальное оружие без явных слабых мест: обеспечивает прекрасный контроль дистанции, скоординированную защиту и сокрушительные контратаки. Идеальный тактический выбор для любого стиля боя.",
        "bonus": {"strength": 3, "stamina": 3, "max_hp": 15},
    },
}

# Справочник уникальных навыков для каждого типа Кагуне (базовые коэффициенты)
KAGUNE_SKILLS = {
    "rinkaku": [
        {"id": "s1", "name": "🩸 Быстрая регенерация", "desc": "Концентрирует RC-клетки, мгновенно восстанавливая здоровье в бою.", "cost_rc": 15, "value": 25},
        {"id": "s2", "name": "⚔️ Тройной разрез", "desc": "Сокрушительный скоординированный удар щупальцами.", "cost_rc": 20, "value": 1.5},
        {"id": "s3", "name": "💀 Безумие Какуджа", "desc": "Вхождение в полу-форму монстра, нанося огромный урон и исцеляя тело.", "cost_rc": 40, "value": 2.2}
    ],
    "ukaku": [
        {"id": "s1", "name": "✨ Кристаллический залп", "desc": "Выстреливает веером острых перьев по уязвимым точкам.", "cost_rc": 15, "value": 1.3},
        {"id": "s2", "name": "💨 Реактивный уворот", "desc": "Мгновенно снижает урон от ответного удара противника.", "cost_rc": 15, "value": 1.0},
        {"id": "s3", "name": "⚡ Ураганный обстрел", "desc": "Сокрушающий непрерывный шторм из сотен RC-кристаллов.", "cost_rc": 35, "value": 2.0}
    ],
    "koukaku": [
        {"id": "s1", "name": "🛡 Тяжелый барьер", "desc": "Формирует щит из закаленной стали, снижающий урон.", "cost_rc": 15, "value": 0.3},
        {"id": "s2", "name": "🌪 Спиральный таран", "desc": "Превращает защитный сегмент в тяжелый пробивающий бур.", "cost_rc": 20, "value": 1.4},
        {"id": "s3", "name": "🌋 Обвал брони", "desc": "Использует массу доспеха для проведения сокрушительной атаки.", "cost_rc": 40, "value": 2.5}
    ],
    "bikaku": [
        {"id": "s1", "name": "🌀 Сметающий взмах", "desc": "Широкий круговой удар хвостом, ослабляющий противника.", "cost_rc": 15, "value": 1.2},
        {"id": "s2", "name": "⚔️ Тактическое парирование", "desc": "Перехватывает инициативу, снижая урон и восстанавливая HP.", "cost_rc": 15, "value": 1.1},
        {"id": "s3", "name": "🐉 Комбо Смерти", "desc": "Безупречная серия быстрых, точно рассчитанных ударов.", "cost_rc": 35, "value": 2.1}
    ]
}

KAGUNE_ALIASES = {
    "ринкакку": "rinkaku",
    "ринкаку": "rinkaku",
    "укаку": "ukaku",
    "кукаку": "koukaku",
    "коукаку": "koukaku",
    "бикаку": "bikaku",
}

ITEMS_SHOP = {
    "mask": {"name": "🎭 Маска Гуля", "cost": 150, "desc": "+5 к выносливости", "stat": "stamina", "val": 5},
    "injector": {"name": "🧪 RC-Стимулятор", "cost": 250, "desc": "+30 к макс. HP навсегда", "stat": "max_hp", "val": 30},
    "brass": {"name": "👊 Кастет из куинке", "cost": 200, "desc": "+6 к силе атаки", "stat": "strength", "val": 6}
}

def normalize_kagune_key(raw_key: str) -> str | None:
    key = raw_key.lower().strip()
    if key in KAGUNE_TYPES:
        return key
    return KAGUNE_ALIASES.get(key)

def get_kagune_key_by_name(name: str) -> str:
    for key, info in KAGUNE_TYPES.items():
        if info["name"].split(" ")[0].lower() == name.split(" ")[0].lower():
            return key
    return "rinkaku"

def get_skill_upgrade_cost(current_level: int) -> int | None:
    costs = {1: 120, 2: 250, 3: 500, 4: 1000}
    return costs.get(current_level, None)

@dataclass
class Player:
    user_id: int
    username: str
    faction: str
    level: int
    exp: int
    hp: int
    max_hp: int
    strength: int
    stamina: int
    yen: int
    kagune: str
    rc_cells: int
    humans_eaten: int
    gacha_pulls: int
    legendary_drops: int
    last_hunt_at: str | None
    last_eat_at: str | None
    last_raid_at: str | None
    last_quest_at: str | None
    skills_json: str | None = '{}'

    def get_skills_dict(self) -> dict:
        if not self.skills_json:
            return {"s1": 1, "s2": 1, "s3": 1}
        try:
            return json.loads(self.skills_json)
        except Exception:
            return {"s1": 1, "s2": 1, "s3": 1}

class GameDB:
    def __init__(self, db_uri: str) -> None:
        self.db_uri = db_uri
        self.is_postgres = db_uri.startswith("postgres://") or db_uri.startswith("postgresql://")
        self._init_db()

    def _connect(self):
        if self.is_postgres:
            if not psycopg2:
                raise ImportError("Для работы с PostgreSQL установите пакет 'psycopg2-binary'")
            url = self.db_uri
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            return psycopg2.connect(url)
        else:
            conn = sqlite3.connect(self.db_uri)
            conn.row_factory = sqlite3.Row
            return conn

    def _init_db(self) -> None:
        query = """
        CREATE TABLE IF NOT EXISTS players (
            user_id BIGINT PRIMARY KEY,
            username TEXT NOT NULL,
            faction TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1,
            exp INTEGER NOT NULL DEFAULT 0,
            hp INTEGER NOT NULL DEFAULT 100,
            max_hp INTEGER NOT NULL DEFAULT 100,
            strength INTEGER NOT NULL DEFAULT 12,
            stamina INTEGER NOT NULL DEFAULT 10,
            yen INTEGER NOT NULL DEFAULT 50,
            kagune TEXT NOT NULL,
            rc_cells INTEGER NOT NULL DEFAULT 0,
            humans_eaten INTEGER NOT NULL DEFAULT 0,
            gacha_pulls INTEGER NOT NULL DEFAULT 0,
            legendary_drops INTEGER NOT NULL DEFAULT 0,
            last_hunt_at TEXT,
            last_eat_at TEXT,
            last_raid_at TEXT,
            last_quest_at TEXT,
            skills_json TEXT NOT NULL DEFAULT '{}'
        )
        """
        if self.is_postgres:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(query)
                    # Проверяем и накатываем структуру столбцов
                    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='players' AND column_name='skills_json'")
                    if not cur.fetchone():
                        cur.execute("ALTER TABLE players ADD COLUMN skills_json TEXT NOT NULL DEFAULT '{}'")
                conn.commit()
            finally:
                conn.close()
        else:
            with self._connect() as conn:
                conn.execute(query)
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(players)").fetchall()}
                if "last_quest_at" not in columns:
                    conn.execute("ALTER TABLE players ADD COLUMN last_quest_at TEXT")
                if "skills_json" not in columns:
                    conn.execute("ALTER TABLE players ADD COLUMN skills_json TEXT NOT NULL DEFAULT '{}'")

    def _q(self, sql: str) -> str:
        if self.is_postgres:
            return sql.replace("?", "%s")
        return sql

    def _row_to_dict(self, cursor, row) -> dict:
        if row is None:
            return None
        if self.is_postgres:
            colnames = [desc[0] for desc in cursor.description]
            return dict(zip(colnames, row))
        return dict(row)

    def _execute(self, sql: str, params: tuple = ()) -> None:
        sql_conv = self._q(sql)
        conn = self._connect()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute(sql_conv, params)
                if self.is_postgres:
                    conn.commit()
        finally:
            conn.close()

    def _fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        sql_conv = self._q(sql)
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(sql_conv, params)
            row = cur.fetchone()
            return self._row_to_dict(cur, row)
        finally:
            conn.close()

    def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        sql_conv = self._q(sql)
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(sql_conv, params)
            rows = cur.fetchall()
            return [self._row_to_dict(cur, r) for r in rows]
        finally:
            conn.close()

    def get_player(self, user_id: int) -> Player | None:
        row = self._fetchone("SELECT * FROM players WHERE user_id = ?", (user_id,))
        if not row:
            return None
        return Player(**row)

    def create_player(self, user_id: int, username: str, kagune_key: str) -> Player:
        chosen = KAGUNE_TYPES[kagune_key]
        bonus = chosen["bonus"]
        sql = """
        INSERT INTO players (user_id, username, faction, kagune, strength, stamina, max_hp, hp, skills_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            user_id,
            username,
            "Гуль",
            chosen["name"],
            12 + bonus["strength"],
            10 + bonus["stamina"],
            100 + bonus["max_hp"],
            100 + bonus["max_hp"],
            '{"s1": 1, "s2": 1, "s3": 1}'
        )
        self._execute(sql, params)
        return self.get_player(user_id)

    def save_player(self, player: Player) -> None:
        sql = """
        UPDATE players
        SET username = ?, faction = ?, level = ?, exp = ?, hp = ?,
            max_hp = ?, strength = ?, stamina = ?, yen = ?, kagune = ?,
            rc_cells = ?, humans_eaten = ?, gacha_pulls = ?, legendary_drops = ?,
            last_hunt_at = ?, last_eat_at = ?, last_raid_at = ?, last_quest_at = ?,
            skills_json = ?
        WHERE user_id = ?
        """
        params = (
            player.username, player.faction, player.level, player.exp, player.hp,
            player.max_hp, player.strength, player.stamina, player.yen, player.kagune,
            player.rc_cells, player.humans_eaten, player.gacha_pulls, player.legendary_drops,
            player.last_hunt_at, player.last_eat_at, player.last_raid_at, player.last_quest_at,
            player.skills_json, player.user_id
        )
        self._execute(sql, params)

    def top_players(self, limit: int = 10) -> list[Player]:
        rows = self._fetchall("SELECT * FROM players ORDER BY level DESC, rc_cells DESC LIMIT ?", (limit,))
        return [Player(**r) for r in rows]


# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И ЛОГИКА ИГРЫ =================

def exp_to_level_up(level: int) -> int:
    return 100 + (level - 1) * 50

def apply_level_up(player: Player) -> str:
    messages = []
    while player.exp >= exp_to_level_up(player.level):
        player.exp -= exp_to_level_up(player.level)
        player.level += 1
        player.max_hp += 15
        player.hp = player.max_hp
        player.strength += 4
        player.stamina += 3
        player.rc_cells += 15
        messages.append(f"🔺 *Уровень повышен до {player.level}!* Характеристики улучшены, получено +15 RC клеток.")
    return "\n".join(messages)

def check_cooldown(last_event_at: str | None, cooldown_delta: timedelta) -> tuple[bool, int]:
    if not last_event_at:
        return True, 0
    try:
        last_event = datetime.fromisoformat(last_event_at)
    except ValueError:
        return True, 0
    now = datetime.now(UTC)
    available_at = last_event + cooldown_delta
    if now >= available_at:
        return True, 0
    return False, int((available_at - now).total_seconds())

def format_time(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} сек."
    minutes = seconds // 60
    return f"{minutes} мин. {seconds % 60} сек."

def render_profile(player: Player) -> str:
    req_exp = exp_to_level_up(player.level)
    skills = player.get_skills_dict()
    return (
        f"👤 *Профиль игрока: {player.username}*\n"
        f"🏷 Фракция: {player.faction}\n"
        f"🧬 Кагуне: {player.kagune}\n\n"
        f"📊 *Характеристики:*\n"
        f"▪️ Уровень: {player.level}  `[{player.exp}/{req_exp} EXP]`\n"
        f"❤️ Здоровье: {player.hp}/{player.max_hp} HP\n"
        f"⚔️ Сила (Атака): {player.strength}\n"
        f"🛡 Выносливость (Броня): {player.stamina}\n\n"
        f"⚡ *Степени развития умений:*\n"
        f"🔸 Навык 1: `Lvl {skills.get('s1', 1)}/5`\n"
        f"🔸 Навык 2: `Lvl {skills.get('s2', 1)}/5`\n"
        f"🔸 Ультимейт: `Lvl {skills.get('s3', 1)}/5`\n\n"
        f"💰 Баланс: {player.yen} ¥\n"
        f"🧪 RC-клетки: {player.rc_cells}\n"
        f"🥩 Поедание людей: {player.humans_eaten}\n"
        f"🎲 Прокрутки Гачи: {player.gacha_pulls} *(Легендарки: {player.legendary_drops})*"
    )

def eat_human(player: Player) -> str:
    player.last_eat_at = datetime.now(UTC).isoformat()
    gained_rc = random.randint(25, 50)
    gained_exp = random.randint(20, 35)
    player.rc_cells += gained_rc
    player.exp += gained_exp
    player.humans_eaten += 1
    
    heal = random.randint(15, 30)
    player.hp = min(player.max_hp, player.hp + heal)
    
    lvl_msg = apply_level_up(player)
    return (
        f"🍖 *Успешная ночная охота!*\n"
        f"Вы выследили нарушителя комендантского часа и восполнили свои запасы.\n\n"
        f"🧬 Получено: +{gained_rc} RC клеток\n"
        f"📈 Опыт: +{gained_exp} EXP\n"
        f"🩸 Регенерация: +{heal} HP (Текущее: {player.hp}/{player.max_hp})\n"
        f"{lvl_msg}"
    ).strip()

def roll_gacha(player: Player) -> str:
    if player.rc_cells < 100:
        return "❌ Недостаточно RC-клеток. Для одного прокрута требуется 100 🧪 клеток."
    
    player.rc_cells -= 100
    player.gacha_pulls += 1
    roll = random.random()
    
    if roll < 0.05:
        player.legendary_drops += 1
        player.max_hp += 80
        player.hp = player.max_hp
        player.strength += 12
        return (
            "💎 *ЛЕГЕНДАРНЫЙ СИНТЕЗ!*\n"
            "Вы успешно пересадили себе *Ядро Какуджа*!\n\n"
            "🔺 Макс. HP навсегда увеличено на *+80*!\n"
            "🔺 Сила навсегда увеличена на *+12*!"
        )
    elif roll < 0.35:
        stat_choice = random.choice(["strength", "stamina"])
        gain = random.randint(3, 5)
        if stat_choice == "strength":
            player.strength += gain
            stat_name = "Сила"
        else:
            player.stamina += gain
            stat_name = "Выносливость"
        return (
            "✨ *Редкий исход!*\n"
            f"Вы выпили очищенную RC-эмульсию. Ваша *{stat_name}* увеличилась на *+{gain}*!"
        )
    else:
        yen_gain = random.randint(100, 250)
        player.yen += yen_gain
        return (
            "📦 *Обычный исход!*\n"
            f"Вы выгодно перепродали излишки биоматериала информаторам. Получено: *+{yen_gain} ¥*."
        )

def drink_coffee(player: Player) -> str:
    if player.yen < 15:
        return "❌ У вас нет 15 ¥ на чашечку фирменного кофе."
    
    player.yen -= 15
    heal = 40
    player.hp = min(player.max_hp, player.hp + heal)
    return (
        "☕ *Кофейня Антейку*\n"
        "Йошимура лично приготовил вам чашку качественного кофе. Напряжение спало, а голод притупился.\n\n"
        f"❤️ Восстановлено: +{heal} HP (Текущее: {player.hp}/{player.max_hp})\n"
        "💰 Потрачено: 15 ¥"
    )

def start_raid(player: Player) -> str:
    player.last_raid_at = datetime.now(UTC).isoformat()
    
    hp_loss = random.randint(30, 50)
    if player.hp <= hp_loss:
        player.hp = int(player.max_hp * 0.1)
        stolen_yen = min(player.yen, random.randint(10, 30))
        player.yen -= stolen_yen
        return (
            "🚨 *Провал рейда на штаб-квартиру CCG!*\n\n"
            "Вы попали в засаду следователей особого класса. "
            f"Вас тяжело ранили (осталось 10% HP) и вы потеряли {stolen_yen} ¥ при поспешном отступлении."
        )
    
    player.hp -= hp_loss
    rc_reward = random.randint(50, 100)
    yen_reward = random.randint(150, 300)
    exp_reward = random.randint(50, 90)
    
    player.rc_cells += rc_reward
    player.yen += yen_reward
    player.exp += exp_reward
    
    lvl_msg = apply_level_up(player)
    return (
        "🚨 *Успешный Рейд на штаб CCG!*\n"
        "Вы прорвались сквозь баррикады следователей и взломали секретную лабораторию.\n\n"
        f"🩸 Полученный урон: -{hp_loss} HP (Текущее: {player.hp}/{player.max_hp})\n"
        f"🧬 Получено: +{rc_reward} RC-клеток\n"
        f"💰 Трофеи: +{yen_reward} ¥\n"
        f"📈 Опыт: +{exp_reward} EXP\n\n"
        f"{lvl_msg}"
    ).strip()


# ================= СИСТЕМА ПОШАГОВОГО БОЯ С УЧЕТОМ УРОВНЕЙ УМЕНИЙ =================

def execute_combat_turn(player: Player, session: dict, action: str) -> dict | str:
    key = get_kagune_key_by_name(player.kagune)
    skills_cfg = KAGUNE_SKILLS[key]
    player_skills = player.get_skills_dict()
    
    player_dmg = 0
    mob_dmg = max(2, session["mob_atk"] - (player.stamina // 2))
    skill_activated_msg = ""
    
    if action == "basic":
        player_dmg = max(5, player.strength + random.randint(-3, 5))
        skill_activated_msg = f"⚔️ Вы нанесли базовый удар кагуне, нанеся *{player_dmg}* урон."
        
    elif action == "skill1":
        skill = skills_cfg[0]
        lvl = player_skills.get("s1", 1)
        scale = 1.0 + (lvl - 1) * 0.15 # Каждая ступень увеличивает урон/эффективность на 15%
        
        if player.rc_cells < skill["cost_rc"]:
            return f"❌ Недостаточно RC-клеток! Для навыка требуется {skill['cost_rc']} 🧪 клеток."
        player.rc_cells -= skill["cost_rc"]
        
        if key == "rinkaku":
            heal_val = int(skill["value"] * scale)
            player.hp = min(player.max_hp, player.hp + heal_val)
            player_dmg = max(5, int(player.strength * 0.8 * scale))
            skill_activated_msg = (
                f"🌀 Применено умение *{skill['name']}* `Lvl {lvl}` (-{skill['cost_rc']}🧪):\n"
                f"🧬 Восстановлено *+{heal_val} HP*. Нанесено *{player_dmg}* урон."
            )
        elif key == "ukaku":
            player_dmg = max(5, int((player.strength * skill["value"] * scale) + random.randint(1, 4)))
            skill_activated_msg = (
                f"🌀 Применено умение *{skill['name']}* `Lvl {lvl}` (-{skill['cost_rc']}🧪):\n"
                f"✨ Кристаллический перьевой веер нанес *{player_dmg}* урон."
            )
        elif key == "koukaku":
            player_dmg = max(5, int(player.strength * 0.6 * scale))
            shield_factor = max(0.1, skill["value"] - (lvl - 1) * 0.05) # Снижает урон сильнее на высоких уровнях
            mob_dmg = max(1, int(mob_dmg * shield_factor))
            skill_activated_msg = (
                f"🌀 Применено умение *{skill['name']}* `Lvl {lvl}` (-{skill['cost_rc']}🧪):\n"
                f"🛡 Сверхпрочный металлический барьер заблокировал удар. Получено всего -{mob_dmg} HP. Нанесено *{player_dmg}* урон."
            )
        elif key == "bikaku":
            player_dmg = max(5, int(player.strength * skill["value"] * scale))
            debuff_factor = max(0.2, 0.5 - (lvl - 1) * 0.075)
            mob_dmg = max(1, int(mob_dmg * debuff_factor))
            skill_activated_msg = (
                f"🌀 Применено умение *{skill['name']}* `Lvl {lvl}` (-{skill['cost_rc']}🧪):\n"
                f"🌪 Хвостовой взмах сбил темп противника. Получено всего -{mob_dmg} HP. Нанесено *{player_dmg}* урон."
            )
            
    elif action == "skill2":
        skill = skills_cfg[1]
        lvl = player_skills.get("s2", 1)
        scale = 1.0 + (lvl - 1) * 0.15
        
        if player.rc_cells < skill["cost_rc"]:
            return f"❌ Недостаточно RC-клеток! Для навыка требуется {skill['cost_rc']} 🧪 клеток."
        player.rc_cells -= skill["cost_rc"]
        
        if key == "rinkaku":
            player_dmg = max(5, int((player.strength * skill["value"] * scale) + random.randint(2, 6)))
            skill_activated_msg = (
                f"🌀 Применено умение *{skill['name']}* `Lvl {lvl}` (-{skill['cost_rc']}🧪):\n"
                f"⚔️ Тройной веер щупалец пронзил врага насквозь на *{player_dmg}* урон."
            )
        elif key == "ukaku":
            player_dmg = max(5, int(player.strength * skill["value"] * scale))
            evade_factor = max(0.2, 0.5 - (lvl - 1) * 0.075)
            mob_dmg = max(1, int(mob_dmg * evade_factor))
            skill_activated_msg = (
                f"🌀 Применено умение *{skill['name']}* `Lvl {lvl}` (-{skill['cost_rc']}🧪):\n"
                f"💨 Скоростной рывок увел от атаки. Получено всего -{mob_dmg} HP. Нанесено *{player_dmg}* урон."
            )
        elif key == "koukaku":
            player_dmg = max(5, int((player.strength * skill["value"] * scale) + random.randint(4, 8)))
            skill_activated_msg = (
                f"🌀 Применено умение *{skill['name']}* `Lvl {lvl}` (-{skill['cost_rc']}🧪):\n"
                f"🌪 Пробивающий доспешный вихревой бур нанес *{player_dmg}* урон."
            )
        elif key == "bikaku":
            player_dmg = max(5, int(player.strength * skill["value"] * scale))
            heal_val = 15 + (lvl - 1) * 5
            player.hp = min(player.max_hp, player.hp + heal_val)
            skill_activated_msg = (
                f"🌀 Применено умение *{skill['name']}* `Lvl {lvl}` (-{skill['cost_rc']}🧪):\n"
                f"⚔️ Парирование восстановило *+{heal_val} HP*. Нанесено *{player_dmg}* ответного урона."
            )
            
    elif action == "ult":
        skill = skills_cfg[2]
        lvl = player_skills.get("s3", 1)
        scale = 1.0 + (lvl - 1) * 0.15
        
        if player.rc_cells < skill["cost_rc"]:
            return f"❌ Недостаточно RC-клеток! Для ультимейта требуется {skill['cost_rc']} 🧪 клеток."
        player.rc_cells -= skill["cost_rc"]
        
        player_dmg = max(10, int((player.strength * skill["value"] * scale) + random.randint(8, 15)))
        
        if key == "rinkaku":
            heal_val = 35 + (lvl - 1) * 10
            player.hp = min(player.max_hp, player.hp + heal_val)
            skill_activated_msg = (
                f"💀 *АКТИВИРОВАНА ПОЛУКАКУДЖА* `Lvl {lvl}` (-{skill['cost_rc']}🧪):\n"
                f"🩸 Чудовищное безумие восстановило вам *+{heal_val} HP* и уничтожило цель на *{player_dmg}* урон!"
            )
        elif key == "ukaku":
            skill_activated_msg = (
                f"💀 *УЛЬТИМЕЙТ: {skill['name']}* `Lvl {lvl}` (-{skill['cost_rc']}🧪):\n"
                f"⚡ Опустошительный кристаллический обстрел искромсал врага на *{player_dmg}* урон!"
            )
        elif key == "koukaku":
            skill_activated_msg = (
                f"💀 *УЛЬТИМЕЙТ: {skill['name']}* `Lvl {lvl}` (-{skill['cost_rc']}🧪):\n"
                f"🌋 Сокрушительный обвал брони сверху раздавил кости противника на *{player_dmg}* урон!"
            )
        elif key == "bikaku":
            skill_activated_msg = (
                f"💀 *УЛЬТИМЕЙТ: {skill['name']}* `Lvl {lvl}` (-{skill['cost_rc']}🧪):\n"
                f"🐉 Серия ультимативных тактических выпадов хвостом нанесла врагу *{player_dmg}* урон!"
            )

    session["mob_hp"] -= player_dmg
    if session["mob_hp"] > 0:
        player.hp = max(0, player.hp - mob_dmg)
        
    return {
        "player_dmg": player_dmg,
        "mob_dmg": mob_dmg,
        "msg": skill_activated_msg
    }

def pvp_attack(attacker: Player, defender: Player) -> str:
    if attacker.user_id == defender.user_id:
        return "❌ Вы не можете напасть на самого себя!"
    
    if defender.level < 2:
        return "❌ Нельзя атаковать новичков ниже 2 уровня."

    evade_chance = min(0.4, (defender.stamina * 0.01))
    if random.random() < evade_chance:
        return f"💨 *{defender.username}* уклонился от вашей внезапной атаки благодаря высокой ловкости!"

    damage = max(5, (attacker.strength + random.randint(5, 15)) - (defender.stamina // 2))
    defender.hp = max(0, defender.hp - damage)

    if defender.hp == 0:
        stolen_yen = min(defender.yen, random.randint(30, 80))
        stolen_rc = min(defender.rc_cells, random.randint(10, 25))
        
        attacker.yen += stolen_yen
        defender.yen -= stolen_yen
        attacker.rc_cells += stolen_rc
        defender.rc_cells -= stolen_rc
        
        defender.hp = int(defender.max_hp * 0.2)
        
        exp_gain = random.randint(25, 45)
        attacker.exp += exp_gain
        lvl_msg = apply_level_up(attacker)
        
        return (
            f"⚔️ *Полная победа над {defender.username}!*\n"
            f"Вы отправили соперника в нокаут, нанеся {damage} урона.\n\n"
            f"💰 Ограбление: +{stolen_yen} ¥\n"
            f"🧬 Поглощение: +{stolen_rc} RC клеток\n"
            f"📈 Опыт: +{exp_gain} EXP\n"
            f"{lvl_msg}"
        ).strip()
    else:
        counter_damage = max(2, (defender.strength // 2) - (attacker.stamina // 3))
        attacker.hp = max(1, attacker.hp - counter_damage)
        return (
            f"⚔️ *Стычка с {defender.username}!*\n"
            f"Вы нанесли врагу {damage} урона, но не смогли дожать его.\n"
            f"💥 В ответном ударе вы получили: -{counter_damage} HP.\n"
            f"🩸 Здоровье цели: {defender.hp}/{defender.max_hp} HP."
        )
