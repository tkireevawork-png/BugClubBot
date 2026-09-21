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
    # Fallback на reasoning_content, если он есть
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
            max_tokens=800,
            temperature=0.7,
        )
        logging.info(f"Успех. Модель: {response.model}")
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
        "Ты — Багси 🐞, опытный преподаватель английского языка. "
        "Составь для ученика персональные упражнения на основе его ошибок. "
        "ПРАВИЛА:\n"
        "1. Создай ровно 3 упражнения, каждое — на одну из ошибок ученика.\n"
        "2. Типы упражнений:\n"
        "   • Выбор правильного варианта (a/b/c/d)\n"
        "   • Раскрыть скобки, поставив глагол в нужную форму\n"
        "   • Перевести предложение с русского на английский\n"
        "3. Пиши на русском, дружелюбно, с эмодзи.\n"
        "4. ПОСЛЕ упражнений напиши блок «✅ Ответы» с правильными ответами.\n"
        "5. Не обрывай мысль на полуслове. Объём — 10-15 предложений."
    )

    user_prompt = f"Ошибки ученика:\n\n{errors_text}\n\nСоставь персональные упражнения."

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1500,     # ← увеличили, чтобы модель успевала завершить
            temperature=0.7,
        )
        logging.info(f"Упражнения сгенерированы. Модель: {response.model}")
        return extract_text(response) or None
    except Exception as e:
        logging.error(f"Ошибка при генерации упражнений: {e}")
        return None