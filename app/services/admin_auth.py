"""Stateless single-password admin authentication with signed CSRF sessions."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as BinasciiError
from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import os
import secrets
import time
from collections.abc import Mapping


class AdminAuthError(ValueError):
    """Base class for intentionally generic admin authentication failures."""


class AdminDisabledError(AdminAuthError):
    pass


class InvalidAdminCredentials(AdminAuthError):
    pass


class InvalidAdminSession(AdminAuthError):
    pass


class InvalidCsrfToken(AdminAuthError):
    pass


@dataclass(frozen=True)
class AdminSession:
    csrf_token: str
    expires_at: int


@dataclass(frozen=True)
class AdminAuthConfig:
    password: str | None
    session_secret: str | None
    cookie_secure: bool = False
    session_ttl_seconds: int = 8 * 60 * 60
    cookie_name: str = "pokemon_admin_session"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AdminAuthConfig:
        values = env if env is not None else os.environ
        secure_value = values.get("ADMIN_COOKIE_SECURE", "false").strip().casefold()
        if secure_value not in {"true", "false", "1", "0"}:
            raise ValueError("ADMIN_COOKIE_SECURE must be true or false")
        try:
            ttl = int(values.get("ADMIN_SESSION_TTL_SECONDS", str(8 * 60 * 60)))
        except ValueError as exc:
            raise ValueError("ADMIN_SESSION_TTL_SECONDS must be an integer") from exc
        if not 300 <= ttl <= 7 * 24 * 60 * 60:
            raise ValueError("ADMIN_SESSION_TTL_SECONDS must be between 300 and 604800")
        return cls(
            password=values.get("ADMIN_PASSWORD") or None,
            session_secret=values.get("ADMIN_SESSION_SECRET") or None,
            cookie_secure=secure_value in {"true", "1"},
            session_ttl_seconds=ttl,
        )


class AdminAuth:
    """Authenticate one configured password without creating user records."""

    def __init__(self, config: AdminAuthConfig, *, clock=time.time) -> None:
        self.config = config
        self._clock = clock

    @property
    def enabled(self) -> bool:
        return bool(self.config.password and self.config.session_secret)

    def login(self, password: str) -> tuple[str, AdminSession]:
        self._ensure_enabled()
        assert self.config.password is not None
        if not secrets.compare_digest(str(password), self.config.password):
            raise InvalidAdminCredentials("Invalid administrator credentials")
        session = AdminSession(
            csrf_token=secrets.token_urlsafe(32),
            expires_at=int(self._clock()) + self.config.session_ttl_seconds,
        )
        return self._encode(session), session

    def verify_session(self, token: str | None) -> AdminSession:
        self._ensure_enabled()
        if not token or "." not in token:
            raise InvalidAdminSession("Invalid administrator session")
        payload_part, signature_part = token.split(".", 1)
        try:
            expected = self._signature(payload_part)
        except UnicodeEncodeError:
            raise InvalidAdminSession("Invalid administrator session") from None
        if not secrets.compare_digest(signature_part, expected):
            raise InvalidAdminSession("Invalid administrator session")
        try:
            payload = json.loads(self._decode_part(payload_part))
            csrf_token = str(payload["csrf"])
            expires_at = int(payload["exp"])
        except (
            BinasciiError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
        ):
            raise InvalidAdminSession("Invalid administrator session") from None
        if expires_at <= int(self._clock()) or len(csrf_token) < 32:
            raise InvalidAdminSession("Invalid administrator session")
        return AdminSession(csrf_token=csrf_token, expires_at=expires_at)

    @staticmethod
    def verify_csrf(session: AdminSession, token: str | None) -> None:
        if not token or not secrets.compare_digest(token, session.csrf_token):
            raise InvalidCsrfToken("Invalid CSRF token")

    def _ensure_enabled(self) -> None:
        if not self.enabled:
            raise AdminDisabledError("Administrator access is not configured")
        assert self.config.session_secret is not None
        if len(self.config.session_secret) < 32:
            raise AdminDisabledError("Administrator access is not configured")

    def _encode(self, session: AdminSession) -> str:
        payload = json.dumps(
            {"csrf": session.csrf_token, "exp": session.expires_at},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        payload_part = self._encode_part(payload)
        return f"{payload_part}.{self._signature(payload_part)}"

    def _signature(self, payload_part: str) -> str:
        assert self.config.session_secret is not None
        digest = hmac.new(
            self.config.session_secret.encode("utf-8"),
            payload_part.encode("ascii"),
            sha256,
        ).digest()
        return self._encode_part(digest)

    @staticmethod
    def _encode_part(value: bytes) -> str:
        return urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_part(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return urlsafe_b64decode(value + padding)
