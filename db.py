"""
db.py — работа с базой данных PostgreSQL для BugClub bot.
"""

import asyncpg
import os
from datetime import datetime, timedelta

DATABASE_URL = os.getenv("DATABASE_URL")

pool: asyncpg.Pool = None


async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id SERIAL PRIMARY KEY,
                topic TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                closed_at TIMESTAMP
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mood_log (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                session_id INTEGER NOT NULL,
                stage TEXT NOT NULL,
                anxiety_score INTEGER,
                fear_of_judgment_score INTEGER,
                emotion_reaction TEXT,
                self_corrected TEXT,
                created_at TIMESTAMP NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS errors_log (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                session_id INTEGER NOT NULL,
                error_text TEXT NOT NULL,
                correction_text TEXT,
                category TEXT,
                kind TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS current_session (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                session_id INTEGER
            )
        """)
        await conn.execute(
            "INSERT INTO current_session (id, session_id) VALUES (1, NULL) "
            "ON CONFLICT (id) DO NOTHING"
        )

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_interaction TIMESTAMP NOT NULL
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_usage (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                action TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL
            )
        """)


# ---------- Пользователи ----------

async def save_user(user_id: int, username: str = None, first_name: str = None):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, first_name, last_interaction)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE
            SET username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_interaction = EXCLUDED.last_interaction
        """, user_id, username, first_name, datetime.utcnow())


async def get_user_id_by_username(username: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM users WHERE LOWER(username) = LOWER($1)",
            username
        )
        return row["user_id"] if row else None


# ---------- Сессии ----------

async def start_new_session(topic: str) -> int:
    async with pool.acquire() as conn:
        session_id = await conn.fetchval(
            "INSERT INTO sessions (topic, created_at) VALUES ($1, $2) RETURNING id",
            topic, datetime.utcnow()
        )
        await conn.execute(
            "UPDATE current_session SET session_id = $1 WHERE id = 1",
            session_id
        )
        return session_id


async def get_current_session_id():
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT session_id FROM current_session WHERE id = 1")
        return row["session_id"] if row else None


async def get_current_session_topic():
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT s.topic FROM sessions s
            JOIN current_session cs ON cs.session_id = s.id
            WHERE cs.id = 1
        """)
        return row["topic"] if row else None


async def close_current_session():
    """Закрывает текущую встречу: ставит closed_at и сбрасывает current_session."""
    session_id = await get_current_session_id()
    if not session_id:
        return None
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET closed_at = $1 WHERE id = $2",
            datetime.utcnow(), session_id
        )
        await conn.execute(
            "UPDATE current_session SET session_id = NULL WHERE id = 1"
        )
    return session_id


# ---------- Настроение ----------

async def save_mood_before(user_id: int, session_id: int, anxiety_score: int, fear_score: int):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO mood_log (user_id, session_id, stage, anxiety_score, fear_of_judgment_score, created_at)
            VALUES ($1, $2, 'before', $3, $4, $5)
        """, user_id, session_id, anxiety_score, fear_score, datetime.utcnow())


async def save_mood_after(user_id: int, session_id: int, anxiety_score: int, emotion_reaction: str, self_corrected: str):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO mood_log (user_id, session_id, stage, anxiety_score, emotion_reaction, self_corrected, created_at)
            VALUES ($1, $2, 'after', $3, $4, $5, $6)
        """, user_id, session_id, anxiety_score, emotion_reaction, self_corrected, datetime.utcnow())


async def get_mood_stats():
    session_id = await get_current_session_id()
    if not session_id:
        return None
    async with pool.acquire() as conn:
        before = await conn.fetchrow("""
            SELECT COUNT(*) as cnt,
                COALESCE(AVG(anxiety_score), 0)::float as avg_anxiety,
                COALESCE(AVG(fear_of_judgment_score), 0)::float as avg_fear
            FROM mood_log WHERE session_id = $1 AND stage = 'before'
        """, session_id)
        after = await conn.fetchrow("""
            SELECT COUNT(*) as cnt,
                COALESCE(AVG(anxiety_score), 0)::float as avg_anxiety
            FROM mood_log WHERE session_id = $1 AND stage = 'after'
        """, session_id)
        return {"before": dict(before), "after": dict(after)}


# ---------- Ошибки ----------

async def save_error(session_id: int, error_text: str, correction_text: str, category: str, kind: str, user_id: int = None):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO errors_log (user_id, session_id, error_text, correction_text, category, kind, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, user_id, session_id, error_text, correction_text, category, kind, datetime.utcnow())


async def get_user_errors(user_id: int, limit: int = 5):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT error_text, correction_text, category, kind
            FROM errors_log WHERE user_id = $1
            ORDER BY id DESC LIMIT $2
        """, user_id, limit)
        return rows


async def get_all_user_errors(user_id: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT error_text, correction_text, category, kind
            FROM errors_log WHERE user_id = $1 ORDER BY id DESC
        """, user_id)
        return rows


async def get_session_errors(session_id: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT error_text, correction_text, category, kind
            FROM errors_log WHERE session_id = $1 ORDER BY id
        """, session_id)
        return rows


async def get_top_error_categories(limit: int = 3):
    session_id = await get_current_session_id()
    if not session_id:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT category, COUNT(*) as cnt FROM errors_log
            WHERE session_id = $1 GROUP BY category
            ORDER BY cnt DESC LIMIT $2
        """, session_id, limit)
        return rows


async def get_total_users_count():
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM users")
        return row["cnt"] if row else 0


# ---------- Rate limit для LLM ----------

async def check_rate_limit(user_id: int, action: str, minutes: int = 5) -> bool:
    """True — можно делать запрос. False — ещё рано."""
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    async with pool.acquire() as conn:
        count = await conn.fetchval("""
            SELECT COUNT(*) FROM llm_usage
            WHERE user_id = $1 AND action = $2 AND created_at > $3
        """, user_id, action, cutoff)
        return count == 0


async def log_llm_usage(user_id: int, action: str):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO llm_usage (user_id, action, created_at)
            VALUES ($1, $2, $3)
        """, user_id, action, datetime.utcnow())


# ---------- Экспорт ----------

async def get_all_data_for_export():
    """Возвращает (users, errors, mood) для экспорта в CSV."""
    async with pool.acquire() as conn:
        users = await conn.fetch("""
            SELECT user_id, username, first_name, last_interaction
            FROM users ORDER BY user_id
        """)

        errors = await conn.fetch("""
            SELECT e.id, e.user_id, u.username, u.first_name,
                   s.topic as session_topic, e.error_text, e.correction_text,
                   e.category, e.kind, e.created_at
            FROM errors_log e
            LEFT JOIN users u ON u.user_id = e.user_id
            LEFT JOIN sessions s ON s.id = e.session_id
            ORDER BY e.id
        """)

        mood = await conn.fetch("""
            SELECT m.id, m.user_id, u.username, u.first_name,
                   s.topic as session_topic, m.stage, m.anxiety_score,
                   m.fear_of_judgment_score, m.emotion_reaction,
                   m.self_corrected, m.created_at
            FROM mood_log m
            LEFT JOIN users u ON u.user_id = m.user_id
            LEFT JOIN sessions s ON s.id = m.session_id
            ORDER BY m.id
        """)

        return users, errors, mood