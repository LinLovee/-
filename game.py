import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

KAGUNE_TYPES = {
    "rinkaku": {
        "name": "Ринкакку",
        "description": "Щупальца с чудовищной регенерацией и высоким уроном. Идеален для агрессии.",
        "bonus": {"strength": 3, "stamina": 1, "max_hp": 8},
    },
    "ukaku": {
        "name": "Укаку",
        "description": "Скоростной кагуне дальнего боя. Больше манёвра и уклонения.",
        "bonus": {"strength": 2, "stamina": 3, "max_hp": 4},
    },
    "koukaku": {
        "name": "Коукаку",
        "description": "Тяжёлый бронированный тип. Ниже мобильность, но мощная защита.",
        "bonus": {"strength": 2, "stamina": 4, "max_hp": 10},
    },
    "bikaku": {
        "name": "Бикаку",
        "description": "Сбалансированный тип: стабильный урон, контроль и гибкость.",
        "bonus": {"strength": 3, "stamina": 2, "max_hp": 6},
    },
}

KAGUNE_ALIASES = {
    "ринкакку": "rinkaku",
    "укаку": "ukaku",
    "кукаку": "koukaku",
    "коукаку": "koukaku",
    "бикаку": "bikaku",
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


class GameDB:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS players (
                    user_id INTEGER PRIMARY KEY,
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
                    last_raid_at TEXT
                )
                """
            )

            columns = {row["name"] for row in conn.execute("PRAGMA table_info(players)").fetchall()}
            alter_statements = {
                "rc_cells": "ALTER TABLE players ADD COLUMN rc_cells INTEGER NOT NULL DEFAULT 0",
                "humans_eaten": "ALTER TABLE players ADD COLUMN humans_eaten INTEGER NOT NULL DEFAULT 0",
                "gacha_pulls": "ALTER TABLE players ADD COLUMN gacha_pulls INTEGER NOT NULL DEFAULT 0",
                "legendary_drops": "ALTER TABLE players ADD COLUMN legendary_drops INTEGER NOT NULL DEFAULT 0",
                "last_eat_at": "ALTER TABLE players ADD COLUMN last_eat_at TEXT",
                "last_raid_at": "ALTER TABLE players ADD COLUMN last_raid_at TEXT",
            }
            for column, statement in alter_statements.items():
                if column not in columns:
                    conn.execute(statement)

    def get_player(self, user_id: int) -> Player | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM players WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return None
        return Player(**dict(row))

    def create_player(self, user_id: int, username: str, kagune_key: str) -> Player:
        chosen = KAGUNE_TYPES[kagune_key]
        bonus = chosen["bonus"]

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO players (
                    user_id, username, faction, kagune, strength, stamina, max_hp, hp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    username,
                    "Гуль",
                    chosen["name"],
                    12 + bonus["strength"],
                    10 + bonus["stamina"],
                    100 + bonus["max_hp"],
                    100 + bonus["max_hp"],
                ),
            )
        return self.get_player(user_id)  # type: ignore[return-value]

    def save_player(self, player: Player) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE players
                SET username = ?, faction = ?, level = ?, exp = ?, hp = ?,
                    max_hp = ?, strength = ?, stamina = ?, yen = ?, kagune = ?,
                    rc_cells = ?, humans_eaten = ?, gacha_pulls = ?, legendary_drops = ?,
                    last_hunt_at = ?, last_eat_at = ?, last_raid_at = ?
                WHERE user_id = ?
                """,
                (
                    player.username,
                    player.faction,
                    player.level,
                    player.exp,
                    player.hp,
                    player.max_hp,
                    player.strength,
                    player.stamina,
                    player.yen,
                    player.kagune,
                    player.rc_cells,
                    player.humans_eaten,
                    player.gacha_pulls,
                    player.legendary_drops,
                    player.last_hunt_at,
                    player.last_eat_at,
                    player.last_raid_at,
                    player.user_id,
                ),
            )

    def top_players(self, limit: int = 10) -> list[Player]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM players ORDER BY level DESC, rc_cells DESC, exp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Player(**dict(r)) for r in rows]


def kagune_help_text() -> str:
    lines = ["Выбери кагуне при первом /start:"]
    for key, value in KAGUNE_TYPES.items():
        lines.append(f"- `{key}` ({value['name']}): {value['description']}")
    lines.append("Русские алиасы: ринкакку, укаку, кукаку/коукаку, бикаку")
    lines.append("Примеры: /start rinkaku или /start ринкакку")
    return "\n".join(lines)


def exp_to_level_up(level: int) -> int:
    return 100 + (level - 1) * 40


