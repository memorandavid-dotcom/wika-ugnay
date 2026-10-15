"""Value normalization helpers. Syntax only: nothing here verifies a mailbox exists."""
import re
from urllib.parse import urlsplit, urlunsplit

_EMAIL_SYNTAX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    cleaned = value.strip().lower()
    if cleaned.startswith("mailto:"):
        cleaned = cleaned[len("mailto:"):]
    if cleaned.count("@") != 1:
        raise ValueError("email must contain exactly one '@'")
    local, domain = cleaned.split("@")
    domain = domain.rstrip(".")
    if not local or not domain:
        raise ValueError("email is missing its local part or domain")
    return f"{local}@{domain}"


def has_valid_email_syntax(normalized: str) -> bool:
    return bool(_EMAIL_SYNTAX.match(normalized)) and ".." not in normalized


def normalize_phone(value: str) -> str:
    stripped = value.strip()
    digits = re.sub(r"\D", "", stripped)
    if len(digits) < 7:
        raise ValueError("phone number is too short")
    return ("+" if stripped.startswith("+") else "") + digits


def normalize_domain(value: str) -> str:
    cleaned = value.strip().lower().rstrip(".")
    if not cleaned or any(ch in cleaned for ch in "/@ \t"):
        raise ValueError("not a bare domain name")
    return cleaned


def normalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError("not an http(s) URL")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, "")
    )


_NORMALIZERS = {
    "email": normalize_email,
    "phone": normalize_phone,
    "contact_form": normalize_url,
}


def normalize_contact_value(method_type: str, value: str) -> str:
    try:
        normalizer = _NORMALIZERS[method_type]
    except KeyError:
        raise ValueError(f"unsupported contact method type: {method_type!r}") from None
    return normalizer(value)