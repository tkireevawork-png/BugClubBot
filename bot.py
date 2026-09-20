"""
BugClub bot — версия с базой данных и тестом настроения.

Что умеет:
1. Подключается к Telegram через токен из переменных окружения.
2. Главное меню: Анонсы, О Багси, Тест настроения, Мои ошибки,
   Обратная связь, О клубе.
3. "Тест настроения" — полноценный диалог до/после встречи (FSM).
4. "Мои ошибки" — показывает последние ошибки из базы данных.
5. Админ-команды /new_session и /log_error — только для модератора
   (список ADMIN_IDS ниже).

Файлы проекта:
- bot.py (этот файл) — логика общения с Telegram
- db.py — работа с базой данных SQLite
- requirements.txt — список зависимостей
- Procfile — команда запуска для Railway
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

logging.basicConfig(level=logging.INFO)

# Токен хранится в переменных окружения Railway, а не в коде.
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ⚠️ ВАЖНО: впиши сюда свой telegram user_id (узнать у @userinfobot).
# Пока список пуст — ЛЮБОЙ участник сможет открыть встречу и логировать
# ошибки. Впиши свой id, например: ADMIN_IDS = [123456789]
ADMIN_IDS = [8905096909]

router = Router()


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
    text = State()
    correction = State()


# ---------- Клавиатуры ----------

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Анонсы"), KeyboardButton(text="🐞 О Багси")],
            [KeyboardButton(text="📊 Тест настроения")],
            [KeyboardButton(text="📝 Мои ошибки"), KeyboardButton(text="🎤 Обратная связь")],
            [KeyboardButton(text="ℹ️ О клубе")],
        ],
        resize_keyboard=True,
    )


def scale_1_10_keyboard(prefix: str) -> InlineKeyboardMarkup:
    """Кнопки с цифрами 1-10. prefix помогает отличать, к какому
    вопросу относится нажатие (например 'anxbefore_5')."""
    buttons = [
        InlineKeyboardButton(text=str(n), callback_data=f"{prefix}_{n}")
        for n in range(1, 11)
    ]
    rows = [buttons[0:5], buttons[5:10]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def before_after_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="До встречи", callback_data="mood_before"),
        InlineKeyboardButton(text="После встречи", callback_data="mood_after"),
    ]])


def emotion_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😳 Стыдно", callback_data="emotion_shame")],
        [InlineKeyboardButton(text="😐 Нейтрально", callback_data="emotion_neutral")],
        [InlineKeyboardButton(text="🤔 Любопытно", callback_data="emotion_curious")],
        [InlineKeyboardButton(text="😎 Горжусь, что рискнул(а)", callback_data="emotion_proud")],
    ])


def self_correction_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, заметил(а) сам(а)", callback_data="selfcorrect_yes")],
        [InlineKeyboardButton(text="Нет", callback_data="selfcorrect_no")],
        [InlineKeyboardButton(text="Ошибок не было", callback_data="selfcorrect_none")],
    ])


def kind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Mistake (оговорка)", callback_data="kind_mistake"),
        InlineKeyboardButton(text="Error (системная)", callback_data="kind_error"),
    ]])


def category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Grammar", callback_data="cat_grammar"),
        InlineKeyboardButton(text="Vocabulary", callback_data="cat_vocabulary"),
        InlineKeyboardButton(text="Pronunciation", callback_data="cat_pronunciation"),
    ]])


# ---------- Базовые команды ----------

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я Багси 🐞 — бот BugClub.\n"
        "Здесь можно ошибаться, и от этого расти. Выбери, что тебя интересует:",
        reply_markup=main_menu_keyboard(),
    )


@router.message(F.text == "📅 Анонсы")
async def show_announcements(message: Message):
    # TODO: подтягивать реальную дату и тему из таблицы sessions.
    await message.answer(
        "Ближайшая встреча: 11 октября в 18:00. "
        "Тема: Starting from Scratch"
    )


@router.message(F.text == "🎤 Обратная связь")
async def feedback(message: Message):
    # TODO: сохранять следующее сообщение пользователя как анонимный фидбек
    await message.answer(
        "Напиши свой анонимный фидбек о встрече одним сообщением — я его сохраню."
    )


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


# ---------- Мои ошибки ----------

@router.message(F.text == "📝 Мои ошибки")
async def my_errors(message: Message):
    rows = db.get_user_errors(message.from_user.id, limit=5)
    if not rows:
        await message.answer(
            "Пока не зафиксировано ни одной твоей ошибки — это хороший знак 🙂"
        )
        return

    lines = ["Вот твои последние ошибки:\n"]
    for error_text, correction_text, category, kind in rows:
        kind_label = "оговорка" if kind == "mistake" else "системная"
        lines.append(f"• [{category}, {kind_label}] «{error_text}» → «{correction_text}»")
    lines.append("\nПерсональные упражнения на их основе появятся здесь чуть позже.")
    await message.answer("\n".join(lines))


# ---------- Тест настроения ----------

@router.message(F.text == "📊 Тест настроения")
async def mood_test_start(message: Message):
    session_id = db.get_current_session_id()
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
    await state.set_state(MoodBefore.anxiety)
    await callback.message.answer(
        "Насколько ты сейчас волнуешься перед тем, как говорить на английском? "
        "(1 — совсем нет, 10 — очень)",
        reply_markup=scale_1_10_keyboard("anxbefore"),
    )
    await callback.answer()


@router.callback_query(MoodBefore.anxiety, F.data.startswith("anxbefore_"))
async def mood_before_anxiety(callback: CallbackQuery, state: FSMContext):
    score = int(callback.data.split("_")[1])
    await state.update_data(anxiety=score)
    await state.set_state(MoodBefore.fear)
    await callback.message.answer(
        "Насколько боишься, что тебя осудят за ошибку? (1 — совсем нет, 10 — очень)",
        reply_markup=scale_1_10_keyboard("fear"),
    )
    await callback.answer()


@router.callback_query(MoodBefore.fear, F.data.startswith("fear_"))
async def mood_before_fear(callback: CallbackQuery, state: FSMContext):
    fear_score = int(callback.data.split("_")[1])
    data = await state.get_data()
    session_id = db.get_current_session_id()
    db.save_mood_before(
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
    await state.set_state(MoodAfter.anxiety)
    await callback.message.answer(
        "А сейчас, после встречи, насколько ты тревожишься? (1 — совсем нет, 10 — очень)",
        reply_markup=scale_1_10_keyboard("anxafter"),
    )
    await callback.answer()


@router.callback_query(MoodAfter.anxiety, F.data.startswith("anxafter_"))
async def mood_after_anxiety(callback: CallbackQuery, state: FSMContext):
    score = int(callback.data.split("_")[1])
    await state.update_data(anxiety=score)
    await state.set_state(MoodAfter.emotion)
    await callback.message.answer(
        "Если сегодня был момент, когда ты ошибся(-лась) — что почувствовал(а)?",
        reply_markup=emotion_keyboard(),
    )
    await callback.answer()


@router.callback_query(MoodAfter.emotion, F.data.startswith("emotion_"))
async def mood_after_emotion(callback: CallbackQuery, state: FSMContext):
    emotion = callback.data.split("_")[1]  # shame / neutral / curious / proud
    await state.update_data(emotion=emotion)
    await state.set_state(MoodAfter.self_corrected)
    await callback.message.answer(
        "Заметил(а) свою ошибку сам(а), до того как услышал(а) фидбек?",
        reply_markup=self_correction_keyboard(),
    )
    await callback.answer()


@router.callback_query(MoodAfter.self_corrected, F.data.startswith("selfcorrect_"))
async def mood_after_self_corrected(callback: CallbackQuery, state: FSMContext):
    self_corrected = callback.data.split("_")[1]  # yes / no / none
    data = await state.get_data()
    session_id = db.get_current_session_id()
    db.save_mood_after(
        user_id=callback.from_user.id,
        session_id=session_id,
        anxiety_score=data["anxiety"],
        emotion_reaction=data["emotion"],
        self_corrected=self_corrected,
    )
    await state.clear()
    await callback.message.answer("Спасибо! Это очень помогает делать клуб лучше 🐞")
    await callback.answer()


# ---------- Admin: новая встреча ----------

@router.message(Command("new_session"))
async def new_session(message: Message):
    if ADMIN_IDS and message.from_user.id not in ADMIN_IDS:
        return
    topic = message.text.replace("/new_session", "").strip()
    if not topic:
        await message.answer("Формат: /new_session Тема сегодняшних дебатов")
        return
    session_id = db.start_new_session(topic)
    await message.answer(
        f"Встреча #{session_id} на тему «{topic}» открыта. "
        "Тест настроения теперь доступен."
    )


# ---------- Admin: фиксация ошибки ----------

@router.message(Command("log_error"))
async def log_error_start(message: Message, state: FSMContext):
    if ADMIN_IDS and message.from_user.id not in ADMIN_IDS:
        return
    session_id = db.get_current_session_id()
    if session_id is None:
        await message.answer("Сначала открой встречу командой /new_session")
        return
    await state.set_state(LogError.kind)
    await message.answer("Это mistake или error?", reply_markup=kind_keyboard())


@router.callback_query(LogError.kind, F.data.startswith("kind_"))
async def log_error_kind(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.split("_")[1]  # mistake / error
    await state.update_data(kind=kind)
    await state.set_state(LogError.category)
    await callback.message.answer("Категория?", reply_markup=category_keyboard())
    await callback.answer()


@router.callback_query(LogError.category, F.data.startswith("cat_"))
async def log_error_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split("_")[1]  # grammar / vocabulary / pronunciation
    await state.update_data(category=category)
    await state.set_state(LogError.text)
    await callback.message.answer("Напиши, как сказал участник (можно без имени):")
    await callback.answer()


@router.message(LogError.text)
async def log_error_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    await state.set_state(LogError.correction)
    await message.answer("А как правильно?")


@router.message(LogError.correction)
async def log_error_correction(message: Message, state: FSMContext):
    data = await state.get_data()
    session_id = db.get_current_session_id()
    db.save_error(
        session_id=session_id,
        error_text=data["text"],
        correction_text=message.text,
        category=data["category"],
        kind=data["kind"],
    )
    await state.clear()
    await message.answer("Записал 🐞")


# ---------- Запуск ----------

async def main():
    db.init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())