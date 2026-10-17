"""Importa todos os modelos para que o Alembic os enxergue em Base.metadata."""

from app.models.availability import Block, DateException, WeeklyRule
from app.models.booking import Booking, Customer
from app.models.catalog import Resource, Service, service_resources
from app.models.tenant import AdminUser, ApiKey, Tenant

__all__ = [
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
