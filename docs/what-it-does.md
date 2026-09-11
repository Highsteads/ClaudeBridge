---
title: What it does
nav_order: 3
---

# What it does

Claude Bridge gives Claude Code **168 MCP tools**, enough to read and change
anything on a running Indigo server. They fall into the groups below, and every
tool is listed by name in the [Tool reference](tools.md).

### Devices
- **List, search, and inspect** every Indigo device — by ID, by name (exact or
  partial, capitals optional), by type (relay, dimmer, sensor, thermostat,
  speed control, sprinkler, …), or by current state.
- **Search in plain English** across devices, variables, and action groups —
  asking for "light" finds your lamps and dimmers, "plug" finds your sockets.
  Results are kept brief by default so answers come back quickly, with the
  full detail available when you ask for it.
- **Control devices** — on / off / toggle, brightness, colour and colour
  temperature, fan speed, lock / unlock, or nudge a device to report in.
- **Timed actions** *(new in 2.9.0)* — "turn the fan on for ten minutes" or
  "switch that off in half an hour" is a single request. Indigo's own
  delayed-action engine does the timing, so it keeps working even if Claude
  has long since gone. There's a matching tool to cancel a pending timed
  action on one device without disturbing anything else.
- **Identify and check devices** *(new in 2.9.0)* — ask a device to beep so
  you can find it on the shelf, or ping it to check it still answers on the
  network.
- **One-call name-and-action shortcut** — say what you want done to which
  device and it happens in a single round trip.

### Heating / HVAC
- Per-zone snapshot, absolute setpoints, incremental bumps, and HVAC mode
  switching (off / heat / cool / auto / program*) across any Indigo thermostat
  device (Evohome, RAMSES, Z-Wave, etc.).

### Energy intelligence
- Live solar / battery / grid status, plus day-by-day analysis from
  SigenEnergyManager's log files: list available days, daily summary
  (imports, exports, solar, battery trace), or compare days side-by-side.
- **Reset an energy total** *(new in 2.9.0)* — zero the lifetime kWh count on
  an energy-metering plug when you want to start a fresh measurement.

### Variables & action groups
- Create, read, update, and organise variables and their folders.
- List, inspect, and run action groups.

### Triggers & schedules
- List, enable, and disable any trigger or schedule.
- **`fire_indigo_event`** — fires the Claude Bridge plugin's custom
  `claudeEvent` channel with a JSON payload that Indigo Triggers can read via
  `%%eventData:name%%`.
- **`fire_trigger`** — executes an Indigo trigger directly by ID or name via
  `indigo.trigger.execute()`.

### Plugins
- Enumerate every installed plugin (version + enabled/running state), get
  detail by ID, query status, and restart.

### Scripts (auto-backed-up)
- Read, write (with timestamped auto-backup, max 5 per script), create,
  archive ("delete" moves to `_backups/_archived/`), and run scripts in
  Indigo's Python context. Covers both the `Scripts` and `Python Scripts`
  folders automatically.
- **`scaffold_automation_script`** — generates a ready-to-run script in the
  consistent house style every script here uses: a documented file header
  (what it does, author, date, version), UPPER_CASE named constants for every
  device and variable ID so no magic numbers appear in the logic, a
  millisecond-timestamped `log()` helper so output lines up with the plugins'
  logs, and error handling around anything that can fail — with every ID and
  name resolved live from your actual Indigo server, so the script is correct
  before you've even read it.
- **`run_script`** auto-injects `indigo` into the script's globals (matching
  Indigo's GUI action runner) so ad-hoc scripts don't need their own
  `import indigo`.

### Event log & live watching
- Search the Indigo event log by keyword, device, plugin, or time — including
  older entries beyond what the Indigo window shows, because it reads the log
  files themselves.
- **Watch things as they happen** — ask Claude to keep an eye on a device or
  variable and it can pick up every change as it occurs, so "tell me the next
  time the back door opens" actually works.

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

### Plugin-provided tools — other plugins bring their own

Any Indigo plugin can add tools of its own to Claude Bridge by shipping one JSON file, `Contents/Resources/mcp-manifest.json`, in its bundle. Claude Bridge finds the file on its own, lists the tools to Claude under that plugin's prefix (the Dashboards plugin's come out as `dashboards_get_status`, `dashboards_set_camera` and so on), and forwards each call to the plugin, which does the work and answers. Nothing to configure on either side, and a plugin picked up the moment it starts. The format is the provider-manifest contract published by [mlamoure's Indigo MCP Server](https://github.com/mlamoure/indigo-mcp-server), so a plugin written for that server works here unchanged, and one written for Claude Bridge works there. Tools a plugin marks as writes are governed by one switch under Configure, *Allow plugin-provided tools to make changes*, on by default; read tools always work. How to make your own plugin a provider is on [its own page](providers.md).

### Persistent memory
- `remember` / `recall` / `recall_topics` / `forget` — JSON-on-disk cross-
  session memory, topic-tagged, capped at 100 entries with per-topic
  fairness (the oldest entry of the same topic is evicted first).

### Audit, health, diagnostics
- Whole-system audits, a security snapshot, and a system-health summary.
- Finders for devices in error, low batteries, devices that have gone quiet,
  leftover data from uninstalled plugins, scripts nothing uses any more,
  oversized files, and naming or wiring conflicts.
- **"What would break if I deleted this?"** — for any device or variable,
  Claude can list everything that refers to it before you touch it.
- **"Has Indigo gained anything new?"** *(new in 2.9.0)* — after an Indigo
  upgrade, one tool compares the live system against a snapshot of every
  capability this plugin knew about at release, and reports anything new
  worth bridging. The plugin keeps itself honest.

### Reporting
- **`home_status_report`** — prose-markdown narrative of the whole home,
  configurable by section (energy, heating, security, devices, alerts,
  automation).
- **`analyze_historical_data`** — runs historical device/variable analysis,
  using InfluxDB if the `INFLUXDB_*` keys are configured.

### Notifications
- `send_email` via Indigo's first SMTP device, `send_notification` via
  Pushover (priority, sound, title, body), and `log_message` for writing a
  line straight to the Indigo event log.

### Folders & server info
- Create device and variable folders (asking twice is harmless — it just finds
  the existing one), and *(new in 2.9.0)* delete them again. A folder with
  things still in it is politely refused unless you explicitly say you mean
  the contents to go too.
- Whole-house broadcasts *(new in 2.9.0)* — Indigo's native all-lights-on,
  all-lights-off and all-devices-off commands. Worth knowing: these only
  reach devices Indigo talks to directly (Z-Wave and the like) — devices
  that belong to plugins such as zigbee2mqtt or Shelly don't hear
  broadcasts, and Claude will tell you so rather than pretend.
- Look up your Reflector remote-access address.

### Scripting shell — ADMIN scope
- **`execute_indigo_python`** — runs arbitrary Python in this plugin's
  Indigo context via in-process `exec()`. `mode='exec'` returns captured
  stdout/stderr, `mode='eval'` returns the expression's repr. Use it for
  one-shot Indigo API calls no dedicated tool covers. Treat it as full
  code execution on the Indigo server.
- **`execute_plugin_menu_item`** — clicks a plugin's `<MenuItem>` under the
  Indigo client's Plugins menu via AppleScript GUI scripting — the only
  known way to fire a third-party plugin's menu callback from outside.
  Requires the Indigo GUI running plus System Events permission.

For how the tools are kept from doing harm — read, write and admin, the delete switch, the webhook
firewall — see [Security](security.md).
