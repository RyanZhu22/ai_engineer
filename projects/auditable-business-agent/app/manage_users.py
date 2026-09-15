from __future__ import annotations

import argparse
import getpass

from sqlalchemy.exc import IntegrityError

from app.auth import hash_password
from app.db import build_session_factory
from app.models import UserRole
from app.repositories import SqlAlchemyUserRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or reset a local Auditable Business Agent user")
    parser.add_argument("username")
    parser.add_argument("--role", choices=[role.value for role in UserRole])
    parser.add_argument("--reset-password", action="store_true")
    args = parser.parse_args()
    if not args.reset_password and args.role is None:
        parser.error("--role is required when creating a user")
    password = getpass.getpass("Password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    users = SqlAlchemyUserRepository(build_session_factory())
    if args.reset_password:
        if not users.set_password(username=args.username, password_hash=hash_password(password)):
            raise SystemExit("Username does not exist")
        print(f"Reset password for {args.username}.")
        return
    try:
        user = users.create(
            username=args.username,
            password_hash=hash_password(password),
            role=args.role,
        )
    except IntegrityError as error:
        raise SystemExit("Username already exists") from error
    print(f"Created {user.username} with role {user.role.value}.")


if __name__ == "__main__":
    main()
