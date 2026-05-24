"""
src/auth/auth.py
Fix #9 — User authentication with Flask-Login + bcrypt password hashing.
"""

import re
import logging
import bcrypt
from flask_login import UserMixin

logger = logging.getLogger(__name__)

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


class User(UserMixin):
    """Flask-Login compatible user model backed by SQLite."""

    def __init__(self, id: int, username: str, email: str):
        self.id       = id
        self.username = username
        self.email    = email

    # ── Flask-Login required ──────────────────────────────────────────────────
    def get_id(self) -> str:
        return str(self.id)

    # ── Factory methods ───────────────────────────────────────────────────────
    @classmethod
    def get(cls, user_id: int | str, db) -> "User | None":
        row = db.get_user_by_id(int(user_id))
        if row:
            return cls(row["id"], row["username"], row["email"])
        return None

    @classmethod
    def authenticate(cls, username: str, password: str, db) -> "User | None":
        if not username or not password:
            return None
        row = db.get_user_by_username(username.strip())
        if not row:
            # Constant-time dummy check to prevent user-enumeration via timing
            bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt()))
            return None
        stored_hash = row["password_hash"]
        if isinstance(stored_hash, str):
            stored_hash = stored_hash.encode()
        if bcrypt.checkpw(password.encode(), stored_hash):
            return cls(row["id"], row["username"], row["email"])
        return None

    @classmethod
    def create(cls, username: str, password: str, email: str, db) -> "User":
        """
        Creates a new user.  Raises ValueError on validation failure.
        """
        username = (username or "").strip()
        password = (password or "").strip()
        email    = (email or "").strip()

        if not USERNAME_RE.match(username):
            raise ValueError("Username must be 3–32 characters: letters, numbers, underscores only.")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if db.get_user_by_username(username):
            raise ValueError(f"Username '{username}' is already taken.")

        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user_id = db.create_user(username, email, pw_hash)
        logger.info("New user registered: %s (id=%d)", username, user_id)
        return cls(user_id, username, email)
