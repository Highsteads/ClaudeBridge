#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    zwave.py
# Description: Z-Wave network management — configuration parameters, mesh
#              optimisation, and pairing or unpairing hardware.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from ..registry import tool
from ._schema import bad_choice, boolean, enum, id_or_name, integer, refuse, unused_args

_ACTIONS = {
    "set_config_parameter":     ("device_id", "param_index", "param_size", "param_value",
                                 "wait_for_ack"),
    "start_optimize":           ("device_id",),
    "stop_optimize":            (),
    "enter_inclusion":          ("use_encryption",),
    "enter_exclusion":          (),
    "exit_inclusion_exclusion": (),
}


@tool("zwave", scope="admin", invalidates={"device"},
      description=(
          "Manage the Z-Wave network. ADMIN. set_config_parameter: program a device "
          "(device_id, param_index, param_size = byte width 1, 2 or 4, param_value; "
          "wait_for_ack default true) — tune motion sensitivity, report intervals and so on "
          "from the device manual's parameter numbers. start_optimize: heal the mesh, the whole "
          "network or around device_id; stop_optimize ends it. enter_inclusion: put the "
          "controller into inclusion mode to ADD hardware (use_encryption for S0), then the "
          "user presses the device's pairing button. enter_exclusion: REMOVE a device. "
          "exit_inclusion_exclusion: cancel either mode."),
      properties={
          "action": enum(list(_ACTIONS), "What to do"),
          "device_id": id_or_name("Device id (set_config_parameter; optional for "
                                  "start_optimize)"),
          "param_index": integer("Config parameter number"),
          "param_size": integer("Byte width: 1, 2 or 4"),
          "param_value": integer("Value to set"),
          "wait_for_ack": boolean("Wait for the device to acknowledge (default true)"),
          "use_encryption": boolean("Use S0 encryption during inclusion (default false)"),
      },
      required=["action"])
def zwave(ctx, action, device_id=None, param_index=None, param_size=None, param_value=None,
          wait_for_ack=None, use_encryption=None):
    if action not in _ACTIONS:
        return bad_choice("action", action, _ACTIONS)
    given = {"device_id": device_id, "param_index": param_index, "param_size": param_size,
             "param_value": param_value, "wait_for_ack": wait_for_ack,
             "use_encryption": use_encryption}
    stray = unused_args("zwave", action, given, _ACTIONS[action])
    if stray:
        return stray
    ext = ctx.extended_tools_handler
    if action == "set_config_parameter":
        missing = [k for k in ("device_id", "param_index", "param_size", "param_value")
                   if given[k] is None]
        if missing:
            return refuse(f"zwave: set_config_parameter needs {', '.join(missing)}")
        return ext.zwave_send_config_parameter(
            device_id, param_index=param_index, param_size=param_size,
            param_value=param_value, wait_for_ack=True if wait_for_ack is None else wait_for_ack)
    if action == "start_optimize":
        return ext.zwave_start_network_optimize(device_id)
    if action == "enter_inclusion":
        return ext.zwave_enter_inclusion_mode(use_encryption=bool(use_encryption))
    method = {"stop_optimize": "zwave_stop_network_optimize",
              "enter_exclusion": "zwave_enter_exclusion_mode",
              "exit_inclusion_exclusion": "zwave_exit_inclusion_exclusion_mode"}[action]
    return getattr(ext, method)()
