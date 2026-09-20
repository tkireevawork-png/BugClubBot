"""
db.py — работа с базой данных SQLite для BugClub bot.
"""

import sqlite3
from datetime import datetime

DB_PATH = "bugclub.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mood_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_id INTEGER NOT NULL,
            stage TEXT NOT NULL,
            anxiety_score INTEGER,
            fear_of_judgment_score INTEGER,
            emotion_reaction TEXT,
            self_corrected TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS errors_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_id INTEGER NOT NULL,
            error_text TEXT NOT NULL,
            correction_text TEXT,
            category TEXT,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS current_session (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            session_id INTEGER
        )
    """)
    cur.execute("INSERT OR IGNORE INTO current_session (id, session_id) VALUES (1, NULL)")

    conn.commit()
    conn.close()


def start_new_session(topic: str) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sessions (topic, created_at) VALUES (?, ?)",
        (topic, datetime.utcnow().isoformat()),
    )
    session_id = cur.lastrowid
    cur.execute("UPDATE current_session SET session_id = ? WHERE id = 1", (session_id,))
    conn.commit()
    conn.close()
    return session_id


def get_current_session_id():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT session_id FROM current_session WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def save_mood_before(user_id: int, session_id: int, anxiety_score: int, fear_score: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO mood_log (user_id, session_id, stage, anxiety_score, fear_of_judgment_score, created_at)
        VALUES (?, ?, 'before', ?, ?, ?)
    """, (user_id, session_id, anxiety_score, fear_score, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def save_mood_after(user_id: int, session_id: int, anxiety_score: int, emotion_reaction: str, self_corrected: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO mood_log (user_id, session_id, stage, anxiety_score, emotion_reaction, self_corrected, created_at)
        VALUES (?, ?, 'after', ?, ?, ?, ?)
    """, (user_id, session_id, anxiety_score, emotion_reaction, self_corrected, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def save_error(session_id: int, error_text: str, correction_text: str, category: str, kind: str, user_id: int = None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO errors_log (user_id, session_id, error_text, correction_text, category, kind, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, session_id, error_text, correction_text, category, kind, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def get_user_errors(user_id: int, limit: int = 5):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT error_text, correction_text, category, kind
        FROM errors_log
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows