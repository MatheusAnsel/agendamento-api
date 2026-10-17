from fastapi import APIRouter

from app.routers.public import availability, bookings, catalog

router = APIRouter()
router.include_router(catalog.router)
router.include_router(availability.router)
router.include_router(bookings.router)
