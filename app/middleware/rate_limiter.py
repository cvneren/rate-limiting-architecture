from typing import Any, Awaitable, Callable, Dict

from cachetools import TTLCache  # type: ignore

from app.core.config import settings
from app.services.rate_limit_evaluator import evaluate_request


class RateLimitMiddleware:
    """
    Pure ASGI Middleware for high-performance rate limiting.
    Bypasses Starlette's BaseHTTPMiddleware to avoid latency overhead.
    """

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app
        # Blocklist limited to 10,000 entries, max 5 second TTL
        self.blocklist = TTLCache(maxsize=10000, ttl=5)

    async def __call__(
        self,
        scope: Dict[str, Any],
        receive: Callable[..., Awaitable[Any]],
        send: Callable[..., Awaitable[Any]],
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract IP from X-Forwarded-For or fallback to scope client
        headers = dict(scope.get("headers", []))
        x_forwarded_for = headers.get(b"x-forwarded-for")

        if x_forwarded_for:
            # Get the first IP in the comma-separated list (the true client)
            client_id = x_forwarded_for.decode().split(",")[0].strip()
        else:
            client = scope.get("client")
            client_id = client[0] if client else "unknown"

        # Check Hot Key Blocklist
        if client_id in self.blocklist:
            await self._send_429(send, 0.0)  # Already blocked
            return

        # Evaluate against Redis/L1 Fail-Open
        is_allowed, remaining, retry_after = await evaluate_request(client_id)

        if not is_allowed:
            # Hot-Key Protection: Add to L1 Blocklist if rate limited.
            # This protects Redis from volumetric exhaustion by same client.
            self.blocklist[client_id] = True

            await self._send_429(send, retry_after)
            return

        # Inject Rate Limit Headers in the response
        async def send_wrapper(message: Dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                resp_headers = list(message.get("headers", []))
                resp_headers.append(
                    (b"x-ratelimit-limit", str(settings.RATE_LIMIT_LIMIT).encode())
                )
                resp_headers.append((b"x-ratelimit-remaining", str(remaining).encode()))
                message["headers"] = resp_headers
            await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _send_429(
        self, send: Callable[..., Awaitable[Any]], retry_after: float
    ) -> None:
        """Sends a raw ASGI HTTP 429 response."""
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(int(retry_after)).encode()),
                    (b"x-ratelimit-remaining", b"0"),
                ],
            }
        )
        await send(
            {"type": "http.response.body", "body": b'{"error": "Too Many Requests"}'}
        )
