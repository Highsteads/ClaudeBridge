# Claude Bridge — Indigo Plugin

**Claude Bridge** is an [Indigo](https://www.indigodomo.com) home automation plugin that lets [Claude](https://www.anthropic.com/claude) see and control your actual Indigo system — your real devices, your real variables, your real event log — from an ordinary conversation.

Once it's installed you can simply ask. "Which lights are on?" "Turn the fan on for ten minutes." "Why didn't the bathroom light go off last night?" Claude looks at your system, does the thing, and checks its own work — no scripting, no copying device IDs about, no screenshots.

**Platform:** Indigo 2023.2 or later, macOS
**Bundle ID:** `com.clives.indigoplugin.claudebridge`
**Version:** 2.9.0

*Developed and tested on Indigo 2025.2. Older Indigo releases back to 2023.2 should also work.*

---

## How it works

Claude Bridge runs quietly inside Indigo. When you use [Claude Code](https://claude.ai/download) (Anthropic's terminal app), a little go-between script — installed and wired up for you automatically — passes Claude's requests to Indigo's own built-in web server, where the plugin answers them. That gives Claude **147 tools** for reading and controlling your system.

```
┌─────────────────────┐         ┌──────────────────────┐         ┌──────────────┐
│  Claude Code        │         │  go-between script   │         │  Indigo web  │
│  (you, chatting)    │ ───────►│  (installed for you) │ ───────►│  server +    │
│                     │         │  adds your access    │         │  this plugin │
│                     │         │  key automatically   │         │  (147 tools) │
└─────────────────────┘         └──────────────────────┘         └──────────────┘
```

From your point of view all of that is invisible — you open a Claude Code session and the Indigo tools are just there. Everything stays on your own machine and goes through Indigo's existing web server, protected by the same access key Indigo already uses.

### Why this matters

Before Claude Bridge, asking AI to help with Indigo meant pasting
screenshots, copying device IDs by hand, and hoping the AI remembered
what state your Hall PIR was in three messages ago. Claude was writing
into a vacuum.

With Claude Bridge, Claude can:

- **Read your actual Indigo state, live.** Not a description of it —
  the real device states, plugin states, variable values, event log,
  and trigger configurations as they are right now.
- **Make changes and verify them.** Turn a device on, then read its
  state back to confirm. Edit a script, restart the plugin that uses
  it, query the log to see if it loaded cleanly — all in one
  conversation.
- **Reason about your home.** "Which sensors haven't reported in 24
  hours?" "Does any script depend on variable ID 12345?" "What plugins
  are disabled that shouldn't be?" Claude uses the audit and
  diagnostic tools and answers.

---

## Vibe coding for Indigo

["Vibe coding"](https://en.wikipedia.org/wiki/Vibe_coding) is a term
coined by Andrej Karpathy in early 2025 for a particular style of
working with AI coding agents: you describe what you want in plain
language, the AI writes the code, you describe what you want changed,
the AI iterates. You guide by intent rather than by syntax. The "vibe"
is the conversational, iterative feedback loop — fewer keystrokes, more
back-and-forth. Done well, it produces working code in a fraction of
the time it would take to write line-by-line; done carelessly, it
produces plausible-looking code that doesn't run. The difference is
having a feedback loop that lets the AI **verify** what it just wrote.

Claude Bridge turns the Indigo system itself into that feedback loop.

A confession that doubles as a credential: **this plugin was itself written by
vibe coding.** Every version of Claude Bridge has been developed through a
conversation with Claude — described in plain English, written by Claude, and
tested by Claude against the live Indigo server, using the previous version of
this very plugin as its eyes and hands. The twenty-odd other plugins on this
GitHub account were built and are maintained the same way, with Claude Bridge
as the feedback loop — the git history backs every word of that, if you fancy
checking. So the examples below aren't speculation about what you could do.
They're a description of how the thing you're reading about came to exist.

Examples of how a session might go:

### Example 1 — write a Python script in one prompt

> **You:** "Write me a script that runs at sunset, turns on the porch
> light, and sends me a Pushover notification if the front door is
> currently open."

Claude Code:
1. Calls `search_entities` to find your porch light and front door sensor
2. Calls `get_device_by_name` to confirm IDs and states
3. Writes the script via `scaffold_automation_script` with the correct
   IDs baked in and a `log()` helper
4. Writes the file via `create_script`
5. Tells you the script name and tells you to schedule it for sunset

You read the result, hit Enter to commit, done. No Googling
`indigo.device.turnOn()`. No copy-pasting device IDs.

### Example 2 — write an Indigo plugin from a description

> **You:** "Build me a plugin that listens to my Tuya Zigbee thermostat
> via the Z2M bridge, exposes setpoint changes as states, and fires a
> trigger when the schedule kicks in."

Claude Code:
1. Reads your existing Zigbee2MQTTBridge plugin's device list to find
   the thermostat and discover its state names
2. Inspects similar plugins in your `Indigo 2025.2/Plugins/` folder
   for the conventions you use (Devices.xml structure, log format,
   header style)
3. Scaffolds the new plugin bundle with `Info.plist`, `Devices.xml`,
   `Events.xml`, and `plugin.py`
4. Restarts the plugin via `restart_plugin`
5. Queries the event log via `query_event_log` to confirm it started
   cleanly
6. Asks you to trigger a setpoint change and watches the events via
   `subscribe` + `get_events` to verify the state updates flow

When something fails, Claude sees the error in your log immediately and
fixes it. The iteration loop is seconds, not minutes.

### Example 3 — debug something weird

> **You:** "My bathroom light hasn't been turning off after the motion
> sensor clears for a week. Find out why."

Claude Code:
1. `query_event_log` for recent bathroom motion events
2. `dependency_map` for the bathroom motion sensor → which scripts and
   action groups reference it
3. `read_script` on each candidate
4. Spots a script that compares `var.value` to `"true"` (string) when
   the variable was set as `True` (bool, coerced to `"True"`)
5. Proposes the fix, you say yes, Claude `write_script`s the change
   and tells you it's done

This kind of cross-referencing diagnostic would take a human 20-30
minutes; Claude does it in a couple of round-trips.

### What you get out of it

- **Plugin development goes from days to hours.** Most of the
  boilerplate (Devices.xml, action callbacks, MenuItems.xml, file
  headers) is generated. Your input is the design and the review.
- **Scripts you'd put off get written.** A 50-line automation that
  would take an evening of digging through Indigo's IOM docs becomes a
  five-minute prompt.
- **Debugging is faster.** Claude has the whole log, the whole device
  tree, every script, and every plugin's state in scope at once. You
  don't have to context-load it manually.
- **You can be sloppy in your prompt.** "The hall light isn't doing
  the thing" works, because Claude can look at the hall light, see
  what it's doing, and infer what "the thing" might be.

### Honest limits

- **Claude can't read Indigo Trigger conditions or Action Group
  steps** — Indigo's API doesn't expose those. Claude can read what
  scripts do, but for Trigger logic it has to work from the names and
  ask you what they do.
- **Claude can't enable/disable plugins or create Triggers
  programmatically** — Indigo restricts those to the UI. You'll get a
  scaffolded `.indigoPlugin` bundle and instructions; you do the
  enable click.
- **Vibe coding is a force multiplier, not a magic wand.** Review
  what's been written. Test changes. The point of Claude Bridge is
  that *verification is one tool call away* — use it.

---

## What it does

Claude Bridge exposes **147 MCP tools** across **16 categories** that give Claude
Code full read/write access to a running Indigo server. The capability surface
falls into the following groups — the full per-tool listing is in
[Available Tools](#available-tools) further down.

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
  stdout/stderr; `mode='eval'` returns the expression's repr. Used for
  one-shot Indigo API calls not covered by a dedicated tool. Treat as
  full code execution on the Indigo server.
- **`execute_plugin_menu_item`** — clicks a plugin's `<MenuItem>` under the
  Indigo client's Plugins menu via AppleScript GUI scripting; the only
  known way to fire a third-party plugin's menu callback from outside.
  Requires the Indigo GUI running plus System Events permission.

### How it keeps your house safe
- **Everything stays local.** Searching and control all happen on your own
  Mac. The only thing that ever leaves the machine is your conversation with
  Claude itself.
- **No extra doors into your network.** Everything travels through Indigo's
  own web server on its existing port, protected by Indigo's own access key,
  and the Reflector gives you secure remote access for free.
- **Permission levels.** Every tool is classed as read, write, or admin. If
  you hand out a read-only key it really is read-only — and anything
  destructive (deleting things, running code, unlocking a door, the new
  folder deletes) needs the admin level. Anything not explicitly classified
  is locked down, not waved through.
- **Careful by default.** Dangerous operations refuse ambiguous input rather
  than guessing, deletes that can cascade make you say so explicitly, and
  the plugin checks its own permission setup every time it starts.

---

## Requirements

- Indigo 2023.2 or later, on macOS (the plugin runs on your Indigo server machine)
- [Claude Code](https://claude.ai/download) — the free Anthropic app you talk to Claude through
- A **paid Claude account** — see below

### What this costs — read this before installing

There are two Anthropic things people mix up, and only ONE of them is required:

**1. A Claude subscription — required.** Claude Code (the app you chat in) needs a
paid Claude account: a **Claude Pro or Max subscription** from
[claude.ai](https://claude.ai) is the usual route. This is the monthly plan that
pays for your conversations — every question you ask and every answer Claude
gives. If you already pay for Claude Pro or Max, you're done — this plugin adds
nothing to that bill. (The alternative for the technically inclined is an
Anthropic API account with pay-as-you-go billing instead of a subscription.)

**2. An Anthropic API key for the plugin itself — optional, most people can skip
it.** The plugin can hold its own API key from
[console.anthropic.com](https://console.anthropic.com), but it only uses it for
one thing: writing AI summaries inside the historical-analysis tool, which also
needs an InfluxDB database set up — a niche feature. **All 147 tools work
perfectly without this key.** If you do set one up, it bills per use
(typically pennies a month), entirely separately from your subscription.

In short: **pay for Claude Pro or Max, skip the API key**, and everything in
this README works.

---

## Installation

### Quick Install (recommended)

Clone the repo and run the installer — it handles everything except enabling the plugin in Indigo:

```bash
git clone https://github.com/Highsteads/ClaudeBridge.git
cd ClaudeBridge
python3 "Claude Bridge.indigoPlugin/Contents/Server Plugin/install.py"
```

The script:
- Copies the plugin bundle to Indigo's Plugins directory
- Copies the proxy script to Indigo's `Scripts` directory
- Reads your Bearer token from Indigo's `secrets.json` and patches the proxy automatically
- Creates/updates `~/.mcp.json` and `~/.claude/settings.json`

Then do these two final steps manually:

1. **Indigo → Plugins → Manage Plugins → Enable Claude Bridge**
   *(The plugin auto-creates its device on first enable — no "New Device" step needed)*

2. **Restart Claude Code** — you should see 147 `indigo-mcp` tools available

> **Credentials policy:** All sensitive values are read from
> `/Library/Application Support/Perceptive Automation/IndigoSecrets.py` first; the
> plugin's PluginConfig dialog is a fallback only. Keys this plugin reads:
> `ANTHROPIC_API_KEY` (optional — see "What this costs" above),
> `CLAUDEBRIDGE_BEARER_TOKEN`, and (optional) `INFLUXDB_HOST`,
> `INFLUXDB_PORT`, `INFLUXDB_USERNAME`, `INFLUXDB_PASSWORD`, `INFLUXDB_DATABASE`.
> If a value is missing from BOTH sources, the plugin logs an ERROR pointing
> here and skips that feature. See `IndigoSecrets_example.py` for the template.

---

### Manual Install

<details>
<summary>Click to expand manual installation steps</summary>

#### 1. Install the Plugin

1. Go to the [Releases page](https://github.com/Highsteads/ClaudeBridge/releases) and download `Claude.Bridge.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Claude Bridge.indigoPlugin`
3. Double-click `Claude Bridge.indigoPlugin` — Indigo will install it automatically
4. In the Indigo client: **Plugins → Manage Plugins → Enable** Claude Bridge

#### 2. Configure the Plugin

**Plugins → Claude Bridge → Configure:**

| Field | Value |
|-------|-------|
| Anthropic API Key | **Optional** — only for the historical-analysis AI summaries. Leave blank otherwise |
| Access Mode | Read/Write (recommended) |

Click **Test** to verify the API connection, then **Save**.

> **Tip:** Leave the API Key field blank and add `ANTHROPIC_API_KEY = "sk-ant-..."` to
> `/Library/Application Support/Perceptive Automation/IndigoSecrets.py` instead.
> The plugin checks for this file automatically on startup.
> A template (`IndigoSecrets_example.py`) is included in the plugin bundle
> (inside `Contents/Server Plugin/`).

#### 3. Device auto-creation

The plugin auto-creates a Claude Bridge device on first startup.
No manual "New Device" step is needed. If you need to create it manually:
**Devices → New Device → Plugin: Claude Bridge → Type: Claude Bridge**

#### 4. Install the Proxy Script

Save `indigo_mcp_proxy.py` (from the bundle's `Contents/Server Plugin/` folder) to:
```
/Library/Application Support/Perceptive Automation/Scripts/indigo_mcp_proxy.py
```

Edit the `BEARER_TOKEN` constant at the top of the script — use the first value from:
```
/Library/Application Support/Perceptive Automation/Indigo <your version>/Preferences/secrets.json
```

#### 5. Register with Claude Code

Add to `~/.mcp.json`:
```json
{
  "mcpServers": {
    "indigo-mcp": {
      "command": "python3",
      "args": ["/Library/Application Support/Perceptive Automation/Scripts/indigo_mcp_proxy.py"]
    }
  }
}
```

Add to `~/.claude/settings.json`:
```json
{
  "enabledMcpjsonServers": ["indigo-mcp"]
}
```

#### 6. Restart Claude Code

The `indigo-mcp` tools will appear on next session start. You should see 147 tools available.

</details>

---

## Credentials — `IndigoSecrets.py` vs `IndigoSecrets_example.py`

This plugin (along with all CliveS Indigo plugins) reads sensitive values from
a shared master credentials file at:

`/Library/Application Support/Perceptive Automation/IndigoSecrets.py`

| File | Purpose | Real data? | Committed to GitHub? |
|------|---------|------------|----------------------|
| `IndigoSecrets.py` | Working file the plugin reads at runtime. Keep a backup in a password manager. | YES | **NO** — listed in `.gitignore` |
| `IndigoSecrets_example.py` | Template only — empty placeholders. Shipped in the plugin bundle. | NO | YES |

If you do not have `IndigoSecrets.py`, copy `IndigoSecrets_example.py` from
the plugin bundle to `/Library/Application Support/Perceptive Automation/` and rename it to `IndigoSecrets.py`, then fill in your values. Or skip
`IndigoSecrets.py` entirely and enter values via the plugin's configuration
dialog — `IndigoSecrets.py` wins over the dialog when both are set.

If a required value is set in NEITHER source the plugin logs an ERROR
pointing the user to either fill in the matching field or add the key to
`IndigoSecrets.py`.

**Keys read by this plugin**: `ANTHROPIC_API_KEY` (optional — used only for
the AI summaries in the historical-analysis tool; every other tool works
without it), `CLAUDEBRIDGE_BEARER_TOKEN` (fallback for the web-server access
key — first preference is Indigo's own `Preferences/secrets.json`), and the
optional `INFLUXDB_*` keys for the historical-analysis tools.

---

## Connecting Claude Code

Claude Code connects via a lightweight Python proxy script (`indigo_mcp_proxy.py`) that handles
authentication and protocol translation. The **Quick Install** script above sets this up automatically.

### Find Your Endpoint URL

**Plugins → Claude Bridge → Print MCP Client Connection Information**

The endpoint will be shown in the Indigo event log, e.g.:
```
Local:   http://localhost:8176/message/com.clives.indigoplugin.claudebridge/mcp/
Network: http://<your-indigo-server-ip>:8176/message/com.clives.indigoplugin.claudebridge/mcp/
```

---

## Available Tools

**147 tools, grouped by security scope.** This table is **auto-generated** from the
plugin's own tool registry (`mcp_server/mcp_handler.py`) cross-referenced with the
deny-by-default scope classification (`mcp_server/security/scope_manager.py`), so it
can never drift from the code. Regenerate with `python3 scripts/generate_tool_doc.py
--write`. A read-only token can call only the **Read** tools, a read-write token the
Read + Write tools, and `admin` is required for the **Admin** tools. For a friendlier
overview organised by function (devices, heating, energy, …) see
[What it does](#what-it-does) above.

> **A note on variable values.** The Read tools that return variables (`get_variable_by_id`,
> `list_variables`, `home_status` and the like) return each variable's value in full, so any
> token with the `read` scope can see them. If you keep a secret in an Indigo variable — an API
> token, a password — bear in mind that a read-only Claude Bridge token can read it, the same way
> any Indigo script or control page can. Keep genuine secrets in `IndigoSecrets.py` rather than in
> a variable, and don't hand a read token to anyone you wouldn't trust with those values. (Claude
> Bridge no longer writes a variable's full value into the event log either — long values are
> shortened in the log line, though they're still returned to the caller as normal.)

<!-- BEGIN TOOL TABLE -->
<!-- AUTO-GENERATED by scripts/generate_tool_doc.py — 147 tools. Do not edit by hand. -->

### Read tools (62)

_Pure queries — no state change. Require the `read` scope._

| Tool | Description |
|------|-------------|
| `action_group_get_dependencies` | Get dependents of an action group. Useful before deleting. |
| `analyze_historical_data` | Analyze historical data patterns and trends for specific devices using AI-powered insights. IMPORTANT: Requires EXACT device names - use 'search_entities' or 'list_devices' first to find correct device names. Only works if InfluxDB historical data logging is enabled. |
| `audit_api_coverage` | Diff the live indigo.* command namespaces against the frozen baseline captured at build time. Run after an Indigo upgrade to see new API callables Claude Bridge hasn't surfaced as tools yet (and removals that may break existing tools). |
| `audit_home` | Run a comprehensive Indigo configuration health check. Returns devices in error, low-battery devices, stale devices (no change in 7+ days), empty/null variables, disabled triggers and schedules, and automation counts. Use this for a quick health overview. |
| `audit_variables` | Report variables not referenced in any Python script (potentially unused), and variables with empty, None, or 'null' values. |
| `calculate_sunrise` | Sunrise for today (default) or YYYY-MM-DD date_iso. |
| `calculate_sunset` | Sunset for today (default) or YYYY-MM-DD date_iso. |
| `check_plugin_updates` | Sweep every installed plugin and report which have a compatible update available. Single call replaces N get_plugin_status calls. |
| `dependency_map` | Show everything that references a given device or variable. Returns which Python scripts reference it by ID, plus a full list of all triggers and action groups (Indigo's API does not expose their internal conditions, so content filtering is not possible — the full list is returned for manual review). |
| `device_history` | Read recent SQL Logger history for one device. Returns timestamp + non-null state columns. Far cheaper than analyze_historical_data for a focused trend query. |
| `energy_compare` | Compare two energy periods. Default: this week vs last week. Returns kWh deltas and % changes for PV, import, export, home consumption, and self-sufficiency. |
| `energy_daily_summary` | Parse SigenEnergyManager daily log files into per-day kWh totals: PV generated, grid imported, grid exported, home consumption, max/min SOC, and overall self-sufficiency percentage. |
| `energy_log_days` | Return raw SigenEnergyManager log lines for the last N days (max 14). Useful for asking Claude to reason about specific events, decisions, or anomalies. |
| `energy_status` | Return a live energy snapshot from SigenEnergyManager device states: battery SOC, solar generation, grid import/export, tariff, and related variable values. |
| `find_conflicts` | Detect configuration conflicts in Indigo. Checks for: duplicate device names, devices sharing the same hardware address, triggers with duplicate names, Python scripts referencing deleted device/variable IDs (orphaned refs), and multiple scripts writing to the same variable (potential race condition). |
| `find_devices_in_error` | Return all Indigo devices currently in an error or fault state. |
| `find_large_files` | Walk a directory tree and return files exceeding a size threshold, sorted largest first. Defaults to scanning the entire Indigo install folder for files >= 10 MB. |
| `find_low_battery` | Return all devices with a batteryLevel state below the given threshold (default 20%). Sorted lowest battery first. |
| `find_orphaned_plugin_data` | Compare Preferences/Plugins subdirectories against installed plugin bundle IDs. Returns any prefs directories that belong to plugins that are no longer installed, along with their size on disk. Safe to delete orphaned entries to recover disk space. |
| `find_orphaned_scripts` | Scan all Python scripts in the Indigo Scripts folder and report any that reference device or variable IDs which no longer exist in Indigo. Useful for finding stale scripts after devices or variables have been deleted. |
| `find_stale_devices` | Return enabled devices whose state has not changed in more than N days (default 7). Helps identify dead or forgotten hardware. |
| `get_action_group_by_id` | Get a specific action group by ID |
| `get_control_page` | Return a control page's properties (and controls if available). |
| `get_deprecated_elements` | Scan for deprecated Indigo objects. include_warnings=True also surfaces warning-level items. |
| `get_device_by_id` | Get a specific device by ID |
| `get_device_by_name` | Find a device by name and return its full state in one round trip. Tries exact match, then case-insensitive, then partial match. Returns all device states, properties, and current values. |
| `get_devices_by_state` | Find devices where a specific state matches a value. E.g. state_key='heatIsOn' state_value='true' to find heating zones, or state_key='onState' state_value='true' for devices that are on. |
| `get_devices_by_type` | Get all devices of a specific type |
| `get_events` | Drain queued Indigo change events. Pass `since` (Unix timestamp) to get only events after a previous call. Returns up to `limit` events (default 50). Requires at least one active subscription. |
| `get_latitude_longitude` | Return the latitude/longitude configured in Indigo preferences. |
| `get_plugin_by_id` | Get specific plugin information by ID |
| `get_plugin_status` | Get detailed plugin status |
| `get_reflector_url` | Return the Indigo Reflector remote-access URL if configured on this server (indigo.server.getReflectorURL). |
| `get_variable_by_id` | Get a specific variable by ID |
| `get_web_server_url` | Return the local Indigo web server URL. |
| `heating_status` | Return all heating/thermostat device states — RAMSES ESP TRVs (12 zones), with setpoints, current temperatures, and zone modes. |
| `home_status` | Return a comprehensive snapshot of the home: all devices grouped by type, key variable values, energy status, active alerts (errors/low battery), and automation counts. Ideal for a full status report. |
| `home_status_report` | Generate a configurable markdown prose report of home status, suitable for presenting directly to the user. Specify sections to include (any of: energy, heating, security, devices, alerts, automation), or omit for the full report. Example: home_status_report(sections=['energy','alerts']) |
| `list_action_groups` | List all action groups |
| `list_control_pages` | List all control pages with id/name/folder/etc. |
| `list_devices` | List all devices with optional state filtering |
| `list_plugins` | List all Indigo plugins |
| `list_python_scripts` | List all Python scripts (.py files) in the Indigo Scripts folder. Returns name, size, last-modified date, and full path. |
| `list_schedules` | List all Indigo schedules with their ID, name, enabled state, and next scheduled execution time. |
| `list_script_backups` | List auto-backups available for a given script. |
| `list_subscriptions` | List active event subscriptions and current queue depth. |
| `list_triggers` | List all Indigo triggers with their ID, name, enabled state, and plugin type information. |
| `list_variable_folders` | List all variable folders for organization |
| `list_variables` | List all variables with id, name, and folder (when not in root) |
| `plugin_diff_source_vs_installed` | Diff a plugin's source repo bundle against its installed bundle. Catches static-asset stale-sync, gutted Packages dir, version-bump mismatches and any drift between dev and runtime. |
| `plugin_lint` | Lint plugin.py against CliveS-plugin conventions: header format, log() helper, no bare print(), open() of .py needs encoding='utf-8', no hardcoded Indigo version paths, subscribeToChanges needs the pluginId loop-guard. |
| `plugin_node_check_html` | Run `node --check` on every inline <script> block in any HTML file under the plugin's Contents/Resources/. Catches stale-paste JS syntax bugs in 50ms per block. |
| `plugin_show_packages_versions` | Walk a plugin's Contents/Packages/*.dist-info and return the {name: version} map of every bundled third-party library. Useful for diagnosing wrong-version-of-paho-mqtt class bugs. |
| `plugin_validate_xml` | Parse Devices/Actions/Events/MenuItems/PluginConfig XML and check Indigo naming rules: state IDs must be camelCase ASCII (no underscores), Actions uiPath must have no spaces, batteryLevel is reserved. |
| `query_event_log` | Query Indigo server event log entries. Without after/before returns the most recent line_count entries. With after/before reads from the on-disk log files and returns all entries in that time window (useful for investigating past events). Time formats: 'HH:MM:SS' (today assumed), 'YYYY-MM-DDTHH:MM:SS' (full). |
| `read_script` | Read the full content of a Python script from the Indigo Scripts folder. |
| `recall` | Retrieve stored memories. Pass a topic to filter, or omit to return all memories. Results are newest first. |
| `recall_topics` | List all memory topics and how many notes each has. |
| `schedule_get_dependencies` | Get dependents of a schedule (which devices/variables it references). Useful before deleting. |
| `search_entities` | Search for Indigo entities using natural language. Results are slim by default (id, name, state, lastChanged). Use detail='full' only when you need complete device properties such as Z-Wave config or plugin props. |
| `security_status` | Return all contact sensors (open doors/windows), active motion sensors, and active leak/smoke/CO alerts. |
| `system_health` | Return a snapshot of Mac Mini system health: macOS version, Python version, disk usage (total/used/free/%), RAM summary, and uptime. No parameters required. |

### Write tools (63)

_Modify Indigo state. Require `write` (or `admin`)._

| Tool | Description |
|------|-------------|
| `action_execute_group` | Execute an action group |
| `all_devices_off` | Send Indigo's native all-devices-OFF broadcast. Native-protocol devices (Z-Wave/Insteon/X10) ONLY — plugin-owned devices are not affected. |
| `all_lights_off` | Send Indigo's native all-lights-OFF broadcast. Reaches native-protocol devices (Z-Wave/Insteon/X10) ONLY — devices owned by plugins (zigbee2mqtt, Shelly, Tasmota) are NOT affected; turn those off individually or via an action group. |
| `all_lights_on` | Send Indigo's native all-lights-ON broadcast. Native-protocol devices (Z-Wave/Insteon/X10) ONLY — plugin-owned devices are not affected. |
| `beep_device` | Ask a device to beep so you can physically identify it. Devices that don't support beeping ignore the command. |
| `clear_events` | Flush the event queue without returning its contents. |
| `create_device_folder` | Create a new device folder. Returns the existing folder if one with the same name already exists (idempotent). |
| `create_variable_folder` | Create a new variable folder. Returns the existing folder if one with the same name already exists (idempotent). |
| `decrease_heat_setpoint` | Decrease the heat setpoint on a thermostat/TRV by a given delta (default 0.5 degC). Use for small step adjustments. |
| `device_control` | Find a device by name and control it in one step — faster than search_entities + device_turn_on/off. Use this for all simple on/off/brightness commands. |
| `device_remove_delayed_actions` | Cancel pending delayed/timed actions for ONE device (e.g. a queued auto-off from device_turn_on duration), leaving other devices' delayed actions untouched. |
| `device_set_brightness` | Set device brightness level |
| `device_toggle` | Toggle on/off state. Auto-detects dimmer/relay/speedcontrol. |
| `device_turn_off` | Turn off a device. Optional delay (turn off in N seconds) and duration (auto-ON again after N seconds). |
| `device_turn_on` | Turn on a device. Optional delay (turn on in N seconds) and duration (auto-off after N seconds) — 'fan on for 10 minutes' is one call with duration=600. |
| `dimmer_brighten_by` | Increase dimmer brightness by N percent. Clamps at 100. |
| `dimmer_dim_by` | Decrease dimmer brightness by N percent. Clamps at 0. |
| `disable_schedule` | Disable an Indigo schedule by ID or name. |
| `disable_trigger` | Disable an Indigo trigger by ID or name. |
| `duplicate_action_group` | Duplicate an action group. |
| `duplicate_device` | Duplicate a device. Optional new_name — Indigo defaults to 'Copy of <name>'. |
| `duplicate_schedule` | Duplicate a schedule. |
| `enable_device` | Enable or disable a device's communication. NOT the same as on/off — this controls whether Indigo polls/listens to the device at all. |
| `enable_schedule` | Enable an Indigo schedule by ID or name. |
| `enable_trigger` | Enable an Indigo trigger by ID or name. |
| `execute_schedule_now` | Execute a schedule immediately. ignore_conditions=True bypasses the schedule's own conditions. |
| `fire_indigo_event` | Fire all Indigo Triggers of type 'Claude Bridge → Claude Event' with a structured payload. Use this to drive Indigo automations from a Claude tool call. Inside the user's Trigger actions, the payload is available via Indigo's event-data substitution %%e:"name"%%, %%e:"data"%%, %%e:"source"%%. Users filter on event name with a Script Condition testing event_data.get('name'). |
| `fire_trigger` | Execute a single Indigo trigger directly by ID or name (indigo.trigger.execute). Use this when you want to invoke a specific trigger's actions without going through the event system used by fire_indigo_event. |
| `forget` | Delete a specific memory entry by its ID. |
| `increase_heat_setpoint` | Increase the heat setpoint on a thermostat/TRV by a given delta (default 0.5 degC). Use for small step adjustments. |
| `log_message` | Write a message to the Indigo on-screen event log (Log Viewer). The message appears immediately. Use for status updates, confirmations, or debug output that the user can see in the Indigo UI. |
| `move_device_to_folder` | Move a device to a different folder. folder_id=0 means root. |
| `move_trigger_to_folder` | Move a trigger to a different folder. folder_id=0 means root. |
| `ping_device` | Ping a device to check it is reachable on its network (Z-Wave and other native protocols). Returns reachability and round-trip time where supported. |
| `remember` | Store a persistent note under a topic, accessible across future Claude sessions. Examples: remember(topic='devices', note='Back door sensor false-positives in direct sunlight') or remember(topic='energy', note='Bias factor was 1.5 as of April 2026'). |
| `rename_device` | Rename a device. |
| `request_status_update` | Request an immediate status update from a device (polls the device for current state). |
| `reset_energy_accumulator` | Reset a device's accumulated energy total (kWh) to zero — e.g. start a fresh count on an energy-metering smart plug. The previous total is returned but cannot be restored. |
| `schedule_remove_delayed_actions` | Remove any pending delayed actions for a schedule. |
| `send_email` | Send an email via Indigo's configured SMTP device. Use for detailed reports, logs, or non-urgent notifications. |
| `send_notification` | Send a Pushover push notification to the user's device. Use for important alerts, confirmations, or proactive updates. |
| `server_speak` | Speak text through Indigo server (macOS text-to-speech). |
| `set_color` | Set the colour of an RGB or RGBW light dimmer. Provide EITHER a 'color' string (a hex code like '#FF8000' or '#F80', or a CSS/X11 colour name like 'dodgerblue' — 148 names, British 'grey' spellings accepted) OR explicit red/green/blue channels (0-255 each). 'color' takes precedence if both are given. |
| `set_cool_setpoint` | Set the cool setpoint on a thermostat device. Value is in degrees Celsius. |
| `set_fan_mode` | Set thermostat fan mode. mode ∈ {auto, alwaysOn}. |
| `set_fan_speed` | Set the speed level on a fan or speed-control device (0-100%). |
| `set_heat_setpoint` | Set the heat setpoint on a thermostat/TRV device (e.g. RAMSES, Evohome). Value is in degrees Celsius. |
| `set_hvac_mode` | Set the HVAC operating mode on a thermostat device. |
| `speedcontrol_decrease` | Decrease speed index by one. |
| `speedcontrol_increase` | Increase speed index by one. |
| `speedcontrol_set_index` | Set speed index on a speed-control device (0=off, 1=low, 2=med, 3=high). |
| `sprinkler_next_zone` | Advance to the next sprinkler zone. |
| `sprinkler_pause` | Pause the sprinkler. |
| `sprinkler_previous_zone` | Go back to the previous sprinkler zone. |
| `sprinkler_resume` | Resume a paused sprinkler. |
| `sprinkler_run` | Run a sprinkler programme. |
| `sprinkler_set_zone` | Set the active zone on a sprinkler device (1-based index). |
| `sprinkler_stop` | Stop the sprinkler. |
| `subscribe` | Subscribe to Indigo device or variable change events. ClaudeBridge will queue any matching state changes. Use get_events() to poll the queue. entity_type: 'device', 'variable', or 'all'. entity_id: specific ID to watch, or omit for all of that type. |
| `unsubscribe` | Remove an event subscription by its ID. |
| `variable_create` | Create a new variable |
| `variable_move_to_folder` | Move a variable to a different folder. folder_id=0 means root. |
| `variable_update` | Update a variable's value |

### Admin tools (22)

_Destructive / irreversible / code-execution / lifecycle / physical-security. Require `admin`._

| Tool | Description |
|------|-------------|
| `create_script` | Create a new Python script in the Indigo Scripts folder. Fails if the file already exists — use write_script to update. |
| `delete_action_group` | Permanently delete an action group. |
| `delete_device` | Permanently delete a device. Destructive — cannot be undone. |
| `delete_device_folder` | Delete a device folder by ID or name. Refuses a non-empty folder unless delete_children=true (which deletes the devices inside it — irreversible). |
| `delete_schedule` | Permanently delete a schedule. |
| `delete_script` | Safely archive a Python script (moves to _backups/_archived/). Does not permanently delete — can be recovered manually. |
| `delete_trigger` | Permanently delete a trigger. |
| `delete_variable_folder` | Delete a variable folder by ID or name. Refuses a non-empty folder unless delete_children=true (which deletes the variables inside it — irreversible). |
| `execute_indigo_python` | Run arbitrary Python in this plugin's Indigo context. Has full access to the `indigo` module (devices, variables, triggers, thermostat.setHeatSetpoint, etc). mode='exec' runs a statement block and returns captured stdout/stderr. mode='eval' evaluates a single expression and returns its repr in 'value'. ADMIN scope — treat as arbitrary code execution on the Indigo server. |
| `execute_plugin_menu_item` | Click a plugin's menu item under the Indigo client's Plugins menu (e.g. plugin_name='Zigbee2MQTT Bridge', menu_item_name='Refresh Device Capabilities'). Uses AppleScript GUI scripting — requires the Indigo GUI client to be running and System Events permission granted. ADMIN scope. |
| `lock_device` | Lock a Z-Wave or other lock device. |
| `plugin_refresh_deps` | Delete the pip-install success marker so Indigo re-runs requirements.txt on next plugin restart. restart=true also triggers the restart immediately. |
| `remove_all_delayed_actions` | Remove every pending delayed action across all schedules. Destructive — confirm with the user first. |
| `restart_plugin` | Restart an Indigo plugin |
| `run_script` | Execute a Python script from the Python Scripts folder in the Indigo Python context. The script runs with full access to the indigo module. Use for triggering automation logic, one-off tasks, or testing scripts. Returns stdout/stderr output. |
| `scaffold_automation_script` | Generate and save a complete Python script template to the Indigo Scripts folder. Pre-fills the standard header, log() helper, and named constants for any supplied device/variable IDs (names looked up live). Ready to open in Indigo and add logic. Fails if the script already exists. |
| `unlock_device` | Unlock a Z-Wave or other lock device, optionally with a PIN code. |
| `variable_delete` | Permanently delete a variable. Destructive — cannot be undone. |
| `webhook_create` | Register an OUTBOUND webhook: the home POSTs a signed JSON event to an APPROVED external URL when a device/variable condition is met. ADMIN. The target must be on the egress allow-list (default-deny — private/LAN ranges need an explicit CIDR opt-in). Returns a one-time HMAC signing key — capture it. Requires 'Enable Event Webhooks' in the plugin config. |
| `webhook_delete` | Delete an outbound webhook subscription by id. ADMIN. |
| `webhook_list` | List outbound webhook subscriptions with delivery-health stats. ADMIN. Secrets are redacted (signing key omitted, bearer token shown as ***). |
| `write_script` | Overwrite an existing Python script with new content. A timestamped backup is created automatically before writing. Use this to fix or update a script. For new scripts, use create_script instead. |
<!-- END TOOL TABLE -->

---

## Why is there a go-between script?

Claude Code and Indigo's web server don't quite speak the same dialect out of the box, so a small script sits between them and smooths things over. It speaks to Claude Code the way Claude Code expects, attaches your Indigo access key to every request so you never have to think about it, keeps the connection alive and quietly repairs it if Indigo restarts, and tidies up the odd formatting difference between the two sides. It's installed and configured for you — the only time you'd ever look at it is if something in the Troubleshooting section below sends you there.

---

## Troubleshooting

**"Could not attach to MCP server indigo-mcp"**
→ Claude Bridge plugin not running in Indigo. Check Plugins → Manage Plugins.

**"Unsupported protocol version"**
→ Proxy script not in use, or stale process. Restart Claude Code.

**401 Unauthorized**
→ Wrong bearer token in proxy script. Check `secrets.json`.

**Search returns 0 results**
→ Use simple device name terms ("conservatory", "lamp"). The search is substring-based.

**Device control says "expected number"**
→ Using old cached schema. Restart Claude Code to refresh tool definitions.

**Plugin updates — when to restart Claude Code**
→ Bug fixes to existing tools: restart Indigo plugin only, no Claude Code restart needed.
→ New tools added: restart Claude Code once to pick up the updated tool list.

**Plugin fails to start after a pip-install loop (`anthropic`/`influxdb`/etc. `__init__.py` missing)**
→ Indigo's per-restart pip step occasionally leaves `Contents/Packages/` in a
half-installed state: the package directory exists but the top-level
`__init__.py` (and most other `.py` files) are gone, so every import fails with
"cannot import name X from Y (unknown location)". `--force-reinstall` against
the same target doesn't fix it — pip skips because the directory is "already
present". The reliable recovery is to wipe and let Indigo re-install on the
next start:
```bash
DST="/Library/Application Support/Perceptive Automation/Indigo 2025.2/Plugins/Claude Bridge.indigoPlugin"
rm -rf "$DST/Contents/Packages"
mkdir -p "$DST/Contents/Packages"
# Then reload Claude Bridge via the Plugins menu (or the Indigo GUI), which
# triggers a clean pip install from requirements.txt.
```
Confirmed 2026-05-23 — every package directory in Packages/ was missing its
`__init__.py` after a routine restart, and clearing the whole tree restored a
fully-working install. This pattern can affect any plugin that ships a
`requirements.txt`; treat it as the standard recovery if a restart suddenly
starts logging `module 'X' has no attribute 'Y'` for previously-working
imports.

---

## Claude Code skills that complement this plugin

Claude Bridge is the **runtime** bridge — it lets Claude Code talk to a live
Indigo server (read state, control devices, query history). For the
**design-time** side — Indigo SDK docs, plugin lifecycle reference, 16 example
plugins, the IOM, and troubleshooting recipes — the companion is Simon's
`indigo:dev` Claude Code skill, distributed via
[simons-plugins/indigo-claude-plugin](https://github.com/simons-plugins/indigo-claude-plugin).

Loaded with `/indigo:dev`, it provides ~40 KB of curated SDK references for
Claude Code to draw on while writing new plugins or debugging existing ones,
without ballooning the context window.

How the two fit together:

| Layer        | Tool                    | Provided by    | What it gives Claude Code |
|--------------|-------------------------|----------------|---------------------------|
| Design-time  | `indigo:dev` skill      | simons-plugins | SDK docs, example plugins, lifecycle reference, IOM, troubleshooting |
| Runtime      | Claude Bridge MCP       | this plugin    | Live device control, variable / schedule access, event log, scripts, history |

Typical workflow:

1. **`/indigo:dev`** — Claude Code loads SDK context, scaffolds new plugin
   code, looks up correct API signatures.
2. **Claude Bridge** — Claude Code reads live device states via MCP to verify
   the new code is doing what's expected, fires triggers / runs scripts /
   updates variables to test integration end-to-end.

Other related Claude Code skills published in the same repo
(`indigo:api`, `indigo:control-pages`, `indigo:html-pages`, `indigo:update-plugins`,
`indigo:debug-sqllogger`) follow the same pattern: design-time docs and
guided workflows in the skill, runtime data and control via Claude Bridge.
Neither side requires the other to function — Claude Bridge works fine
without the skills installed, and the skills work fine without a live Indigo
server — but together they give Claude Code a complete end-to-end loop for
Indigo development.

---

## Project Structure

```
Claude Bridge.indigoPlugin/
├── Contents/
│   ├── Info.plist                          # Plugin metadata & bundle ID
│   └── Server Plugin/
│       ├── plugin.py                       # Indigo plugin lifecycle
│       ├── requirements.txt
│       ├── Actions.xml
│       ├── Devices.xml
│       ├── MenuItems.xml
│       ├── PluginConfig.xml
│       └── mcp_server/
│           ├── mcp_handler.py              # MCP protocol implementation
│           ├── adapters/                   # Indigo data provider
│           ├── common/
│           │   ├── openai_client/          # Anthropic Claude API client
│           │   └── vector_store/           # Text search store
│           ├── handlers/                   # List/resource handlers
│           ├── security/                   # Auth manager
│           └── tools/                      # 18 tool handler modules (147 tools)
│       ├── indigo_mcp_proxy.py             # Claude Code go-between script
│       └── install.py                      # one-shot installer
└── README.md
```

---

## Changelog

### 2.10.1 (2026-07-03)
A follow-up batch working through the medium-priority findings from the same review. Fourteen were real and are fixed (about half of what was flagged turned out to be already-handled or harmless, and was left alone).

The one you'd actually notice: **low-battery alerts now see your whole house.** They only ever looked at one of the three places Indigo can store a battery level, which happened to be the one your Zigbee sensors don't use — so 43 of the 55 battery devices here were invisible to the alert. All three places are checked now.

The rest are the quiet sort: two on/off settings that could switch themselves back on when saved (a blank-looking value reading as "yes"), the log tool honouring the level you ask for instead of always saying "info", writing an empty value instead of the word "None" when you clear a variable, a couple of tools that used to claim success on input Indigo can't actually do (delaying an action group, looking up a plugin that isn't installed) now saying so plainly, the plugin-restart tool no longer freezing the web server while it waits, a week-vs-week energy comparison refusing a silly date range, the "is this variable still used" check erring on the side of caution when it can't tell, and the cache noticing a few more changes so it doesn't hand back stale lists.

299 tests.

### 2.10.0 (2026-07-03)
A deep-review fix batch — a full multi-agent bug hunt of the plugin, with every finding verified against the live system before anything was touched. Nine genuine faults came out of it, several of them tools that had never actually worked.

The headline one is subtle but mattered. When a tool hit an error it handed the failure back as a tidy little result rather than raising it, and the plumbing behind the scenes took that at face value — so an error could sit in the read-cache and be served back as a fresh answer for a minute, the health counters cheerfully recorded it as a success, and the careful "don't echo a sensitive tool's raw error to the client" safeguard never fired because there was no exception for it to catch. All three now do the right thing — errors are spotted, never cached, counted honestly, and a mail or webhook failure no longer leaks its host and login into a reply that can travel out over the reflector.

The `/health` page had a related slip — it listed live usage keyed by the raw bearer token, so anyone who could read it could read everyone else's token. Those are now shown as a short one-way fingerprint instead.

Four tools that looked fine but never worked are now fixed or gone. Nudging a dimmer up or down by a few percent called an Indigo method that does not exist — it now uses the real one. Asking "what depends on this schedule or action group before I delete it" always came back empty, which is exactly the wrong answer for a safety check — it now lists the real dependants. The two "enable / disable an action group" tools have been removed altogether, because Indigo simply has no such thing for action groups and they failed every single time (147 tools now, down from 149). And the energy summary tools used to invent a tidy row of zeros when the figures they wanted were not in the logs at all — they now say so plainly and point you at the live figures instead.

A few more: firing a Claude Event now actually delivers its data to the trigger (and the setup notes give the correct way to read it), the "refresh dependencies" tool no longer offers to restart Claude Bridge from inside itself (which would cut its own line mid-sentence), running two bits of Python at once can no longer scramble the plugin's output, and the installer now finds your Indigo version on its own rather than assuming one, and refuses to run from a copy that would delete itself. 292 tests.

### 2.9.0 (2026-06-10)
Ten new tools, all surfacing Indigo capabilities found by walking the live API namespace by namespace — plus the walker itself is now a tool, so the question "has an Indigo upgrade added anything we haven't bridged?" answers itself from now on (`audit_api_coverage` diffs the running server against a frozen baseline of 362 callables).

The one you'll actually use daily: **timed device actions**. `device_turn_on` and `device_turn_off` now take optional `delay` and `duration` arguments, so "fan on for ten minutes" or "turn that off in half an hour" is a single call using Indigo's own delayed-action engine — no scripts, no timers. A companion `device_remove_delayed_actions` cancels a pending timed action on one device without touching anything else's.

The rest: `reset_energy_accumulator` zeroes the lifetime kWh count on an energy-metering plug, `beep_device` and `ping_device` give you physical identification and reachability checks, `all_lights_off` / `all_lights_on` / `all_devices_off` expose Indigo's native broadcast commands (clearly labelled as reaching Z-Wave/Insteon/X10 devices only — plugin-owned devices don't hear broadcasts), and `delete_device_folder` / `delete_variable_folder` complete the folder lifecycle, refusing to delete a non-empty folder unless you explicitly say otherwise.

Under the bonnet, the `/health` endpoint now reports average and maximum **response size per tool** alongside latency — because the real cost of a chatty tool is how much Claude has to read, not how fast the server answers. 283 tests.

### 2.8.6 (2026-06-10)
A housekeeping release off the back of a full repo audit — nothing about how the plugin behaves day-to-day changes, but quite a lot about how safely it can be changed in future does.

The thing users will actually notice: **installs are much lighter**. The plugin's `requirements.txt` had accumulated around twenty packages over its life, of which the code only ever imported four — the rest (pandas and numpy among them, tens of megabytes of compiled code) were downloaded onto every machine for nothing. The list is now exactly the four that are used: `anthropic`, `pydantic`, `influxdb` and `jinja2`. Fewer packages means faster installs, fewer ways for the pip step to go wrong, and less third-party code sitting inside your Indigo folder.

The rest is guard-rails for development. The repo now runs its full test suite (grown from 176 to 213 tests), an errors-only lint pass and a docs-staleness check automatically on every push via GitHub Actions — so a change that breaks a tool, leaves a new tool unclassified in the security scopes, forgets a cache-invalidation entry or lets the README drift out of date now fails loudly instead of shipping. There's a new `CONTRIBUTING.md` with the full recipe for adding a tool, a couple of genuinely dead stub modules have been removed, the documentation now consistently says 139 tools (the capability summary had been stuck on 136 since before the webhooks release), the tool cache no longer keeps expired entries around for keys that are never asked for again, the webhook store re-asserts its owner-only file permissions when loaded (in case it was ever restored from a backup with looser ones), and `setup.py` is now called `install.py` — it was always a one-shot installer, never a Python packaging file, and the old name invited a `pip install .` that could never work.

### 2.8.5 (2026-06-09)
The follow-on to the reliability fix in 2.8.3, closing the last two ways the bridge connection could drop out from under you. The first was a near-cousin of the one already dealt with. A connection that has gone stale while sitting idle does not always fail the moment a request is sent, it sometimes fails a fraction later when the reply is read back, and the earlier fix only caught the first of those. Now both are handled. When Indigo's web server has clearly closed an idle connection and sent nothing back at all, the request plainly never ran, so it is safe to reconnect and send it again whatever it was. On top of that the proxy now does the sensible thing pre-emptively and opens a fresh connection if the old one has been sitting unused for more than ten seconds, so most of these never get the chance to happen in the first place.

The second was a different beast. After Indigo's web server reloads, the bridge's session can be quietly invalidated, and every request after that would come back with a "missing or invalid session" error until the connection was restarted by hand. The proxy now spots that particular error, quietly re-introduces itself to get a fresh session, and replays your original request, so instead of a wall of session errors you simply get your answer.

As before, none of this ever blindly repeats an action that might already have gone through — a failure that happens *after* a request was genuinely sent is still left well alone, so a light is never toggled twice or an event fired twice. It rides along inside the plugin but it is really a change to the little stdio proxy, so it takes effect the next time the bridge connection is started up, not on a plugin reload.

176 tests now.

### 2.8.4 (2026-06-09)
A tidy-up release off the back of the deep review — the lower-priority findings that were worth doing, none of them urgent. The biggest single change is a clear-out: about 1,700 lines of dead code have gone, including three "vector store" modules that hadn't been wired into anything for a good while (the search has been plain keyword matching for ages), a token-validation helper that was created at startup and then never actually used, and a phantom "access mode" setting that was read from a config field that doesn't exist, so it could never be anything other than its default. None of it was doing anything, and carrying dormant code around just makes the place harder to read — it's all recoverable from git history if it's ever wanted again.

Alongside that, a handful of small correctness and safety fixes:

- **TLS verification can only be turned off deliberately.** When you register a webhook, switching off certificate checking now requires a genuine "off" — a stray empty or oddly-typed value can no longer quietly disable it.
- **Boolean values behave.** A device on/off-style flag passed as a real true/false is now handled properly rather than slipping through and being read as a device ID, the enable/disable-a-device tool no longer treats the word "false" as "on", and a variable set to a boolean is now stored Indigo's way (lowercase `true`/`false`) so your triggers and conditions compare it the way you'd expect.
- **The read-only "resources" view now respects scopes.** It exposes the same read-only data as the read tools, so it now needs the same `read` permission rather than being reachable by a token with none.
- **A couple of smaller niggles** — the cache now refreshes after a schedule is fired directly (a fired schedule can move devices), and a strong exact-match search no longer claims it "truncated" results when it didn't.
- **Secrets in variables are treated more carefully.** If you keep a token or password in an Indigo variable, its full value is no longer written into the event log (the log line is shortened) — though do note the read tools still return variable values in full, so a read-only token can see them. There's a short note about this in the [security section](#available-tools) above; the proper home for a real secret is `IndigoSecrets.py`.

171 tests now.

### 2.8.3 (2026-06-09)
A reliability fix for the bridge connection itself. Every so often the very first request after a long quiet spell — or the first one straight after the plugin had been reloaded — would come back with a "Connection error … broken pipe" rather than doing the job, and you'd have to ask again. The cause was in the little stdio proxy that carries requests to Indigo: it keeps one connection open and reuses it, which is the right thing to do for speed, but Indigo's web server is entitled to quietly close that connection once it has been sitting idle for a while (and a plugin reload closes it outright). When that had happened, the next request hit a dead line. The proxy already knew to reconnect and try again for harmless read-only calls, but it deliberately would not replay an action that might change something, in case it had already half-happened. The fix is to tell the two situations apart: if the request never actually made it onto the wire — which is exactly the case when the connection has gone stale — then nothing happened at the other end, so it is completely safe to reconnect and send it again, whatever the request was. Only a failure *after* the request had already been sent is now left un-retried. The upshot is that those occasional first-call hiccups simply heal themselves. It rides along inside the plugin but it's really a proxy change, so it takes effect the next time the connection is started up.

### 2.8.2 (2026-06-09)
A deep multi-agent review, run fresh against the new Claude release, going right through the plugin one lens at a time and then having a second set of agents try to knock down every finding before anything was acted on. The reassuring headline first — the security-critical core was gone over hard and held up. The SSRF firewall on the new webhooks, the connection pinning, the per-token scope layer and the secret-handling all stood up to a determined look, which is exactly what you want to hear about a plugin that can be reached from the internet.

What the review did turn up was a genuine correctness bug in the housekeeping tools, plus a cluster of smaller fixes worth having. The honest improvements this release:

- **The audit tools now tell the truth.** `audit_variables` used to flag very nearly every variable as "unreferenced", which made it worse than useless — act on it and you could delete a variable that was quietly running half the house. The cause was twofold: it only ever looked in one of the two Indigo script folders (so everything in your main "Python Scripts" folder was invisible to it), and it only matched variables used by their numeric ID, never by name. It now reads both folders, matches by name as well as ID, and cross-checks Indigo's own dependency list, so a variable used by a trigger, a schedule or by name in a script is no longer wrongly called unused. It is also now clearly labelled a *candidate* list and not a "safe to delete" list — a plugin that hard-codes an ID in its own source still can't be seen, so it tells you to double-check before deleting. The same both-folders fix flows through `find_conflicts` and `dependency_map`.
- **`write_script` won't lose your work.** If it can't write the safety backup first — a full disk, a permissions snag — it now refuses to overwrite the existing script and tells you, rather than ploughing on and leaving you with nothing. The write itself is now atomic too, so an interrupted save can't leave a half-written file.
- **The self-sufficiency figure is honest about gaps.** The energy summary used to treat a missing reading on a partial day as a zero, which could quietly inflate the self-sufficiency percentage, and it had no floor so an odd day could even show a negative. It now works the figure out only from days where it actually has both numbers, tells you how many days it used, and is clamped to a sensible range.
- **Searches return what you asked for.** A "minimal" device search was accidentally stripping out the device's own sensor readings, so a temperature sensor could come back with no temperature. And filtering a search by device type could come up short because the filter ran after the results had already been trimmed. Both fixed.
- **A few tidies on the new webhooks and config.** A busy webhook target can no longer cause a healthy one to be switched off, a corrupt saved entry can't turn a single-device watch into a firehose, the feature now defaults to off in every code path, and the InfluxDB toggle behaves itself when you open and save the config.

Two findings were deliberately left for a later release rather than rushed — a re-check on duration-gated webhooks at the moment they fire, and a tightening of the no-token case — both written up so they're not forgotten. 165 tests now.

### 2.8.1 (2026-06-09)
Hardening pass on the new Event Webhooks, off the back of a multi-agent adversarial review that tried hard to break it. The good news first — the egress firewall itself held: no way was found to make it POST to the LAN, loopback, the cloud-metadata address or the Indigo box itself, across sixteen different attack angles, and the signing and secret-handling stood up too. What the review did turn up was a handful of robustness foot-guns, all now fixed: `any_change` can no longer be quietly combined with a state condition (it would have ignored the condition); `max_fires` now counts only successful deliveries, so a flapping receiver can't make a subscription delete itself; the delivery queue is bounded so a storm of changes against a slow receiver can't grow memory without limit; the store is no longer rewritten on every dropped event; shutting down or disabling the feature now cleans up its timers properly (no orphaned worker on reload, no stale event after a disable/re-enable); and turning off TLS verification now logs a clear warning about the risk. None of these were security holes — the feature ships off by default and the tools are admin-only — but they're worth having right before anyone leans on it. 63 tests now, including the adversarial battery.

### 2.8.0 (2026-06-09)
The big one — **Event Webhooks**, the feature that lets the home call out rather than only ever answering when you ask. You register a subscription ("the next time the front door opens", "if the battery drops below 20%", "when the garage stays open for ten minutes") and the plugin POSTs a signed JSON event to a web address you run, the instant the condition is met. That turns Claude Bridge from something you consult into something that can be wired into the loop — point the events at a little listener and have it act, notify, or hand the moment to Claude with the full context.

It ships **switched off**, and it is deliberately careful about where it is allowed to send. Webhook targets are **default-deny**: nothing can be registered until you add an approved host to the allow-list (in the plugin config, or `IndigoSecrets.py` `WEBHOOK_ALLOWLIST`, which is read first). Anything pointing at the Indigo box itself, your router, the rest of the LAN, or a cloud metadata address is refused outright — a private or loopback address can only ever be reached if you knowingly opt its range in as a CIDR (e.g. `192.168.1.50/32`). Every delivery is checked again at send time (so a target can't quietly re-point itself at something internal after the fact), the connection is pinned to the address that was checked, redirects are never followed, and every event is signed with HMAC-SHA256 so your receiver can be sure it really came from your plugin. The three new tools (`webhook_create`, `webhook_list`, `webhook_delete`) are all admin-scope.

There's a small reference receiver in `examples/webhook_receiver.py` that verifies the signature and prints each event, so you can see the whole thing working in a couple of minutes. To turn it on: Plugins → Claude Bridge → Configure → tick **Enable Event Webhooks** and fill in an allow-list. (Concept inspired by mlamoure's indigo-mcp-server, but written from scratch — that project ships no licence, so nothing was copied from it.)

### 2.7.3 (2026-06-08)
A small but genuinely handy search improvement. Asking Claude to "find all the lights" now turns up your dimmers and bulbs even when they're named "Lamp" rather than "Light", "find the plugs" turns up your Shelly and Tasmota sockets, "motion" finds the occupancy sensors, and "radiator" or "trv" finds the heating zones — the search now understands the *kind* of device, not just the words in its name. It's a curated set of synonyms matched to the device types you actually have here, and it only ever *adds* matches, so a proper name match always still comes top. Worth a note for anyone reading the code — the folder is called `vector_store` but there are no embeddings and no OpenAI key involved, it has been plain in-memory keyword search for a while now, and this just makes it a bit cleverer.

### 2.7.2 (2026-06-08)
- **Colours by name.** `set_color` now takes a colour as a hex code (`#FF8000`) or a plain name (`dodgerblue`, `tomato`, and 146 others, British "grey" spellings included), so you no longer have to work out three 0–255 numbers. The individual red/green/blue channels still work exactly as before.
- **The tool list documents itself.** The table of all 136 tools further up this README is now generated straight from the plugin's own code and grouped by what each tool is allowed to do (read, write or admin), so it can't drift out of date.

### 2.7.1 (2026-06-08)
- **Plugin versions report correctly.** `get_plugin_status` and `list_plugins` were showing `1.0.0` for every plugin (they were reading the wrong field). They now show the real version.

### 2.7.0 (2026-06-06)
A thorough security and robustness pass off the back of a full multi-agent review. The headline is that the optional per-token scope layer now does what it says on the tin.

- **Per-token scopes are properly enforced now (deny-by-default).** If you hand out a `scopes.json` token marked read-only, it really is read-only. Before this, a good number of the device, variable, schedule and script tools weren't classified and quietly fell through to the read bucket, so a read-only token could still change things. Every one of the 136 tools is now sorted into read, write or admin, anything destructive (deleting, running scripts, unlocking a lock, restarting a plugin) needs admin, and a token with an empty scope list or one that isn't listed at all is denied rather than waved through. There is also a startup self-check that shouts in the log if a newly added tool ever slips through unclassified. If you don't use `scopes.json` at all then nothing changes for you — your single Indigo bearer token still has full access exactly as before, gated by Indigo's own web-server authentication.
- **The file-handling tools now stay where they belong.** The script tools, the plugin-dev helpers and `find_large_files` are confined to the Indigo and script folders, so a stray or mistyped name can't wander off elsewhere on the Mac.
- **The proxy is gentler with your arguments.** A value like `true`, `null` or a code with a leading zero is left exactly as you typed it rather than being turned into something else, the connection timeout is more generous for long-running tools, and a dropped connection no longer risks running the same action twice.
- **`restart_plugin` will no longer restart Claude Bridge itself** — that only ever pulled the rug out from under the live session. Use the Indigo Plugins menu for that.
- **A long tail of smaller robustness fixes** — guarded number handling throughout (a blank or odd config field can't crash startup any more), a couple of threading tidy-ups, a brightness request of 1 now means 1 per cent rather than full, and the historical-analysis property suggestion talks to Claude properly (it had been silently falling back).
- **New test suite** — 75 tests covering the scope model, the proxy coercion, the state filters and the script-path safety, so these don't quietly regress.

No action needed on your part — update the plugin and carry on as before.

### 2.4.1 (2026-05-23)
- **Credentials no longer leaked to subprocesses (secrets-policy compliance).**
  Up to v2.4.0 the plugin wrote `ANTHROPIC_API_KEY` plus the full InfluxDB
  credential set (host / port / username / password / database) into
  `os.environ` so the MCP server modules could read them via `os.environ.get(...)`.
  Two tool handlers shell out without an explicit `env=` (`system_tools_handler.py`
  and `scripting_shell_handler.py`), inheriting those credentials into every
  child process — a real leak.
- New `mcp_server/runtime_config.py` in-process config store. `plugin.py`
  populates it at startup and on every PluginConfig save; downstream modules
  (`influxdb/client.py`, `openai_client/main.py`, `tools/historical_analysis/main.py`,
  `mcp_handler.py`) read via `runtime_config.get(...)` instead of `os.environ`.
- No behaviour change for users — the plugin starts, MCP tools work, etc.
  exactly as before. Subprocess leak gone.

### 2.4.0 (2026-05-22)
- **Six new MCP tools** exposing recently-verified Indigo APIs:
  - `fire_trigger` — execute an Indigo trigger directly by ID/name
    (`indigo.trigger.execute`). Complements `fire_indigo_event` which fires
    custom Claude-Bridge plugin events via the `claudeEvent` channel.
  - `get_reflector_url` — return `indigo.server.getReflectorURL()`.
  - `create_device_folder` / `create_variable_folder` — idempotent folder
    creation via `indigo.devices.folder.create()` /
    `indigo.variables.folder.create()`.
  - `execute_indigo_python` — run arbitrary Python in the plugin's Indigo
    context via in-process `exec()` (same pattern as `run_script` but for
    ad-hoc code strings). `mode='exec'` returns captured stdout/stderr;
    `mode='eval'` returns the expression's repr in `value`. **ADMIN scope.**
  - `execute_plugin_menu_item` — click a plugin's menu item under the
    Indigo client's **Plugins** menu via AppleScript GUI scripting.
    The only known way to fire a third-party plugin's `<MenuItem>`
    callback from outside (the `indigo.server.getPlugin()` wrapper has
    no menu API). Requires the Indigo GUI running on the host.
    **ADMIN scope.**
- New tool package `mcp_server/tools/scripting_shell/`.
- `scope_manager`: `fire_trigger`, `create_device_folder`,
  `create_variable_folder` classified WRITE; `execute_indigo_python` and
  `execute_plugin_menu_item` classified ADMIN.

### 2.3.3 (2026-05-18)
- **`run_script` now pre-injects `indigo` into the exec globals**, matching
  Indigo's GUI action runner. Scripts run via this tool no longer need an
  explicit `import indigo` at the top — bare `indigo.devices.iter(...)` works.
  Discovered when an ad-hoc device-create script for MQTTExplorerBridge
  failed with `name 'indigo' is not defined`. Fix in
  `mcp_server/tools/script_tools/script_tools_handler.py:run_script`.

### 2.3.2 (2026-05-12)
- **`ServerApiVersion` lowered 3.6 → 3.4.** Plugin uses `requirements.txt`
  auto-install (introduced API 3.4) but does NOT use the API 3.6 feature
  (`dict(indigo.triggers[id])`-style iteration on Trigger/Schedule objects);
  it serialises those by reading attributes one-by-one. Lowering the API
  floor extends compatibility down to Indigo 2023.2 / Python 3.11
  (was Indigo 2024.2). Verified by grep — no `dict()` calls on
  trigger/schedule objects anywhere in the codebase.
- README "Platform" / "Requirements" lines corrected: was overstated as
  "Indigo 2025.2 / Python 3.13" (which is just the dev environment); now
  honestly reflects the API floor of 3.4 → Indigo 2023.2 / Python 3.11+.

### 2.3.1 (2026-05-12)
- **Docs sync** — README and `CAPABILITY_SUMMARY.md` brought up to date with the
  current tool surface. Tool count corrected from the stale "64" reference to
  the real 80. Categories expanded to cover the heating, energy, triggers /
  schedules, notifications, audit, and reporting groups that had drifted out of
  the previous categorisation. All log strings and config-dialog labels
  updated from `secrets.py` → `IndigoSecrets.py` to match the May-2026 rename
  policy.

### 2.3.0 (2026-05-10)
- **Standards-compliance pass** following the audit applied to all CliveS plugins
- **Version is now read dynamically from Info.plist** via `self.pluginVersion` (no separate Python constant)
- **Startup banner** via bundled `plugin_utils.py` — shows plugin name, version, ID, Indigo version, API version, architecture, Python version, macOS version
- **Show Plugin Info** menu item — re-runs the banner on demand with extras (MCP URL, Anthropic key status, InfluxDB status, access mode)
- **Trigger lifecycle fixed** — implemented `triggerStartProcessing` / `triggerStopProcessing` and rewrote `fire_claude_event()`. Previously called the non-existent `self.triggerEvent()` method which raised `AttributeError` silently, so `claudeEvent` triggers never actually fired
- **`deviceUpdated` self-loop guard** — plugin both `subscribeToChanges()` and writes its own `mcpServer` device states; without the guard a future state write inside the callback could loop
- **Bearer token rotated out of source** — `indigo_mcp_proxy.py` now ships with a deliberately invalid placeholder. Real value comes from Indigo's IWS `Preferences/secrets.json` first, with `CLAUDEBRIDGE_BEARER_TOKEN` in `IndigoSecrets.py` as a fallback. Plugin patches the deployed copy at install time
- **Secrets handling rebuilt** using `importlib` pattern with `clives_secrets` module name to avoid shadowing Python's stdlib `secrets` module (used by `mcp_handler` for `token_urlsafe()`). Also now correctly sources `INFLUXDB_*` from `IndigoSecrets.py` (was PluginConfig-only)
- **PluginConfig.xml policy banner** at the top — explicit explanation of IndigoSecrets.py vs PluginConfig precedence + the keys this plugin reads
- **Auto-configure Claude Code opt-out** — new checkbox so users can disable silent rewriting of `~/.mcp.json` and `~/.claude/settings.json`
- `fire_claude_event` data serialisation fixed (was collapsing `0` and `False` to `""`)
- Bare `except:` in `mcp_server/common/vector_store/validation.py` changed to `except Exception:`

### 2.2.0
- Prior release.

### 2.0.0 (2026-04-05)
- **64 MCP tools** (up from 23): added Scripts (5), Memory (4), Event Subscriptions (5), Audit (7), Home Intelligence (7), plus `find_conflicts` and `home_status_report`
- Script tools with auto-backup on write
- Persistent memory store (memory.json) — `remember` / `recall` / `forget`
- Push-model event subscriptions via ring-buffer fed by `deviceUpdated` / `variableUpdated` callbacks
- Audit tools: `audit_home`, `find_devices_in_error`, `find_low_battery`, `find_stale_devices`, `audit_variables`, `dependency_map`, `find_conflicts`
- Home intelligence: `home_status`, `energy_status`, `heating_status`, `security_status`, `home_status_report`
- Energy intelligence: reads SigenEnergyManager daily log files (`energy_log_days`, `energy_daily_summary`, `energy_compare`)
- `variableUpdated()` callback added; `deviceUpdated()` extended to queue all non-mcpServer state changes
- Fixed `Scripts` folder resolution — prefers `Scripts` over legacy `Python Scripts`

### 1.2.0 (2026-04-02)
- Zero-config install: plugin self-configures Claude Code on first enable
- `_setup_claude_code_integration()` in `startup()`: copies bundled proxy to `Scripts/`, patches Bearer token, updates `~/.mcp.json` and `~/.claude/settings.json`
- `setup.py` at repo root for CLI/advanced users
- Proxy (`indigo_mcp_proxy.py`) now lives inside bundle — single source of truth
- Auto-creates Claude Bridge device on first startup — no manual "New Device" step

### 1.1.1 (2026-03-24)
- Fixed `get_devices_by_state`: now searches full device data including top-level properties (e.g. `heatIsOn`, `onState`)
- Fixed `get_devices_by_state` crashing when proxy coerces `state_value` from string to bool
- `get_devices_by_state` schema changed to flat `state_key` + `state_value` string params (avoids object type validation issues)

### 1.1.0 (2026-03-24)
- Added `device_control` tool: find and control a device by name in a single MCP call (~1s vs ~5s)
- Search results now slim by default (id, name, state, score only); use `detail="full"` for complete config
- Fixed `get_device_by_id`, `get_variable_by_id`, `get_action_group_by_id` rejecting numeric IDs
- Proxy: added `proxy_elapsed_ms` timing to all tool call responses
- Reduced vector store sync log verbosity

### 1.0.3 (2026-03-24)
- API key field can now be left blank if `IndigoSecrets.py` provides `ANTHROPIC_API_KEY`
- Fixed config save erroring when API key field is blank but IndigoSecrets.py has the key
- Added `indigo_mcp_proxy.py` to repository

### 1.0.2 (2026-03-24)
- Renamed from "MCP Server" to "Claude Bridge"
- Replaced OpenAI/Voyage AI with Anthropic Claude API throughout
- Fixed text search: LLM query expansion disabled (broke substring matching)
- Proxy: persistent HTTP keep-alive connection
- Proxy: automatic type coercion (string → int/float/array)
- Proxy: MCP protocol version translation (2025-11-25 → 2025-06-18)
- Removed all third-party AI service dependencies

### 1.0.1
- Initial release with OpenAI + Voyage AI embeddings

---

## Logging

Every log line is prefixed with a millisecond timestamp `[HH:MM:SS.mmm]` so
events can be correlated tightly with other CliveS plugins (Device Activity
Monitor uses the same convention).

To turn the prefix off (or back on) at any time:

**Plugins → Claude Bridge → Toggle Timestamps in Log (on/off)**

The setting is stored in `pluginPrefs` (`timestampEnabled`) and persists across
restarts. Defaults to ON.

---

## Contributing

Pull requests welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for how to run
the test suite (no Indigo install needed) and the recipe for adding a new MCP
tool. Every push and pull request runs the tests, lint and a docs-staleness
check automatically.

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

Built conversationally — CliveS describing what the plugin should do and keeping it honest, Claude writing the code and testing it against the live system, each new version developed through the one before it. Which, fittingly, is exactly the way of working this plugin exists to give you. The proof is the plugin itself.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
