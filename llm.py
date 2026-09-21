"""
llm.py — работа с LLM через OpenRouter с автоматическим перебором моделей.
"""

import aiohttp
import os
import logging

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Список бесплатных моделей. Бот пробует их по очереди, пока какая-нибудь
# не ответит. Если все недоступны — возвращает None.
# Актуальные бесплатные модели: openrouter.ai/models?max_price=0
MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "google/gemma-2-9b-it:free",
    "mistralai/mistral-7b-instruct:free",
    "microsoft/phi-3-medium-128k-instruct:free",
]


async def call_model(session: aiohttp.ClientSession, model: str, headers: dict, payload: dict) -> str:
    """Пробует одну модель. Возвращает текст ответа или None при ошибке."""
    payload["model"] = model
    try:
        async with session.post(OPENROUTER_URL, headers=headers, json=payload) as response:
            if response.status != 200:
                error_text = await response.text()
                logging.warning(f"Модель {model} не сработала ({response.status}): {error_text[:200]}")
                return None
            data = await response.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logging.error(f"Ошибка при запросе к {model}: {e}")
        return None


async def generate_digest(errors: list) -> str:
    """
    Принимает список ошибок и возвращает персональный разбор.
    Перебирает модели по очереди, пока одна не ответит.
    """
    if not OPENROUTER_API_KEY:
        logging.error("OPENROUTER_API_KEY не задан в переменных окружения")
        return None

    # Собираем ошибки в текст для промпта
    errors_text = ""
    for i, row in enumerate(errors, 1):
        kind_label = "оговорка" if row["kind"] == "mistake" else "системная"
        errors_text += (
            f"{i}. [{row['category']}, {kind_label}] "
            f"Сказал: «{row['error_text']}» → Правильно: «{row['correction_text']}»\n"
        )

    system_prompt = (
        "Ты — Багси 🐞, дружелюбный талисман клуба английского языка BugClub. "
        "Твоя задача — мягко и поддерживающе проанализировать ошибки участника "
        "и дать ему персональные рекомендации. "
        "ВАЖНО: ошибаться — это нормально, никогда не осуждай. "
        "Пиши на русском, кратко (3-5 предложений), дружелюбно, с эмодзи. "
        "Структура ответа: 1) что общего в ошибках, 2) что потренировать, 3) поддерживающая фраза."
    )

    user_prompt = f"Вот ошибки участника за последние встречи:\n\n{errors_text}\n\nДай персональный разбор."

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 500,
        "temperature": 0.7,
    }

    async with aiohttp.ClientSession() as session:
        for model in MODELS:
            logging.info(f"Пробую модель: {model}")
            result = await call_model(session, model, headers, payload)
            if result:
                logging.info(f"Успех с моделью: {model}")
                return result
            # небольшая пауза между попытками
            await aiohttp.helpers.asyncio.sleep(1)

    logging.error("Все модели из списка не сработали.")
    return None