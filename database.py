import sqlite3
from contextlib import contextmanager
from typing import List

DB_FILE = "reminder.db"


@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_FILE)
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Initialize the SQLite database and create tables if they don't exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def get_all_users() -> List[int]:
    """
    Get all user IDs from the database.
    
    Returns:
        List of user IDs.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users ORDER BY added_at")
        return [row[0] for row in cursor.fetchall()]


def add_user(user_id: int) -> bool:
    """
    Add a user to the database.
    
    Args:
        user_id: Discord user ID.
        
    Returns:
        True if user was added, False if already exists.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        return cursor.rowcount > 0


def remove_user(user_id: int) -> bool:
    """
    Remove a user from the database.
    
    Args:
        user_id: Discord user ID.
        
    Returns:
        True if user was removed, False if not found.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0


def user_exists(user_id: int) -> bool:
    """
    Check if a user exists in the database.
    
    Args:
        user_id: Discord user ID.
        
    Returns:
        True if user exists, False otherwise.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None

