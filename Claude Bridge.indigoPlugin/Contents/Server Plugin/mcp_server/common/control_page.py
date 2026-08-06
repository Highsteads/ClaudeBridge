"""Decode a raw control-page reply into something a human can read.

Control pages are the one part of Indigo the IOM never covered — the scripting
guide says outright that they did not make it into v1 — so `indigo.ControlPage`
carries the page's own properties (name, size, background) and nothing at all
about what is ON it. The layout is only reachable through the undocumented
`indigo.rawServerRequest("GetControlPage", ...)`, which is exactly what
Perceptive Automation's own utils.py uses to render a page.

The numeric codes below are transcribed from that same utils.py
(IndigoPluginHost3.app/Contents/Resources/PlugIns/utils.py), which ships as
readable source, so they are PA's values rather than anything inferred from
observed data. Kept as plain dicts, not imports of indigo.utils, so the decoding
is testable with no Indigo present.
"""

from typing import Any, Dict, Optional, Tuple

# indigo.utils.FULL_PAGE_FLAGS — calc_getPage_flags(False, True, False, False).
# Asks for the page elements and skips the actions attached to them.
FULL_PAGE_FLAGS = 65538

# PageElementTypeEnum
PAGE_ELEMENT_TYPES: Dict[int, str] = {
    0:   "none",
    1:   "device",
    2:   "variable",
    3:   "video",
    4:   "action_group",
    5:   "control_page_link",
    80:  "folder_filter",
    100: "image_text",
    101: "refreshing_image",
    200: "server_status",
    201: "server_icon",
}

# ServerActionClassEnum
SERVER_ACTION_CLASSES: Dict[int, str] = {
    0: "base", 1: "control_devices", 2: "control_sprinkler",
    3: "control_thermostat", 4: "control_io", 5: "control_ir",
    6: "control_video", 7: "control_speed_control", 8: "control_sensor",
    9: "control_general", 100: "execute_group", 101: "execute_script",
    102: "execute_scene", 200: "enable_disable", 201: "modify_variable",
    202: "remove_delayed_actions", 300: "send_email",
    301: "reset_interface_conn", 999: "plugin", 9999: "is_multiple",
}

# CaptionPlacementEnum — note 3 is deliberately absent in Indigo's own enum.
CAPTION_PLACEMENTS: Dict[int, str] = {
    0: "center_above_image", 1: "center_on_image", 2: "center_below_image",
    4: "left_of_image", 5: "right_of_image",
}

# TextAlignmentTypeEnum
TEXT_ALIGNMENTS: Dict[int, str] = {0: "left", 1: "right", 2: "center"}

# Which Indigo collection a page element's TargetElemID points into. Element
# types absent here (server status, image/text, video…) carry no target at all.
TARGET_COLLECTION: Dict[str, str] = {
    "device":            "devices",
    "variable":          "variables",
    "action_group":      "actionGroups",
    "control_page_link": "controlPages",
}


def _pair(value: Any) -> Optional[Tuple[int, int]]:
    """Parse Indigo's "12 34" geometry strings into a pair of ints."""
    if not isinstance(value, str):
        return None
    parts = value.split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _named(table: Dict[int, str], code: Any) -> Optional[str]:
    """Look a code up, returning None rather than inventing a name for it.

    An unrecognised code means Indigo has grown a value we do not know about;
    saying so honestly beats labelling it as something it is not, and the raw
    code is always kept alongside so nothing is lost.
    """
    return table.get(code) if isinstance(code, int) else None


def describe_element(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise one raw PageElemList entry into a readable dict.

    Every decoded field keeps its raw code beside it, so an element type we do
    not recognise still reports its number rather than vanishing.
    """
    kind_code = raw.get("ControlType")
    kind = _named(PAGE_ELEMENT_TYPES, kind_code)

    out: Dict[str, Any] = {
        "index": raw.get("ServerIndex"),
        "type": kind or f"unknown({kind_code})",
        "type_code": kind_code,
    }

    pos, size = _pair(raw.get("Position")), _pair(raw.get("Size"))
    if pos:
        out["position"] = {"x": pos[0], "y": pos[1]}
    if size:
        out["size"] = {"width": size[0], "height": size[1]}

    caption = raw.get("CaptionName")
    if caption:
        out["caption"] = caption

    # The target is the useful part: what this control actually points at.
    if raw.get("TargetElemID") is not None:
        out["target"] = {
            "id": raw.get("TargetElemID"),
            "name": raw.get("TargetElemName"),
            "state": raw.get("TargetElemSubKey"),
            "collection": TARGET_COLLECTION.get(kind or ""),
        }

    if raw.get("ValueLong") is not None:
        out["displayed_value"] = raw.get("ValueLong")

    action_class = raw.get("ServerActionClass")
    if action_class is not None:
        out["action_class"] = (_named(SERVER_ACTION_CLASSES, action_class)
                               or f"unknown({action_class})")
        out["action_class_code"] = action_class

    if raw.get("ImageFileName"):
        out["image"] = raw["ImageFileName"]

    placement = _named(CAPTION_PLACEMENTS, raw.get("CaptionPlacement"))
    if placement:
        out["caption_placement"] = placement
    alignment = _named(TEXT_ALIGNMENTS, raw.get("StateTextAlignment"))
    if alignment:
        out["text_alignment"] = alignment

    return out
