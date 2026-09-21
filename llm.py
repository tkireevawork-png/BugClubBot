"""
llm.py — работа с LLM через российский агрегатор Ranvik API.

Методическая рамка:
- Noticing Frame (Schmidt) — помочь ученику ЗАМЕТИТЬ паттерн.
- Градация corrective feedback (Lyster & Ranta) — от мягкого к прямому.
- Error gravity — выбираем 2-3 значимые ошибки, не все подряд.
- PPP (Presentation–Practice–Production) — для упражнений.
- CLT (Communicative Language Teaching) — фокус на коммуникации, не на форме ради формы.
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


# ─── ОБЩАЯ МЕТОДОЛОГИЯ (единый голос Багси) ──────────────────────────────────

BUGSI_SYSTEM_PROMPT = """
Ты — Багси 🐞, методический ассистент спикинг-клуба BugClub.
Ты работаешь как опытный методист уровня CELTA/DELTA в рамках
коммуникативного подхода (Communicative Language Teaching).

Ты помогаешь взрослым (18–24, A2–B2) замечать свои ошибки
без стыда и превращать их в точки роста.

Философия клуба: «Здесь можно ошибаться, и от этого расти».
Ошибка (bug) — не провал, а данные для обучения.
Ошибка — нормальная часть межъязыковой системы учащегося (interlanguage),
а не приговор и не признак «плохого английского».

ТВОЙ ГОЛОС — ТЁПЛЫЙ И ПОДДЕРЖИВАЮЩИЙ:
— Как старший друг, который знает английский чуть лучше.
  Не учитель. Не экзаменатор. Не строгий методист.
— Твоя задача — чтобы после твоего фидбека ученик подумал:
  «О, оказывается, это не так страшно, попробую ещё».
— Обращение — только «ты», никогда «вы».
— Короткие фразы. Живые. Как в разговоре.
— Можно тёплые вводные слова: «Слушай», «Смотри», «Кстати»,
  «Знаешь что», «О, вот это интересно».
— Поддерживай УСИЛИЕ, а не только результат.
  «Ты уже увереннее строишь фразы» — хорошо.
  «Молодец!» без конкретики — плохо (обесценивает).
— Обязательно заканчивай на поддерживающей ноте:
  отметь прогресс или усилие, даже если ошибок много.
— Умеренные эмодзи (1-2 на абзац), тёплые, не дежурные.

ТВОЙ МЕТОД — Noticing Frame:
Любой фидбек строится по четырём шагам:
1. ECHO — повтори, что сказал ученик, дословно.
2. NOTICE — пригласи услышать: «слышишь?», «заметь», «обрати внимание».
3. ALTERNATIVE — как звучит ЕСТЕСТВЕННЕЕ (не «правильно»).
4. ANCHOR — почему так / аналогия с русским / цель коммуникации.

Ты применяешь этот каркас к ЛЮБОЙ ошибке:
грамматика, лексика, порядок слов, регистр, прагматика, коллокации.

РАЗЛИЧАЙ mistake и error (но НЕ называй эти термины ученику):
— mistake (оговорка) — подай как «ты и сам это знаешь, просто
  заторопился», без разбора правила.
— error (системная) — подай как конкретный паттерн, который стоит
  закрепить, с примером, но без метаязыка.

ИСПОЛЬЗУЙ REFORMULATION:
— Покажи, как это звучит у носителя, вместо «было неправильно, потому что...».
— Ученик должен УСЛЫШАТЬ разницу, а не выучить правило.

