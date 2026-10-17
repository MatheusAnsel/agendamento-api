from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.core.config import Settings, get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)


def test_api_key_generation_and_hash():
    plain, prefix, key_hash = generate_api_key()
    assert plain.startswith("pk_")
    assert plain.startswith(prefix)
    assert key_hash == hash_api_key(plain)
    assert generate_api_key()[0] != plain


def test_password_hash_roundtrip():
    stored = hash_password("senha-forte-123")
    assert stored.startswith("scrypt$")
    assert verify_password("senha-forte-123", stored)
    assert not verify_password("outra-senha", stored)
    assert hash_password("senha-forte-123") != stored  # salt aleatorio


@pytest.mark.parametrize("stored", ["", "lixo", "bcrypt$1$2$3$4$5", "scrypt$x$y$z$a$b"])
def test_verify_password_rejects_malformed_hash(stored):
    assert not verify_password("qualquer", stored)


def test_token_roundtrip():
    admin_id, tenant_id = uuid4(), uuid4()
    claims = decode_access_token(create_access_token(admin_id, tenant_id))
    assert claims["sub"] == str(admin_id)
    assert claims["tid"] == str(tenant_id)


def test_expired_token_rejected():
    old = datetime.now(UTC) - timedelta(days=2)
    token = create_access_token(uuid4(), uuid4(), now=old)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_token_with_wrong_signature_or_type_rejected():
    now = datetime.now(UTC)
    claims = {"sub": "x", "tid": "y", "iat": now, "exp": now + timedelta(hours=1)}
    forged = jwt.encode({**claims, "typ": "admin"}, "outro-segredo-qualquer-123456789012", "HS256")
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(forged)
    wrong_type = jwt.encode({**claims, "typ": "x"}, get_settings().jwt_secret, "HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(wrong_type)


def test_production_requires_real_secret():
    with pytest.raises(ValueError):
        Settings(env="production", jwt_secret="troque-em-producao")
    with pytest.raises(ValueError):
        Settings(env="production", jwt_secret="curto")
    assert Settings(env="production", jwt_secret="x" * 40).env == "production"
    assert Settings(env="development").env == "development"
