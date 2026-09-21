"""
BugClub bot — версия с PostgreSQL, LLM-разбором и интерактивными упражнениями.
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

import db
import llm

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# ⚠️ Впиши сюда свой telegram user_id (узнать у @userinfobot).
ADMIN_IDS = []

router = Router()


# ---------- Вспомогательные функции ----------

def split_message(text: str, limit: int = 4000):
    """Режет длинный текст на куски по limit символов, не разрывая слова."""
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


# ---------- Состояния диалогов (FSM) ----------

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


# ---------- Клавиатуры ----------

def back_row():
    """Одна кнопка Назад. На первом шаге работает как выход в меню."""
    return [
        InlineKeyboardButton(text="◀️ Назад", callback_data="back"),
    ]


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
    rows = [buttons[0:5], buttons[5:10], back_row()]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def before_after_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="До встречи", callback_data="mood_before"),
            InlineKeyboardButton(text="После встречи", callback_data="mood_after"),
        ],
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
        [
            InlineKeyboardButton(text="Mistake (оговорка)", callback_data="kind_mistake"),
            InlineKeyboardButton(text="Error (системная)", callback_data="kind_error"),
        ],
        back_row(),
    ])


def category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Grammar", callback_data="cat_grammar"),
            InlineKeyboardButton(text="Vocabulary", callback_data="cat_vocabulary"),
            InlineKeyboardButton(text="Pronunciation", callback_data="cat_pronunciation"),
        ],
        back_row(),
    ])


# ---------- Функции отправки вопросов ----------

async def ask_mood_before_anxiety(message: Message, state: FSMContext):
    await state.set_state(MoodBefore.anxiety)
    await message.answer(
        "Насколько ты сейчас волнуешься перед тем, как говорить на английском? (1 — совсем нет, 10 — очень)",
        reply_markup=scale_1_10_keyboard("anxbefore"),
    )


async def ask_mood_before_fear(message: Message, state: FSMContext):
    await state.set_state(MoodBefore.fear)
    await message.answer(
        "Насколько боишься, что тебя осудят за ошибку? (1 — совсем нет, 10 — очень)",
        reply_markup=scale_1_10_keyboard("fear"),
    )


async def ask_mood_after_anxiety(message: Message, state: FSMContext):
    await state.set_state(MoodAfter.anxiety)
    await message.answer(
        "А сейчас, после встречи, насколько ты тревожишься? (1 — совсем нет, 10 — очень)",
        reply_markup=scale_1_10_keyboard("anxafter"),
    )


async def ask_mood_after_emotion(message: Message, state: FSMContext):
    await state.set_state(MoodAfter.emotion)
    await message.answer(
        "Если сегодня был момент, когда ты ошибся(-лась) — что почувствовал(а)?",
        reply_markup=emotion_keyboard(),
    )


async def ask_mood_after_self_corrected(message: Message, state: FSMContext):
    await state.set_state(MoodAfter.self_corrected)
    await message.answer(
        "Заметил(а) свою ошибку сам(а), до того как услышал(а) фидбек?",
        reply_markup=self_correction_keyboard(),
    )


async def ask_log_error_kind(message: Message, state: FSMContext):
    await state.set_state(LogError.kind)
    await message.answer("Это mistake или error?", reply_markup=kind_keyboard())


async def ask_log_error_category(message: Message, state: FSMContext):
    await state.set_state(LogError.category)
    await message.answer("Категория?", reply_markup=category_keyboard())


async def ask_log_error_who(message: Message, state: FSMContext):
    await state.set_state(LogError.who)
    await message.answer(
        "Кто это сказал? Введи @username участника (например, @ivan) или «аноним»:",
        reply_markup=back_inline_keyboard(),
    )


async def ask_log_error_text(message: Message, state: FSMContext):
    await state.set_state(LogError.text)
    await message.answer(
        "Напиши, как сказал участник:",
        reply_markup=back_inline_keyboard(),
    )


async def ask_log_error_correction(message: Message, state: FSMContext):
    await state.set_state(LogError.correction)
    await message.answer(
        "А как правильно?",
        reply_markup=back_inline_keyboard(),
    )


# ---------- Базовые команды ----------

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
        "BugClub — место, где можно ошибаться на английском и не бояться этого. "
        "Дебаты, живое общение и разбор ошибок без осуждения."
    )


@router.message(F.text == "🐞 О Багси")
async def about_bagsy(message: Message):
    photo_url = "https://i.pinimg.com/1200x/17/08/fb/1708fba00cf32988748c7ce160f86eaf.jpg"
    await message.answer_photo(
        photo=photo_url,
        caption=(
            "Привет! Я Багси 🐞 — талисман BugClub.\n\n"
            "Меня зовут так, потому что 'bug' — это и 'жучок', и 'ошибка'. "
            "Я здесь, чтобы напоминать: ошибаться — это нормально! "
            "Каждая ошибка — это шаг к тому, чтобы говорить лучше.\n\n"
            "Я буду помогать тебе на встречах, следить за настроением и хранить твои победы."
        ),
    )


# ---------- Обратная связь ----------

@router.message(F.text == "🎤 Обратная связь")
async def feedback_start(message: Message, state: FSMContext):
    await state.set_state(Feedback.waiting)
    await message.answer(
        "Напиши свой анонимный фидбек о встрече одним сообщением — я передам его модератору.",
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
            await message.bot.send_message(
                admin_id,
                f"🎤 Анонимный фидбек:\n\n{message.text}"
            )
            sent += 1
        except Exception as e:
            logging.error(f"Не удалось отправить фидбек админу {admin_id}: {e}")

    await state.clear()
    if sent > 0:
        await message.answer(
            "Спасибо! Твой фидбек передан модератору 🐞",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await message.answer(
            "Спасибо! Фидбек сохранён, но модератор пока не подключён.",
            reply_markup=main_menu_keyboard(),
        )


# ---------- Мои ошибки ----------

@router.message(F.text == "📝 Мои ошибки")
async def my_errors(message: Message):
    rows = await db.get_user_errors(message.from_user.id, limit=5)
    if not rows:
        await message.answer(
            "Пока не зафиксировано ни одной твоей ошибки — это хороший знак 🙂"
        )
        return

    lines = ["Вот твои последние ошибки:\n"]
    for row in rows:
        kind_label = "оговорка" if row["kind"] == "mistake" else "системная"
        lines.append(f"• [{row['category']}, {kind_label}] «{row['error_text']}» → «{row['correction_text']}»")

    await message.answer("\n".join(lines))

    all_errors = await db.get_all_user_errors(message.from_user.id)
    if len(all_errors) >= 3:
        await message.answer("🧠 Генерирую персональный разбор... Это займет несколько секунд.")
        digest = await llm.generate_digest(all_errors)
        if digest:
            for part in split_message(f"🐞 Разбор от Багси:\n\n{digest}"):
                await message.answer(part)
        else:
            await message.answer("Не удалось сгенерировать разбор. Попробуй позже.")
    else:
        await message.answer(
            "Пройди ещё несколько встреч — и я смогу дать персональный разбор твоих ошибок! 🐞"
        )


# ---------- Тест настроения ----------

@router.message(F.text == "📊 Тест настроения")
async def mood_test_start(message: Message):
    session_id = await db.get_current_session_id()
    if session_id is None:
        await message.answer(
            "Пока нет активной встречи — тест откроется, когда модератор начнёт сессию."
        )
        return
    await message.answer(
        "Это тест до встречи или после?", reply_markup=before_after_keyboard()
    )


@router.callback_query(F.data == "mood_before")
async def mood_before_start(callback: CallbackQuery, state: FSMContext):
    await ask_mood_before_anxiety(callback.message, state)
    await callback.answer()


@router.callback_query(MoodBefore.anxiety, F.data.startswith("anxbefore_"))
async def mood_before_anxiety(callback: CallbackQuery, state: FSMContext):
    score = int(callback.data.split("_")[1])
    await state.update_data(anxiety=score)
    await ask_mood_before_fear(callback.message, state)
    await callback.answer()


@router.callback_query(MoodBefore.fear, F.data.startswith("fear_"))
async def mood_before_fear(callback: CallbackQuery, state: FSMContext):
    fear_score = int(callback.data.split("_")[1])
    data = await state.get_data()
    session_id = await db.get_current_session_id()
    await db.save_mood_before(
        user_id=callback.from_user.id,
        session_id=session_id,
        anxiety_score=data["anxiety"],
        fear_score=fear_score,
    )
    await state.clear()
    await callback.message.answer("Спасибо! Увидимся на встрече 🐞")
    await callback.answer()


@router.callback_query(F.data == "mood_after")
async def mood_after_start(callback: CallbackQuery, state: FSMContext):
    await ask_mood_after_anxiety(callback.message, state)
    await callback.answer()


@router.callback_query(MoodAfter.anxiety, F.data.startswith("anxafter_"))
async def mood_after_anxiety(callback: CallbackQuery, state: FSMContext):
    score = int(callback.data.split("_")[1])
    await state.update_data(anxiety=score)
    await ask_mood_after_emotion(callback.message, state)
    await callback.answer()


@router.callback_query(MoodAfter.emotion, F.data.startswith("emotion_"))
async def mood_after_emotion(callback: CallbackQuery, state: FSMContext):
    emotion = callback.data.split("_")[1]
    await state.update_data(emotion=emotion)
    await ask_mood_after_self_corrected(callback.message, state)
    await callback.answer()


@router.callback_query(MoodAfter.self_corrected, F.data.startswith("selfcorrect_"))
async def mood_after_self_corrected(callback: CallbackQuery, state: FSMContext):
    self_corrected = callback.data.split("_")[1]
    data = await state.get_data()
    session_id = await db.get_current_session_id()
    await db.save_mood_after(
        user_id=callback.from_user.id,
        session_id=session_id,
        anxiety_score=data["anxiety"],
        emotion_reaction=data["emotion"],
        self_corrected=self_corrected,
    )
    await state.clear()
    await callback.message.answer("Спасибо! Это очень помогает делать клуб лучше 🐞")
    await callback.answer()


# ---------- Интерактивные упражнения (Quiz) ----------

@router.message(F.text == "🏋️ Упражнения")
async def quiz_start(message: Message, state: FSMContext):
    rows = await db.get_all_user_errors(message.from_user.id)
    if not rows:
        await message.answer(
            "Пока не зафиксировано ни одной твоей ошибки. "
            "После первых встреч я смогу составить для тебя упражнения! 🐞"
        )
        return

    if len(rows) < 3:
        await message.answer(
            f"Нужно хотя бы 3 ошибки, чтобы я составил упражнения. "
            f"Сейчас у тебя их {len(rows)}. Продолжай заниматься! 🐞"
        )
        return

    await message.answer("🏋️ Готовлю персональные упражнения... Это займёт несколько секунд.")
    questions = await llm.generate_quiz(rows)
    if not questions:
        await message.answer("Не удалось сгенерировать упражнения. Попробуй позже.")
        return

    await state.set_state(Quiz.answering)
    await state.update_data(questions=questions, current=0, score=0)
    await send_quiz_question(message, state)


async def send_quiz_question(message: Message, state: FSMContext):
    """Отправляет текущий вопрос с инлайн-кнопками вариантов."""
    data = await state.get_data()
    questions = data["questions"]
    current = data["current"]
    score = data["score"]

    if current >= len(questions):
        total = len(questions)
        await state.clear()
        await message.answer(
            f"🎉 Упражнения пройдены!\n\n"
            f"Правильных ответов: {score} из {total}.\n\n"
            f"Продолжай в том же духе! 🐞"
        )
        return

    q = questions[current]
    buttons = []
    for i, opt in enumerate(q["options"]):
        letter = chr(97 + i)  # a, b, c, d
        buttons.append([
            InlineKeyboardButton(text=f"{letter}) {opt}", callback_data=f"quiz_{i}")
        ])

    await message.answer(
        f"Вопрос {current + 1} из {len(questions)}:\n\n{q['sentence']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(Quiz.answering, F.data.startswith("quiz_"))
async def quiz_answer(callback: CallbackQuery, state: FSMContext):
    chosen = int(callback.data.split("_")[1])
    data = await state.get_data()
    questions = data["questions"]
    current = data["current"]
    score = data["score"]
    q = questions[current]

    # Убираем кнопки у старого сообщения, чтобы нельзя было нажать повторно
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if chosen == q["correct_index"]:
        await callback.message.answer(f"✅ Верно!\n\n{q['explanation']}")
        score += 1
    else:
        correct_letter = chr(97 + q["correct_index"])
        correct_opt = q["options"][q["correct_index"]]
        await callback.message.answer(
            f"❌ Не совсем.\n\n"
            f"Правильный ответ: {correct_letter}) {correct_opt}\n\n"
            f"{q['explanation']}"
        )

    await state.update_data(current=current + 1, score=score)
    await callback.answer()
    await send_quiz_question(callback.message, state)


# ---------- Admin: новая встреча ----------

@router.message(Command("new_session"))
async def new_session(message: Message):
    if ADMIN_IDS and message.from_user.id not in ADMIN_IDS:
        return
    topic = message.text.replace("/new_session", "").strip()
    if not topic:
        await message.answer("Формат: /new_session Тема сегодняшних дебатов")
        return
    session_id = await db.start_new_session(topic)
    await message.answer(
        f"Встреча #{session_id} на тему «{topic}» открыта. "
        "Тест настроения теперь доступен."
    )


# ---------- Admin: статистика ----------

@router.message(Command("stats"))
async def stats(message: Message):
    if ADMIN_IDS and message.from_user.id not in ADMIN_IDS:
        return

    session_id = await db.get_current_session_id()
    if session_id is None:
        await message.answer("Нет активной встречи. Открой её командой /new_session.")
        return

    mood = await db.get_mood_stats()
    top_cats = await db.get_top_error_categories()
    users_count = await db.get_total_users_count()

    lines = [f"📊 Статистика по встрече #{session_id}\n"]
    lines.append(f"👥 Всего в базе: {users_count}")

    if mood:
        before = mood["before"]
        after = mood["after"]
        lines.append(f"\n📝 Прошли тест «до»: {before['cnt']}")
        if before["cnt"] > 0:
            lines.append(f"   Средняя тревога: {before['avg_anxiety']:.1f}")
            lines.append(f"   Средний страх осуждения: {before['avg_fear']:.1f}")
        lines.append(f"📝 Прошли тест «после»: {after['cnt']}")
        if after["cnt"] > 0:
            lines.append(f"   Средняя тревога: {after['avg_anxiety']:.1f}")

    if top_cats:
        lines.append("\n🏆 Топ категорий ошибок:")
        for i, row in enumerate(top_cats, 1):
            lines.append(f"   {i}. {row['category']} — {row['cnt']}")

    await message.answer("\n".join(lines))


# ---------- Admin: фиксация ошибки ----------

@router.message(Command("log_error"))
async def log_error_start(message: Message, state: FSMContext):
    if ADMIN_IDS and message.from_user.id not in ADMIN_IDS:
        return
    session_id = await db.get_current_session_id()
    if session_id is None:
        await message.answer("Сначала открой встречу командой /new_session")
        return
    await ask_log_error_kind(message, state)


@router.callback_query(LogError.kind, F.data.startswith("kind_"))
async def log_error_kind(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.split("_")[1]
    await state.update_data(kind=kind)
    await ask_log_error_category(callback.message, state)
    await callback.answer()


@router.callback_query(LogError.category, F.data.startswith("cat_"))
async def log_error_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split("_")[1]
    await state.update_data(category=category)
    await ask_log_error_who(callback.message, state)
    await callback.answer()


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
            f"Не нашёл участника @{username} в базе. "
            "Убедись, что он хотя бы раз запускал бота (/start), "
            "или напиши «аноним».",
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
    session_id = await db.get_current_session_id()
    await db.save_error(
        session_id=session_id,
        error_text=data["text"],
        correction_text=message.text,
        category=data["category"],
        kind=data["kind"],
        user_id=data.get("user_id"),
    )
    await state.clear()
    await message.answer("Записал 🐞", reply_markup=main_menu_keyboard())


# ---------- Обработчики Назад и Отмена ----------

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
    prev_state = prev_map.get(current, "not_found")

    if prev_state == "not_found" or prev_state is None:
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=main_menu_keyboard())
        return

    if prev_state == MoodBefore.anxiety:
        await ask_mood_before_anxiety(message, state)
    elif prev_state == MoodAfter.anxiety:
        await ask_mood_after_anxiety(message, state)
    elif prev_state == MoodAfter.emotion:
        await ask_mood_after_emotion(message, state)
    elif prev_state == LogError.kind:
        await ask_log_error_kind(message, state)
    elif prev_state == LogError.category:
        await ask_log_error_category(message, state)
    elif prev_state == LogError.who:
        await ask_log_error_who(message, state)
    elif prev_state == LogError.text:
        await ask_log_error_text(message, state)
    else:
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=main_menu_keyboard())


@router.callback_query(F.data == "back")
async def back_handler(callback: CallbackQuery, state: FSMContext):
    await back_handler_logic(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cancel_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Действие отменено.", reply_markup=main_menu_keyboard())
    await callback.answer()


# ---------- Запуск ----------

async def main():
    await db.init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())