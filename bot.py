"""
BugClub bot — финальная версия: PostgreSQL, LLM, квиз, экспорт, лимиты, дайджест.
"""

import asyncio
import csv
import io
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile,
)

import db
import llm

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# ⚠️ Впиши свой telegram user_id (узнать у @userinfobot).
ADMIN_IDS = []

router = Router()


# ---------- Вспомогательные ----------

def split_message(text: str, limit: int = 4000):
    """Режет длинный текст на куски по limit символов."""
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        cut = text.rfind(" ", 0, limit)
        if cut == -1:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip()
    return parts


# ---------- Состояния ----------

class MoodBefore(StatesGroup):
    anxiety = State()
    fear = State()


class MoodAfter(StatesGroup):
    anxiety = State()
    emotion = State()
    self_corrected = State()


class LogError(StatesGroup):
    kind = State()
    category = State()
    who = State()
    text = State()
    correction = State()


class Feedback(StatesGroup):
    waiting = State()


class Quiz(StatesGroup):
    answering = State()
    waiting_for_text = State()


# ---------- Клавиатуры ----------

def back_row():
    return [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]


def back_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[back_row()])


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Анонсы"), KeyboardButton(text="🐞 О Багси")],
            [KeyboardButton(text="📊 Тест настроения")],
            [KeyboardButton(text="📝 Мои ошибки"), KeyboardButton(text="🏋️ Упражнения")],
            [KeyboardButton(text="🎤 Обратная связь"), KeyboardButton(text="ℹ️ О клубе")],
        ],
        resize_keyboard=True,
    )


def scale_1_10_keyboard(prefix: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=str(n), callback_data=f"{prefix}_{n}")
        for n in range(1, 11)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[0:5], buttons[5:10], back_row()])


def before_after_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="До встречи", callback_data="mood_before"),
         InlineKeyboardButton(text="После встречи", callback_data="mood_after")],
        back_row(),
    ])


def emotion_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😳 Стыдно", callback_data="emotion_shame")],
        [InlineKeyboardButton(text="😐 Нейтрально", callback_data="emotion_neutral")],
        [InlineKeyboardButton(text="🤔 Любопытно", callback_data="emotion_curious")],
        [InlineKeyboardButton(text="😎 Горжусь, что рискнул(а)", callback_data="emotion_proud")],
        back_row(),
    ])


def self_correction_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, заметил(а) сам(а)", callback_data="selfcorrect_yes")],
        [InlineKeyboardButton(text="Нет", callback_data="selfcorrect_no")],
        [InlineKeyboardButton(text="Ошибок не было", callback_data="selfcorrect_none")],
        back_row(),
    ])


def kind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Mistake (оговорка)", callback_data="kind_mistake"),
         InlineKeyboardButton(text="Error (системная)", callback_data="kind_error")],
        back_row(),
    ])


def category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Grammar", callback_data="cat_grammar"),
         InlineKeyboardButton(text="Vocabulary", callback_data="cat_vocabulary"),
         InlineKeyboardButton(text="Pronunciation", callback_data="cat_pronunciation")],
        back_row(),
    ])


# ---------- Функции отправки вопросов ----------

async def ask_mood_before_anxiety(message, state):
    await state.set_state(MoodBefore.anxiety)
    await message.answer(
        "Насколько ты сейчас волнуешься перед тем, как говорить на английском? (1-10)",
        reply_markup=scale_1_10_keyboard("anxbefore"),
    )


async def ask_mood_before_fear(message, state):
    await state.set_state(MoodBefore.fear)
    await message.answer(
        "Насколько боишься, что тебя осудят за ошибку? (1-10)",
        reply_markup=scale_1_10_keyboard("fear"),
    )


async def ask_mood_after_anxiety(message, state):
    await state.set_state(MoodAfter.anxiety)
    await message.answer(
        "А сейчас, после встречи, насколько ты тревожишься? (1-10)",
        reply_markup=scale_1_10_keyboard("anxafter"),
    )


async def ask_mood_after_emotion(message, state):
    await state.set_state(MoodAfter.emotion)
    await message.answer(
        "Если сегодня был момент, когда ты ошибся(-лась) — что почувствовал(а)?",
        reply_markup=emotion_keyboard(),
    )


