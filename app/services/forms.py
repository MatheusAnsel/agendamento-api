"""Validacao dos dados do cliente contra o form_config do negocio."""

import re
from typing import Any

from app.core.errors import AppError

PHONE_MIN_DIGITS = 10
PHONE_MAX_DIGITS = 15
BRAZIL_DDI = "55"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CUSTOM_TYPES = {"text", "number", "select"}
MAX_TEXT = 200


def normalize_phone(raw: str) -> str:
    """Devolve o telefone em formato E.164. Sem '+', assume Brasil (DDD + numero)."""
    digits = re.sub(r"\D", "", raw)
    if not raw.strip().startswith("+") and len(digits) in (10, 11):
        digits = BRAZIL_DDI + digits
    if not PHONE_MIN_DIGITS <= len(digits) <= PHONE_MAX_DIGITS:
        raise AppError(422, "invalid_phone", "Telefone invalido")
    return "+" + digits


def _invalid(field: str, message: str) -> AppError:
    return AppError(422, "invalid_field", f"{field}: {message}")


def validate_form(
    form_config: dict[str, Any],
    *,
    name: str,
    phone: str,
    email: str | None,
    notes: str | None,
    custom: dict[str, Any],
    has_resource_choice: bool,
    consent_lgpd: bool,
) -> dict[str, Any]:
    """Valida e limpa os campos. Nome e telefone sao sempre obrigatorios."""
    required = set(form_config.get("required_fields", [])) | {"name", "phone"}
    optional = set(form_config.get("optional_fields", []))
    allowed = required | optional

    name = name.strip()
    if not name:
        raise _invalid("name", "obrigatorio")

    email = (email or "").strip() or None
    if "email" in required and not email:
        raise _invalid("email", "obrigatorio")
    if email and (len(email) > 254 or not EMAIL_RE.match(email)):
        raise _invalid("email", "invalido")

    notes = (notes or "").strip() or None
    if "notes" in required and not notes:
        raise _invalid("notes", "obrigatorio")
    if "resource_id" in required and not has_resource_choice:
        raise _invalid("resource_id", "obrigatorio")
    if "consent_lgpd" in required and not consent_lgpd:
        raise _invalid("consent_lgpd", "e necessario aceitar o uso dos dados")

    definitions = {f["key"]: f for f in form_config.get("custom_fields", [])}
    unknown = set(custom) - set(definitions)
    if unknown:
        raise _invalid("custom", f"campos desconhecidos: {', '.join(sorted(unknown))}")

    cleaned_custom: dict[str, Any] = {}
    for key, definition in definitions.items():
        value = custom.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if definition.get("required"):
                raise _invalid(key, "obrigatorio")
            continue
        kind = definition.get("type", "text")
        label = definition.get("label", key)
        if kind == "number":
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise _invalid(label, "deve ser um numero")
        else:
            if not isinstance(value, str) or len(value) > MAX_TEXT:
                raise _invalid(label, f"texto de ate {MAX_TEXT} caracteres")
            value = value.strip()
            if kind == "select" and value not in definition.get("options", []):
                raise _invalid(label, "opcao invalida")
        cleaned_custom[key] = value

    return {
        "name": name,
        "phone": normalize_phone(phone),
        "email": email if "email" in allowed else None,
        "notes": notes if "notes" in allowed else None,
        "custom": cleaned_custom,
    }
