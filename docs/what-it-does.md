---
title: What it does
nav_order: 3
---

# What it does

Claude Bridge gives Claude Code **71 MCP tools**, enough to read and change
anything on a running Indigo server. They fall into the groups below, and every
tool is listed by name in the [Tool reference](tools.md).

### Devices
- **List, search, and inspect** every Indigo device — by ID, by name (exact or
  partial, capitals optional), by type (relay, dimmer, sensor, thermostat,
  speed control, sprinkler, …), or by current state, all through
  `list_devices`, `get_device_by_id`, `get_device_by_name` and `search_entities`.
  Long lists come a page at a time, sorted by name: the devices, variables,
  triggers, schedules and action groups lists each say how many there are and
  where the next page starts.
- **Search in plain English** across devices, variables, and action groups —
  asking for "light" finds your lamps and dimmers, "plug" finds your sockets.
  Results are kept brief by default so answers come back quickly, with the
  full detail available when you ask for it.
- **Control devices with one tool** — `device_control` does on / off / toggle,
  brightness, brighten and dim, colour and colour temperature, a status poll,
  beep and ping. Give it a device id, or just the name: a name must match one
  device exactly or confidently, and if it could mean two, nothing is switched
  and Claude is shown the candidates instead.
- **Timed actions** — "turn the fan on for ten minutes" or "switch that off in
  half an hour" is a single request. Indigo's own delayed-action engine does the
  timing, so it keeps working even if Claude has long since gone.
  `remove_delayed_actions` cancels a pending one on one device without
  disturbing anything else.
- **Fans, sprinklers and locks** — `speed_control` (level, speed index or a
  step), `sprinkler_control` (run, stop, pause, resume, zones) and
  `lock_control`, which is admin-only because it is physical security.

### Heating / HVAC
- `home_status` with `section='heating'` gives the per-zone snapshot.
  `thermostat_control` sets absolute setpoints, steps them up or down, and
  switches HVAC and fan modes (off / heat / cool / auto / program*) on any
  Indigo thermostat (Evohome, RAMSES, Z-Wave, etc.) — any combination in one
  call, and the reply lists what was done.

### Energy intelligence
- Live solar / battery / grid status (`home_status`, `section='energy'`), and
  `energy_history` for day-by-day totals from SigenEnergyManager's own daily
  record, or two periods compared side by side.
- **Reset an energy total** — `device_control` with `action='reset_energy'`
  zeroes the lifetime kWh count on an energy-metering plug when you want to
  start a fresh measurement. The old total cannot be put back, so this one
  action needs an admin key.

### Variables & action groups
- Create, read, update, and organise variables and their folders.
- List, inspect, and run action groups.

### Triggers & schedules
- List any trigger or schedule, read its full definition with
  `get_automation`, enable or disable it with `set_enabled` (optionally for a
  set time), edit its name, description or a trigger's event with
  `update_automation`.
- **`fire_indigo_event`** — fires the Claude Bridge plugin's custom
  `claudeEvent` channel with a JSON payload that Indigo Triggers can read via
  `%%eventData:name%%`.
- **`fire_trigger`** — executes an Indigo trigger directly by ID or name via
  `indigo.trigger.execute()`.

### Plugins
- Enumerate every installed plugin (version + enabled/running state), check one
  with `get_plugin_status`, and restart. `plugin_check` runs the development
  checks — XML naming rules, `node --check` on inline scripts, the lint, the
  source-against-installed diff and the bundled library versions — in one call.

### Scripts (auto-backed-up)
- Read, write (with timestamped auto-backup, max 5 per script), create with
  `write_script(create=true)`, archive ("delete" moves to
  `_backups/_archived/`), and run scripts in Indigo's Python context. Covers
  both the `Scripts` and `Python Scripts` folders automatically.
  `list_python_scripts` lists them, or one script's backups.
- **`run_script`** auto-injects `indigo` into the script's globals (matching
  Indigo's GUI action runner) so ad-hoc scripts don't need their own
  `import indigo`.
- **Long runs don't hold anything up.** A script — or a block of Python — that
  takes longer than a few seconds carries on in the background and Claude gets
  a job id to collect the result with. Before 3.0 the whole web server waited
  for it, so every dashboard froze until it finished.

### Event log
- Search the Indigo event log by keyword, device, plugin, or time — including
  older entries beyond what the Indigo window shows, because it reads the log
  files themselves.

### Event webhooks — the home calls out (optional, off by default)
- Have Indigo send a message to a web address you run the moment something
  happens — "the next time a leak sensor trips", "if the battery drops below
  20%", "when the garage has been open for ten minutes".
