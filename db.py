"""
db.py — работа с базой данных PostgreSQL для BugClub bot.
"""

import asyncpg
import os
from datetime import datetime

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
                created_at TIMESTAMP NOT NULL
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

        # Новая таблица: здесь храним всех, кто хоть раз нажал /start
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_interaction TIMESTAMP NOT NULL
            )
        """)


async def save_user(user_id: int, username: str = None, first_name: str = None):
    """Сохраняет или обновляет пользователя при /start."""
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
    """Ищет user_id по username (без @). Возвращает None, если не найден."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM users WHERE LOWER(username) = LOWER($1)",
            username
        )
        return row["user_id"] if row else None


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
            FROM errors_log
            WHERE user_id = $1
            ORDER BY id DESC
            LIMIT $2
        """, user_id, limit)
        return rows