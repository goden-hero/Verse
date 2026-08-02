"""Password hashing and verification utilities using bcrypt."""

import logging
import bcrypt

logger = logging.getLogger("music_rec.auth.password")


def hash_password(password: str) -> str:
    """Hashes a plain text password using bcrypt with standard salt generation.

    Args:
        password: Plain text password string.

    Returns:
        Hashed password string suitable for storage.
    """
    if not password:
        raise ValueError("Password string cannot be empty for hashing.")

    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    hashed_bytes = bcrypt.hashpw(password_bytes, salt)
    return hashed_bytes.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verifies a plain text candidate password against a stored bcrypt hash.

    Args:
        password: Candidate plain text password string.
        password_hash: Stored bcrypt hash string.

    Returns:
        True if password matches hash, False otherwise.
    """
    if not password or not password_hash:
        return False

    try:
        password_bytes = password.encode("utf-8")
        hash_bytes = password_hash.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except Exception as e:
        logger.warning("Password verification failed with exception: %s", e)
        return False
