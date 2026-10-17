from fastapi import APIRouter

from app.routers.admin import auth

router = APIRouter()
router.include_router(auth.router)
