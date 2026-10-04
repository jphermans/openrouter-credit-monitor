"""Mask OpenRouter Credit Monitor secrets in the plugins settings API response.

Runs at the implicit extension point api.plugins.Plugins._get_config.end so
stored credentials are replaced with a mask before the settings modal ever
receives them.
"""

from helpers.extension import Extension

MASK = "***"
SECRET_KEYS = ("openrouter_management_key", "openrouter_api_key")
PLUGIN_NAME = "openrouter_credit_monitor"


class MaskCreditMonitorSecrets(Extension):
    def execute(self, data: dict, **kwargs):
        result = data.get("result")
        if not isinstance(result, dict) or not result.get("ok"):
            return
        payload = result.get("data")
        if not isinstance(payload, dict):
            return
        # Only touch this plugin's config payloads.
        input_data = (data.get("kwargs") or {}).get("input") or {}
        # The handler is a method; recover plugin_name from original args.
        plugin_name = ""
        if isinstance(input_data, dict):
            plugin_name = str(input_data.get("plugin_name") or "")
        if not plugin_name:
            # When args-based call, inspect positional input dict.
            args = data.get("args") or ()
            for arg in args:
                if isinstance(arg, dict) and arg.get("plugin_name"):
                    plugin_name = str(arg.get("plugin_name"))
                    break
        if plugin_name != PLUGIN_NAME:
            return
        for key in SECRET_KEYS:
            if str(payload.get(key) or "").strip():
                payload[key] = MASK
        data["result"] = result
