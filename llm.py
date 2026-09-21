"""
llm.py — работа с LLM через российский агрегатор Ranvik API.
"""

import os
import logging
from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key=os.getenv("RANVIK_API_KEY"),
    base_url="https://api.ranvik.ru/v1"
)

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
        "Ты — Багси 🐞, дружелюбный и опытный преподаватель английского языка в клубе BugClub. "
        "Твоя задача — проанализировать ошибки ученика и дать ему персональный, педагогичный разбор. "
        "ПРАВИЛА:\n"
        "1. Будь поддерживающим. Ошибаться — нормально. Никогда не осуждай.\n"
        "2. Пиши на русском, дружелюбно, с эмодзи, но без сюсюканья.\n"
        "3. Структура ответа:\n"
        "   • Что общего в ошибках (какие темы или правила нужно подтянуть).\n"
        "   • Конкретные рекомендации: что и как потренировать (можно с примерами).\n"
        "   • Мини-упражнение или совет, как запомнить правило.\n"
        "   • Поддерживающая фраза в конце.\n"
        "4. Ответ должен быть законченным. Не обрывай мысль на полуслове.\n"
        "5. Объём: 5-8 предложений, не больше."
    )

    user_prompt = f"Вот ошибки участника за последние встречи:\n\n{errors_text}\n\nДай персональный педагогический разбор."

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=800,      # ← увеличили, чтобы ответ не обрывался
            temperature=0.7,
        )
        logging.info(f"Успех. Модель: {response.model}")
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Ошибка при запросе к Ranvik: {e}")
        return None