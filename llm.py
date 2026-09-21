"""
llm.py — работа с LLM через российский агрегатор Ranvik API.
"""

import os
import logging
from openai import AsyncOpenAI

# Ranvik API полностью совместим с OpenAI SDK.
# Меняем только base_url и ключ — код остаётся прежним.
client = AsyncOpenAI(
    api_key=os.getenv("RANVIK_API_KEY"),
    base_url="https://api.ranvik.ru/v1"
)

# Название модели. Можно посмотреть в каталоге: api.ranvik.ru/models
# deepseek-v4-flash — быстрая и дешёвая, хорошо подходит для анализа.
MODEL = "deepseek-v4-flash"


async def generate_digest(errors: list) -> str:
    """
    Принимает список ошибок и возвращает персональный разбор от LLM.
    """
    if not os.getenv("RANVIK_API_KEY"):
        logging.error("RANVIK_API_KEY не задан в переменных окружения")
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
        logging.error(f"Ошибка при запросе к Ranvik: {e}")
        return None