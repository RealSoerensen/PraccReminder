from typing import Iterable

from database import get_all_users


class DatabaseUserRepository:
    """Concrete UserRepository backed by the existing database module."""

    def get_all_users(self) -> Iterable[int]:
        return get_all_users()
