import re
from typing import Optional, Tuple
from datetime import date

from .date_utils import _parse_relative_date_word, _parse_weekday, _parse_russian_date, _parse_time_pair, DEFAULT_TZ


def _normalize_text(t: str) -> str:
    """
    Нормализация пользовательского ввода:
    - Приведение к нижнему регистру
    - Исправление времени "15 00" -> "15:00"
    """
    t = t.lower().strip()
    # «15 00» -> «15:00»
    t = re.sub(r"\b(\d{1,2})\s+(\d{2})\b", r"\1:\2", t)
    return t


def _extract_title(text: str) -> str:
    """
    Извлекает название события из текста, удаляя служебные слова и даты/время.
    """
    t = _normalize_text(text)
    # убрать служебные конструкции
    t = re.sub(r"\b(создай|добавь|добавить|событие)\b", " ", t)
    t = re.sub(r"\b(сегодня|завтра|послезавтра)\b", " ", t)
    t = re.sub(r"\b(с|до)\b", " ", t)
    # убрать даты/время
    t = re.sub(r"\d{4}-\d{2}-\d{2}", " ", t)
    t = re.sub(r"\b\d{1,2}[.\-]\d{1,2}\b", " ", t)
    t = re.sub(r"\b\d{1,2}\s+[а-яё]+", " ", t)  # 13 октября
    t = re.sub(r"\d{1,2}(:\d{2})?\s*[-]\s*\d{1,2}(:\d{2})?", " ", t)
    t = re.sub(r"с\s*\d{1,2}(:\d{2})?\s*до\s*\d{1,2}(:\d{2})?", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .,:;")
    return t if t else "Событие"


def _sanitize_llm(text: str) -> str:
    """
    Очищает ответ LLM от служебных символов и лишних переносов строк.
    """
    text = re.sub(r"\{\{.*?\}\}", "", text)          # вырезаем шаблоны {{ ... }}
    text = re.sub(r"```.*?```", "", text, flags=re.S)  # вырезаем кодовые блоки
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def try_handle_create_event_locally(user_text: str) -> Optional[str]:
    """
    Локальная обработка команд создания событий.
    Понимает: «создай/добавь ... сегодня/завтра/13 октября/суббота ... с 9 до 12:20 ...»
    и сразу вызывает add_simple_event без обращения к LLM.
    """
    from .config import DEFAULT_TZ, DEFAULT_CALENDAR
    
    t = _normalize_text(user_text)
    if not re.search(r"\b(создай|добавь|добавить)\b", t):
        return None

    # дата: относительная или русская/iso
    the_day: Optional[date] = None
    
    # Сначала проверяем относительные даты (сегодня, завтра, послезавтра)
    for kw in ("сегодня", "завтра", "послезавтра"):
        if kw in t:
            the_day = _parse_relative_date_word(kw, DEFAULT_TZ)
            break
    
    # Если не нашли, проверяем дни недели (суббота, воскресенье и т.д.)
    if the_day is None:
        the_day = _parse_weekday(t, DEFAULT_TZ)
    
    # Если все еще не нашли, ищем конкретные даты
    if the_day is None:
        m_iso = re.search(r"\d{4}-\d{2}-\d{2}", t)
        m_dm = re.search(r"\b\d{1,2}[.\-]\d{1,2}\b", t)
        m_ru = re.search(r"\b\d{1,2}\s+[а-яё]+\b", t)
        if m_iso:
            the_day = _parse_russian_date(m_iso.group(0), DEFAULT_TZ)
        elif m_dm:
            the_day = _parse_russian_date(m_dm.group(0), DEFAULT_TZ)
        elif m_ru:
            the_day = _parse_russian_date(m_ru.group(0), DEFAULT_TZ)

    if the_day is None:
        return None  # отдаём LLM, раз сами не разобрали дату

    # время
    tp = _parse_time_pair(t)
    if not tp:
        return "Нужен интервал времени (например, «с 9 до 12:20»)."
    start_hhmm, end_hhmm = tp

    # заголовок
    title = _extract_title(t)
    start_str = f"{the_day.isoformat()} {start_hhmm}"
    end_str = f"{the_day.isoformat()} {end_hhmm}"

    # Импортируем инструмент здесь, чтобы избежать циклических импортов
    from .calendar_tools import add_simple_event
    
    # прямой вызов инструмента
    result = add_simple_event.invoke({
        "title": title,
        "start": start_str,
        "end": end_str,
        "timezone": DEFAULT_TZ,
        "calendar_id": DEFAULT_CALENDAR
    })
    return result


def handle_quick_responses(user_input: str) -> Optional[str]:
    """
    Обработка быстрых ответов без обращения к LLM.
    Например: "какой сегодня день", "какая сегодня дата"
    """
    from .config import WEEKDAYS_RU
    from .date_utils import now_in_tz, DEFAULT_TZ
    
    tnorm = _normalize_text(user_input)
    
    # "какой сегодня день"
    if re.search(r"(какой|что)\s+сегодня\s+д(е|ё)н(ь)", tnorm):
        n = now_in_tz(DEFAULT_TZ)
        return f"Сегодня {WEEKDAYS_RU[n.weekday()]}, {n.strftime('%d.%m.%Y')}."
    
    # "какая сегодня дата"
    if re.search(r"(какая|какой)\s+сегодня\s+дата", tnorm) or tnorm == "дата":
        n = now_in_tz(DEFAULT_TZ)
        return f"Сегодня {n.strftime('%d.%m.%Y')}."
    
    return None
