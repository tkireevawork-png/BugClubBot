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
    """Достаёт текст ответа, учитывая reasoning-модели."""
    choice = response.choices[0]
    content = choice.message.content or ""
    reasoning = getattr(choice.message, "reasoning_content", None) or ""
    result = content.strip() if content.strip() else reasoning.strip()
    logging.info(
        f"LLM: content={len(content)} симв, reasoning={len(reasoning)} симв, итог={len(result)}"
    )
    return result


def _parse_json(raw: str):
    """Снимает возможные markdown-обёртки и парсит JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


async def generate_digest(errors: list) -> str:
    """Персональный разбор ошибок ученика."""
    if not os.getenv("RANVIK_API_KEY"):
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
        "Проанализируй ошибки ученика и дай персональный разбор.\n"
        "ПРАВИЛА:\n"
        "1. Будь поддерживающим. Ошибаться — нормально.\n"
        "2. Пиши на русском, с эмодзи.\n"
        "3. Структура: что общего → что потренировать → мини-совет → поддержка.\n"
        "4. Не больше 5-6 предложений.\n"
        "5. Не используй символы * _ [ ] `.\n"
        "6. Обязательно закончи мысль."
    )
    user_prompt = f"Ошибки ученика:\n\n{errors_text}\n\nДай краткий разбор."

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
        return extract_text(response) or None
    except Exception as e:
        logging.error(f"Ошибка digest: {e}")
        return None


async def generate_quiz(errors: list) -> list:
    """Квиз из 3 вопросов. 2 типа: choice (кнопки) и text (ввод)."""
    if not os.getenv("RANVIK_API_KEY"):
        return None

    errors_text = ""
    for i, row in enumerate(errors, 1):
        kind_label = "оговорка" if row["kind"] == "mistake" else "системная"
        errors_text += (
            f"{i}. [{row['category']}, {kind_label}] "
            f"Сказал: «{row['error_text']}» → Правильно: «{row['correction_text']}»\n"
        )

    system_prompt = (
        "Ты — преподаватель английского. Создай ровно 3 вопроса "
        "на основе ошибок ученика.\n\n"
        "Формат каждого вопроса: либо type=choice, либо type=text.\n\n"
        "ВЕРНИ ТОЛЬКО JSON:\n"
        "{\n"
        '  "questions": [\n'
        "    {\n"
        '      "type": "choice",\n'
        '      "sentence": "My sister wants to ___ me to drive.",\n'
        '      "options": ["learn", "teach"],\n'
        '      "correct_index": 1,\n'
        '      "explanation": "Teach — учить кого-то, learn — учиться самому."\n'
        "    },\n"
        "    {\n"
        '      "type": "text",\n'
        '      "sentence": "Переведи: Я сфотографировал собаку вчера.",\n'
        '      "correct_answer": "I took a photo of the dog yesterday.",\n'
        '      "explanation": "Take a photo — устойчивое выражение, не make."\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "ПРАВИЛА:\n"
        "1. Ровно 3 вопроса: 2 типа choice (с кнопками) + 1 типа text (перевод или раскрытие скобок).\n"
        "2. Для choice — options 2-4 варианта, correct_index — индекс правильного (0,1,2...).\n"
        "3. Для text — correct_answer — эталонный ответ, sentence — задание.\n"
        "4. explanation — 1-2 предложения на русском.\n"
        "5. Никакого текста до/после JSON."
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
            max_tokens=1800,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        raw = extract_text(response)
        if not raw:
            return None
        data = _parse_json(raw)
        questions = data.get("questions", [])
        if not questions:
            return None
        logging.info(f"Квиз: {len(questions)} вопросов")
        return questions
    except json.JSONDecodeError as e:
        logging.error(f"JSON parse error: {e}")
        logging.error(f"Сырой ответ: {raw[:500]}")
        return None
    except Exception as e:
        logging.error(f"Ошибка quiz: {e}")
        return None


async def check_text_answer(sentence: str, correct_answer: str, user_answer: str) -> dict:
    """Проверяет текстовый ответ ученика. Возвращает {"is_correct": bool, "explanation": str}."""
    if not os.getenv("RANVIK_API_KEY"):
        return None

    system_prompt = (
        "Ты — преподаватель английского. Проверь ответ ученика. "
        "Учитывай, что небольшие расхождения (пунктуация, регистр) — это НЕ ошибка. "
        "Верни ТОЛЬКО JSON: "
        '{"is_correct": true или false, "explanation": "1-2 предложения на русском"}'
    )
    user_prompt = (
        f"Задание: {sentence}\n"
        f"Эталонный ответ: {correct_answer}\n"
        f"Ответ ученика: {user_answer}"
    )

    raw = ""
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=600,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw = extract_text(response)
        if not raw:
            return None
        return _parse_json(raw)
    except Exception as e:
        logging.error(f"Ошибка check_text_answer: {e}")
        return None


async def generate_session_digest(errors: list, topic: str) -> str:
    """Педагогический дайджест по итогам встречи для админа."""
    if not os.getenv("RANVIK_API_KEY"):
        return None

    if not errors:
        return "На этой встрече не было зафиксировано ошибок."

    errors_text = ""
    for i, row in enumerate(errors, 1):
        kind_label = "оговорка" if row["kind"] == "mistake" else "системная"
        errors_text += (
            f"{i}. [{row['category']}, {kind_label}] "
            f"«{row['error_text']}» → «{row['correction_text']}»\n"
        )

    system_prompt = (
        "Ты — методист, анализирующий ошибки учеников после разговорной встречи. "
        "Проанализируй ВСЕ ошибки встречи и дай педагогические рекомендации модератору.\n"
        "ПРАВИЛА:\n"
        "1. Пиши на русском, чётко и по делу.\n"
        "2. Структура:\n"
        "   • Какие темы хромают больше всего (топ-2-3).\n"
        "   • Что тренировать на следующей встрече.\n"
        "   • Какие ошибки системные (однотипные) — их надо разбирать особенно тщательно.\n"
        "3. 5-7 предложений, не растекайся.\n"
        "4. Не используй символы * _ [ ] `.\n"
        "5. Не обрывай мысль."
    )
    user_prompt = f"Встреча на тему «{topic}». Ошибки:\n\n{errors_text}\n\nДай рекомендации."

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
        return extract_text(response) or None
    except Exception as e:
        logging.error(f"Ошибка session_digest: {e}")
        return None