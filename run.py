import asyncio
import logging
import os
# ... импорты ...
from bot import router, ADMIN_IDS, BOT_TOKEN
import db  # <--- добавь это

# ...

def main():
    logging.basicConfig(level=logging.INFO)
    db.init_db()  # <--- добавь вызов инициализации базы прямо здесь
    
    bot = Bot(token=BOT_TOKEN)

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# Импортируем роутер из твоего основного файла bot.py
from bot import router, ADMIN_IDS, BOT_TOKEN

# --- Настройки для вебхука ---
# Amvera автоматически подставит сюда URL твоего проекта
BASE_URL = os.getenv("BASE_URL") 
if not BASE_URL:
    # Если переменная не задана, используем URL по умолчанию (для локального теста)
    BASE_URL = "https://your-project-name.amvera.io" 
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

# Amvera автоматически задаст порт через переменную окружения PORT, но мы укажем 8080 для надёжности
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", 8080))


async def on_startup(bot: Bot):
    """Действия при запуске бота."""
    logging.info(f"Устанавливаю вебхук на {WEBHOOK_URL}")
    await bot.set_webhook(WEBHOOK_URL)
    if ADMIN_IDS:
        await bot.send_message(ADMIN_IDS[0], "🚀 Бот запущен на Amvera!")


async def on_shutdown(bot: Bot):
    """Действия при остановке бота."""
    logging.info("Удаляю вебхук...")
    await bot.delete_webhook()


def main():
    # Настраиваем логирование
    logging.basicConfig(level=logging.INFO)

    # Инициализируем бота и диспетчер
    # Важно: bot.py должен экспортировать BOT_TOKEN
    bot = Bot(token=BOT_TOKEN) 
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрируем роутер из bot.py
    dp.include_router(router)

    # Регистрируем функции startup и shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Создаём веб-приложение aiohttp
    app = web.Application()

    # Создаём обработчик вебхука
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    # Регистрируем его по нужному пути
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    # Связываем приложение с диспетчером и ботом
    setup_application(app, dp, bot=bot)

    # Запускаем веб-сервер
    logging.info(f"Запускаю веб-сервер на {HOST}:{PORT}")
    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()