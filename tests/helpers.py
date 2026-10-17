from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

SITE = "https://site.com.br"
PASSWORD = "senha-do-dono-123"


def headers(env, **extra):
    return {"X-API-Key": env["key"], **extra}


def future_day(days=3) -> date:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date() + timedelta(days=days)
