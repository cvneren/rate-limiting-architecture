from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.redis_pool import redis_manager


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        # Trigger startup events
        if redis_manager.pool:
            async with redis_manager.pool.pipeline() as pipe:
                await pipe.flushdb()
                await pipe.execute()
        yield ac


@pytest.fixture(autouse=True)
async def setup_redis() -> AsyncGenerator[None, None]:
    await redis_manager.init_pool()
    yield
    # Explicitly close pool after each test to avoid event loop leakage
    # across shared global state in different test runs.
    if redis_manager.pool:
        try:
            await redis_manager.pool.flushdb()
        finally:
            await redis_manager.close_pool()
