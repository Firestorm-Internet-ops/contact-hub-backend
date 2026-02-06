import redis

from app.core.config import settings

# Create a global Redis connection pool
pool = redis.ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)

def get_redis_client():
    """Get or create a Redis client instance."""
    return redis.Redis(connection_pool=pool)