def apply_level_up(player: Player) -> str:
    messages = []
    while player.exp >= exp_to_level_up(player.level):
        player.exp -= exp_to_level_up(player.level)
        player.level += 1
        player.max_hp += 12
        player.hp = player.max_hp
        player.strength += 3
        player.stamina += 2
        player.rc_cells += 10
        messages.append(f"⬆️ Уровень {player.level}! (+10 RC)")
    return "\n".join(messages)


def _check_cooldown(last_event_at: str | None, hours: int, action_name: str) -> tuple[bool, str]:
    if not last_event_at:
        return True, ""
    last_event = datetime.fromisoformat(last_event_at)
    next_event = last_event + timedelta(hours=hours)
    now = datetime.now(UTC)
    if now >= next_event:
        return True, ""
    left = next_event - now
    rem_seconds = int(left.total_seconds())
    h, rem = divmod(rem_seconds, 3600)
    m = rem // 60
    return False, f"⏳ До действия «{action_name}» осталось: {h} ч {m} мин."


def can_hunt(player: Player) -> tuple[bool, str]:
    return _check_cooldown(player.last_hunt_at, 24, "охота")


def can_eat_human(player: Player) -> tuple[bool, str]:
    return _check_cooldown(player.last_eat_at, 12, "пожирание")


def can_raid(player: Player) -> tuple[bool, str]:
    return _check_cooldown(player.last_raid_at, 6, "рейд на район")


HUNT_STYLES = {
    "aggressive": {
        "name": "Агрессия",
        "aliases": {"агрессия", "агро", "aggro", "aggressive"},
        "power": (4, 10),
        "risk": (8, 20),
        "reward": (1.25, 1.1, 1.15),
        "story": "Ты врываешься в квартал без колебаний.",
    },
    "stealth": {
        "name": "Стелс",
        "aliases": {"стелс", "тихо", "stealth"},
        "power": (-1, 7),
        "risk": (3, 12),
        "reward": (1.0, 1.05, 1.3),
        "story": "Ты выслеживаешь цель в тенях и ждёшь ошибки.",
    },
    "balanced": {
        "name": "Баланс",
        "aliases": {"баланс", "balanced", "обычно"},
        "power": (1, 8),
        "risk": (5, 15),
        "reward": (1.1, 1.1, 1.1),
        "story": "Ты действуешь хладнокровно и без лишнего риска.",
    },
}


RAID_STYLES = {
    "assault": {
        "name": "Штурм",
        "aliases": {"штурм", "assault"},
        "roll": (4, 12),
        "damage": (8, 20),
        "reward": (1.2, 1.15, 1.1),
        "story": "Ты собираешь боевую группу и идёшь в лобовую атаку.",
    },
    "sabotage": {
        "name": "Саботаж",
        "aliases": {"саботаж", "sabotage"},
        "roll": (0, 10),
        "damage": (5, 14),
        "reward": (1.0, 1.35, 1.2),
        "story": "Ты ломаешь склады CCG и вывозишь редкие RC материалы.",
    },
    "scout": {
        "name": "Разведка",
        "aliases": {"разведка", "scout"},
        "roll": (2, 11),
        "damage": (4, 12),
        "reward": (1.3, 1.0, 1.15),
        "story": "Ты изучаешь патрули и бьёшь только по уязвимым точкам.",
    },
}


def normalize_hunt_style(raw_style: str | None) -> str:
    if not raw_style:
        return "balanced"
    key = raw_style.lower().strip()
    for style_key, style in HUNT_STYLES.items():
        if key in style["aliases"]:
            return style_key
    return "balanced"


def normalize_raid_style(raw_style: str | None) -> str:
    if not raw_style:
        return "assault"
    key = raw_style.lower().strip()
    for style_key, style in RAID_STYLES.items():
        if key in style["aliases"]:
            return style_key
    return "assault"


