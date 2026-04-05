# ClaudeBridge — Full Capability Summary
*For anyone evaluating whether to download and install ClaudeBridge v2.0.0*

ClaudeBridge connects **Claude Code** (Anthropic's AI coding agent) directly to your running **Indigo home automation server** via the Model Context Protocol (MCP). Instead of asking Claude to write scripts blindly, Claude can read your actual devices, check live states, query history, write and test scripts, and reason about your real home — all from a single conversation.

This document describes everything ClaudeBridge can do, what it requires, and what to expect in terms of speed and cost.

---

## What Claude Can Do With ClaudeBridge Installed

### 1. Device Control & Queries (12 tools)

Read and control every Indigo device without leaving the conversation:

- List all devices (with optional folder or type filters)
- Get a single device by ID — including all custom states, plugin states, and metadata
- Find devices by current state (e.g. "all motion sensors currently triggered")
- Find devices by type (relay, dimmer, thermostat, sensor, speed control, etc.)
- Turn devices on or off
- Set dimmer brightness (0–100%)
- Full device control — send any supported command with a values dictionary

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

### 4. Plugin Management (3 tools)

- List all installed plugins with version and status
- Get detailed status for a specific plugin
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

### 6. Script Tools (6 tools)

Full read/write access to the Indigo Python Scripts folder:

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

### 8. Event Subscriptions & Push Feed (4 tools)

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

### 9. Audit & Diagnostics (2 tools)

**Dependency map** — for any device or variable, find everything that references it:
- Action groups that act on it
- Triggers that watch it
- Scripts that contain its numeric ID

**Find conflicts** — scans your entire Indigo setup for five classes of problem:
- Duplicate device names (case-insensitive)
- Multiple devices sharing the same hardware address
- Duplicate trigger names
- Orphaned script references (a script contains an ID that no longer exists)
- Variable write races (multiple scripts calling `updateValue()` on the same variable ID)

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

### 12. Plugin Development & Testing Workflow

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
| Device control & queries | 12 | Full read/write, all device types |
| Variable management | 5 | Full CRUD, folder support |
| Action groups | 3 | List, get, execute |
| Plugin management | 3 | List, status, restart |
| Event log queries | 1 | Live search with filters |
| Script tools | 6 | Read/write/create/delete/scaffold/backups |
| Memory tools | 4 | Persistent cross-session, topic-organised |
| Event subscriptions | 4 | Real-time device/variable change feed |
| Audit & diagnostics | 2 | Dependency map + conflict scanner |
| Home status report | 1 | Prose narrative, configurable sections |
| General search | 1 | Cross-entity name search |
| Plugin dev & testing | — | Workflow combining tools above |
| **Total** | **64** | |

**Requirements:** Indigo 2025.1+, macOS, Claude Code (requires Claude.ai Pro/Max or Anthropic API key)

**Cost:** Included in Claude.ai Pro ($20/month) or under $1/month on API billing for typical home automation use

**Speed:** 3–10 seconds per interaction — dominated by Anthropic's AI response time, not local hardware
