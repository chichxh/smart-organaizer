import os
from typing import List, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from .config import SCOPES, CREDENTIALS_FILE, TOKEN_FILE
from .date_utils import _to_rfc3339, _find_free_slot


def get_calendar_service():
    """
    Получение авторизованного сервиса Google Calendar.
    При первом запуске открывает браузер для авторизации.
    """
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def _get_events_between(service, calendar_id: str, start: datetime, end: datetime) -> List[dict]:
    """
    Получение событий из календаря за указанный период.
    """
    events: List[dict] = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=calendar_id,
            timeMin=_to_rfc3339(start),
            timeMax=_to_rfc3339(end),
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token,
        ).execute()
        events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return events


def _event_time_range(ev: dict) -> Tuple[datetime, datetime]:
    """
    Извлекает время начала и окончания события из объекта Google Calendar.
    Возвращает (start_dt, end_dt) как aware datetime.
    """
    from dateutil import parser as dtparser
    
    def parse_field(obj, key):
        if "dateTime" in obj[key]:
            return dtparser.isoparse(obj[key]["dateTime"])
        # события "на весь день" (date без времени)
        d = dtparser.isoparse(obj[key]["date"]).date()
        z = ZoneInfo("UTC")
        if key == "start":
            return datetime(d.year, d.month, d.day, 0, 0, tzinfo=z)
        d2 = d + timedelta(days=1)
        return datetime(d2.year, d2.month, d2.day, 0, 0, tzinfo=z)

    start = parse_field(ev, "start")
    end = parse_field(ev, "end")
    return start, end
