import json
from redis import Redis


def cache_get(redis: Redis, key: str):
    data = redis.get(key)
    return json.loads(data) if data else None


def cache_set(redis: Redis, key: str, data, ttl_seconds: int):
    redis.setex(key, ttl_seconds, json.dumps(data, default=str))


def cache_delete(redis: Redis, key: str):
    redis.delete(key)


def cache_delete_pattern(redis: Redis, pattern: str):
    keys = redis.keys(pattern)
    if keys:
        redis.delete(*keys)
