from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import os
import re
import secrets
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SENSITIVE_PATTERN = re.compile(
    r"(?i)(authorization|cookie|password|api[_-]?key|token)\s*[:=]\s*([^\s,;]+)"
)


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("invalid email")
    return email


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${derived.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n_value, r_value, p_value, salt_hex, digest_hex = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n_value),
            r=int(r_value),
            p=int(p_value),
            dklen=len(bytes.fromhex(digest_hex)),
        )
        return hmac.compare_digest(actual, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


DUMMY_PASSWORD_HASH = hash_password("not-a-real-user-password")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def expires_at(hours: int) -> str:
    value = datetime.now(timezone.utc) + timedelta(hours=hours)
    return value.isoformat().replace("+00:00", "Z")


def validate_https_url(url: str, allowed_hosts: set[str]) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("remote URL must be an HTTPS URL without credentials")
    if parsed.port not in {None, 443}:
        raise ValueError("remote URL uses a disallowed port")
    host = parsed.hostname.rstrip(".").lower()
    if not any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts):
        raise ValueError("remote URL host is not allowed")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ValueError("remote URL host could not be resolved") from error
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("remote URL resolves to a non-public address")
    return url


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = SENSITIVE_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", message)
        record.msg = redacted
        record.args = ()
        return True


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
