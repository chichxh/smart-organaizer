import re
from typing import Optional, Tuple
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from dateutil import parser as dtparser

from .config import DEFAULT_TZ, RU_MONTHS


def now_in_tz(tz: str = DEFAULT_TZ) -> datetime:
    """Получить текущее время в указанной временной зоне"""
    return datetime.now(ZoneInfo(tz))


def _to_rfc3339(dt: datetime) -> str:
    """Преобразовать datetime в RFC3339 формат для Google Calendar API"""
    if dt.tzinfo is None:
        raise ValueError("datetime должен быть 'aware' (с таймзоной)")
    return dt.isoformat()


def _parse_date_any(d: str, tz: str = DEFAULT_TZ) -> date:
    """
    Универсальный парсер дат: принимает ISO/русские форматы, дополняет текущим годом.
    Поддерживает форматы: YYYY-MM-DD, DD.MM, DD-MM, "13 октября", "8 окт"
    """
    d = d.strip().lower()
    
    # ISO YYYY-MM-DD
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        return datetime.fromisoformat(d).date()
    
    # DD.MM или DD-MM
    if re.fullmatch(r"\d{1,2}[.\-]\d{1,2}", d):
        dd, mm = re.split(r"[.\-]", d)
        y = now_in_tz(tz).year
        return date(y, int(mm), int(dd))
    
    # «13 октября», «8 окт»
    m = re.match(r"(\d{1,2})\s+([а-яё]+)$", d)
    if m:
        day = int(m.group(1))
        mon_word = m.group(2)
        # сопоставим по префиксу 3 буквы
        for full, num in RU_MONTHS.items():
            if mon_word.startswith(full[:3]):
                y = now_in_tz(tz).year
                return date(y, num, day)
    
    # Падаем на dateutil как на универсальный fallback
    return dtparser.parse(d).date()


def _parse_local_dt(s: str, tz: str) -> datetime:
    """
    Принимает 'YYYY-MM-DD HH:MM' или ISO и возвращает aware datetime в зоне tz.
    """
    z = ZoneInfo(tz)
    dt = dtparser.parse(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=z)
    return dt.astimezone(z)


def _work_hours_to_range(day: date, work_hours: str, tz: str) -> Tuple[datetime, datetime]:
    """
    Преобразует строку рабочих часов '09:00-18:00' в диапазон datetime для указанного дня.
    """
    start_str, end_str = work_hours.split("-")
    z = ZoneInfo(tz)
    day_start = datetime.combine(day, dtparser.parse(start_str).time()).replace(tzinfo=z)
    day_end = datetime.combine(day, dtparser.parse(end_str).time()).replace(tzinfo=z)
    if day_end <= day_start:
        raise ValueError("Конец рабочего дня должен быть позже начала.")
    return day_start, day_end


def _parse_relative_date_word(word: str, tz: str = DEFAULT_TZ) -> Optional[date]:
    """Парсинг относительных дат: сегодня, завтра, послезавтра"""
    today = now_in_tz(tz).date()
    if word == "сегодня":
        return today
    if word == "завтра":
        return today + timedelta(days=1)
    if word == "послезавтра":
        return today + timedelta(days=2)
    return None


def _parse_weekday(text: str, tz: str = DEFAULT_TZ) -> Optional[date]:
    """
    Обрабатывает дни недели: 'суббота', 'воскресенье', 'понедельник' и т.д.
    Возвращает ближайший день недели от текущей даты.
    """
    text = text.strip().lower()
    today = now_in_tz(tz).date()
    current_weekday = today.weekday()  # 0=понедельник, 6=воскресенье
    
    # Словарь дней недели (0=понедельник, 6=воскресенье)
    weekdays = {
        "понедельник": 0, "вторник": 1, "среда": 2, "четверг": 3,
        "пятница": 4, "суббота": 5, "воскресенье": 6
    }
    
    # Ищем дни недели в тексте, включая фразы типа "в эту субботу", "на субботу"
    for day_name, day_num in weekdays.items():
        # Проверяем различные варианты: "суббота", "в субботу", "на субботу", "в эту субботу"
        patterns = [
            f"{day_name}",  # просто "суббота"
            f"в\\s+{day_name}",  # "в субботу"
            f"на\\s+{day_name}",  # "на субботу"
            f"в\\s+эту\\s+{day_name}",  # "в эту субботу"
            f"эту\\s+{day_name}",  # "эту субботу"
        ]
        
        for pattern in patterns:
            if re.search(pattern, text):
                days_ahead = day_num - current_weekday
                if days_ahead <= 0:  # Если день уже прошел на этой неделе
                    days_ahead += 7  # Берем следующий раз
                return today + timedelta(days=days_ahead)
    
    return None


def _parse_russian_date(text: str, tz: str = DEFAULT_TZ) -> Optional[date]:
    """Парсинг русских дат в различных форматах"""
    text = text.strip().lower()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.fromisoformat(text).date()
        if re.fullmatch(r"\d{1,2}[.\-]\d{1,2}", text):
            d, m = re.split(r"[.\-]", text)
            y = now_in_tz(tz).year
            return date(y, int(m), int(d))
    except Exception:
        pass
    
    m = re.match(r"(\d{1,2})\s+([а-яё]+)$", text)
    if m:
        d = int(m.group(1))
        mon_word = m.group(2)
        for full, num in RU_MONTHS.items():
            if mon_word.startswith(full[:3]):
                y = now_in_tz(tz).year
                return date(y, num, d)
    return None


def _parse_time_pair(text: str) -> Optional[Tuple[str, str]]:
    """
    Парсинг временных интервалов: 'с 9 до 12:20', '9-12', '9:00–12:20', '15 до 18'
    Возвращает ('HH:MM','HH:MM')
    """
    t = text.replace("—", "-").replace("–", "-")
    patterns = [
        r"с\s*(\d{1,2}(:\d{2})?)\s*до\s*(\d{1,2}(:\d{2})?)",
        r"(\d{1,2}(:\d{2})?)\s*-\s*(\d{1,2}(:\d{2})?)"
    ]
    
    for p in patterns:
        m = re.search(p, t)
        if m:
            s, e = m.group(1), m.group(3)
            def norm(hhmm: str) -> str:
                if ":" not in hhmm:
                    return f"{int(hhmm):02d}:00"
                h, m = hhmm.split(":")
                return f"{int(h):02d}:{int(m):02d}"
            return norm(s), norm(e)
    return None


def _find_free_slot(
    busy: list[Tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
) -> Optional[Tuple[datetime, datetime]]:
    """
    Находит первое свободное окно заданной длительности в указанном временном диапазоне.
    """
    cursor = window_start
    for b_start, b_end in busy:
        if b_end <= cursor:
            continue
        if b_start - cursor >= duration:
            return cursor, cursor + duration
        cursor = max(cursor, b_end)
        if cursor >= window_end:
            break
    if window_end - cursor >= duration:
        return cursor, cursor + duration
    return None
