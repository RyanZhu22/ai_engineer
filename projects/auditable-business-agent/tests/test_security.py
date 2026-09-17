from datetime import datetime, timedelta, timezone
import unittest

import jwt

from app.auth import auth_secret


class ApiSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        from tests.test_api import ApiTests

        fixture = ApiTests()
        fixture.setUp()
        self._fixture = fixture
        self.client = fixture.client

    def tearDown(self) -> None:
        self._fixture.tearDown()

    def test_case_endpoints_require_bearer_token(self) -> None:
        self.assertEqual(self.client.post("/cases", json={}).status_code, 401)
        self.assertEqual(self.client.get("/cases/CASE-100/audit").status_code, 401)

    def test_tampered_token_is_rejected(self) -> None:
        headers = self._fixture.headers_for("agent-1", "customer-service-password")
        token = headers["Authorization"].split(" ", 1)[1]
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")

        response = self.client.get("/cases/CASE-100/audit", headers={"Authorization": f"Bearer {tampered}"})

        self.assertEqual(response.status_code, 401)

    def test_token_claimed_role_must_match_database_role(self) -> None:
        user = self._fixture.app.state.runtime.user_repository.get_by_username("agent-1")
        token = jwt.encode({"sub": user.username, "role": "approver"}, auth_secret(), algorithm="HS256")

        response = self.client.get("/cases/CASE-100/audit", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 401)

    def test_expired_token_is_rejected(self) -> None:
        user = self._fixture.app.state.runtime.user_repository.get_by_username("agent-1")
        token = jwt.encode(
            {
                "sub": user.username,
                "role": user.role.value,
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            auth_secret(),
            algorithm="HS256",
        )

        response = self.client.get(
            "/cases/CASE-100/audit",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