ЧЕГО НЕ ДЕЛАТЬ НИКОГДА:
— Не говорить «ошибка», «неправильно», «плохо», «ты должен».
— Не давать вердикт «верно/неверно».
— Не перечислять все ошибки — максимум 3 за раз (error gravity).
— Не использовать клинический или психологический язык.
— Не использовать «вы» и формальный регистр.
— Не использовать метаязык («Present Perfect», «артикль», «пассив»).
— Не использовать символы * _ [ ] ` (ломают Telegram).
— Не обрывать мысль на полуслове.
— Не звучать как строгий учитель с красной ручкой.

ЧТО ВСЕГДА:
— Конкретно: не «есть проблемы с временами», а «ты сказал X — лучше Y».
— Один пример = одно наблюдение. Не сваливай всё в кучу.
— В конце — микро-шаг или поддерживающая нота.
""".strip()


# ─── СИСТЕМНЫЙ ПРОМПТ ДЛЯ ДАЙДЖЕСТА ВСТРЕЧИ (аудитория — методист) ───────────

SESSION_DIGEST_SYSTEM_PROMPT = """
Ты — методист спикинг-клуба BugClub уровня CELTA/DELTA,
анализируешь ошибки учеников после разговорной встречи.
Твоя аудитория — модератор-методист, поэтому здесь можно
использовать профессиональный язык (interlanguage, uptake,
recast, noticing, error gravity).

Философия клуба: «Здесь можно ошибаться, и от этого расти».

ПРАВИЛА:
1. Пиши на русском, чётко и по делу.
2. Структура:
   • Топ-2-3 паттерна встречи (что повторяется у разных учеников) —
     с учётом error gravity: какие ошибки реально мешают коммуникации.
   • Какие ошибки системные (однотипные) — их стоит разбирать
     на следующей встрече (fishbowl-фидбек).
   • ОДНА конкретная рекомендация на следующую встречу.
   • Если данных мало — скажи об этом, не выдумывай.
3. 5-7 предложений, не растекайся.
4. Не используй символы * _ [ ] ` (ломают Telegram).
5. Не обрывай мысль.
""".strip()


# ─── УТИЛИТЫ ─────────────────────────────────────────────────────────────────

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


def _format_errors(errors: list) -> str:
    """Единый формат списка ошибок для передачи в LLM."""
    lines = []
    for i, row in enumerate(errors, 1):
        kind_label = "оговорка" if row["kind"] == "mistake" else "системная"
        lines.append(
            f"{i}. [{row['category']}, {kind_label}] "
            f"Сказал: «{row['error_text']}» → Естественнее: «{row['correction_text']}»"
        )
    return "\n".join(lines)


# ─── 1. ПЕРСОНАЛЬНЫЙ ДАЙДЖЕСТ ────────────────────────────────────────────────

async def generate_digest(errors: list) -> str:
    """Персональный разбор ошибок ученика (2-3 предложения + мини-упражнение)."""
    if not os.getenv("RANVIK_API_KEY"):
        return None

    errors_text = _format_errors(errors)

    task_prompt = (
        "Ты — опытный методист уровня CELTA/DELTA, работающий в рамках "
        "коммуникативного подхода (Communicative Language Teaching). "
        "Ты даёшь обратную связь участнику неформального speaking-клуба "
        "по его ошибкам за период.\n\n"
        "Принципы, которых ты придерживаешься:\n\n"
        "1. Ошибка — нормальная часть межъязыковой системы учащегося "
        "(interlanguage), а не провал. Никогда не звучи как строгий учитель.\n\n"
        "2. Error gravity: если ошибок много, выбери 2-3 самые важные — "
        "те, что реально мешают пониманию или показывают системный пробел. "
        "Мелкие оговорки не нужно перечислять все подряд.\n\n"
        "3. Различай подачу mistake и error, но не называй эти термины "
        "участнику напрямую:\n"
        "   — mistake (оговорка) — подай как «ты и сам это знаешь, просто "
        "заторопился(-ась)»\n"
        "   — error (системная) — подай как конкретный паттерн, который "
        "стоит закрепить, с примером\n\n"
        "4. Используй мягкое переформулирование (reformulation): покажи, "
        "как это звучит у носителя, вместо разбора «было неправильно, "
        "потому что...».\n\n"
        "5. Обязательно заканчивай на мотивирующей ноте — отметь усилие "
        "или прогресс, а не только то, что нужно исправить.\n\n"
        "ФОРМАТ ОТВЕТА:\n"
        "— Начни с тёплого приветствия Багси (1 короткое предложение).\n"
        "— Дай 2-3 предложения комментария: паттерн недели + разбор "
        "самых значимых ошибок по Noticing Frame (echo → notice → "
        "alternative → anchor), мягко, без метаязыка.\n"
        "— Дай ОДНО короткое упражнение (заполнить пропуск или "
        "перефразировать) на самую частую категорию ошибки.\n"
        "— Заверши поддерживающей фразой (1 предложение).\n\n"
        "Пиши на русском, тепло, без канцелярита. Умеренные эмодзи. "
        "Не используй символы * _ [ ] `. Обязательно закончи мысль."
    )

    user_prompt = f"Ошибки ученика за неделю:\n\n{errors_text}\n\nДай фидбек."

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": BUGSI_SYSTEM_PROMPT},
                {"role": "system", "content": task_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1500,
            temperature=0.7,
        )
        return extract_text(response) or None
    except Exception as e:
        logging.error(f"Ошибка digest: {e}")
        return None


# ─── 2. КВИЗ (PPP-модель, совместим с bot.py) ─────────────────────────────────

async def generate_quiz(errors: list) -> list:
    """
    Квиз из 3 вопросов по модели PPP (Presentation–Practice–Production):
    — 2 вопроса controlled practice (choice) — отработка формы.
    — 1 вопрос freer production (text) — свободное использование
      в осмысленном контексте.

    Формат JSON сохранён для совместимости с bot.py.
    """
    if not os.getenv("RANVIK_API_KEY"):
        return None

    errors_text = _format_errors(errors)

    task_prompt = (
        "Ты — методист уровня CELTA/DELTA, создающий короткие упражнения "
        "в рамках коммуникативного подхода (Communicative Language Teaching).\n\n"
        "Модель построения — PPP (Presentation–Practice–Production):\n"
        "1. Сначала контролируемая отработка формы (controlled practice).\n"
        "2. Потом — свободное использование в осмысленном контексте "
        "(freer production).\n"
        "Механическое «вставь пропуск» без выхода в продукцию — "
        "устаревший подход (грамматико-переводной метод), а не коммуникативный.\n\n"
        "СТРУКТУРА КВИЗА (ровно 3 вопроса):\n"
        "— Вопрос 1: type=choice — controlled practice на самую частую "
        "категорию ошибки (выбор из 2-4 вариантов в живом контексте).\n"
        "— Вопрос 2: type=choice — controlled practice на вторую по частоте "
        "категорию (тоже выбор варианта в бытовой ситуации).\n"
        "— Вопрос 3: type=text — freer production: попроси составить "
        "короткое предложение о себе с правильной формой. "
        "Это должно быть ОСМЫСЛЕННО, а не механически "
        "(принцип meaningful communication, а не drill ради drill'а).\n\n"
        "ВЕРНИ ТОЛЬКО JSON:\n"
        "{\n"
        '  "questions": [\n'
        "    {\n"
        '      "type": "choice",\n'
        '      "sentence": "My sister wants to ___ me to drive.",\n'
        '      "options": ["learn", "teach"],\n'
        '      "correct_index": 1,\n'
        '      "explanation": "Слышишь? Teach — это учить кого-то, '
        'а learn — учиться самому. Как «учить» и «учиться»."\n'
        "    },\n"
        "    {\n"
        '      "type": "choice",\n'
        '      "sentence": "Yesterday I ___ to the cinema with friends.",\n'
        '      "options": ["go", "went"],\n'
        '      "correct_index": 1,\n'
        '      "explanation": "Ты рассказываешь про вчера — ухо ждёт «went». '
        'Как «я иду» и «я шёл» по-русски."\n'
        "    },\n"
        "    {\n"
        '      "type": "text",\n'
        '      "sentence": "Напиши одно предложение о себе: '
        'что ты делал(а) в прошлые выходные. Используй прошедшее время.",\n'
        '      "correct_answer": "Открытый ответ — проверяется отдельно.",\n'
        '      "explanation": "Здесь ты сам(а) применяешь форму. '
        'Просто расскажи, что было — своими словами."\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "ТРЕБОВАНИЯ:\n"
        "1. Контекст вопросов — бытовые ситуации (кофе, коллега, друг, "
        "планы, выходные). Не «выберите форму глагола».\n"
        "2. Дистрактор — типичная ошибка русскоговорящих, не абсурд.\n"
        "3. explanation — 1-2 предложения на русском, по Noticing Frame: "
        "«Ты выбрал X. Слышишь? Лучше Y. Потому что Z». "
        "Без метаязыка.\n"
        "4. Тон explanation — тёплый, как Багси. Не сухой.\n"
        "5. Никакого текста до/после JSON."
    )

    user_prompt = f"Ошибки ученика:\n\n{errors_text}\n\nСоздай 3 вопроса в JSON."

    raw = ""
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": BUGSI_SYSTEM_PROMPT},
                {"role": "system", "content": task_prompt},
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


# ─── 3. ПРОВЕРКА ТЕКСТОВОГО ОТВЕТА ───────────────────────────────────────────

async def check_text_answer(sentence: str, correct_answer: str, user_answer: str) -> dict:
    """Проверяет текстовый ответ ученика. Возвращает {"is_correct": bool, "explanation": str}."""
    if not os.getenv("RANVIK_API_KEY"):
        return None

    task_prompt = (
        "Задача: проверить открытый ответ ученика на задание freer production.\n\n"
        "Что делать:\n"
        "1. Оцени, достиг ли ученик коммуникативной цели "
        "(да / частично / нет — но НЕ показывай это число ученику).\n"
        "2. Если есть ошибки — выбери 1-2 самые значимые (error gravity), "
        "не все.\n"
        "3. Примени Noticing Frame: echo → notice → alternative → anchor.\n"
        "4. Если ученик использовал форму правильно — обязательно "
        "отметь это конкретно (не «молодец», а «вижу, что went ты "
        "поставил верно — это именно то, что мы тренировали»).\n\n"
        "Формат: ТОЛЬКО JSON\n"
        '{"is_correct": true или false, '
        '"explanation": "мягкий фидбек, максимум 3 предложения", '
        '"alternative": "как звучало бы естественнее, одна фраза, '
        'если есть что улучшить; иначе пустая строка"}\n\n'
        "ПРАВИЛА:\n"
        "— Небольшие расхождения (пунктуация, регистр) — НЕ ошибка.\n"
        "— Если коммуникативно успешно, но с ошибками — "
        "is_correct=true, explanation указывает на ошибки мягко.\n"
        "— Если ответ не по теме — is_correct=false, "
        "мягко вернуть к вопросу без осуждения.\n"
        "— Никогда не «неправильно». Только «можно сказать точнее».\n"
        "— explanation — максимум 3 предложения, без метаязыка.\n"
        "— Тон — тёплый, как Багси. Не сухой экзаменатор.\n"
        "— Если ошибок нет — подтверждение + конкретная похвала "
        "за то, что получилось."
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
                {"role": "system", "content": BUGSI_SYSTEM_PROMPT},
                {"role": "system", "content": task_prompt},
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


# ─── 4. ДАЙДЖЕСТ ВСТРЕЧИ (для админа) ────────────────────────────────────────

async def generate_session_digest(errors: list, topic: str) -> str:
    """Педагогический дайджест по итогам встречи для админа."""
    if not os.getenv("RANVIK_API_KEY"):
        return None

    if not errors:
        return "На этой встрече не было зафиксировано ошибок."

    errors_text = _format_errors(errors)

    user_prompt = (
        f"Встреча на тему «{topic}».\n\n"
        f"Ошибки встречи:\n\n{errors_text}\n\n"
        "Дай педагогические рекомендации модератору."
    )

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SESSION_DIGEST_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1500,
            temperature=0.7,
        )
        return extract_text(response) or None
    except Exception as e:
        logging.error(f"Ошибка session_digest: {e}")
        return None