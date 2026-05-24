# game.py
import os
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Пробуем импортировать библиотеку для работы с PostgreSQL
try:
    import psycopg2
except ImportError:
    psycopg2 = None

UTC = timezone.utc

KAGUNE_TYPES = {
    "rinkaku": {
        "name": "Ринкаку",
        "description": "Щупальца с чудовищной регенерацией и высоким уроном. Идеален для агрессии.",
        "bonus": {"strength": 4, "stamina": 1, "max_hp": 15},
    },
    "ukaku": {
        "name": "Укаку",
        "description": "Скоростной кагуне дальнего боя. Больше манёвра и уклонения.",
        "bonus": {"strength": 2, "stamina": 4, "max_hp": 10},
    },
    "koukaku": {
        "name": "Коукаку",
        "description": "Тяжёлый бронированный тип. Ниже мобильность, но мощная защита.",
        "bonus": {"strength": 2, "stamina": 5, "max_hp": 25},
    },
    "bikaku": {
        "name": "Бикаку",
        "description": "Сбалансированный тип: стабильный урон, контроль и гибкость.",
        "bonus": {"strength": 3, "stamina": 3, "max_hp": 15},
    },
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

class GameDB:
    def __init__(self, db_uri: str) -> None:
        self.db_uri = db_uri
        # Автоматическое определение типа СУБД по строке подключения
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
        # Для Telegram ID используем BIGINT, так как они выходят за пределы стандартных 32-битных чисел
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
            last_quest_at TEXT
        )
        """
        if self.is_postgres:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(query)
                conn.commit()
            finally:
                conn.close()
        else:
            with self._connect() as conn:
                conn.execute(query)
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(players)").fetchall()}
                if "last_quest_at" not in columns:
                    conn.execute("ALTER TABLE players ADD COLUMN last_quest_at TEXT")

    def _q(self, sql: str) -> str:
        # Адаптация плейсхолдеров (? для SQLite, %s для PostgreSQL)
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
        INSERT INTO players (user_id, username, faction, kagune, strength, stamina, max_hp, hp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            user_id,
            username,
            "Гуль",
            chosen["name"],
            12 + bonus["strength"],
            10 + bonus["stamina"],
            100 + bonus["max_hp"],
            100 + bonus["max_hp"]
        )
        self._execute(sql, params)
        return self.get_player(user_id)

    def save_player(self, player: Player) -> None:
        sql = """
        UPDATE players
        SET username = ?, faction = ?, level = ?, exp = ?, hp = ?,
            max_hp = ?, strength = ?, stamina = ?, yen = ?, kagune = ?,
            rc_cells = ?, humans_eaten = ?, gacha_pulls = ?, legendary_drops = ?,
            last_hunt_at = ?, last_eat_at = ?, last_raid_at = ?, last_quest_at = ?
        WHERE user_id = ?
        """
        params = (
            player.username, player.faction, player.level, player.exp, player.hp,
            player.max_hp, player.strength, player.stamina, player.yen, player.kagune,
            player.rc_cells, player.humans_eaten, player.gacha_pulls, player.legendary_drops,
            player.last_hunt_at, player.last_eat_at, player.last_raid_at, player.last_quest_at,
            player.user_id
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
        messages.append(f"⬆️ *Уровень повышен до {player.level}!* Характеристики улучшены, получено +15 RC клеток.")
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
    return (
        f"👤 *Профиль игрока: {player.username}*\n"
        f"🏷 Фракция: {player.faction}\n"
        f"🧬 Кагуне: {player.kagune}\n\n"
        f"📊 *Характеристики:*\n"
        f"▪️ Уровень: {player.level}  `[{player.exp}/{req_exp} EXP]`\n"
        f"❤️ Здоровье: {player.hp}/{player.max_hp} HP\n"
        f"⚔️ Сила: {player.strength}\n"
        f"🛡 Выносливость: {player.stamina}\n\n"
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
        return "❌ Недостаточно RC-клеток. Для одного прокрута на черном рынке необходимо 100 🧪 клеток."
    
    player.rc_cells -= 100
    player.gacha_pulls += 1
    roll = random.random()
    
    if roll < 0.05:  # 5% шанс на Легендарный предмет
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
    elif roll < 0.35:  # 30% Редкий
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
    else:  # 65% Обычный
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
    player.last_raid_at = datetime.now(UTC).isoformat()  # Поле 'last_raid_at' переиспользуем под кулдаун кофе
    
    return (
        "☕ *Кофейня Антейку*\n"
        "Йошимура лично приготовил вам чашку качественного кофе. Напряжение спало, а голод притупился.\n\n"
        f"❤️ Восстановлено: +{heal} HP (Текущее: {player.hp}/{player.max_hp})\n"
        "💰 Потрачено: 15 ¥"
    )

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