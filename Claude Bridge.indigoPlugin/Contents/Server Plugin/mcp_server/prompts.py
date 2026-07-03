"""MCP prompts — reusable, one-click task templates.

Claude Bridge advertised the `prompts` capability but shipped none. These turn
common household tasks into guided starting points: the client sees a short menu
(prompts/list) and picks one (prompts/get), which returns a ready instruction
that steers Claude through the right Claude Bridge tools. Purely additive — no
device access here, just text templates.

Each entry: name, description, optional arguments (name/description/required),
and a `template` whose {placeholders} are filled from the supplied arguments.
"""

from typing import Any, Dict, List, Optional

_PROMPTS: Dict[str, Dict[str, Any]] = {
    "house_state": {
        "description": "Full snapshot of the house right now — presence, openings, alerts, energy.",
        "arguments": [],
        "template": (
            "Give me a concise picture of the house right now. Use home_status (and "
            "search_entities / get_devices_by_state as needed) to cover: who's home "
            "(presence devices), any open doors or windows, any devices in error or "
            "offline, low batteries, and the live energy flow (solar, battery SOC, grid "
            "import/export). Lead with anything that needs attention, then the rest."
        ),
    },
    "energy_day_review": {
        "description": "Review today's solar / battery / grid performance and self-sufficiency.",
        "arguments": [],
        "template": (
            "Review today's energy performance. Use energy_status and the Sigenergy "
            "Inverter + Battery Manager device states (and energy_status variables) to "
            "report: PV generated, home consumption, grid import/export, battery SOC "
            "range, and self-sufficiency. Note the current tariff and whether the "
            "battery strategy looks right for the rest of the day. Favour keeping kWh "
            "in the battery over exporting (self-sufficiency is the top KPI)."
        ),
    },
    "battery_sweep": {
        "description": "Check every battery device across the estate and flag anything low.",
        "arguments": [
            {"name": "threshold", "description": "Low-battery percentage threshold (default 20)", "required": False},
        ],
        "template": (
            "Do a battery sweep of the whole estate. Call find_low_battery with "
            "threshold={threshold}. List anything at or below it, worst first, with the "
            "device name and which room it's in. If nothing is low, say so plainly."
        ),
    },
    "recover_wedged_plugin": {
        "description": "Diagnose and recover a plugin that seems stuck.",
        "arguments": [
            {"name": "plugin", "description": "Plugin name or bundle id that seems stuck", "required": True},
        ],
        "template": (
            "The plugin '{plugin}' seems stuck. Diagnose it: check get_plugin_status, "
            "scan query_event_log for its recent errors/tracebacks, and check whether "
            "its devices have gone stale (find_stale_devices / lastSuccessfulComm). "
            "Explain what you find. Only if it's genuinely wedged, propose restarting "
            "it (restart_plugin) — and never restart Claude Bridge itself from here."
        ),
    },
    "zwave_tune_sensor": {
        "description": "Guided help to set a Z-Wave configuration parameter on a device.",
        "arguments": [
            {"name": "device", "description": "Z-Wave device name or id to tune", "required": True},
        ],
        "template": (
            "I want to change a Z-Wave configuration parameter on '{device}'. First find "
            "the device (search_entities / get_device_by_name) and confirm it's Z-Wave. "
            "Ask me which parameter (number), its byte size (1/2/4) and the value if I "
            "haven't said — check the device manual for the parameter map. Then set it "
            "with zwave_send_config_parameter. Some battery devices must be woken first, "
            "and a few parameters only take effect after a re-inclusion — mention that if relevant."
        ),
    },
}


def list_prompts() -> List[Dict[str, Any]]:
    """Return the prompts/list payload."""
    out = []
    for name, p in _PROMPTS.items():
        out.append({
            "name": name,
            "description": p["description"],
            "arguments": p.get("arguments", []),
        })
    return out


def get_prompt(name: str, arguments: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Return the prompts/get payload for *name*, or None if unknown."""
    p = _PROMPTS.get(name)
    if not p:
        return None
    args = dict(arguments or {})
    # Fill declared arguments, defaulting the optional ones sensibly.
    fmt = {"threshold": args.get("threshold", 20)}
    for a in p.get("arguments", []):
        fmt[a["name"]] = args.get(a["name"], fmt.get(a["name"], f'<{a["name"]}>'))
    try:
        text = p["template"].format(**fmt)
    except (KeyError, IndexError):
        text = p["template"]
    return {
        "description": p["description"],
        "messages": [
            {"role": "user", "content": {"type": "text", "text": text}}
        ],
    }
