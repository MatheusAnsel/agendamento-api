from fastapi import APIRouter

from app.routers.admin import auth, bookings, catalog, schedule, settings

router = APIRouter()
router.include_router(auth.router)
router.include_router(settings.router)
router.include_router(catalog.router)
router.include_router(schedule.router)
router.include_router(bookings.router)
