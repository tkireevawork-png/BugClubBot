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

MODEL = "deepseek-flash"


def extract_text(response) -> str:
    """
    Достаёт текст ответа. Учитывает особенность reasoning-моделей:
    иногда текст лежит в reasoning_content, а content пустой.
    """
    choice = response.choices[0]
    content = choice.message.content or ""
    reasoning = getattr(choice.message, "reasoning_content", None) or ""
    result = content.strip() if content.strip() else reasoning.strip()
    logging.info(
        f"LLM ответ: content={len(content)} символов, "
        f"reasoning={len(reasoning)} символов, итог={len(result)} символов"
    )
    return result


async def generate_digest(errors: list) -> str:
    """Принимает список ошибок и возвращает персональный разбор от LLM."""
    if not os.getenv("RANVIK_API_KEY"):
        logging.error("RANVIK_API_KEY не задан в переменных окружения")
        return None

    errors_text = ""
    for i, row in enumerate(errors, 1):
        kind_label = "оговорка" if row["kind"] == "mistake" else "системная"
        errors_text += (
            f"{i}. [{row['category']}, {kind_label}] "
            f"Сказал: «{row['error_text']}» → Правильно: «{row['correction_text']}»\n"
        )

    system_prompt = (
        "Ты — Багси 🐞, дружелюбный преподаватель английского в клубе BugClub. "
        "Проанализируй ошибки ученика и дай персональный разбор. "
        "ПРАВИЛА:\n"
        "1. Будь поддерживающим. Ошибаться — нормально.\n"
        "2. Пиши на русском, с эмодзи, без сюсюканья.\n"
        "3. Структура: что общего в ошибках → что потренировать → мини-упражнение → поддержка.\n"
        "4. ЖЁСТКИЙ ЛИМИТ: не больше 5-6 предложений. Не растекайся мыслью.\n"
        "5. Не используй символы * _ [ ] ` — они ломают форматирование Telegram.\n"
        "6. Не обрывай мысль на полуслове."
    )

    user_prompt = f"Ошибки ученика:\n\n{errors_text}\n\nДай краткий персональный разбор (5-6 предложений)."

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
        logging.info(f"Дайджест сгенерирован. Модель: {response.model}")
        return extract_text(response) or None
    except Exception as e:
        logging.error(f"Ошибка при запросе к Ranvik: {e}")
        return None


async def generate_exercises(errors: list) -> str:
    """Составляет персональные упражнения на основе ошибок ученика."""
    if not os.getenv("RANVIK_API_KEY"):
        logging.error("RANVIK_API_KEY не задан")
        return None

    errors_text = ""
    for i, row in enumerate(errors, 1):
        kind_label = "оговорка" if row["kind"] == "mistake" else "системная"
        errors_text += (
            f"{i}. [{row['category']}, {kind_label}] "
            f"Сказал: «{row['error_text']}» → Правильно: «{row['correction_text']}»\n"
        )

    system_prompt = (
        "Ты — Багси 🐞, преподаватель английского. "
        "Составь для ученика ровно 3 упражнения на основе его ошибок. "
        "ПРАВИЛА:\n"
        "1. Каждое упражнение — на одну из ошибок.\n"
        "2. Типы: выбор варианта (a/b/c/d), раскрыть скобки, перевод с русского.\n"
        "3. Пиши на русском, дружелюбно.\n"
        "4. После упражнений — блок «✅ Ответы».\n"
        "5. ЖЁСТКИЙ ЛИМИТ: не больше 4000 знаков. Будь кратким.\n"
        "6. Не используй символы * _ [ ] ` — они ломают форматирование Telegram.\n"
        "7. Не обрывай мысль на полуслове."
    )

    user_prompt = f"Ошибки ученика:\n\n{errors_text}\n\nСоставь 3 кратких упражнения."

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=900,
            temperature=0.7,
        )
        logging.info(f"Упражнения сгенерированы. Модель: {response.model}")
        return extract_text(response) or None
    except Exception as e:
        logging.error(f"Ошибка при генерации упражнений: {e}")
        return None