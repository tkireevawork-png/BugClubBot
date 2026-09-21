"""
llm.py — работа с LLM через OpenRouter для BugClub bot.
"""

import aiohttp
import os
import logging

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Бесплатная модель. Если будет тормозить — можно заменить на другую.
# Список бесплатных моделей: openrouter.ai/models?max_price=0
MODEL = "deepseek/deepseek-chat:free"


async def generate_digest(errors: list) -> str:
    """
    Принимает список ошибок (записей из БД) и возвращает персональный
    разбор от LLM в виде текста.
    """
    if not OPENROUTER_API_KEY:
        return None

    # Собираем ошибки в читаемый текст для промпта
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
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 500,
        "temperature": 0.7,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logging.error(f"OpenRouter error {response.status}: {error_text}")
                    return None
                data = await response.json()
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        logging.error(f"Ошибка при запросе к OpenRouter: {e}")
        return None