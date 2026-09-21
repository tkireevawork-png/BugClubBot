"""
llm.py — работа с LLM через российский агрегатор Ranvik API.
"""

import os
import json
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
        "6. Обязательно закончи мысль. Не обрывай на полуслове."
    )

    user_prompt = f"Ошибки ученика:\n\n{errors_text}\n\nДай краткий персональный разбор."

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1500,
            temperature=0.7,
        )
        logging.info(f"Дайджест сгенерирован. Модель: {response.model}")
        return extract_text(response) or None
    except Exception as e:
        logging.error(f"Ошибка при запросе к Ranvik (дайджест): {e}")
        return None


async def generate_quiz(errors: list) -> list:
    """
    Генерирует интерактивный квиз на основе ошибок.
    Возвращает список вопросов:
    [
        {
            "sentence": "My sister wants to ___ me to drive.",
            "options": ["learn", "teach"],
            "correct_index": 1,
            "explanation": "Teach — учить кого-то. Learn — учиться самому."
        },
        ...
    ]
    Или None при ошибке.
    """
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
        "Ты — преподаватель английского. Создай ровно 3 интерактивных вопроса "
        "на основе ошибок ученика. Каждый вопрос — с выбором одного правильного ответа "
        "из 2-4 вариантов.\n\n"
        "ВЕРНИ ТОЛЬКО ВАЛИДНЫЙ JSON, без пояснений и markdown-обёрток, строго такого формата:\n"
        "{\n"
        '  "questions": [\n'
        "    {\n"
        '      "sentence": "My sister wants to ___ me to drive.",\n'
        '      "options": ["learn", "teach"],\n'
        '      "correct_index": 1,\n'
        '      "explanation": "Teach — учить кого-то, learn — учиться самому."\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "ПРАВИЛА:\n"
        "1. sentence — предложение с пропуском ___.\n"
        "2. options — 2-4 варианта ответа, кратких (1-3 слова).\n"
        "3. correct_index — индекс правильного варианта (0 для первого, 1 для второго).\n"
        "4. explanation — 1-2 предложения на русском, почему этот вариант правильный.\n"
        "5. Не используй символ * в тексте.\n"
        "6. Никакого текста до или после JSON."
    )

    user_prompt = f"Ошибки ученика:\n\n{errors_text}\n\nСоздай 3 вопроса в JSON."

    raw = ""
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1500,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        raw = extract_text(response)
        if not raw:
            logging.error("LLM вернула пустой ответ для квиза")
            return None

        # Иногда модель оборачивает JSON в ```json ... ```
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)
        questions = data.get("questions", [])
        if not questions:
            logging.error("В JSON нет поля questions")
            return None

        logging.info(f"Квиз сгенерирован: {len(questions)} вопросов")
        return questions

    except json.JSONDecodeError as e:
        logging.error(f"Не удалось распарсить JSON от LLM: {e}")
        logging.error(f"Сырой ответ: {raw[:500]}")
        return None
    except Exception as e:
        logging.error(f"Ошибка при генерации квиза: {e}")
        return None