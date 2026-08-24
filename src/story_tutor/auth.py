from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from http.cookies import SimpleCookie
import secrets
from typing import Any


ROLES = {"ADMIN", "STUDENT"}
SESSION_COOKIE = "lws_session"
PASSWORD_ITERATIONS = 240_000


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    email: str
    display_name: str
    learner_id: int
    roles: frozenset[str]
    csrf_token: str

    @property
    def is_admin(self) -> bool:
        return "ADMIN" in self.roles

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "learner_id": self.learner_id,
            "roles": sorted(self.roles),
            "is_admin": self.is_admin,
            "csrf_token": self.csrf_token,
        }


def normalize_email(value: str) -> str:
    return "".join(str(value).strip().casefold().split())[:254]


def validate_password(value: str) -> str:
    password = str(value)
    if len(password) < 10 or len(password) > 200:
        raise ValueError("Password must contain between 10 and 200 characters")
    if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        raise ValueError("Password must contain at least one letter and one number")
    return password


def hash_password(password: str) -> str:
    password = validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", str(password).encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(actual, bytes.fromhex(digest_hex))
    except (TypeError, ValueError):
        return False


def new_session_values(days: int = 14) -> tuple[str, str, str, str]:
    token = secrets.token_urlsafe(40)
    csrf = secrets.token_urlsafe(24)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return token, token_hash, csrf, expires


def session_hash_from_cookie(cookie_header: str) -> str:
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header or "")
        token = cookie.get(SESSION_COOKIE)
        return hashlib.sha256(token.value.encode("utf-8")).hexdigest() if token else ""
    except Exception:
        return ""


def session_cookie(token: str, *, secure: bool = False, delete: bool = False) -> str:
    value = f"{SESSION_COOKIE}={'' if delete else token}; Path=/; HttpOnly; SameSite=Strict"
    if secure:
        value += "; Secure"
    value += "; Max-Age=0" if delete else "; Max-Age=1209600"
    return value
