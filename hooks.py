"""Lifecycle and settings hooks for the OpenRouter Credit Monitor plugin."""

from copy import deepcopy

from usr.plugins.openrouter_credit_monitor.helpers import state

SECRET_KEYS = ("openrouter_management_key", "openrouter_api_key")
MASK = "***"


def _normalize(settings: dict | None) -> dict:
    config = deepcopy(settings or {})
    for key in SECRET_KEYS:
        value = str(config.get(key) or "").strip()
        # Keep the stored value unless the UI submits the unchanged mask.
        config[key] = "" if value == MASK else value
    try:
        interval = int(config.get("refresh_interval_seconds", state.DEFAULT_INTERVAL))
    except (TypeError, ValueError):
        interval = state.DEFAULT_INTERVAL
    config["refresh_interval_seconds"] = (
        interval if interval in state.ALLOWED_INTERVALS else state.DEFAULT_INTERVAL
    )
    for name, fallback in (("low_credit_warning", 5.0), ("critical_credit_warning", 1.0)):
        try:
            value = float(config.get(name, fallback))
            config[name] = value if value >= 0 else fallback
        except (TypeError, ValueError):
            config[name] = fallback
    if float(config["critical_credit_warning"]) > float(config["low_credit_warning"]):
        config["critical_credit_warning"] = config["low_credit_warning"]
    config["show_balance_in_ui"] = bool(config.get("show_balance_in_ui", True))
    return config


def _merge_with_stored(settings: dict, stored: dict | None) -> dict:
    """Re-attach stored secrets when the UI submits the unchanged mask.

    Mask ("***") keeps the stored secret; an explicitly emptied field clears
    it, and any other non-empty value replaces it.
    """
    merged = dict(settings)
    stored = stored or {}
    for key in SECRET_KEYS:
        submitted = str(merged.get(key) or "").strip()
        if submitted == MASK:
            merged[key] = str(stored.get(key) or "").strip()
    return merged


def _load_stored_settings() -> dict:
    from helpers.plugins import get_plugin_config
    from helpers import files, plugins

    # Read the raw stored config.json (without recursion into hooks).
    entries = plugins.find_plugin_assets(
        plugins.CONFIG_FILE_NAME,
        plugin_name=state.PLUGIN_NAME,
        project_name="",
        agent_profile="",
        only_first=True,
    )
    if entries:
        path = entries[0].get("path", "")
        if path and files.exists(path):
            import json

            try:
                data = json.loads(files.read_file(path) or "{}")
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    return {}


def get_plugin_config(default=None, hook_context=None, **kwargs):
    """Runtime config; redacted for UI callers so secrets never render."""
    config = _normalize(default)
    caller = (hook_context or {}).get("caller", "api")
    if caller == "ui":
        for key in SECRET_KEYS:
            if str(config.get(key) or "").strip():
                config[key] = MASK
    return config


def save_plugin_config(settings=None, default=None, **kwargs):
    """Persist settings; keep existing secrets when the UI submits masks."""
    submitted = _normalize(settings if isinstance(settings, dict) else default)
    stored = _load_stored_settings()
    merged = _merge_with_stored(submitted, stored)
    return _normalize(merged)


def install():
    """Idempotent post-install/update initialization.

    No external dependencies are required: httpx ships with the framework.
    """
    state.reset()
    return True


def pre_update():
    """Clear in-memory state before a plugin code update."""
    state.reset()
    return True


def uninstall():
    """Remove only plugin-owned resources.

    Credentials live in the user-space config.json / secrets.env managed by
    Agent Zero; this plugin removes only its own in-memory state.
    """
    state.reset()
    return True