async def ask_mood_after_self_corrected(message, state):
    await state.set_state(MoodAfter.self_corrected)
    await message.answer(
        "Заметил(а) свою ошибку сам(а), до того как услышал(а) фидбек?",
        reply_markup=self_correction_keyboard(),
    )


async def ask_log_error_kind(message, state):
    await state.set_state(LogError.kind)
    await message.answer("Это mistake или error?", reply_markup=kind_keyboard())


async def ask_log_error_category(message, state):
    await state.set_state(LogError.category)
    await message.answer("Категория?", reply_markup=category_keyboard())


async def ask_log_error_who(message, state):
    await state.set_state(LogError.who)
    await message.answer(
        "Кто это сказал? Введи @username или «аноним»:",
        reply_markup=back_inline_keyboard(),
    )


async def ask_log_error_text(message, state):
    await state.set_state(LogError.text)
    await message.answer("Напиши, как сказал участник:", reply_markup=back_inline_keyboard())


async def ask_log_error_correction(message, state):
    await state.set_state(LogError.correction)
    await message.answer("А как правильно?", reply_markup=back_inline_keyboard())


# ---------- Базовые ----------

@router.message(CommandStart())
async def cmd_start(message: Message):
    await db.save_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    await message.answer(
        "Привет! Я Багси 🐞 — бот BugClub.\n"
        "Здесь можно ошибаться, и от этого расти. Выбери, что тебя интересует:",
        reply_markup=main_menu_keyboard(),
    )


@router.message(F.text == "📅 Анонсы")
async def show_announcements(message: Message):
    topic = await db.get_current_session_topic()
    if topic:
        await message.answer(f"Ближайшая встреча.\nТема: {topic}")
    else:
        await message.answer("Пока нет активной встречи. Следи за обновлениями! 🐞")


@router.message(F.text == "ℹ️ О клубе")
async def about(message: Message):
    await message.answer(
        "BugClub — место, где можно ошибаться на английском и не бояться этого."
    )


@router.message(F.text == "🐞 О Багси")
async def about_bagsy(message: Message):
    await message.answer_photo(
        photo="https://i.pinimg.com/1200x/17/08/fb/1708fba00cf32988748c7ce160f86eaf.jpg",
        caption=(
            "Привет! Я Багси 🐞 — талисман BugClub.\n\n"
            "Меня зовут так, потому что 'bug' — это и 'жучок', и 'ошибка'. "
            "Я здесь, чтобы напоминать: ошибаться — это нормально!"
        ),
    )


# ---------- Обратная связь ----------

@router.message(F.text == "🎤 Обратная связь")
async def feedback_start(message: Message, state: FSMContext):
    await state.set_state(Feedback.waiting)
    await message.answer(
        "Напиши свой анонимный фидбек о встрече одним сообщением — я передам модератору.",
        reply_markup=back_inline_keyboard(),
    )


@router.message(Feedback.waiting)
async def feedback_receive(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await back_handler_logic(message, state)
        return

    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, f"🎤 Анонимный фидбек:\n\n{message.text}")
            sent += 1
        except Exception as e:
            logging.error(f"Фидбек админу {admin_id}: {e}")

    await state.clear()
    await message.answer(
        "Спасибо! Твой фидбек передан 🐞" if sent else "Фидбек сохранён.",
        reply_markup=main_menu_keyboard(),
    )


# ---------- Мои ошибки ----------

