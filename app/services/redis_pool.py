from typing import Optional

import redis.asyncio as redis

from app.core.config import settings


class RedisPool:
    def __init__(self) -> None:
        self.pool: Optional[redis.Redis] = None
        self.gcra_sha: Optional[str] = None

    async def init_pool(self) -> None:
        """Initialize the global Redis connection pool."""
        if self.pool is None:
            self.pool = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
            await self.load_scripts()

    async def load_scripts(self) -> None:
        """Load the GCRA Lua script into Redis and store its SHA1 digest."""
        try:
            with open("app/scripts/gcra.lua", "r") as f:
                lua_script = f.read()
            if self.pool:
                # Suppress MyPy Union awaitable warning for script_load
                self.gcra_sha = await self.pool.script_load(
                    lua_script
                )  # type: ignore[misc]
        except FileNotFoundError:
            # Handle during development if file doesn't exist yet
            pass

    async def close_pool(self) -> None:
        """Gracefully close the Redis connection pool."""
        if self.pool:
            await self.pool.aclose()
            self.pool = None

    def get_client(self) -> redis.Redis:
        """Get a client from the pool."""
        if self.pool is None:
            raise RuntimeError("Redis pool not initialized")
        return self.pool


redis_manager = RedisPool()
