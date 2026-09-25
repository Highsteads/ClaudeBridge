---
title: Upgrading to 3.0
nav_order: 12
---

# Upgrading to 3.0

Claude Bridge 3.0 cut the tool list from 169 in 2.27 to 69. Most of the difference is families of
near-identical tools merged into one tool that takes an `action` or `kind`, so nothing you could
do before has gone except the items listed at the end. Claude reads the new tool list when it
connects, so in conversation you need do nothing. This page is for anything you have written
down that names a tool: a saved prompt, a skill, a permission allow-list, a script.

Tools not listed here kept their names and arguments.

## Devices

| Old tool | 3.0 |
|---|---|
| `device_turn_on`, `device_turn_off` | `device_control(device, action="on"/"off", delay, duration)` |
| `device_toggle` | `device_control(device, action="toggle")` |
| `device_set_brightness` | `device_control(device, action="brightness", value)` |
| `dimmer_brighten_by`, `dimmer_dim_by` | `device_control(device, action="brighten"/"dim", value)` |
| `set_color` | `device_control(device, action="color", color / red, green, blue, white, white_temperature)` |
| `request_status_update`, `beep_device`, `ping_device` | `device_control(device, action="status_request"/"beep"/"ping")` |
| `reset_energy_accumulator` | `device_control(device, action="reset_energy")` |
| `device_control(name, ...)` | `device_control(device, ...)`: `device` takes an id or a name |
| `set_heat_setpoint`, `set_cool_setpoint`, `increase_/decrease_heat_setpoint`, `increase_/decrease_cool_setpoint`, `set_hvac_mode`, `set_fan_mode` | `thermostat_control(device, heat_setpoint, cool_setpoint, heat_delta, cool_delta, hvac_mode, fan_mode)` |
| `set_fan_speed`, `speedcontrol_set_index`, `speedcontrol_increase`, `speedcontrol_decrease` | `speed_control(device, level / index / step)` |
| `sprinkler_run`, `_stop`, `_pause`, `_resume`, `_next_zone`, `_previous_zone`, `_set_zone` | `sprinkler_control(device, action, zone)` |
| `lock_device`, `unlock_device` | `lock_control(device, action="lock"/"unlock", code)` |
| `all_lights_on`, `all_lights_off`, `all_devices_off` | `all_devices(action="lights_on"/"lights_off"/"all_off")` |
| `get_devices_by_type`, `get_devices_by_state` | `list_devices(device_type, state_filter)` |
| `duplicate_device` | `duplicate(kind="device", id, new_name)` |
| `move_device_to_folder` | `move_to_folder(kind="device", id, folder_id)` |
| `create_device_folder`, `delete_device_folder` | `create_folder(kind="device", ...)`, `delete_folder(kind="device", ...)` |
| `device_remove_delayed_actions` | `remove_delayed_actions(kind="device", id)` |

## Triggers, schedules and action groups

| Old tool | 3.0 |
|---|---|
| `get_trigger_details`, `get_schedule_details`, `get_action_group_details`, `get_action_group_by_id` | `get_automation(kind, id, include_scripts)` |
| `update_trigger`, `update_schedule`, `update_action_group` | `update_automation(kind, id, fields)` |
| `enable_trigger`, `disable_trigger`, `enable_schedule`, `disable_schedule` | `set_enabled(kind, id, enabled, delay_seconds, duration_seconds)` |
| `delete_trigger`, `delete_schedule`, `delete_action_group` | `delete_automation(kind, id, confirm)` |
| `duplicate_schedule`, `duplicate_action_group` | `duplicate(kind, id, new_name)` |
| `move_trigger_to_folder` | `move_to_folder(kind="trigger", id, folder_id)` |
| `trigger_get_dependencies`, `schedule_get_dependencies`, `action_group_get_dependencies` | `get_dependencies(kind, id)` |
| `dependency_map` | `find_automation_references` |
| `schedule_remove_delayed_actions`, `remove_all_delayed_actions` | `remove_delayed_actions(kind="schedule"/"all", id)` |

## Variables

| Old tool | 3.0 |
|---|---|
| `variable_move_to_folder` | `move_to_folder(kind="variable", id, folder_id)` |
| `create_variable_folder`, `delete_variable_folder` | `create_folder(kind="variable", ...)`, `delete_folder(kind="variable", ...)` |

## Reports, checks and server details

| Old tool | 3.0 |
|---|---|
| `energy_status`, `heating_status`, `security_status`, `home_status_report` | `home_status(section="energy"/"heating"/"security"/"report")` |
| `energy_daily_summary`, `energy_compare` | `energy_history(days, compare)` |
| `audit_home`, `find_devices_in_error`, `find_low_battery`, `find_stale_devices`, `audit_variables`, `find_conflicts`, `find_orphaned_scripts`, `find_orphaned_plugin_data`, `get_deprecated_elements`, `audit_api_coverage`, `find_large_files` | `audit(check="home"/"errors"/"low_battery"/"stale"/"variables"/"conflicts"/"orphaned_scripts"/"orphaned_plugin_data"/"deprecated"/"api_coverage"/"large_files")` |
| `get_indigo_paths`, `get_web_server_url`, `get_reflector_url`, `get_reflector_status`, `get_latitude_longitude`, `calculate_sunrise`, `calculate_sunset` | `server_info(date_iso)` |
| `list_control_pages`, `get_control_page` | `control_pages(page_id)` |

## Scripts and plugins

| Old tool | 3.0 |
|---|---|
| `create_script` | `write_script(name, content, create=true)` |
| `list_script_backups` | `list_python_scripts(backups_for=name)` |
| `get_plugin_by_id` | `get_plugin_status(plugin_id)` |
| `plugin_validate_xml`, `plugin_node_check_html`, `plugin_lint`, `plugin_diff_source_vs_installed`, `plugin_show_packages_versions` | `plugin_check(plugin_name, checks)`, all five checks by default |
| `zwave_send_config_parameter`, `zwave_start_network_optimize`, `zwave_stop_network_optimize`, `zwave_enter_inclusion_mode`, `zwave_enter_exclusion_mode`, `zwave_exit_inclusion_exclusion_mode` | `zwave(action, ...)` |

## Changed behaviour

- **`execute_indigo_python` and `run_script` run as background jobs.** A run that finishes
  within `wait_seconds` (default 5) replies exactly as before. A longer one replies
  `{"status": "running", "job_id": ...}` straight away; call the same tool again with that
  `job_id` to collect the result. This stops a long run freezing Indigo's web server, and every
  dashboard with it, for as long as it takes.

## Removed

- `analyze_historical_data`, which needed InfluxDB and an Anthropic API key. Use
  `device_history`, which reads the SQL Logger.
- `remember`, `recall`, `recall_topics`, `forget`. Claude Code keeps its own memory.
- `subscribe`, `unsubscribe`, `get_events`, `list_subscriptions`, `clear_events`. An MCP client
  cannot be told about a change between messages, so the queue was never read. Outbound
  webhooks (`webhook_create` and friends) do that job and are unchanged.
- `energy_log_days`, `server_speak`, `scaffold_automation_script`.

Claude Bridge no longer needs an Anthropic API key or any extra Python packages. Settings left
over from the removed features, including a stored API key or InfluxDB password, are deleted
from the plugin's preferences the first time 3.0 starts.
