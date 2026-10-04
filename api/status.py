"""Plugin API handler: OpenRouter credit status.

Route: /api/plugins/openrouter_credit_monitor/status (GET or POST)
Returns normalized balance data. Never returns credentials.
"""

from datetime import datetime, timezone

from helpers.api import ApiHandler, Input, Output, Request

from usr.plugins.openrouter_credit_monitor.helpers import state
from usr.plugins.openrouter_credit_monitor.helpers.openrouter_client import (
    AuthenticationError,
    OpenRouterError,
    fetch_credits,
    fetch_key_info,
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify_threshold(remaining: float | None, low: float, critical: float) -> str:
    """Map remaining balance to a display state."""
    if remaining is None:
        return "unknown"
    if remaining <= critical:
        return "critical"
    if remaining <= low:
        return "warning"
    return "normal"


def _build_payload(
    settings: dict,
    credits: dict | None,
    key_info: dict | None,
) -> dict:
    remaining = credits.get("remaining") if credits else None
    threshold = _classify_threshold(
        remaining,
        settings["low_credit_warning"],
        settings["critical_credit_warning"],
    )
    payload = {
        "provider": "OpenRouter",
        "configured": bool(settings["management_key"]),
        "available": credits is not None,
        "status": threshold if credits is not None else "unavailable",
        "show_balance_in_ui": settings["show_balance_in_ui"],
        "total_credits": credits.get("total_credits") if credits else None,
        "total_usage": credits.get("total_usage") if credits else None,
        "remaining": remaining,
        "currency": "USD" if credits else None,
        "key_label": key_info.get("key_label") if key_info else None,
        "key_usage": key_info.get("key_usage") if key_info else None,
        "key_limit": key_info.get("key_limit") if key_info else None,
        "key_limit_remaining": key_info.get("key_limit_remaining") if key_info else None,
        "updated_at": _iso_now(),
        "refresh_interval_seconds": settings["refresh_interval_seconds"],
    }
    return payload


class Status(ApiHandler):
    """Return the current OpenRouter credit status (monitor only)."""

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    @classmethod
    def requires_csrf(cls) -> bool:
        # Read-only status; keep auth but skip CSRF so GET polling works.
        return False

    async def process(self, input: Input, request: Request) -> Output:
        try:
            settings = state.load_settings()
        except Exception:
            # Never break Agent Zero because of a config read.
            return {
                "configured": False,
                "available": False,
                "status": "not_configured",
                "error": "settings_unavailable",
                "updated_at": _iso_now(),
                "refresh_interval_seconds": state.DEFAULT_INTERVAL,
            }

        # Manual refresh bypasses the cache.
        force = bool((input or {}).get("force")) if isinstance(input, dict) else False

        # Serve from in-memory cache when fresh enough.
        cached = state.get_cached_success(max_age=settings["refresh_interval_seconds"])
        if cached and not force:
            cached["cached"] = True
            # Refresh show/hide flag and thresholds from current settings.
            cached["show_balance_in_ui"] = settings["show_balance_in_ui"]
            cached["refresh_interval_seconds"] = settings["refresh_interval_seconds"]
            cached["status"] = _classify_threshold(
                cached.get("remaining"),
                settings["low_credit_warning"],
                settings["critical_credit_warning"],
            )
            return cached

        # Not configured: no Management Key present.
        if not settings["management_key"]:
            return {
                "provider": "OpenRouter",
                "configured": False,
                "available": False,
                "status": "not_configured",
                "show_balance_in_ui": settings["show_balance_in_ui"],
                "refresh_interval_seconds": settings["refresh_interval_seconds"],
                "remaining": None,
                "currency": None,
                "key_label": None,
                "key_usage": None,
                "key_limit": None,
                "key_limit_remaining": None,
                "updated_at": _iso_now(),
            }

        credits: dict | None = None
        key_info: dict | None = None
        error_reason: str | None = None

        # 1) Credits via Management Key (authoritative for account balance).
        try:
            credits = fetch_credits(settings["management_key"])
        except AuthenticationError:
            error_reason = "authentication_failed"
        except OpenRouterError as exc:
            error_reason = exc.reason
        except Exception:
            error_reason = "unexpected_error"

        # 2) Optional key-level info via API Key; failure is non-fatal.
        if settings["api_key"]:
            try:
                key_info = fetch_key_info(settings["api_key"])
            except Exception:
                key_info = None

        if credits is not None:
            payload = _build_payload(settings, credits, key_info)
            state.set_last_success(payload)
            payload["cached"] = False
            return payload

        # Failure path: keep last success (stale) when available.
        if error_reason:
            state.set_last_error(error_reason)
        stale = state.get_cached_success()
        if stale:
            stale["cached"] = True
            stale["stale"] = True
            stale["status"] = _classify_threshold(
                stale.get("remaining"),
                settings["low_credit_warning"],
                settings["critical_credit_warning"],
            )
            stale["show_balance_in_ui"] = settings["show_balance_in_ui"]
            stale["refresh_interval_seconds"] = settings["refresh_interval_seconds"]
            stale["error"] = error_reason or "unavailable"
            return stale

        return {
            "provider": "OpenRouter",
            "configured": True,
            "available": False,
            "status": "unavailable",
            "show_balance_in_ui": settings["show_balance_in_ui"],
            "remaining": None,
            "currency": None,
            "key_label": None,
            "key_usage": None,
            "key_limit": None,
            "key_limit_remaining": None,
            "error": error_reason or "unavailable",
            "updated_at": _iso_now(),
            "refresh_interval_seconds": settings["refresh_interval_seconds"],
        }
