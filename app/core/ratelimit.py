"""Limite de requisicoes em memoria (janela deslizante).

Vale por processo. Para uma unica instancia (plano inicial do Render) basta; com varias
instancias o limite passa a ser por instancia, e o certo seria mover para o Redis.
"""

import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import AppError


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, limit: int, window_seconds: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    """IP do cliente. Atras de proxy usa o X-Forwarded-For, contando TRUSTED_PROXY_HOPS
    entradas a partir do fim (as da esquerda podem ser forjadas pelo cliente)."""
    hops = get_settings().trusted_proxy_hops
    forwarded = request.headers.get("x-forwarded-for")
    if hops > 0 and forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "desconhecido"


def rate_limit(name: str, limit_setting: str, window_seconds: int = 60) -> Callable:
    """Dependencia que bloqueia (429) quando o IP passa do limite configurado."""

    async def dependency(request: Request) -> None:
        settings = get_settings()
        limit = getattr(settings, limit_setting)
        if limit <= 0:
            return
        if not limiter.allow(f"{name}:{client_ip(request)}", limit, window_seconds):
            raise AppError(429, "rate_limited", "Muitas requisicoes. Tente novamente em instantes.")

    return dependency
