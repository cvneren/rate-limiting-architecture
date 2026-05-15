import asyncio
import time
from typing import Any, Awaitable, Tuple, cast

from cachetools import TTLCache  # type: ignore

from app.core.config import settings
from app.services.redis_pool import redis_manager

# L1 Cache for Fail-Open mechanism (Local Token Bucket)
# Limit to 10,000 IPs, evict after 60 seconds
l1_cache: TTLCache[str, dict] = TTLCache(maxsize=10000, ttl=60)


async def evaluate_request(client_id: str) -> Tuple[bool, int, float]:
    """
    Evaluates a rate limit request using GCRA in Redis with a Fail-Open L1 fallback.

    Returns:
        (is_allowed, remaining_burst, retry_after)
    """
    # Hash Tag to ensure all client data resides on the same Redis Cluster slot
    redis_key = f"rate:limit:{{{client_id}}}"

    # Calculate GCRA parameters
    t = settings.RATE_LIMIT_PERIOD / settings.RATE_LIMIT_LIMIT
    tau = (settings.RATE_LIMIT_BURST - 1) * t

    try:
        # Use a strict timeout for Redis calls (Python 3.10 compatible)
        redis_client = redis_manager.get_client()
        if not redis_manager.gcra_sha:
            # Fallback if script not loaded yet (startup race)
            await asyncio.wait_for(redis_manager.load_scripts(), timeout=0.1)

        # Ensure sha is handled as a string for evalsha
        sha = cast(str, redis_manager.gcra_sha)

        # Wrap the evalsha call in wait_for
        # Cast to Awaitable to satisfy MyPy
        result = await asyncio.wait_for(
            cast(Awaitable[Any], redis_client.evalsha(sha, 1, redis_key, t, tau)),
            timeout=0.1,
        )
        # result: [is_allowed, remaining, retry_after]
        return bool(result[0]), int(result[1]), float(result[2])

    except (asyncio.TimeoutError, Exception):
        # Fail-Open: Fallback to L1 Local Cache (Step 2.4)
        return _evaluate_l1_fallback(client_id, t, settings.RATE_LIMIT_BURST)


def _evaluate_l1_fallback(
    client_id: str, t: float, burst: int
) -> Tuple[bool, int, float]:
    """Simple in-memory token bucket fallback for high-availability."""
    now = time.time()
    state = l1_cache.get(client_id, {"tokens": float(burst), "last_refill": now})

    # Refill tokens: (elapsed time / emission interval)
    elapsed = now - state["last_refill"]
    refill = elapsed / t

    new_tokens = min(float(burst), state["tokens"] + refill)

    if new_tokens >= 1:
        state["tokens"] = new_tokens - 1
        state["last_refill"] = now
        l1_cache[client_id] = state
        return True, int(state["tokens"]), 0.0
    else:
        retry_after = t - (now - state["last_refill"]) % t
        return False, 0, retry_after