@router.message(F.text == "📝 Мои ошибки")
async def my_errors(message: Message):
    rows = await db.get_user_errors(message.from_user.id, limit=5)
    if not rows:
        await message.answer("Пока не зафиксировано ни одной твоей ошибки — это хороший знак 🙂")
        return

    lines = ["Вот твои последние ошибки:\n"]
    for row in rows:
        kind_label = "оговорка" if row["kind"] == "mistake" else "системная"
        lines.append(f"• [{row['category']}, {kind_label}] «{row['error_text']}» → «{row['correction_text']}»")
    await message.answer("\n".join(lines))

    all_errors = await db.get_all_user_errors(message.from_user.id)
    if len(all_errors) >= 3:
        # Rate limit: раз в 5 минут
        if not await db.check_rate_limit(message.from_user.id, "digest", minutes=5):
            await message.answer("⏳ Разбор можно запрашивать раз в 5 минут. Попробуй позже.")
            return

        await message.answer("🧠 Генерирую персональный разбор...")
        digest = await llm.generate_digest(all_errors)
        await db.log_llm_usage(message.from_user.id, "digest")
        if digest:
            for part in split_message(f"🐞 Разбор от Багси:\n\n{digest}"):
                await message.answer(part)
        else:
            await message.answer("Не удалось сгенерировать разбор. Попробуй позже.")
    else:
        await message.answer("Пройди ещё несколько встреч — и я смогу дать разбор! 🐞")


# ---------- Тест настроения ----------

@router.message(F.text == "📊 Тест настроения")
async def mood_test_start(message: Message):
    if await db.get_current_session_id() is None:
        await message.answer("Пока нет активной встречи — тест откроется, когда модератор начнёт сессию.")
        return
    await message.answer("Это тест до встречи или после?", reply_markup=before_after_keyboard())


@router.callback_query(F.data == "mood_before")
async def mood_before_start(cb: CallbackQuery, state: FSMContext):
    await ask_mood_before_anxiety(cb.message, state)
    await cb.answer()


@router.callback_query(MoodBefore.anxiety, F.data.startswith("anxbefore_"))
async def mood_before_anxiety(cb: CallbackQuery, state: FSMContext):
    await state.update_data(anxiety=int(cb.data.split("_")[1]))
    await ask_mood_before_fear(cb.message, state)
    await cb.answer()


