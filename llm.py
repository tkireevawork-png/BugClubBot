"""
llm.py — работа с LLM через прямое API DeepSeek.
"""

import os
import logging
from openai import AsyncOpenAI

# Инициализируем клиент OpenAI, но указываем ему адрес DeepSeek
client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

# Модель для анализа. deepseek-chat — это актуальная версия.
MODEL = "deepseek-chat"


async def generate_digest(errors: list) -> str:
    """
    Принимает список ошибок и возвращает персональный разбор от DeepSeek.
    """
    if not os.getenv("DEEPSEEK_API_KEY"):
        logging.error("DEEPSEEK_API_KEY не задан в переменных окружения")
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

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=500,
            temperature=0.7,
        )
        logging.info(f"Успех. Модель: {response.model}")
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Ошибка при запросе к DeepSeek: {e}")
        return None