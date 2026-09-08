"""Stateless single-password admin authentication with signed CSRF sessions."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as BinasciiError
from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import os
import re
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


ADMIN_ROLES = ("viewer", "editor", "admin")
ROLE_PERMISSIONS = {
    "viewer": ("admin:read",),
    "editor": ("admin:read", "admin:write"),
    "admin": ("admin:read", "admin:write", "audit:read"),
}


@dataclass(frozen=True)
class AdminAccount:
    username: str
    password: str
    role: str

    def __post_init__(self) -> None:
        username = self.username.strip().casefold()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,63}", username):
            raise ValueError("admin username must contain only letters, numbers, dot, dash or underscore")
        if not self.password or len(self.password) > 256:
            raise ValueError("admin password must contain between 1 and 256 characters")
        if self.role not in ADMIN_ROLES:
            raise ValueError(f"admin role must be one of: {', '.join(ADMIN_ROLES)}")
        object.__setattr__(self, "username", username)


@dataclass(frozen=True)
class AdminSession:
    csrf_token: str
    expires_at: int
    username: str = "admin"
    role: str = "admin"

    @property
    def permissions(self) -> tuple[str, ...]:
        return ROLE_PERMISSIONS.get(self.role, ())

    def can(self, permission: str) -> bool:
        return permission in self.permissions


@dataclass(frozen=True)
class AdminAuthConfig:
    password: str | None
    session_secret: str | None
    accounts: tuple[AdminAccount, ...] = ()
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
        accounts_value = values.get("ADMIN_ACCOUNTS_JSON", "").strip()
        accounts: tuple[AdminAccount, ...] = ()
        if accounts_value:
            try:
                payload = json.loads(accounts_value)
                if not isinstance(payload, list):
                    raise TypeError("accounts must be a list")
                accounts = tuple(
                    AdminAccount(
                        username=str(item["username"]),
                        password=str(item["password"]),
                        role=str(item["role"]),
                    )
                    for item in payload
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("ADMIN_ACCOUNTS_JSON must be a valid account list") from exc
        return cls(
            password=values.get("ADMIN_PASSWORD") or None,
            session_secret=values.get("ADMIN_SESSION_SECRET") or None,
            accounts=accounts,
            cookie_secure=secure_value in {"true", "1"},
            session_ttl_seconds=ttl,
        )


class AdminAuth:
    """Authenticate environment-configured RBAC accounts."""

    def __init__(self, config: AdminAuthConfig, *, clock=time.time) -> None:
        self.config = config
        self._clock = clock
        configured = list(config.accounts)
        if config.password and not any(item.username == "admin" for item in configured):
            configured.append(AdminAccount("admin", config.password, "admin"))
        self._accounts = {item.username: item for item in configured}
        if len(self._accounts) != len(configured):
            raise ValueError("admin usernames must be unique")

    @property
    def enabled(self) -> bool:
        return bool(self._accounts and self.config.session_secret)

    def login(self, password: str, *, username: str = "admin") -> tuple[str, AdminSession]:
        self._ensure_enabled()
        normalized_username = str(username).strip().casefold()
        account = self._accounts.get(normalized_username)
        expected = account.password if account is not None else "\0" * 32
        if not secrets.compare_digest(str(password), expected) or account is None:
            raise InvalidAdminCredentials("Invalid administrator credentials")
        session = AdminSession(
            csrf_token=secrets.token_urlsafe(32),
            expires_at=int(self._clock()) + self.config.session_ttl_seconds,
            username=account.username,
            role=account.role,
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
            username = str(payload.get("sub", "admin")).strip().casefold()
            role = str(payload.get("role", "admin"))
        except (
            BinasciiError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
        ):
            raise InvalidAdminSession("Invalid administrator session") from None
        account = self._accounts.get(username)
        if (
            expires_at <= int(self._clock())
            or len(csrf_token) < 32
            or account is None
            or role != account.role
        ):
            raise InvalidAdminSession("Invalid administrator session")
        return AdminSession(
            csrf_token=csrf_token,
            expires_at=expires_at,
            username=username,
            role=role,
        )

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
            {
                "csrf": session.csrf_token,
                "exp": session.expires_at,
                "role": session.role,
                "sub": session.username,
            },
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
