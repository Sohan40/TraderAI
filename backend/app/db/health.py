"""Storage dependency health checks."""

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.cache.redis import get_redis_client
from app.db.session import engine


async def check_database() -> bool:
    """Return whether the database accepts a simple query."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


async def check_redis() -> bool:
    """Return whether Redis accepts a ping."""
    try:
        client = get_redis_client()
        return bool(await client.ping())
    except Exception:
        return False
