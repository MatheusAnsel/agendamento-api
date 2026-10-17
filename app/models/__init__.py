"""Importa todos os modelos para que o Alembic os enxergue em Base.metadata."""

from app.models.availability import Block, DateException, WeeklyRule
from app.models.booking import BOOKING_STATUSES, Booking, Customer
from app.models.catalog import Resource, Service, service_resources
from app.models.tenant import AdminUser, ApiKey, Tenant

__all__ = [
    "BOOKING_STATUSES",
    "AdminUser",
    "ApiKey",
    "Block",
    "Booking",
    "Customer",
    "DateException",
    "Resource",
    "Service",
    "Tenant",
    "WeeklyRule",
    "service_resources",
]
