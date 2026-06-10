# ClaudeBridge — Full Capability Summary
*For anyone evaluating whether to download and install ClaudeBridge v2.8.6*

ClaudeBridge connects **Claude Code** (Anthropic's AI coding agent) directly to your running **Indigo home automation server** via the Model Context Protocol (MCP). Instead of asking Claude to write scripts blindly, Claude can read your actual devices, check live states, query history, write and test scripts, and reason about your real home — all from a single conversation.

**Current tool count: 139 tools across 19 categories.** This document describes everything ClaudeBridge can do, what it requires, and what to expect in terms of speed and cost. (The README's tool table is auto-generated from the plugin's own registry and is the authoritative per-tool list.)

---

## What Claude Can Do With ClaudeBridge Installed

### 1. Device Control & Queries (16 tools)

Read and control every Indigo device without leaving the conversation:

- List all devices (with optional folder or type filters)
- Get a device by ID or by name (exact / partial / case-insensitive)
- Find devices by current state (e.g. "all motion sensors currently triggered")
- Find devices by type (relay, dimmer, thermostat, sensor, speed control, etc.)
- Natural-language `search_entities` across devices, variables, action groups
- Turn devices on / off / toggle (`device_control` does name lookup + action in one call)
- Set dimmer brightness (0–100%), RGB / colour-temp, fan speed
- Lock / unlock smart locks
- Request hardware status update
- Whole-home snapshot (`home_status`) — SOC, PV, grid, errors at a glance

**Example prompts:**
> "Which lights are currently on in the house?"
> "Turn off everything in the living room folder"
> "What is the current wattage on the Shelly plug in the garage?"

---

### 2. Variable Management (5 tools)

Full read/write access to Indigo variables:

- List all variables (with optional folder filter)
- List variable folders
- Get a single variable by ID
- Create new variables (with optional folder assignment)
- Update variable values

**Example prompts:**
> "Create a variable called morning_routine_done and set it to false"
> "Show me everything in the Octopus_Energy variable folder"
> "Update the heating_override variable to 1"

---

### 3. Action Groups (3 tools)

- List all action groups
- Get a single action group by ID
- Execute an action group

**Example prompts:**
> "Run the Goodnight action group"
> "What action groups do I have that mention heating?"

---

### 4. Plugin Management (4 tools)

- List all installed plugins with version and status
- Get plugin detail by ID
- Get plugin enabled / running status
- Restart a plugin

**Example prompts:**
> "Which plugins are currently disabled?"
> "Restart the SigenEnergyManager plugin"
> "What version of ClaudeBridge am I running?"

---

### 5. Event Log Queries (1 tool)

Search the live Indigo event log:

- Filter by keyword, device name, or plugin
- Specify how many entries to retrieve
- Returns timestamped log lines in reverse-chronological order

**Example prompts:**
> "Show me the last 20 log entries from SigenEnergyManager"
> "Has the back door sensor triggered today?"
> "Are there any ERROR messages in the log from the last hour?"

---

### 6. Script Tools (8 tools)

Full read/write access to the Indigo Scripts folder (the standard location where all Indigo Python automation scripts live — typically `Scripts` under the Perceptive Automation application support directory). If a `Python Scripts` folder exists instead, it is used as a fallback automatically:

- **Read** a script — returns full content with line count and modification date
- **Write** a script — overwrites with auto-backup (timestamped, max 5 per script)
- **Create** a script — fails safely if it already exists
- **Delete** a script — archives to `_backups/_archived/`, never permanently deletes
- **List backups** for a script — shows all auto-saves with timestamps
- **Scaffold** a new automation script — generates a complete CliveS-convention Python file with file header, `log()` helper, and named constants for every device/variable ID you supply (names looked up live from Indigo)

**Example prompts:**
> "Read the EvoHome_Radiator_Update script and explain what it does"
> "Create a new script called Morning_Lights that turns on the hall and kitchen at 07:00"
> "Show me the backups for the Bedtime_Routine script"
> "Scaffold a new script called Battery_Alert using device ID 123456 and variable ID 789012"

---

### 7. Memory Tools (4 tools)

Persistent cross-session memory stored as JSON on disk — Claude remembers things between conversations:

- **Remember** — store a fact, preference, or note (with optional topic tag)
- **Recall** — retrieve memories matching a query or topic
- **Forget** — delete a specific memory by ID
- **List memories** — show all stored memories with metadata

Capped at 100 entries. When full, oldest entry of the same topic is removed first before touching other topics, so no single topic crowds out the rest.

**Example prompts:**
> "Remember that the conservatory sensor is unreliable in cold weather"
> "What do you remember about my heating preferences?"
> "Forget that note about the garage door"

---

### 8. Event Subscriptions & Push Feed (6 tools — incl. event log)

Real-time monitoring of device and variable changes:

- **Subscribe** — register interest in all events, a specific device, or a specific variable
- **Unsubscribe** — remove a subscription
- **List subscriptions** — show what is currently being monitored
- **Get events** — retrieve all events since a given timestamp (deduplication: rapid changes to the same entity within 1 second are merged)

The plugin automatically queues every device state change and variable update as they happen; Claude polls for new events on demand.

**Example prompts:**
> "Subscribe to the back door sensor and tell me the next time it triggers"
> "Show me all device events from the last 5 minutes"
> "Watch the battery_soc variable and alert me if it drops below 15%"

---

### 9. Audit, Health & Diagnostics (12 tools)

A wide diagnostic toolkit covering the whole Indigo install:

**`audit_home`** — full home configuration audit (devices, plugins, scripts, variables)
**`audit_variables`** — audit variable usage and references
**`security_status`** — security sensor snapshot
**`system_health`** — whole-system health summary

**Finders:**
- `find_devices_in_error` — devices reporting error states
- `find_low_battery` — devices with low battery
- `find_stale_devices` — devices not updated recently
- `find_orphaned_plugin_data` — plugin prefs / data dirs with no installed plugin
- `find_orphaned_scripts` — scripts referenced nowhere
- `find_large_files` — outsized files in plugin data / logs
- `find_conflicts` — duplicate names, shared hardware addresses, orphaned references, variable write races

**`dependency_map`** — for any device or variable, find everything that references it (action groups, scripts that contain its numeric ID, etc.)

**Example prompts:**
> "What would break if I deleted the Hall Motion Sensor device?"
> "Scan my setup for conflicts and tell me what needs fixing"
> "Which scripts reference variable ID 987654?"

---

### 10. Home Status Report (1 tool)

Generates a prose narrative summary of your home's current state, configurable by section:

- **Energy** — solar generation, battery SOC, grid status, today's import/export
- **Heating** — active zones, current vs. target temperatures, any overheating rooms
- **Security** — open doors/windows, triggered motion sensors, lock states
- **Devices** — offline devices, devices in unexpected states, recently changed
- **Alerts** — anything flagged as needing attention
- **Automation** — disabled triggers, recently failed action groups

**Example prompts:**
> "Give me a full home status report"
> "Just the energy and heating sections please"
> "Is anything unusual happening in the house right now?"

---

### 11. General Search (1 tool)

Search across all entity types simultaneously:

- Finds devices, variables, action groups, triggers, and plugins matching a name fragment
- Returns brief summary of each match with ID and current state

**Example prompts:**
> "Find everything related to the word 'garden'"
> "Is there anything called morning in my setup?"

---

### 12. Heating / HVAC (6 tools)

Full control of any Indigo thermostat device:

- `heating_status` — per-zone snapshot
- `set_heat_setpoint` / `set_cool_setpoint` — absolute targets
- `increase_heat_setpoint` / `decrease_heat_setpoint` — bump up/down
- `set_hvac_mode` — off / heat / cool / auto / fan

**Example prompts:**
> "What heating zones are above their target right now?"
> "Bump the hall by 1 degree for the next hour"
> "Put the conservatory into auto mode"

---

### 13. Energy intelligence (4 tools)

Reads SigenEnergyManager's daily log files for richer energy analysis than the live `energy_status` snapshot:

- `energy_status` — solar / battery / grid live
- `energy_log_days` — list available log days
- `energy_daily_summary` — day's energy summary (imports, exports, PV, SOC trace)
- `energy_compare` — side-by-side comparison across days

**Example prompts:**
> "Compare yesterday's energy use against the same day last week"
> "What was my solar peak last Friday?"
> "Summarise energy for Tuesday"

---

### 14. Triggers & schedules (8 tools)

- `list_triggers` / `list_schedules`
- `enable_trigger` / `disable_trigger` / `enable_schedule` / `disable_schedule`
- `fire_indigo_event` — fire a custom "Claude Bridge → Claude Event" trigger with a JSON payload that Indigo Triggers can read via `%%eventData:name%%` etc.
- `fire_trigger` — execute an Indigo trigger directly by ID or name (`indigo.trigger.execute`). Use when you want to invoke a specific trigger's actions without the eventData payload channel.

**Example prompts:**
> "Disable the Morning_Lights trigger for the rest of today"
> "Are any of my schedules disabled that shouldn't be?"
> "Fire a 'leak_detected' event with location=kitchen"
> "Fire trigger 'Sunset Routine' now"

---

### 15. Notifications & logging (3 tools)

- `send_email` — via Indigo's first SMTP device
- `send_notification` — via Pushover (priority, sound, title, body)
- `log_message` — write a line to the Indigo event log

**Example prompts:**
> "Pushover me when this finishes"
> "Email a summary of today's energy report to me"

---

### 16. Folders & server info (3 tools)

- `create_device_folder` / `create_variable_folder` — idempotent folder creation; returns the existing folder if one with the same name already exists.
- `get_reflector_url` — returns the Indigo Reflector remote-access URL if configured (else reports it's not configured).

**Example prompts:**
> "Make a new variable folder called Forecasting"
> "What's our reflector URL?"

---

### 17. Scripting shell (2 tools — ADMIN scope)

These two tools require the token to hold the `admin` scope (default tokens do; restricted tokens won't). Treat them as full code execution on the Indigo server.

- `execute_indigo_python` — run arbitrary Python in this plugin's Indigo context via in-process `exec()` (same pattern as `run_script` but for ad-hoc code strings). `mode='exec'` (default) returns captured stdout/stderr; `mode='eval'` evaluates a single expression and returns its repr in `value`. Useful when an action needs a one-shot Indigo API call that isn't covered by a dedicated tool (e.g. probing a brand-new API method, reading an obscure device property, calling `indigo.thermostat.setHeatSetpoint` from a script outside the Indigo context).
- `execute_plugin_menu_item` — click a plugin's menu item under the Indigo client's **Plugins** menu via AppleScript GUI scripting (e.g. `plugin_name="Zigbee2MQTT Bridge"`, `menu_item_name="Refresh Device Capabilities"`). The only known way to invoke a third-party plugin's `<MenuItem>` callback from outside, because `indigo.server.getPlugin()` exposes no menu API. Requires the Indigo GUI client to be running on the host and System Events permission granted.

**Example prompts:**
> "Use execute_indigo_python to print the displayStateId of every Z2M button device"
> "Click the 'Refresh Device Capabilities' menu item under Zigbee2MQTT Bridge"

---

### 18. Plugin Development & Testing Workflow

ClaudeBridge makes Claude a hands-on partner for developing, debugging, and testing Indigo plugins — because it can see your live system at every step.

**Plugin introspection:**
- List all installed plugins with version, enabled/disabled state, and plugin ID
- Get full status for a specific plugin — confirms it loaded, shows its bundle ID and version
- Read the event log filtered by plugin name — see exactly what a plugin is logging in real time
- Inspect every device the plugin has created, including all custom plugin states, via `get_device_by_id`
- Watch plugin device states update live using event subscriptions — no manual refreshing

**During development (edit → test → verify loop):**
- Read the current plugin source file directly from the Scripts or plugin bundle folder
- Write an updated version back — ClaudeBridge auto-backs up the previous copy before overwriting
- Restart the plugin immediately after a change — no need to touch Indigo's UI
- Query the event log straight away to confirm the new version loaded and ran correctly
- Check device states before and after an action to verify the change had the intended effect

**Debugging:**
- Pull the last N log lines from the event log to find errors or unexpected output
- Subscribe to a specific device's state changes and watch what the plugin does when triggered
- Use `find_conflicts` to check whether a new plugin has introduced naming clashes or address collisions with existing devices
- Use `dependency_map` to understand everything that depends on a device or variable the plugin manages — so you know the blast radius before making a change

**Testing scripts that interact with plugins:**
- Scaffold a complete test script with correct header convention, named constants for all device/variable IDs, and a `log()` helper — ready to run immediately
- Execute action groups that exercise the plugin from the outside
- Check variable values that the plugin writes to confirm correct output
- Read backed-up script versions to compare before/after behaviour

**Example prompts:**
> "Restart SigenEnergyManager and show me the last 20 log lines to confirm it started cleanly"
> "Read the current plugin.py for ClaudeBridge and tell me what version of each handler it's using"
> "I just updated the battery_manager — check the device states on the Sigenergy device and tell me if the SOC threshold changed"
> "Watch the hall motion sensor and tell me the next three state changes you see"
> "Did the plugin log any errors in the last hour?"
> "Scaffold a test script that exercises the shellyRelay device with ID 123456 and logs the result to variable 789012"

### 19. Outbound Event Webhooks (3 tools — ADMIN scope)

Push Indigo events to an external HTTPS receiver the moment they happen — no polling. Added in v2.8.0.

- `webhook_create` — subscribe a receiver URL to device/variable changes, with optional state conditions, transition detection (`any_change` or specific from→to), dwell timers (state must hold for N seconds before firing) and a max-fires cap
- `webhook_list` — list active subscriptions (signing keys redacted)
- `webhook_delete` — remove a subscription

**Security posture (default-deny):** the feature ships **disabled** (a PluginConfig checkbox turns it on). Receiver URLs must be HTTPS and pass an egress firewall — private/loopback/link-local/metadata address ranges are hard-blocked, the destination must be on your explicit allowlist (`IndigoSecrets.WEBHOOK_ALLOWLIST`, the config field, or `webhook_allowlist.json`), the URL is re-vetted at send time with the connection pinned to the vetted IP, and redirects are never followed. Every delivery is HMAC-SHA256 signed so the receiver can verify origin. Delivery is queued on a background worker — a slow receiver never blocks Indigo.

A reference receiver and a webhook→Pushover relay ship in the repo's `examples/` folder.

**Example prompts:**
> "Create a webhook that POSTs to my relay whenever a water leak sensor turns on"
> "List my webhook subscriptions and tell me which one fired last"

---

## What Claude Cannot Do (Hard Limits)

These are Indigo API restrictions — not ClaudeBridge limitations:

| Capability | Status |
|---|---|
| Read trigger conditions (what makes a trigger fire) | Not exposed by Indigo API |
| Read action group steps (what actions it contains) | Not exposed by Indigo API |
| Create or modify triggers programmatically | Not possible via Indigo API |
| Create or modify action groups programmatically | Not possible via Indigo API |
| Access HomeKit, Z-Wave, or Zigbee pairing internals | Not exposed |
| Control devices in other home automation platforms directly | Only via Indigo's own device model |

For automations, the recommended approach is: **Claude scaffolds a script → you review it → you run it from Indigo**. Claude cannot push a trigger live without you clicking Enable.

---

## Subscription & Cost Requirements

### What You Need

ClaudeBridge is designed for **Claude Code** — Anthropic's AI coding and automation agent. This is distinct from the Claude.ai chat website.

**Option A — Claude.ai Pro or Max (recommended)**

| Plan | Monthly cost (US) | Claude Code included |
|---|---|---|
| Free | $0 | No — Claude Code not available |
| Pro | ~$20/month | Yes |
| Max | ~$100/month | Yes — higher limits |

Pro is the right starting point for home automation use. Claude Code usage is included in the subscription flat fee — no additional per-query billing.

**Option B — Anthropic API key (pay-as-you-go)**

No monthly subscription. Billed per token at model rates. Suitable for developers who already have API access or want precise cost control.

**Free Claude.ai does not work.** The free tier has no Claude Code access and no API access. ClaudeBridge would be unreachable.

### Typical Cost on API Billing

For users on Option B (API key), costs are extremely low for home automation queries:

| Query type | Approx. cost |
|---|---|
| `list_devices` (100 devices) | ~$0.001 |
| `home_status_report` (full) | ~$0.003–0.005 |
| `query_event_log` (50 entries) | ~$0.002 |
| Write + debug a script (5-minute session) | ~$0.02–0.05 |
| Active month (daily status, weekly diagnostics, occasional scripting) | ~$0.50–1.00 |

At Claude Sonnet pricing (~$3/million input tokens, ~$15/million output tokens), a typical month of active ClaudeBridge use is well under $1 on API billing, or effectively free within a Pro subscription.

---

## Speed & Timing — What to Expect and Why

### The Round-Trip

Every ClaudeBridge interaction has three stages:

```
You type a prompt
    → Claude reasons about what tools to call            [Anthropic servers, ~1–3s]
    → Claude calls tool(s) via MCP → Indigo responds     [local network, <100ms]
    → Claude reads results and writes its reply           [Anthropic servers, ~1–5s]
Total visible response time: typically 3–10 seconds
```

The overwhelming bottleneck is **Anthropic's server response time** — the AI model runs entirely on Anthropic's infrastructure, not on your Mac. No amount of local hardware improvement changes this.

### Why Local Hardware Makes Almost No Difference

ClaudeBridge itself is architecturally lightweight:
- Each tool call is a short Python function that queries Indigo's in-memory object model
- No large datasets are held in memory (the largest structure is the 500-entry events deque, ~100KB)
- No ML inference, no image processing, no background computation
- All external API calls (Modbus, Solcast, Octopus) are network-bound regardless

**RAM:** Once Indigo's baseline requirements are met (8GB comfortable for a full plugin stack), additional RAM brings no ClaudeBridge benefit.

**CPU:** Tool calls complete in milliseconds. Even listing 500 devices is faster than the network round-trip to Anthropic.

**Storage:** No meaningful disk I/O except when writing scripts or backups.

### Factors That Do Affect Speed

| Factor | Impact | Why |
|---|---|---|
| Anthropic server load | High | AI model runs there — peak times add 2–5s |
| Your internet connection latency | Moderate | Every prompt + response crosses the internet |
| Number of Indigo devices | Minor | More devices = slightly larger JSON payloads |
| Complex multi-tool queries | Minor | Claude may chain 3–4 tool calls; each adds one round-trip |
| Indigo's own load | Minor | If Indigo is processing a Z-Wave flood, tool calls queue briefly |

### Multi-Step Queries

For complex requests ("scan for conflicts and then tell me which scripts reference the affected devices"), Claude will call multiple tools in sequence — each tool call adds roughly one Anthropic round-trip of latency. A five-tool diagnostic session might take 20–40 seconds end-to-end. This is expected behaviour, not a performance problem.

### Local-Only Operations (Fast)

Script reads, writes, and backups are entirely local — no Anthropic round-trip for the file operation itself. Only the conversation around them involves the AI.

---

## Summary

| Capability area | Tools | Notes |
|---|---|---|
| Device queries & search | 6 | List, get, search; by id / name / type / state |
| Device control | 10 | On/off/toggle/brightness/colour/fan/lock/unlock + whole-home status |
| Heating / HVAC | 6 | Setpoints, mode, increment helpers |
| Energy intelligence | 4 | Live status + SigenEnergyManager daily logs |
| Variable management | 5 | Full CRUD, folder support |
| Action groups | 3 | List, get, execute |
| Triggers & schedules | 8 | List, enable/disable, plus `fire_indigo_event` + `fire_trigger` |
| Plugin management | 4 | List, get, status, restart |
| Scripts | 8 | Read/write/create/delete/run/scaffold/list/backups |
| Events & subscriptions | 6 | Event log + real-time device/variable change feed |
| Memory | 4 | Persistent cross-session, topic-organised |
| Audit, health, diagnostics | 12 | Wide finder set + dependency map + conflict scan |
| Notifications & logging | 3 | Email, Pushover, write to event log |
| Reporting & analysis | 2 | `home_status_report` + `analyze_historical_data` |
| Folders & server info | 3 | Idempotent folder creation + Reflector URL |
| Scripting shell (ADMIN scope) | 2 | `execute_indigo_python` + `execute_plugin_menu_item` |
| Extended IOM wrappers (v2.5) | 43 | Thin wrappers over additional Indigo Object Model APIs (delete/duplicate/rename/move, fan/speed/sprinkler control, dependency lookups, etc.) |
| Plugin-dev helpers (v2.6) | 7 | `plugin_lint` / `plugin_validate_xml` / `plugin_node_check_html` / `plugin_diff_source_vs_installed` / `plugin_show_packages_versions` / `plugin_refresh_deps` / `device_history` |
| **Total** | **136** | |

**Requirements:** Indigo 2023.2+ (Python 3.11+), macOS, Claude Code (requires Claude.ai Pro/Max or Anthropic API key). Developed and tested on Indigo 2025.2 / Python 3.13.

**Cost:** Included in Claude.ai Pro ($20/month) or under $1/month on API billing for typical home automation use

**Speed:** 3–10 seconds per interaction — dominated by Anthropic's AI response time, not local hardware
