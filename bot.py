"""
BugClub bot — стартовый скелет.

Что делает этот код:
1. Подключается к Telegram через твой токен.
2. При команде /start показывает меню с кнопками (как в опорном документе).
3. На каждую кнопку пока отвечает заглушкой — это нормально, дальше
   будем заменять заглушки на реальную логику (база данных, LLM и т.д.)
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

# Логи помогают видеть, что происходит с ботом, пока разбираешься —
# в терминале будет видно каждое входящее сообщение.
logging.basicConfig(level=logging.INFO)

# Токен лучше не хранить прямо в коде — но для самого первого запуска
# можно временно вставить его сюда вместо строки ниже.
# Позже (когда дойдём до деплоя) вынесем его в переменные окружения.
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Router — это место, куда мы будем регистрировать все обработчики
# сообщений (хендлеры). У большого бота их может быть в разных файлах,
# но пока держим всё в одном для простоты.
router = Router()


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Собирает клавиатуту с кнопками главного меню из опорного документа."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Анонсы"), KeyboardButton(text="🐞 О Багси")],
	    [KeyboardButton(text="📊 Тест настроения")],
            [KeyboardButton(text="📝 Частые ошибки"), KeyboardButton(text="🎤 Обратная связь")],
            [KeyboardButton(text="ℹ️ О клубе")],
        ],
        resize_keyboard=True,  # кнопки подстраиваются под размер экрана
    )


# Декоратор @router.message(...) говорит aiogram: "вызови эту функцию,
# когда придёт сообщение, подходящее под условие в скобках".

@router.message(CommandStart())
async def cmd_start(message: Message):
    """Срабатывает на команду /start — первое, что видит пользователь."""
    await message.answer(
        "Привет! Я Багси 🐞 — бот BugClub.\n"
        "Здесь можно ошибаться, и от этого расти. Выбери, что тебя интересует:",
        reply_markup=main_menu_keyboard(),
    )
@router.message(F.text == "📅 Анонсы")
async def show_announcements(message: Message):
    # TODO: подтягивать реальную дату и тему дебатов из базы данных
    await message.answer("Ближайшая встреча: Ближайшая встреча: 11 октября в 18:00. Тема: Starting from Scratch")


@router.message(F.text == "📊 Тест настроения")
async def mood_test(message: Message):
    # TODO: здесь будет шкала 1–10 и запись ответа в таблицу mood_log
    await message.answer("Тест настроения будет здесь. Пока — заглушка.")


@router.message(F.text == "📝 Мои ошибки")
async def my_errors(message: Message):
    # TODO: подтягивать ошибки пользователя из errors_log
    # и генерировать персональный комментарий через LLM
    await message.answer("Твой персональный разбор ошибок появится здесь после первых встреч.")


@router.message(F.text == "🎤 Обратная связь")
async def feedback(message: Message):
    # TODO: сохранять следующее сообщение пользователя как анонимный фидбек
    await message.answer("Напиши свой анонимный фидбек о встрече одним сообщением — я его сохраню.")


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
        )
    )

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    # start_polling — бот сам будет спрашивать Telegram "есть новые сообщения?"
    # раз в небольшой промежуток времени. Для начала этого достаточно.
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
