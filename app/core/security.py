"""Chaves de API, senhas e tokens JWT.

- Chave de API: gerada aleatoriamente, exibida uma unica vez e guardada apenas como hash
  SHA-256 (a chave tem alta entropia, entao um hash rapido e suficiente).
- Senha: scrypt da biblioteca padrao, com salt aleatorio por senha.
- JWT: HS256 assinado com JWT_SECRET, com expiracao.
"""

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt

from app.core.config import get_settings

API_KEY_PREFIX = "pk_"
API_KEY_DISPLAY_PREFIX_LENGTH = 10
JWT_ALGORITHM = "HS256"
JWT_TYPE = "admin"

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_KEY_LENGTH = 32


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Devolve (chave completa, prefixo para exibicao, hash para guardar)."""
    plain = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return plain, plain[:API_KEY_DISPLAY_PREFIX_LENGTH], hash_api_key(plain)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_KEY_LENGTH,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Hash de uma senha qualquer, usado para gastar o mesmo tempo quando o usuario nao existe.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def create_access_token(admin_id: UUID, tenant_id: UUID, now: datetime | None = None) -> str:
    settings = get_settings()
    issued = now or datetime.now(UTC)
    claims = {
        "sub": str(admin_id),
        "tid": str(tenant_id),
        "typ": JWT_TYPE,
        "iat": issued,
        "exp": issued + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Valida assinatura, expiracao e tipo. Levanta jwt.PyJWTError se algo estiver errado."""
    claims = jwt.decode(
        token,
        get_settings().jwt_secret,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp", "iat", "sub", "tid"]},
    )
    if claims.get("typ") != JWT_TYPE:
        raise jwt.InvalidTokenError("tipo de token invalido")
    return claims