def do_hunt(player: Player, style: str = "balanced") -> str:
    picked = HUNT_STYLES.get(style, HUNT_STYLES["balanced"])
    scene = random.choice([
        "мокрый переулок 20-го района",
        "крыши возле заброшенного рынка",
        "подземные тоннели старого метро",
    ])
    enemy_power = random.randint(10, 32)
    player_power = player.strength + random.randint(0, player.stamina) + random.randint(*picked["power"])
    player.last_hunt_at = datetime.now(UTC).isoformat()

    if player_power >= enemy_power:
        reward_exp = int(random.randint(24, 52) * picked["reward"][0])
        reward_yen = int(random.randint(20, 85) * picked["reward"][1])
        reward_rc = int(random.randint(8, 22) * picked["reward"][2])
        hp_cost = random.randint(max(2, picked["risk"][0] - 3), picked["risk"][1])
        player.exp += reward_exp
        player.yen += reward_yen
        player.rc_cells += reward_rc
        player.hp = max(1, player.hp - hp_cost)
        level_message = apply_level_up(player)
        return (
            f"🕷 Локация: {scene}.\n"
            f"🎯 Тактика: {picked['name']}. {picked['story']}\n"
            f"⚔️ Схватка: {player_power} vs {enemy_power}. Победа!\n"
            f"💰 Добыча: +{reward_exp} EXP, +{reward_yen} ¥, +{reward_rc} RC.\n"
            f"🩸 Расход сил: -{hp_cost} HP. Текущее HP: {player.hp}/{player.max_hp}.\n"
            f"{level_message}".strip()
        )

    damage = random.randint(*picked["risk"])
    consolation = random.randint(2, 8)
    player.exp += consolation
    player.hp = max(1, player.hp - damage)
    level_message = apply_level_up(player)
    return (
        f"🕷 Локация: {scene}.\n"
        f"🎯 Тактика: {picked['name']}.\n"
        f"💥 Ты отступил: {player_power} vs {enemy_power}.\n"
        f"🧠 За опыт боя: +{consolation} EXP.\n"
        f"🩸 Потеря: -{damage} HP. Текущее HP: {player.hp}/{player.max_hp}.\n"
        f"{level_message}".strip()
    )


def eat_human(player: Player) -> str:
    player.last_eat_at = datetime.now(UTC).isoformat()
    danger_roll = random.random()
    gained_rc = random.randint(15, 40)
    gained_exp = random.randint(12, 26)
    player.rc_cells += gained_rc
    player.exp += gained_exp
    player.humans_eaten += 1

    if danger_roll < 0.25:
        damage = random.randint(8, 22)
        player.hp = max(1, player.hp - damage)
        base_result = f"🚨 Засада CCG! Получен урон: {damage}."
    else:
        heal = random.randint(6, 18)
        player.hp = min(player.max_hp, player.hp + heal)
        base_result = f"🩸 Охота прошла чисто. Восстановлено {heal} HP."

    level_message = apply_level_up(player)
    return (
        f"🍖 Ты пожираешь человека. +{gained_rc} RC, +{gained_exp} EXP.\n"
        f"{base_result}\n"
        f"Всего жертв: {player.humans_eaten}.\n"
        f"❤️ HP: {player.hp}/{player.max_hp}.\n"
        f"{level_message}".strip()
    )


def raid_district(player: Player, style: str = "assault") -> str:
    picked = RAID_STYLES.get(style, RAID_STYLES["assault"])
    target = random.choice([
        "склад CCG",
        "черный рынок 11-го района",
        "патрульный узел у набережной",
    ])
    player.last_raid_at = datetime.now(UTC).isoformat()
    difficulty = random.randint(24, 60)
    roll = player.strength + player.stamina + random.randint(*picked["roll"])

    if roll >= difficulty:
        yen = int(random.randint(45, 130) * picked["reward"][0])
        rc = int(random.randint(18, 46) * picked["reward"][1])
        exp = int(random.randint(32, 72) * picked["reward"][2])
        player.yen += yen
        player.rc_cells += rc
        player.exp += exp
        level_message = apply_level_up(player)
        return (
            f"🏙 Цель: {target}.\n"
            f"🧠 План: {picked['name']}. {picked['story']}\n"
            f"✅ Рейд успешен: {roll} vs {difficulty}.\n"
            f"🎁 Трофеи: +{yen} ¥, +{rc} RC, +{exp} EXP.\n"
            f"{level_message}".strip()
        )

    damage = random.randint(*picked["damage"])
    partial = random.randint(8, 25)
    player.rc_cells += partial
    player.hp = max(1, player.hp - damage)
    return (
        f"🏙 Цель: {target}.\n"
        f"🧠 План: {picked['name']}.\n"
        f"🚔 Рейд сорван: {roll} vs {difficulty}.\n"
        f"♻️ Удалось вынести +{partial} RC при отступлении.\n"
        f"🩸 Потеря: -{damage} HP. Текущее HP: {player.hp}/{player.max_hp}."
    )


def train(player: Player) -> str:
    cost = 30
    if player.yen < cost:
        return f"❌ Нужно {cost} ¥ для тренировки. У тебя: {player.yen} ¥."

    player.yen -= cost
    player.strength += random.randint(1, 2)
    player.stamina += random.randint(1, 2)
    player.max_hp += random.randint(2, 5)
    player.hp = player.max_hp
    return (
        "💪 Тренировка завершена!\n"
        f"Сила: {player.strength}, Выносливость: {player.stamina}.\n"
        f"❤️ HP: {player.hp}/{player.max_hp}."
    )


