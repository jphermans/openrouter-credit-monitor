"""Server-side OpenRouter HTTP client for the Credit Monitor plugin.

All requests to OpenRouter happen here, inside the Agent Zero framework
runtime. Credentials never reach browser-side JavaScript.
"""

from typing import Any

import httpx

CREDITS_URL = "https://openrouter.ai/api/v1/credits"
KEY_URL = "https://openrouter.ai/api/v1/key"

# Reasonable bounded timeouts (connect, read, write, pool)
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class OpenRouterError(Exception):
    """Base error for OpenRouter communication failures."""

    def __init__(self, reason: str, detail: str = "", status_code: int | None = None):
        self.reason = reason
        self.detail = detail
        self.status_code = status_code
        super().__init__(reason)


class AuthenticationError(OpenRouterError):
    """Raised for HTTP 401/403 responses."""


class RateLimitError(OpenRouterError):
    """Raised for HTTP 429 responses."""


class ServerError(OpenRouterError):
    """Raised for HTTP 5xx responses."""


def _http_error(status_code: int, body: str) -> OpenRouterError:
    detail = (body or "").strip()[:300]
    if status_code in (401, 403):
        return AuthenticationError("authentication_failed", detail=detail, status_code=status_code)
    if status_code == 429:
        return RateLimitError("rate_limited", detail=detail, status_code=status_code)
    if status_code >= 500:
        return ServerError("server_error", detail=detail, status_code=status_code)
    return OpenRouterError(f"http_error_{status_code}", detail=detail, status_code=status_code)


def _classify_request_error(error: Exception) -> OpenRouterError:
    if isinstance(error, httpx.TimeoutException):
        return OpenRouterError("timeout", detail=str(error)[:200])
    if isinstance(error, httpx.ConnectError):
        return OpenRouterError("connect_failed", detail=str(error)[:200])
    if isinstance(error, httpx.HTTPError):
        return OpenRouterError("network_error", detail=str(error)[:200])
    return OpenRouterError("unexpected_error", detail=str(error)[:200])


def _get_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception as exc:  # malformed JSON
        raise OpenRouterError("malformed_json", detail=str(exc)[:200]) from exc
    if not isinstance(data, dict):
        raise OpenRouterError("unexpected_response", detail="top-level JSON is not an object")
    return data


def _to_float(value: Any) -> float | None:
    """Best-effort numeric conversion; returns None when not a usable number."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def fetch_credits(management_key: str) -> dict[str, Any]:
    """GET /api/v1/credits with a Management Key.

    Returns a dict with total_credits, total_usage and derived remaining.
    Raises OpenRouterError subclasses on failure.
    """
    try:
        response = httpx.get(
            CREDITS_URL,
            headers={
                "Authorization": f"Bearer {management_key}",
                "Accept": "application/json",
            },
            timeout=TIMEOUT,
        )
    except Exception as exc:
        raise _classify_request_error(exc) from exc

    if response.status_code != 200:
        raise _http_error(response.status_code, response.text)

    data = _get_json(response).get("data", {})
    if not isinstance(data, dict):
        raise OpenRouterError("unexpected_response", detail="credits 'data' is not an object")

    total_credits = _to_float(data.get("total_credits"))
    total_usage = _to_float(data.get("total_usage"))
    remaining = None
    if total_credits is not None and total_usage is not None:
        remaining = total_credits - total_usage

    return {
        "total_credits": total_credits,
        "total_usage": total_usage,
        "remaining": remaining,
    }


def fetch_key_info(api_key: str) -> dict[str, Any]:
    """GET /api/v1/key with a (optional) API key.

    Returns non-sensitive key metadata: label, usage, limit, remaining limit.
    Raises OpenRouterError subclasses on failure.
    """
    try:
        response = httpx.get(
            KEY_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            timeout=TIMEOUT,
        )
    except Exception as exc:
        raise _classify_request_error(exc) from exc

    if response.status_code != 200:
        raise _http_error(response.status_code, response.text)

    data = _get_json(response).get("data", {})
    if not isinstance(data, dict):
        raise OpenRouterError("unexpected_response", detail="key 'data' is not an object")

    usage = _to_float(data.get("usage"))
    limit = _to_float(data.get("limit"))
    limit_remaining = None
    if limit is not None and usage is not None:
        # limit == -1 means unlimited on OpenRouter
        limit_remaining = None if limit < 0 else max(limit - usage, 0.0)

    label = data.get("label")
    label = str(label).strip() if isinstance(label, str) else ""

    return {
        "key_label": label,
        "key_usage": usage,
        "key_limit": limit,
        "key_limit_remaining": limit_remaining,
    }
