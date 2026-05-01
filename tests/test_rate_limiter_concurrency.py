import asyncio
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.redis_pool import redis_manager


@pytest.mark.asyncio
async def test_simultaneous_token_requests_neutralize_toctou() -> None:
    """
    Simulates a burst of 50 simultaneous requests.
    With Limit=100, Period=60, Burst=10, exactly 10 should succeed.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        # Clear redis first
        await redis_manager.init_pool()
        await redis_manager.get_client().flushdb()

        # Fire 50 concurrent requests from the same "client"
        tasks = [ac.get("/", headers={"X-Forwarded-For": "1.2.3.4"}) for _ in range(50)]
        responses = await asyncio.gather(*tasks)

        successes = [r for r in responses if r.status_code == 200]
        failures = [r for r in responses if r.status_code == 429]

        # Burst capacity is 10
        assert len(successes) == 10
        assert len(failures) == 40

        # Verify headers on failures
        for r in failures:
            assert r.headers["x-ratelimit-remaining"] == "0"
            assert "retry-after" in r.headers


@pytest.mark.asyncio
async def test_fail_open_mechanism() -> None:
    """
    Simulates Redis connection failure.
    The system should fallback to L1 cache (Fail-Open).
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        # Mock Redis client to raise an error
        with patch(
            "app.services.rate_limit_evaluator.redis_manager.get_client"
        ) as mock_get:
            mock_get.side_effect = Exception("Redis Down")

            # First 10 (Burst) should succeed via L1 fallback
            tasks = [
                ac.get("/", headers={"X-Forwarded-For": "5.6.7.8"}) for _ in range(15)
            ]
            responses = await asyncio.gather(*tasks)

            successes = [r for r in responses if r.status_code == 200]
            failures = [r for r in responses if r.status_code == 429]

            assert len(successes) == 10
            assert len(failures) == 5


@pytest.mark.asyncio
async def test_hot_key_isolation_l1_blocklist() -> None:
    """
    Verifies that overwhelming traffic is blocked by L1 blocklist
    without reaching Redis.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        await redis_manager.init_pool()
        await redis_manager.get_client().flushdb()

        client_ip = "9.9.9.9"

        # 1. Exhaust burst
        for _ in range(10):
            await ac.get("/", headers={"X-Forwarded-For": client_ip})

        # 2. Next request should trigger 429 and add to L1 blocklist
        # In our implementation, we add to blocklist if retry_after > 0.5
        resp = await ac.get("/", headers={"X-Forwarded-For": client_ip})
        assert resp.status_code == 429

        # 3. Subsequent request should be near-instant (blocked by L1 blocklist)
        # We can check this by mocking the evaluator to ensure it's NOT called.
        with patch("app.middleware.rate_limiter.evaluate_request") as mock_eval:
            # Avoid ValueError if it accidentally calls through
            mock_eval.return_value = (False, 0, 10.0)
            resp = await ac.get("/", headers={"X-Forwarded-For": client_ip})
            assert resp.status_code == 429
            mock_eval.assert_not_called()


@pytest.mark.asyncio
async def test_independent_client_buckets() -> None:
    """
    Asserts that requests from two different X-Forwarded-For IPs receive
    independent token buckets and do not interfere.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        await redis_manager.init_pool()
        await redis_manager.get_client().flushdb()

        ip_1 = "192.168.1.1"
        ip_2 = "192.168.1.2"

        # Exhaust burst for IP 1
        tasks_1 = [ac.get("/", headers={"X-Forwarded-For": ip_1}) for _ in range(10)]
        responses_1 = await asyncio.gather(*tasks_1)
        assert all(r.status_code == 200 for r in responses_1)

        # Next request for IP 1 should fail
        resp_1_fail = await ac.get("/", headers={"X-Forwarded-For": ip_1})
        assert resp_1_fail.status_code == 429

        # IP 2 should still have its full burst capacity (10 requests)
        tasks_2 = [ac.get("/", headers={"X-Forwarded-For": ip_2}) for _ in range(10)]
        responses_2 = await asyncio.gather(*tasks_2)
        assert all(r.status_code == 200 for r in responses_2)

        # Next request for IP 2 should fail
        resp_2_fail = await ac.get("/", headers={"X-Forwarded-For": ip_2})
        assert resp_2_fail.status_code == 429
