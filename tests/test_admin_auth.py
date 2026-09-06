from __future__ import annotations

import unittest

from app.services.admin_auth import (
    AdminAuth,
    AdminAuthConfig,
    AdminDisabledError,
    InvalidAdminCredentials,
    InvalidAdminSession,
    InvalidCsrfToken,
)


class AdminAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1_700_000_000
        self.auth = AdminAuth(
            AdminAuthConfig(
                password="correct horse battery staple",
                session_secret="s" * 32,
                session_ttl_seconds=600,
            ),
            clock=lambda: self.now,
        )

    def test_login_creates_signed_expiring_session_without_password(self):
        token, session = self.auth.login("correct horse battery staple")

        self.assertNotIn("correct horse battery staple", token)
        self.assertEqual(session.expires_at, self.now + 600)
        self.assertEqual(self.auth.verify_session(token), session)

    def test_wrong_password_tampered_cookie_and_expiry_are_rejected(self):
        with self.assertRaises(InvalidAdminCredentials):
            self.auth.login("wrong")

        token, _session = self.auth.login("correct horse battery staple")
        with self.assertRaises(InvalidAdminSession):
            self.auth.verify_session(f"{token[:-1]}x")
        with self.assertRaises(InvalidAdminSession):
            self.auth.verify_session("惡意內容.signature")

        expired_auth = AdminAuth(self.auth.config, clock=lambda: self.now + 601)
        with self.assertRaises(InvalidAdminSession):
            expired_auth.verify_session(token)

    def test_csrf_must_match_the_signed_session(self):
        _token, session = self.auth.login("correct horse battery staple")

        AdminAuth.verify_csrf(session, session.csrf_token)
        for invalid in (None, "", "not-the-session-token"):
            with self.subTest(invalid=invalid), self.assertRaises(InvalidCsrfToken):
                AdminAuth.verify_csrf(session, invalid)

    def test_missing_password_or_short_secret_disables_admin(self):
        configs = (
            AdminAuthConfig(password=None, session_secret="s" * 32),
            AdminAuthConfig(password="password", session_secret=None),
            AdminAuthConfig(password="password", session_secret="too-short"),
        )

        for config in configs:
            with self.subTest(config=config), self.assertRaises(AdminDisabledError):
                AdminAuth(config).login("password")

    def test_environment_configuration_is_strict(self):
        config = AdminAuthConfig.from_env(
            {
                "ADMIN_PASSWORD": "password",
                "ADMIN_SESSION_SECRET": "s" * 32,
                "ADMIN_COOKIE_SECURE": "true",
                "ADMIN_SESSION_TTL_SECONDS": "900",
            }
        )
        self.assertTrue(config.cookie_secure)
        self.assertEqual(config.session_ttl_seconds, 900)

        for env in (
            {"ADMIN_COOKIE_SECURE": "sometimes"},
            {"ADMIN_SESSION_TTL_SECONDS": "not-an-int"},
            {"ADMIN_SESSION_TTL_SECONDS": "60"},
        ):
            with self.subTest(env=env), self.assertRaises(ValueError):
                AdminAuthConfig.from_env(env)


if __name__ == "__main__":
    unittest.main()