@router.callback_query(MoodBefore.fear, F.data.startswith("fear_"))
async def mood_before_fear(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    sid = await db.get_current_session_id()
    await db.save_mood_before(cb.from_user.id, sid, data["anxiety"], int(cb.data.split("_")[1]))
    await state.clear()
    await cb.message.answer("Спасибо! Увидимся на встрече 🐞")
    await cb.answer()


@router.callback_query(F.data == "mood_after")
async def mood_after_start(cb: CallbackQuery, state: FSMContext):
    await ask_mood_after_anxiety(cb.message, state)
    await cb.answer()


@router.callback_query(MoodAfter.anxiety, F.data.startswith("anxafter_"))
async def mood_after_anxiety(cb: CallbackQuery, state: FSMContext):
    await state.update_data(anxiety=int(cb.data.split("_")[1]))
    await ask_mood_after_emotion(cb.message, state)
    await cb.answer()


@router.callback_query(MoodAfter.emotion, F.data.startswith("emotion_"))
async def mood_after_emotion(cb: CallbackQuery, state: FSMContext):
    await state.update_data(emotion=cb.data.split("_")[1])
    await ask_mood_after_self_corrected(cb.message, state)
    await cb.answer()


@router.callback_query(MoodAfter.self_corrected, F.data.startswith("selfcorrect_"))
async def mood_after_self_corrected(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    sid = await db.get_current_session_id()
    await db.save_mood_after(
        cb.from_user.id, sid, data["anxiety"],
        data["emotion"], cb.data.split("_")[1],
    )
    await state.clear()
    await cb.message.answer("Спасибо! Это помогает делать клуб лучше 🐞")
    await cb.answer()


# ---------- Квиз ----------

@router.message(F.text == "🏋️ Упражнения")
async def quiz_start(message: Message, state: FSMContext):
    rows = await db.get_all_user_errors(message.from_user.id)
    if not rows:
        await message.answer("Пока нет ошибок. После встреч я составлю упражнения! 🐞")
        return
    if len(rows) < 3:
        await message.answer(f"Нужно хотя бы 3 ошибки. Сейчас у тебя их {len(rows)}. 🐞")
        return

    if not await db.check_rate_limit(message.from_user.id, "quiz", minutes=5):
        await message.answer("⏳ Упражнения можно запрашивать раз в 5 минут. Попробуй позже.")
        return

    await message.answer("🏋️ Готовлю персональные упражнения...")
    questions = await llm.generate_quiz(rows)
    await db.log_llm_usage(message.from_user.id, "quiz")
    if not questions:
        await message.answer("Не удалось сгенерировать упражнения. Попробуй позже.")
        return

    await state.set_state(Quiz.answering)
    await state.update_data(questions=questions, current=0, score=0)
    await send_quiz_question(message, state)


async def send_quiz_question(message: Message, state: FSMContext):
    data = await state.get_data()
    questions = data["questions"]
    current = data["current"]
    score = data["score"]

    if current >= len(questions):
        total = len(questions)
        await state.clear()
        await message.answer(
            f"🎉 Упражнения пройдены!\n\nПравильных: {score} из {total}.\n\nМолодец! 🐞"
        )
        return

    q = questions[current]
    if q.get("type") == "text":
        await state.set_state(Quiz.waiting_for_text)
        await message.answer(
            f"Вопрос {current + 1} из {len(questions)}:\n\n{q['sentence']}\n\n✍️ Напиши ответ одним сообщением:"
        )
    else:
        await state.set_state(Quiz.answering)
        buttons = []
        for i, opt in enumerate(q["options"]):
            letter = chr(97 + i)
            buttons.append([InlineKeyboardButton(text=f"{letter}) {opt}", callback_data=f"quiz_{i}")])
        await message.answer(
            f"Вопрос {current + 1} из {len(questions)}:\n\n{q['sentence']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )


@router.callback_query(Quiz.answering, F.data.startswith("quiz_"))
async def quiz_answer(cb: CallbackQuery, state: FSMContext):
    chosen = int(cb.data.split("_")[1])
    data = await state.get_data()
    questions = data["questions"]
    current = data["current"]
    score = data["score"]
    q = questions[current]

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if chosen == q["correct_index"]:
        await cb.message.answer(f"✅ Верно!\n\n{q['explanation']}")
        score += 1
    else:
        correct_letter = chr(97 + q["correct_index"])
        correct_opt = q["options"][q["correct_index"]]
        await cb.message.answer(
            f"❌ Не совсем.\n\nПравильный: {correct_letter}) {correct_opt}\n\n{q['explanation']}"
        )

    await state.update_data(current=current + 1, score=score)
    await cb.answer()
    await send_quiz_question(cb.message, state)


@router.message(Quiz.waiting_for_text)
async def quiz_text_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    questions = data["questions"]
    current = data["current"]
    score = data["score"]
    q = questions[current]

    await message.answer("🤔 Проверяю ответ...")
    result = await llm.check_text_answer(
        sentence=q["sentence"],
        correct_answer=q["correct_answer"],
        user_answer=message.text,
    )

    if result and result.get("is_correct"):
        await message.answer(f"✅ Верно!\n\n{result.get('explanation', '')}")
        score += 1
    else:
        expl = result.get("explanation", "") if result else ""
        await message.answer(
            f"❌ Не совсем.\n\nЭталон: {q['correct_answer']}\n\n{expl}"
        )

    await state.update_data(current=current + 1, score=score)
    await state.set_state(Quiz.answering)
    await send_quiz_question(message, state)


# ---------- Админ: новая встреча ----------

@router.message(Command("new_session"))
async def new_session(message: Message):
    if ADMIN_IDS and message.from_user.id not in ADMIN_IDS:
        return
    topic = message.text.replace("/new_session", "").strip()
    if not topic:
        await message.answer("Формат: /new_session Тема сегодняшних дебатов")
        return
    sid = await db.start_new_session(topic)
    await message.answer(f"Встреча #{sid} на тему «{topic}» открыта.")


# ---------- Админ: закрытие встречи с дайджестом ----------

@router.message(Command("close_session"))
async def close_session(message: Message):
    if ADMIN_IDS and message.from_user.id not in ADMIN_IDS:
        return
    sid = await db.get_current_session_id()
    if sid is None:
        await message.answer("Нет активной встречи для закрытия.")
        return

    topic = await db.get_current_session_topic()
    errors = await db.get_session_errors(sid)
    mood = await db.get_mood_stats()
    top = await db.get_top_error_categories()

    await db.close_current_session()

    # Сводка
    lines = [f"🔒 Встреча #{sid} «{topic}» закрыта.\n"]
    if mood:
        lines.append(f"📝 Тест «до»: {mood['before']['cnt']}, «после»: {mood['after']['cnt']}")
        if mood["before"]["cnt"] > 0:
            lines.append(f"📉 Средняя тревога до: {mood['before']['avg_anxiety']:.1f}")
        if mood["after"]["cnt"] > 0:
            lines.append(f"📈 Средняя тревога после: {mood['after']['avg_anxiety']:.1f}")
    lines.append(f"🐞 Всего ошибок: {len(errors)}")
    if top:
        lines.append("🏆 Топ категорий: " + ", ".join(f"{r['category']} ({r['cnt']})" for r in top))

    await message.answer("\n".join(lines))

    # LLM-дайджест
    if errors:
        await message.answer("🧠 Готовлю педагогический дайджест...")
        digest = await llm.generate_session_digest(errors, topic)
        if digest:
            for part in split_message(f"🧠 Что заметил Багси:\n\n{digest}"):
                await message.answer(part)
        else:
            await message.answer("Не удалось сгенерировать дайджест.")


# ---------- Админ: статистика ----------

@router.message(Command("stats"))
async def stats(message: Message):
    if ADMIN_IDS and message.from_user.id not in ADMIN_IDS:
        return
    sid = await db.get_current_session_id()
    if sid is None:
        await message.answer("Нет активной встречи.")
        return

    mood = await db.get_mood_stats()
    top = await db.get_top_error_categories()
    total = await db.get_total_users_count()

    lines = [f"📊 Статистика по встрече #{sid}\n", f"👥 Всего в базе: {total}"]
    if mood:
        lines.append(f"\n📝 Тест «до»: {mood['before']['cnt']}")
        if mood["before"]["cnt"] > 0:
            lines.append(f"   Средняя тревога: {mood['before']['avg_anxiety']:.1f}")
            lines.append(f"   Страх осуждения: {mood['before']['avg_fear']:.1f}")
        lines.append(f"📝 Тест «после»: {mood['after']['cnt']}")
        if mood["after"]["cnt"] > 0:
            lines.append(f"   Средняя тревога: {mood['after']['avg_anxiety']:.1f}")
    if top:
        lines.append("\n🏆 Топ ошибок:")
        for i, r in enumerate(top, 1):
            lines.append(f"   {i}. {r['category']} — {r['cnt']}")
    await message.answer("\n".join(lines))


# ---------- Админ: экспорт в CSV ----------

@router.message(Command("export"))
async def export_data(message: Message):
    if ADMIN_IDS and message.from_user.id not in ADMIN_IDS:
        return
    users, errors, mood = await db.get_all_data_for_export()
    if not users and not errors and not mood:
        await message.answer("Нет данных для экспорта.")
        return

    await message.answer("📦 Готовлю файлы для экспорта...")

    # users.csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["user_id", "username", "first_name", "last_interaction"])
    for u in users:
        w.writerow([u["user_id"], u["username"], u["first_name"], u["last_interaction"]])
    buf.seek(0)
    await message.answer_document(
        BufferedInputFile(buf.getvalue().encode("utf-8-sig"), filename="users.csv"),
        caption="👥 users.csv",
    )

    # errors.csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "user_id", "username", "first_name", "session_topic",
                "error_text", "correction_text", "category", "kind", "created_at"])
    for r in errors:
        w.writerow([r["id"], r["user_id"], r["username"], r["first_name"],
                    r["session_topic"], r["error_text"], r["correction_text"],
                    r["category"], r["kind"], r["created_at"]])
    buf.seek(0)
    await message.answer_document(
        BufferedInputFile(buf.getvalue().encode("utf-8-sig"), filename="errors.csv"),
        caption="🐞 errors.csv",
    )

    # mood.csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "user_id", "username", "first_name", "session_topic",
                "stage", "anxiety", "fear", "emotion", "self_corrected", "created_at"])
    for r in mood:
        w.writerow([r["id"], r["user_id"], r["username"], r["first_name"],
                    r["session_topic"], r["stage"], r["anxiety_score"],
                    r["fear_of_judgment_score"], r["emotion_reaction"],
                    r["self_corrected"], r["created_at"]])
    buf.seek(0)
    await message.answer_document(
        BufferedInputFile(buf.getvalue().encode("utf-8-sig"), filename="mood.csv"),
        caption="📊 mood.csv",
    )


