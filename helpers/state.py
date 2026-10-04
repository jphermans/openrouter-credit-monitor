"""Plugin-owned runtime state for the OpenRouter Credit Monitor.

Holds the last successful balance snapshot in memory (survives within the
framework process only) so failures can still display a stale value.
"""

import threading
import time
from typing import Any

from helpers.plugins import get_plugin_config

PLUGIN_NAME = "openrouter_credit_monitor"

# Allowed refresh intervals (seconds); 30s is the fastest permitted poll.
ALLOWED_INTERVALS = (30, 60, 120, 300, 600)
DEFAULT_INTERVAL = 60

_lock = threading.Lock()
_last_success: dict[str, Any] | None = None  # last successful normalized payload
_last_success_at: float | None = None  # epoch seconds of that success
_last_error_reason: str | None = None
_last_error_at: float | None = None


def now() -> float:
    return time.time()


def set_last_success(payload: dict[str, Any]) -> None:
    """Store the most recent successful normalized status payload."""
    global _last_success, _last_success_at
    with _lock:
        _last_success = dict(payload)
        _last_success_at = now()


def set_last_error(reason: str) -> None:
    """Record the most recent failure reason for diagnostics."""
    global _last_error_reason, _last_error_at
    with _lock:
        _last_error_reason = reason
        _last_error_at = now()


def get_cached_success(max_age: float | None = None) -> dict[str, Any] | None:
    """Return the last successful payload with staleness metadata, or None."""
    with _lock:
        if _last_success is None or _last_success_at is None:
            return None
        age = now() - _last_success_at
        if max_age is not None and age > max_age:
            return None
        payload = dict(_last_success)
        payload["age_seconds"] = int(age)
        payload["updated_at_epoch"] = _last_success_at
        return payload


def get_last_error() -> dict[str, Any] | None:
    """Return recent error metadata (reason only, never credentials)."""
    with _lock:
        if not _last_error_reason or _last_error_at is None:
            return None
        return {
            "reason": _last_error_reason,
            "age_seconds": int(now() - _last_error_at),
        }


def reset() -> None:
    """Clear all in-memory state (used on uninstall)."""
    global _last_success, _last_success_at, _last_error_reason, _last_error_at
    with _lock:
        _last_success = None
        _last_success_at = None
        _last_error_reason = None
        _last_error_at = None


def _resolve_secret(config_value: Any, secret_keys: tuple[str, ...]) -> str:
    """Resolve a credential: explicit plugin setting first, then A0 secrets.

    The secrets fallback uses the official Agent Zero SecretsManager which
    reads usr/secrets.env (and project secrets); values stay server-side.
    """
    value = str(config_value or "").strip()
    if value:
        return value
    try:
        from helpers.secrets import SecretsManager

        secrets = SecretsManager.get_instance().load_secrets()
        for key in secret_keys:
            secret = str(secrets.get(key) or "").strip()
            if secret:
                return secret
    except Exception:
        # Secrets subsystem unavailable in this context; treat as not set.
        pass
    return ""


def load_settings() -> dict[str, Any]:
    """Load and normalize effective plugin settings."""
    config = get_plugin_config(PLUGIN_NAME) or {}

    interval = config.get("refresh_interval_seconds", DEFAULT_INTERVAL)
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        interval = DEFAULT_INTERVAL
    if interval not in ALLOWED_INTERVALS:
        interval = DEFAULT_INTERVAL

    def _usd(name: str, fallback: float) -> float:
        try:
            value = float(config.get(name, fallback))
            return value if value >= 0 else fallback
        except (TypeError, ValueError):
            return fallback

    low = _usd("low_credit_warning", 5.0)
    critical = _usd("critical_credit_warning", 1.0)
    if critical > low:
        critical = low

    return {
        "management_key": _resolve_secret(
            config.get("openrouter_management_key"),
            ("OPENROUTER_MANAGEMENT_KEY",),
        ),
        "api_key": _resolve_secret(
            config.get("openrouter_api_key"),
            ("OPENROUTER_API_KEY",),
        ),
        "refresh_interval_seconds": interval,
        "low_credit_warning": low,
        "critical_credit_warning": critical,
        "show_balance_in_ui": bool(config.get("show_balance_in_ui", True)),
    }
