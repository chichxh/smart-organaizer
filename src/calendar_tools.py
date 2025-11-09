import json
from typing import List, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain.tools import tool

from .config import DEFAULT_TZ, DEFAULT_CALENDAR
from .date_utils import (
    now_in_tz, _parse_date_any, _parse_local_dt, _work_hours_to_range,
    _find_free_slot, _to_rfc3339
)
from .calendar_api import get_calendar_service, _get_events_between, _event_time_range


@tool
def get_today(tz: str = DEFAULT_TZ) -> str:
    """
    Возвращает фразу вида: 'Сегодня среда, 08.10.2025' + служебные значения.
    """
    from .config import WEEKDAYS_RU
    
    now = now_in_tz(tz)
    dayname = WEEKDAYS_RU[now.weekday()]
    human = now.strftime("%d.%m.%Y")
    iso = now.strftime("%Y-%m-%d")
    return f"Сегодня {dayname}, {human} (ISO: {iso}, TZ: {tz})"


@tool
def list_agenda(date_str: str, calendar_id: str = DEFAULT_CALENDAR, timezone: str = DEFAULT_TZ) -> str:
    """
    Возвращает повестку дня на дату (формат 'YYYY-MM-DD').
    """
    try:
        service = get_calendar_service()
        d = _parse_date_any(date_str, timezone)
        day_start = datetime(d.year, d.month, d.day, 0, 0, tzinfo=ZoneInfo(timezone))
        day_end = day_start + timedelta(days=1)
        items = _get_events_between(service, calendar_id, day_start, day_end)

        agenda = []
        for ev in items:
            s, e = _event_time_range(ev)
            s_local = s.astimezone(ZoneInfo(timezone))
            e_local = e.astimezone(ZoneInfo(timezone))
            agenda.append({
                "title": ev.get("summary", "(без названия)"),
                "start": s_local.strftime("%Y-%m-%d %H:%M"),
                "end": e_local.strftime("%Y-%m-%d %H:%M"),
                "location": ev.get("location", ""),
                "id": ev.get("id", "")
            })
        return json.dumps({"date": d.isoformat(), "events": agenda}, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Ошибка: {e}"


@tool
def add_simple_event(
    title: str,
    start: str,
    end: str,
    timezone: str = DEFAULT_TZ,
    location: str = "",
    description: str = "",
    calendar_id: str = DEFAULT_CALENDAR
) -> str:
    """
    Создаёт событие в календаре.
    """
    try:
        service = get_calendar_service()
        start_dt = _parse_local_dt(start, timezone)
        end_dt = _parse_local_dt(end, timezone)
        if end_dt <= start_dt:
            return "Конец события должен быть позже начала."

        body = {
            "summary": title,
            "location": location or None,
            "description": description or None,
            "start": {"dateTime": _to_rfc3339(start_dt)},
            "end": {"dateTime": _to_rfc3339(end_dt)},
        }
        ev = service.events().insert(calendarId=calendar_id, body=body).execute()
        s_local = start_dt.strftime("%Y-%m-%d %H:%M")
        e_local = end_dt.strftime("%Y-%m-%d %H:%M")
        return f"Создано событие «{title}» {s_local}–{e_local}. ID: {ev.get('id')}"
    except Exception as e:
        return f"Ошибка: {e}"


@tool
def find_and_block_free_slot(
    title: str,
    duration_minutes: int,
    date_str: str = "",
    work_hours: str = "09:00-18:00",
    timezone: str = DEFAULT_TZ,
    calendar_id: str = DEFAULT_CALENDAR
) -> str:
    """
    Находит первое свободное окно заданной длительности в указанный день и создаёт событие.
    Если date_str пуст, берётся сегодняшняя дата (локальная для timezone).
    """
    try:
        service = get_calendar_service()
        local_tz = ZoneInfo(timezone)
        day = _parse_date_any(date_str, timezone) if date_str else now_in_tz(timezone).date()
        window_start, window_end = _work_hours_to_range(day, work_hours, timezone)

        events = _get_events_between(service, calendar_id, window_start, window_end)
        busy: List[Tuple[datetime, datetime]] = []
        for ev in events:
            s, e = _event_time_range(ev)
            s = max(s, window_start)
            e = min(e, window_end)
            if e > s:
                busy.append((s, e))
        busy.sort(key=lambda x: x[0])

        slot = _find_free_slot(busy, window_start, window_end, timedelta(minutes=duration_minutes))
        if not slot:
            # Предложить 3 ближайшие альтернативы после рабочего окна (шаг 30 мин)
            suggestions = []
            cursor = window_end
            step = timedelta(minutes=30)
            tries = 0
            while len(suggestions) < 3 and tries < 40:
                s = cursor
                e = s + timedelta(minutes=duration_minutes)
                future_events = _get_events_between(service, calendar_id, s, e)
                if not future_events:
                    suggestions.append((s.astimezone(local_tz), e.astimezone(local_tz)))
                    cursor = e
                else:
                    cursor += step
                tries += 1
            human = "\n".join([f"- {s.strftime('%Y-%m-%d %H:%M')}–{e.strftime('%H:%M')}" for s, e in suggestions]) or "Нет быстрых альтернатив."
            return f"Свободного окна на {day.isoformat()} нет в пределах {work_hours}. Возможные альтернативы:\n{human}"

        slot_start, slot_end = slot
        body = {
            "summary": title,
            "start": {"dateTime": _to_rfc3339(slot_start.astimezone(local_tz))},
            "end": {"dateTime": _to_rfc3339(slot_end.astimezone(local_tz))},
            "description": f"Создано смарт-органайзером. Длительность: {duration_minutes} мин."
        }
        ev = service.events().insert(calendarId=calendar_id, body=body).execute()
        return (
            f"Забронировано окно «{title}»: "
            f"{slot_start.astimezone(local_tz).strftime('%Y-%m-%d %H:%M')}–"
            f"{slot_end.astimezone(local_tz).strftime('%H:%M')}. ID: {ev.get('id')}"
        )
    except Exception as e:
        return f"Ошибка: {e}"


@tool
def plan_focus_blocks(
    date_str: str,
    total_minutes: int = 120,
    block_len: int = 50,
    break_len: int = 10,
    work_hours: str = "09:00-18:00",
    timezone: str = DEFAULT_TZ,
    title_prefix: str = "FOCUS",
    calendar_id: str = DEFAULT_CALENDAR
) -> str:
    """
    Раскладывает по дню серию фокус-блоков (block_len работа + break_len пауза, кроме последнего),
    избегая пересечений с событиями. Создаёт события в календаре.
    """
    try:
        if block_len <= 0 or total_minutes <= 0:
            return "block_len и total_minutes должны быть > 0."

        service = get_calendar_service()
        day = _parse_date_any(date_str, timezone)
        local_tz = ZoneInfo(timezone)
        window_start, window_end = _work_hours_to_range(day, work_hours, timezone)

        events = _get_events_between(service, calendar_id, window_start, window_end)
        busy: List[Tuple[datetime, datetime]] = []
        for ev in events:
            s, e = _event_time_range(ev)
            s = max(s, window_start)
            e = min(e, window_end)
            if e > s:
                busy.append((s, e))
        busy.sort(key=lambda x: x[0])

        created = []
        minutes_left = total_minutes
        cursor = window_start
        while minutes_left > 0 and cursor < window_end:
            # перескочим занятость при конфликте
            conflict = False
            for b_start, b_end in busy:
                if cursor < b_end and (cursor + timedelta(minutes=block_len)) > b_start:
                    cursor = b_end
                    conflict = True
                    break
            if conflict:
                continue

            if cursor + timedelta(minutes=block_len) > window_end:
                break

            start_dt = cursor.astimezone(local_tz)
            end_dt = (cursor + timedelta(minutes=block_len)).astimezone(local_tz)
            title = f"{title_prefix}: глубокая работа"
            body = {
                "summary": title,
                "start": {"dateTime": _to_rfc3339(start_dt)},
                "end": {"dateTime": _to_rfc3339(end_dt)},
                "description": f"Фокус-блок {block_len} мин. Создано смарт-органайзером."
            }
            ev = service.events().insert(calendarId=calendar_id, body=body).execute()
            created.append({
                "id": ev.get("id"),
                "start": start_dt.strftime("%Y-%m-%d %H:%M"),
                "end": end_dt.strftime("%H:%M")
            })

            minutes_left -= block_len
            cursor = cursor + timedelta(minutes=block_len + (break_len if minutes_left > 0 else 0))

        if not created:
            return f"Не удалось разместить фокус-блоки {total_minutes} мин в пределах {work_hours} {day.isoformat()}."
        return json.dumps({"created_blocks": created}, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Ошибка: {e}"


# Список всех инструментов для экспорта
TOOLS = [get_today, list_agenda, add_simple_event, find_and_block_free_slot, plan_focus_blocks]
