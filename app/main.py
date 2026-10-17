from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.errors import AppError
from app.routers import admin, public

app = FastAPI(
    title="Agendamento API",
    version="0.1.0",
    description="Backend de agendamento multi-tenant para landing pages e sites.",
)

# O CORS fica aberto de proposito: a chave de API vai no header e a lista de origens
# permitidas de cada negocio e verificada no servidor (app.deps.get_tenant).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router)
app.include_router(admin.router)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.message, "code": exc.code}
    )


@app.get("/health", tags=["infra"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
