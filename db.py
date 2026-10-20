"""
db.py — работа с базой данных SQLite для BugClub bot.
"""

import sqlite3
import os
from datetime import datetime, timedelta

# Файл базы данных. Он будет создан автоматически.
DB_PATH = "/data/bugclub.db" if os.getenv("AMVERA") else "bugclub.db"

def get_connection():
    # check_same_thread=False нужен для работы с aiohttp
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            closed_at TIMESTAMP,
            is_first BOOLEAN DEFAULT FALSE
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
            created_at TIMESTAMP NOT NULL,
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
            created_at TIMESTAMP NOT NULL,
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_interaction TIMESTAMP NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS llm_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            level TEXT NOT NULL,
            motivation TEXT,
            created_at TIMESTAMP NOT NULL,
            session_id INTEGER
        )
    """)

    conn.commit()
    conn.close()

# --- Пользователи ---
def save_user(user_id, username=None, first_name=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (user_id, username, first_name, last_interaction)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_interaction = excluded.last_interaction
    """, (user_id, username, first_name, datetime.utcnow()))
    conn.commit()
    conn.close()

def get_user_id_by_username(username):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)", (username,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

# --- Регистрация ---
def save_registration(user_id, name, level, motivation, session_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO registrations (user_id, name, level, motivation, created_at, session_id)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            name = excluded.name,
            level = excluded.level,
            motivation = excluded.motivation,
            created_at = excluded.created_at,
            session_id = excluded.session_id
    """, (user_id, name, level, motivation, datetime.utcnow(), session_id))
    conn.commit()
    conn.close()

def get_registrations_for_session(session_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT r.user_id, r.name, r.level, r.motivation, u.username, r.created_at
        FROM registrations r
        LEFT JOIN users u ON u.user_id = r.user_id
        WHERE r.session_id = ?
        ORDER BY r.created_at ASC
    """, (session_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(zip([column[0] for column in cur.description], row)) for row in rows]

# --- Сессии ---
def start_new_session(topic):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO sessions (topic, created_at) VALUES (?, ?)", (topic, datetime.utcnow()))
    session_id = cur.lastrowid
    cur.execute("UPDATE current_session SET session_id = ? WHERE id = 1", (session_id,))
    conn.commit()
    conn.close()
    return session_id

def start_first_session(topic):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO sessions (topic, created_at, is_first) VALUES (?, ?, TRUE)", (topic, datetime.utcnow()))
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

def get_current_session_topic():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.topic FROM sessions s
        JOIN current_session cs ON cs.session_id = s.id
        WHERE cs.id = 1
    """)
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def get_current_session_is_first():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.is_first FROM sessions s
        JOIN current_session cs ON cs.session_id = s.id
        WHERE cs.id = 1
    """)
    row = cur.fetchone()
    conn.close()
    return bool(row[0]) if row else False

def close_current_session():
    session_id = get_current_session_id()
    if not session_id:
        return None
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE sessions SET closed_at = ? WHERE id = ?", (datetime.utcnow(), session_id))
    cur.execute("UPDATE current_session SET session_id = NULL WHERE id = 1")
    conn.commit()
    conn.close()
    return session_id

# --- Настроение ---
def save_mood_before(user_id, session_id, anxiety_score, fear_score):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO mood_log (user_id, session_id, stage, anxiety_score, fear_of_judgment_score, created_at)
        VALUES (?, ?, 'before', ?, ?, ?)
    """, (user_id, session_id, anxiety_score, fear_score, datetime.utcnow()))
    conn.commit()
    conn.close()

def save_mood_after(user_id, session_id, anxiety_score, emotion_reaction, self_corrected):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO mood_log (user_id, session_id, stage, anxiety_score, emotion_reaction, self_corrected, created_at)
        VALUES (?, ?, 'after', ?, ?, ?, ?)
    """, (user_id, session_id, anxiety_score, emotion_reaction, self_corrected, datetime.utcnow()))
    conn.commit()
    conn.close()

