from fastapi import FastAPI

app = FastAPI(
    title="Agendamento API",
    version="0.1.0",
    description="Backend de agendamento multi-tenant para landing pages e sites.",
)


@app.get("/health", tags=["infra"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
