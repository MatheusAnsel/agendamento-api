from fastapi import APIRouter

from app.routers.public import availability, catalog

router = APIRouter()
router.include_router(catalog.router)
router.include_router(availability.router)
