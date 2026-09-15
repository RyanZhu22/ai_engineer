from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from app.config import auth_secret
from app.models import User, UserRole


TOKEN_TTL_HOURS = 8


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters")
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, encoded_salt, encoded_digest = password_hash.split("$", 2)
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(encoded_salt),
            n=2**14,
            r=8,
            p=1,
        )
        return hmac.compare_digest(digest, base64.b64decode(encoded_digest))
    except (ValueError, TypeError):
        return False


def issue_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user.username,
            "role": user.role.value,
            "iat": now,
            "exp": now + timedelta(hours=TOKEN_TTL_HOURS),
        },
        auth_secret(),
        algorithm="HS256",
    )


def decode_access_token(token: str) -> tuple[str, UserRole]:
    payload = jwt.decode(token, auth_secret(), algorithms=["HS256"])
    return str(payload["sub"]), UserRole(str(payload["role"]))