# ---------- Админ: log_error ----------

@router.message(Command("log_error"))
async def log_error_start(message: Message, state: FSMContext):
    if ADMIN_IDS and message.from_user.id not in ADMIN_IDS:
        return
    if await db.get_current_session_id() is None:
        await message.answer("Сначала открой встречу командой /new_session")
        return
    await ask_log_error_kind(message, state)


@router.callback_query(LogError.kind, F.data.startswith("kind_"))
async def log_error_kind(cb: CallbackQuery, state: FSMContext):
    await state.update_data(kind=cb.data.split("_")[1])
    await ask_log_error_category(cb.message, state)
    await cb.answer()


@router.callback_query(LogError.category, F.data.startswith("cat_"))
async def log_error_category(cb: CallbackQuery, state: FSMContext):
    await state.update_data(category=cb.data.split("_")[1])
    await ask_log_error_who(cb.message, state)
    await cb.answer()


@router.message(LogError.who)
async def log_error_who(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await back_handler_logic(message, state)
        return
    text = message.text.strip()
    if text.lower() == "аноним":
        await state.update_data(user_id=None)
        await ask_log_error_text(message, state)
        return
    username = text.lstrip("@")
    user_id = await db.get_user_id_by_username(username)
    if user_id is None:
        await message.answer(
            f"Не нашёл @{username}. Пусть участник напишет /start, или напиши «аноним».",
            reply_markup=back_inline_keyboard(),
        )
        return
    await state.update_data(user_id=user_id)
    await ask_log_error_text(message, state)


@router.message(LogError.text)
async def log_error_text(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await back_handler_logic(message, state)
        return
    await state.update_data(text=message.text)
    await ask_log_error_correction(message, state)


@router.message(LogError.correction)
async def log_error_correction(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await back_handler_logic(message, state)
        return
    data = await state.get_data()
    sid = await db.get_current_session_id()
    await db.save_error(
        session_id=sid,
        error_text=data["text"],
        correction_text=message.text,
        category=data["category"],
        kind=data["kind"],
        user_id=data.get("user_id"),
    )
    await state.clear()
    await message.answer("Записал 🐞", reply_markup=main_menu_keyboard())


# ---------- Назад ----------

async def back_handler_logic(message: Message, state: FSMContext):
    current = await state.get_state()
    prev_map = {
        "MoodBefore:fear": MoodBefore.anxiety,
        "MoodAfter:emotion": MoodAfter.anxiety,
        "MoodAfter:self_corrected": MoodAfter.emotion,
        "LogError:category": LogError.kind,
        "LogError:who": LogError.category,
        "LogError:text": LogError.who,
        "LogError:correction": LogError.text,
        "Feedback:waiting": None,
    }
    prev = prev_map.get(current, "not_found")
    if prev == "not_found" or prev is None:
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=main_menu_keyboard())
        return
    if prev == MoodBefore.anxiety:
        await ask_mood_before_anxiety(message, state)
    elif prev == MoodAfter.anxiety:
        await ask_mood_after_anxiety(message, state)
    elif prev == MoodAfter.emotion:
        await ask_mood_after_emotion(message, state)
    elif prev == LogError.kind:
        await ask_log_error_kind(message, state)
    elif prev == LogError.category:
        await ask_log_error_category(message, state)
    elif prev == LogError.who:
        await ask_log_error_who(message, state)
    elif prev == LogError.text:
        await ask_log_error_text(message, state)
    else:
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=main_menu_keyboard())


@router.callback_query(F.data == "back")
async def back_handler(cb: CallbackQuery, state: FSMContext):
    await back_handler_logic(cb.message, state)
    await cb.answer()


@router.callback_query(F.data == "cancel")
async def cancel_handler(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Действие отменено.", reply_markup=main_menu_keyboard())
    await cb.answer()


# ---------- Запуск ----------

async def main():
    await db.init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())