def upgrade_with_rc(player: Player, stat: str) -> str:
    stat = stat.lower()
    costs = {"strength": 25, "stamina": 25, "hp": 30}
    if stat not in costs:
        return "❌ Использование: /evolve <strength|stamina|hp>"
    cost = costs[stat]
    if player.rc_cells < cost:
        return f"❌ Нужно {cost} RC. У тебя: {player.rc_cells} RC."

    player.rc_cells -= cost
    if stat == "strength":
        growth = random.randint(2, 4)
        player.strength += growth
        return f"🧬 Сила эволюционировала: +{growth}."
    if stat == "stamina":
        growth = random.randint(2, 4)
        player.stamina += growth
        return f"🧬 Выносливость эволюционировала: +{growth}."
    growth = random.randint(8, 16)
    player.max_hp += growth
    player.hp = player.max_hp
    return f"🧬 Тело мутировало: +{growth} max HP."


def gacha_pull(player: Player) -> str:
    cost = 80
    if player.yen < cost:
        return f"❌ Для гачи нужно {cost} ¥. У тебя: {player.yen} ¥."

    player.yen -= cost
    player.gacha_pulls += 1

    roll = random.random()
    if roll < 0.03:
        player.legendary_drops += 1
        player.strength += 5
        player.stamina += 5
        player.max_hp += 20
        player.hp = player.max_hp
        player.rc_cells += 35
        return "🌟 LEGENDARY: Маска Одноглазого Короля! +5 STR, +5 STA, +20 HP, +35 RC."

    if roll < 0.20:
        bonus = random.randint(12, 25)
        player.rc_cells += bonus
        return f"✨ EPIC: Ампула RC. +{bonus} RC клеток."

    if roll < 0.55:
        bonus = random.randint(25, 70)
        player.yen += bonus
        return f"🔷 RARE: Контракт подполья. Возврат +{bonus} ¥."

    bonus = random.randint(8, 20)
    player.exp += bonus
    level_message = apply_level_up(player)
    return f"▫️ COMMON: Боевой опыт +{bonus} EXP.\n{level_message}".strip()


def pvp_attack(attacker: Player, defender: Player) -> str:
    if attacker.user_id == defender.user_id:
        return "🤨 Нельзя атаковать себя."

    attack_roll = attacker.strength + random.randint(0, attacker.stamina)
    defense_roll = defender.strength + random.randint(0, defender.stamina)

    if attack_roll >= defense_roll:
        steal = min(defender.yen, random.randint(10, 40))
        rc_gain = random.randint(12, 35)
        attacker.yen += steal
        defender.yen -= steal
        attacker.rc_cells += rc_gain
        gain_exp = random.randint(15, 35)
        attacker.exp += gain_exp
        level_msg = apply_level_up(attacker)
        return (
            f"⚔️ Убийство {defender.username} успешно!\n"
            f"Броски: {attack_roll} vs {defense_roll}.\n"
            f"Добыча: {steal} ¥, +{rc_gain} RC, +{gain_exp} EXP.\n"
            f"{level_msg}".strip()
        )

    penalty = min(attacker.yen, random.randint(5, 20))
    attacker.yen -= penalty
    attacker.hp = max(1, attacker.hp - random.randint(3, 12))
    return (
        f"🩸 Ты проиграл дуэль игроку {defender.username}.\n"
        f"Броски: {attack_roll} vs {defense_roll}.\n"
        f"Потеряно: {penalty} ¥.\n"
        f"❤️ HP: {attacker.hp}/{attacker.max_hp}."
    )


def render_profile(player: Player) -> str:
    return (
        f"👤 {player.username} (ID: {player.user_id})\n"
        f"Фракция: {player.faction}\n"
        f"Кагуне: {player.kagune}\n"
        f"Уровень: {player.level} ({player.exp}/{exp_to_level_up(player.level)} EXP)\n"
        f"❤️ HP: {player.hp}/{player.max_hp}\n"
        f"🗡 Сила: {player.strength}\n"
        f"🛡 Выносливость: {player.stamina}\n"
        f"💴 Йены: {player.yen}\n"
        f"🧬 RC клетки: {player.rc_cells}\n"
        f"🍖 Пожрано людей: {player.humans_eaten}\n"
        f"🎰 Гача-круток: {player.gacha_pulls}, легендарок: {player.legendary_drops}"
    )