- It is deliberately careful about where it will send: every destination has
  to be on your approved list, anything pointing back inside your own network
  is refused, and every message is signed so your receiver can be certain it
  really came from your system. The whole feature ships switched off until
  you turn it on. There's a small example receiver in `examples/` to get you
  going in minutes.
- A destination that fails five events in a row is switched off so it cannot
  pile up retries. Once the receiver is back, *Plugins > Claude Bridge >
  Re-enable Quarantined Event Webhooks* turns those subscriptions on again.

### Plugin-provided tools — other plugins bring their own

Any Indigo plugin can add tools of its own to Claude Bridge by shipping one JSON file, `Contents/Resources/mcp-manifest.json`, in its bundle. Claude Bridge finds the file on its own, lists the tools to Claude under that plugin's prefix (the Dashboards plugin's come out as `dashboards_get_status`, `dashboards_set_camera` and so on), and forwards each call to the plugin, which does the work and answers. Nothing to configure on either side, and a plugin picked up the moment it starts. The format is the provider-manifest contract published by [mlamoure's Indigo MCP Server](https://github.com/mlamoure/indigo-mcp-server), so a plugin written for that server works here unchanged, and one written for Claude Bridge works there. Tools a plugin marks as writes are governed by one switch under Configure, *Allow plugin-provided tools to make changes*, on by default; read tools always work. How to make your own plugin a provider is on [its own page](providers.md).

### Audit, health, diagnostics
- **`audit`** — one tool, one check at a time: the whole-system overview,
  devices in error, low batteries, devices that have gone quiet, empty or
  unused variables, naming or wiring conflicts, scripts that name deleted ids,
  leftover data from uninstalled plugins, deprecated objects, oversized files,
  and, after an Indigo upgrade, anything new in the API worth bridging.
- **"What would break if I deleted this?"** — for any device or variable,
  `find_automation_references` lists everything that refers to it before you
  touch it; `get_dependencies` gives Indigo's own view for any kind of object.
- `system_health` for the Mac itself, and `server_info` for the paths, web
  server and Reflector addresses, location and today's sunrise and sunset.

### Reporting
- **`home_status`** with `section='report'` — prose-markdown narrative of the
  whole home, configurable by section (energy, heating, security, devices,
  alerts, automation).
- **`device_history`** — a device's recent history from the SQL Logger
  database, for trends and "when did this last change". SQLite SQL Logger
  only; an install that logs to PostgreSQL gets an error.
- **`variable_history`** — the same for a variable, by id or name, with the
  value it held when the window opened. Its summary says how long each value
  held, which answers "how long was the heating on today", and gives a
  time-weighted average for a number. A deleted variable's history can still
  be read by its old id.

### Notifications
- `send_email` via Indigo's first SMTP device (admin scope, because it can
  reach any address), `send_notification` via Pushover to your own devices
  (priority, sound, title, body), and `log_message` for writing a line
  straight to the Indigo event log.

### Folders & server info
- `create_folder` for device and variable folders (asking twice is harmless —
  it just finds the existing one), and `delete_folder` to remove one again. A
  folder with things still in it is politely refused unless you explicitly say
  you mean the contents to go too.
- `duplicate` a device, schedule or action group, and `move_to_folder` a
  device, variable or trigger.
- Whole-house broadcasts with `all_devices` — Indigo's native all-lights-on,
  all-lights-off and all-devices-off commands. Worth knowing: these only
  reach devices Indigo talks to directly (Z-Wave and the like) — devices
  that belong to plugins such as zigbee2mqtt or Shelly don't hear
  broadcasts, and Claude will tell you so rather than pretend.
- Look up your Reflector remote-access address (`server_info`).

### Scripting shell — ADMIN scope
- **`execute_indigo_python`** — runs arbitrary Python in this plugin's
  Indigo context via in-process `exec()`. `mode='exec'` returns captured
  stdout/stderr, `mode='eval'` returns the expression's repr. Use it for
  one-shot Indigo API calls no dedicated tool covers. Treat it as full
  code execution on the Indigo server. Like `run_script`, a long run goes to
  the background and hands back a job id.
- **`execute_plugin_menu_item`** — clicks a plugin's `<MenuItem>` under the
  Indigo client's Plugins menu via AppleScript GUI scripting — the only
  known way to fire a third-party plugin's menu callback from outside.
  Requires the Indigo GUI running plus System Events permission.

For how the tools are kept from doing harm — read, write and admin, the delete switch, the webhook
firewall — see [Security](security.md).
