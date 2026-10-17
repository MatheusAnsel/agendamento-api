"""Cria um negocio de demonstracao (esmalteria) usando a propria API.

Uso, com a API rodando em http://localhost:8000 e o banco configurado no .env:

    python examples/seed_demo.py

Recria o negocio 'demo-esmalteria' a cada execucao e imprime a chave de API e o login.
"""

import json
import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.cli import create_tenant
from app.core.config import get_settings
from app.models import Booking, Tenant

API = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
SITE_ORIGIN = "http://localhost:5500"
SLUG = "demo-esmalteria"
EMAIL, PASSWORD = "dona@bella.com", "senha-demo-123"
TZ = ZoneInfo("America/Sao_Paulo")


def main() -> None:
    engine = create_engine(get_settings().database_url)
    with Session(engine, expire_on_commit=False) as s:
        old = s.query(Tenant).filter(Tenant.slug == SLUG).one_or_none()
        if old:
            s.execute(delete(Booking).where(Booking.tenant_id == old.id))
            s.execute(delete(Tenant).where(Tenant.id == old.id))
        _, api_key = create_tenant(
            s,
            name="Esmalteria Bella",
            slug=SLUG,
            owner_email=EMAIL,
            owner_password=PASSWORD,
            origins=[SITE_ORIGIN],
            resource_name="Ana",
        )
        s.commit()

    client = httpx.Client(base_url=API, timeout=20)
    token = client.post(
        "/v1/admin/login", json={"tenant_slug": SLUG, "email": EMAIL, "password": PASSWORD}
    ).json()["access_token"]
    admin = {"Authorization": f"Bearer {token}"}
    public = {"X-API-Key": api_key, "Origin": SITE_ORIGIN}

    def post(path, body, headers=admin):
        response = client.post(path, json=body, headers=headers)
        response.raise_for_status()
        return response.json()

    client.patch(
        "/v1/admin/settings",
        headers=admin,
        json={
            "min_notice_minutes": 60,
            "form_config": {
                "required_fields": ["name", "phone", "consent_lgpd"],
                "optional_fields": ["email", "notes"],
                "custom_fields": [
                    {
                        "key": "primeira_vez",
                        "label": "É a sua primeira vez aqui?",
                        "type": "select",
                        "options": ["Sim", "Não"],
                    }
                ],
            },
        },
    ).raise_for_status()

    ana = client.get("/v1/admin/resources", headers=admin).json()[0]
    bia = post("/v1/admin/resources", {"name": "Bia"})
    services = {
        "gel": post(
            "/v1/admin/services",
            {
                "name": "Esmaltação em gel",
                "duration_minutes": 60,
                "buffer_minutes": 10,
                "price_cents": 9000,
                "resource_ids": [ana["id"], bia["id"]],
            },
        ),
        "manicure": post(
            "/v1/admin/services",
            {
                "name": "Manicure",
                "duration_minutes": 40,
                "price_cents": 3500,
                "resource_ids": [ana["id"], bia["id"]],
            },
        ),
        "pedicure": post(
            "/v1/admin/services",
            {
                "name": "Pedicure",
                "duration_minutes": 50,
                "price_cents": 4500,
                "slot_interval_minutes": 30,
                "resource_ids": [bia["id"]],
            },
        ),
    }

    def rules(days, windows):
        return [{"weekday": d, "start_time": a, "end_time": b} for d in days for a, b in windows]

    client.put(
        f"/v1/admin/resources/{ana['id']}/weekly-rules",
        headers=admin,
        json={"rules": rules(range(1, 6), [("09:00:00", "12:00:00"), ("13:00:00", "18:00:00")])},
    ).raise_for_status()
    client.put(
        f"/v1/admin/resources/{bia['id']}/weekly-rules",
        headers=admin,
        json={"rules": rules(range(0, 5), [("10:00:00", "19:00:00")])},
    ).raise_for_status()

    today = datetime.now(TZ).date()
    holiday = today + timedelta(days=9)
    post(
        "/v1/admin/date-exceptions",
        {"date": holiday.isoformat(), "kind": "closed", "reason": "Feriado"},
    )

    def next_weekday(day: date, weekday: int) -> date:
        return day + timedelta(days=(weekday - day.weekday()) % 7 or 7)

    def at(day: date, hour: int, minute: int = 0) -> str:
        return datetime.combine(day, time(hour, minute), tzinfo=TZ).isoformat()

    tuesday, wednesday = next_weekday(today, 1), next_weekday(today, 2)
    post(
        "/v1/admin/blocks",
        {
            "start_at": at(wednesday, 15),
            "end_at": at(wednesday, 16),
            "resource_id": ana["id"],
            "reason": "Dentista",
        },
    )
    samples = [
        ("Camila Rocha", "21 98877-1001", "gel", tuesday, 9),
        ("Fernanda Lima", "21 98877-1002", "manicure", tuesday, 10),
        ("Juliana Costa", "21 98877-1003", "gel", wednesday, 10),
        ("Patricia Alves", "21 98877-1004", "pedicure", wednesday, 14),
    ]
    for name, phone, key, day, hour in samples:
        post(
            "/v1/bookings",
            {
                "service_id": services[key]["id"],
                "start_at": at(day, hour),
                "customer": {"name": name, "phone": phone},
                "consent_lgpd": True,
                "custom": {"primeira_vez": "Não"},
            },
            headers=public,
        )

    print(
        json.dumps(
            {
                "api_url": API,
                "api_key": api_key,
                "login": EMAIL,
                "senha": PASSWORD,
                "slug": SLUG,
                "origin": SITE_ORIGIN,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
