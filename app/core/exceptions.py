class RateLimitException(Exception):
    """Base exception for rate limiting errors."""

    pass


class RedisConnectionError(RateLimitException):
    """Raised when there is an issue connecting to Redis."""

    pass


class LuaScriptError(RateLimitException):
    """Raised when the Lua script execution fails."""

    pass
