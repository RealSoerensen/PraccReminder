import sqlite3
from contextlib import contextmanager
from typing import List
import logging

# Setup logging
logger = logging.getLogger(__name__)

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
    logger.info(f"Initializing database: {DB_FILE}")
    # Create db if not exists
    try:
        open(DB_FILE, 'a').close()
    except Exception as e:
        logger.error(f"Error creating database file: {e}", exc_info=True)
        raise
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
        raise


def get_all_users() -> List[int]:
    """
    Get all user IDs from the database.
    
    Returns:
        List of user IDs.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users ORDER BY added_at")
            users = [row[0] for row in cursor.fetchall()]
            logger.debug(f"Retrieved {len(users)} user(s) from database")
            return users
    except Exception as e:
        logger.error(f"Error retrieving users: {e}", exc_info=True)
        return []


def add_user(user_id: int) -> bool:
    """
    Add a user to the database.
    
    Args:
        user_id: Discord user ID.
        
    Returns:
        True if user was added, False if already exists.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            conn.commit()
            added = cursor.rowcount > 0
            if added:
                logger.info(f"Added user {user_id} to database")
            else:
                logger.debug(f"User {user_id} already exists in database")
            return added
    except Exception as e:
        logger.error(f"Error adding user {user_id}: {e}", exc_info=True)
        return False


def remove_user(user_id: int) -> bool:
    """
    Remove a user from the database.
    
    Args:
        user_id: Discord user ID.
        
    Returns:
        True if user was removed, False if not found.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()
            removed = cursor.rowcount > 0
            if removed:
                logger.info(f"Removed user {user_id} from database")
            else:
                logger.warning(f"User {user_id} not found in database")
            return removed
    except Exception as e:
        logger.error(f"Error removing user {user_id}: {e}", exc_info=True)
        return False


def user_exists(user_id: int) -> bool:
    """
    Check if a user exists in the database.
    
    Args:
        user_id: Discord user ID.
        
    Returns:
        True if user exists, False otherwise.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            exists = cursor.fetchone() is not None
            logger.debug(f"User {user_id} exists: {exists}")
            return exists
    except Exception as e:
        logger.error(f"Error checking user {user_id}: {e}", exc_info=True)
        return False