def get_mood_stats():
    session_id = get_current_session_id()
    if not session_id:
        return None
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), COALESCE(AVG(anxiety_score), 0), COALESCE(AVG(fear_of_judgment_score), 0) FROM mood_log WHERE session_id = ? AND stage = 'before'", (session_id,))
    before = cur.fetchone()
    cur.execute("SELECT COUNT(*), COALESCE(AVG(anxiety_score), 0) FROM mood_log WHERE session_id = ? AND stage = 'after'", (session_id,))
    after = cur.fetchone()
    conn.close()
    return {
        "before": {"cnt": before[0], "avg_anxiety": before[1], "avg_fear": before[2]},
        "after": {"cnt": after[0], "avg_anxiety": after[1]}
    }

# --- Ошибки ---
def save_error(session_id, error_text, correction_text, category, kind, user_id=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO errors_log (user_id, session_id, error_text, correction_text, category, kind, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, session_id, error_text, correction_text, category, kind, datetime.utcnow()))
    conn.commit()
    conn.close()

def get_user_errors(user_id, limit=5):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT error_text, correction_text, category, kind FROM errors_log WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return [dict(zip([column[0] for column in cur.description], row)) for row in rows]

def get_all_user_errors(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT error_text, correction_text, category, kind FROM errors_log WHERE user_id = ? ORDER BY id DESC", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(zip([column[0] for column in cur.description], row)) for row in rows]

def get_session_errors(session_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT error_text, correction_text, category, kind FROM errors_log WHERE session_id = ? ORDER BY id", (session_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(zip([column[0] for column in cur.description], row)) for row in rows]

def get_top_error_categories(limit=3):
    session_id = get_current_session_id()
    if not session_id:
        return []
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT category, COUNT(*) as cnt FROM errors_log WHERE session_id = ? GROUP BY category ORDER BY cnt DESC LIMIT ?", (session_id, limit))
    rows = cur.fetchall()
    conn.close()
    return [dict(zip([column[0] for column in cur.description], row)) for row in rows]

def get_total_users_count():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM users")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0

# --- Rate limit ---
def check_rate_limit(user_id, action, minutes=5):
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM llm_usage WHERE user_id = ? AND action = ? AND created_at > ?", (user_id, action, cutoff))
    count = cur.fetchone()[0]
    conn.close()
    return count == 0

def log_llm_usage(user_id, action):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO llm_usage (user_id, action, created_at) VALUES (?, ?, ?)", (user_id, action, datetime.utcnow()))
    conn.commit()
    conn.close()

# --- Экспорт ---
def get_all_data_for_export():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name, last_interaction FROM users ORDER BY user_id")
    users = [dict(zip([column[0] for column in cur.description], row)) for row in cur.fetchall()]

    cur.execute("""
        SELECT e.id, e.user_id, u.username, u.first_name, s.topic as session_topic,
               e.error_text, e.correction_text, e.category, e.kind, e.created_at
        FROM errors_log e
        LEFT JOIN users u ON u.user_id = e.user_id
        LEFT JOIN sessions s ON s.id = e.session_id
        ORDER BY e.id
    """)
    errors = [dict(zip([column[0] for column in cur.description], row)) for row in cur.fetchall()]

    cur.execute("""
        SELECT m.id, m.user_id, u.username, u.first_name, s.topic as session_topic,
               m.stage, m.anxiety_score, m.fear_of_judgment_score,
               m.emotion_reaction, m.self_corrected, m.created_at
        FROM mood_log m
        LEFT JOIN users u ON u.user_id = m.user_id
        LEFT JOIN sessions s ON s.id = m.session_id
        ORDER BY m.id
    """)
    mood = [dict(zip([column[0] for column in cur.description], row)) for row in cur.fetchall()]
    
    conn.close()
    return users, errors, mood