from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict

from fastapi import FastAPI

from app.middleware.rate_limiter import RateLimitMiddleware
from app.services.redis_pool import redis_manager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: Initialize Redis Pool and load Lua scripts
    await redis_manager.init_pool()
    yield
    # Shutdown: Gracefully close the pool
    await redis_manager.close_pool()


app = FastAPI(lifespan=lifespan)

# Add Pure ASGI Middleware
# Must be added as early as possible.
app.add_middleware(RateLimitMiddleware)


@app.get("/")
async def root() -> Dict[str, str]:
    return {"message": "Hello World - Rate Limited API"}


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}
