# Claude Bridge — Indigo Plugin

**Claude Bridge** is an [Indigo](https://www.indigodomo.com) home automation plugin that connects your Indigo system directly to [Claude AI](https://www.anthropic.com/claude) via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io).

Once installed, Claude can query device states, turn devices on and off, read and write variables, execute action groups, search your home's entity database, and query the Indigo event log — all in natural language, with no manual scripting required.

**Author:** CliveS & Claude Sonnet 4.6
**Platform:** Indigo 2023.2 or later, macOS (Python 3.11+ bundled with Indigo)

*Developed and tested on Indigo 2025.2 / Python 3.13. Older Indigo releases that meet the minimum API version above should also work — the API floor is what Indigo's plugin loader actually checks.*
**Bundle ID:** `com.clives.indigoplugin.claudebridge`
**Version:** 2.3.2

---

## How it works — Claude Code ↔ Claude Bridge ↔ Indigo

Claude Bridge runs inside Indigo as a small **MCP server** (Model Context
Protocol — an open standard from Anthropic for letting AI agents call
external tools). [Claude Code](https://claude.ai/download), Anthropic's
terminal-based coding agent, connects to that server via a tiny stdio
proxy and gains access to **86 tools** that read and write your Indigo
system.

```
┌─────────────────────┐         ┌──────────────────────┐         ┌──────────────┐
│  Claude Code        │  stdio  │  indigo_mcp_proxy.py │  HTTPS  │  Indigo IWS  │
│  (terminal)         │ ───────►│  (local Python)      │ ───────►│  + plugin    │
│  asks for tool      │         │  adds Bearer token,  │         │  exposes 86  │
│  Claude reasons     │         │  protocol bridging   │         │  MCP tools   │
└─────────────────────┘         └──────────────────────┘         └──────────────┘
```

The proxy script is auto-installed by the plugin and auto-registered in
your Claude Code config. From your point of view it's invisible — you
just open a Claude Code session and the `indigo-mcp` toolset is there.

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

## Features

- **86 MCP tools** — full read/write access to devices, variables, action groups, triggers, schedules, plugins, event log, scripts, memory, events, audit & health, heating, energy, notifications, folders, and home intelligence (plus admin-scope scripting shell)
- **`device_control` — single-call search + action** — find and control a device by name in one round trip (~1s)
- **Natural language entity search** — find devices by description ("conservatory lamp", "bedroom sensor")
- **Fast slim search** — returns lightweight results by default; use `detail="full"` only when deep config is needed
- **Claude-powered** — uses Anthropic's Claude API directly; no OpenAI or third-party embedding services
- **Local text search** — fast substring/fuzzy matching; no vector database required
- **Session management** — persistent MCP sessions with per-session access control
- **Secure** — Bearer token authentication on all requests; configurable access modes

---

## Requirements

- Indigo 2023.2 or later (Python 3.11+)
- macOS (runs on the Indigo server machine)
- Python 3.11+ (bundled with Indigo 2023.2+)
- [Anthropic API key](https://console.anthropic.com) (Claude API)
- [Claude Code](https://claude.ai/download) or Claude Desktop (to use the tools)

---

## Installation

### Quick Install (recommended)

Clone the repo and run the setup script — it handles everything except enabling the plugin in Indigo:

```bash
git clone https://github.com/Highsteads/ClaudeBridge.git
cd ClaudeBridge
python3 setup.py
```

The script:
- Copies the plugin bundle to Indigo's Plugins directory
- Copies the proxy script to Indigo's `Scripts` directory
- Reads your Bearer token from Indigo's `secrets.json` and patches the proxy automatically
- Creates/updates `~/.mcp.json` and `~/.claude/settings.json`

Then do these two final steps manually:

1. **Indigo → Plugins → Manage Plugins → Enable Claude Bridge**
   *(The plugin auto-creates its device on first enable — no "New Device" step needed)*

2. **Restart Claude Code** — you should see 86 `indigo-mcp` tools available

> **Credentials policy:** All sensitive values are read from
> `/Library/Application Support/Perceptive Automation/IndigoSecrets.py` first; the
> plugin's PluginConfig dialog is a fallback only. Keys this plugin reads:
> `ANTHROPIC_API_KEY`, `CLAUDEBRIDGE_BEARER_TOKEN`, and (optional) `INFLUXDB_HOST`,
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
| Anthropic API Key | Your `sk-ant-...` key from console.anthropic.com |
| Access Mode | Read/Write (recommended) |

Click **Test** to verify the API connection, then **Save**.

> **Tip:** Leave the API Key field blank and add `ANTHROPIC_API_KEY = "sk-ant-..."` to
> `/Library/Application Support/Perceptive Automation/IndigoSecrets.py` instead.
> The plugin checks for this file automatically on startup.
> A template (`IndigoSecrets_example.py`) is included in the repository.

#### 3. Device auto-creation

The plugin auto-creates a Claude Bridge device on first startup.
No manual "New Device" step is needed. If you need to create it manually:
**Devices → New Device → Plugin: Claude Bridge → Type: Claude Bridge**

#### 4. Install the Proxy Script

Save `indigo_mcp_proxy.py` (from this repo) to:
```
/Library/Application Support/Perceptive Automation/Scripts/indigo_mcp_proxy.py
```

Edit the `BEARER_TOKEN` constant at the top of the script — use the first value from:
```
/Library/Application Support/Perceptive Automation/Indigo 2025.1/Preferences/secrets.json
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

The `indigo-mcp` tools will appear on next session start. You should see 86 tools available.

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
the plugin bundle to that location and fill in your values. Or skip
`IndigoSecrets.py` entirely and enter values via the plugin's configuration
dialog — `IndigoSecrets.py` wins over the dialog when both are set.

If a required value is set in NEITHER source the plugin logs an ERROR
pointing the user to either fill in the matching field or add the key to
`IndigoSecrets.py`.

**Keys read by this plugin**: `ANTHROPIC_API_KEY` (required for Claude API
features), `CLAUDEBRIDGE_BEARER_TOKEN` (fallback for IWS auth — first
preference is Indigo's own `Preferences/secrets.json`), and the optional
`INFLUXDB_*` keys for historical-analysis MCP tools.

---

## Connecting Claude Code

Claude Code connects via a lightweight Python proxy script (`indigo_mcp_proxy.py`) that handles
authentication and protocol translation. The **Quick Install** script above sets this up automatically.

### Find Your Endpoint URL

**Plugins → Claude Bridge → Print MCP Client Connection Information**

The endpoint will be shown in the Indigo event log, e.g.:
```
Local:   http://localhost:8176/message/com.clives.indigoplugin.claudebridge/mcp/
Network: http://192.168.100.160:8176/message/com.clives.indigoplugin.claudebridge/mcp/
```

---

## Available Tools

**86 tools in 16 categories.** Counts verified against the plugin's tool
registration at `mcp_server/mcp_handler.py`.

### Device queries & search (6)
| Tool | Description |
|------|-------------|
| `list_devices` | List all Indigo devices with states |
| `get_device_by_id` | Full detail for a specific device |
| `get_device_by_name` | Look up a device by exact, partial, or case-insensitive name |
| `get_devices_by_type` | Filter devices by type (relay, dimmer, sensor, thermostat, etc.) |
| `get_devices_by_state` | Find devices matching a state condition |
| `search_entities` | Natural-language search across devices / variables / actions |

### Device control (10)
| Tool | Description |
|------|-------------|
| `device_turn_on` | Turn a device on |
| `device_turn_off` | Turn a device off |
| `device_control` | Find by name and turn on / off / toggle in one call |
| `device_set_brightness` | Set dimmer brightness (0–100) |
| `set_color` | Set RGB / colour-temp for colour-capable devices |
| `set_fan_speed` | Set fan speed on speed-control devices |
| `lock_device` | Lock a smart lock |
| `unlock_device` | Unlock a smart lock |
| `request_status_update` | Force a hardware status refresh |
| `home_status` | Whole-home snapshot (SOC, PV, grid, errors) |

### Heating / HVAC (6)
| Tool | Description |
|------|-------------|
| `heating_status` | Per-zone heating snapshot |
| `set_heat_setpoint` | Absolute heat setpoint |
| `set_cool_setpoint` | Absolute cool setpoint |
| `increase_heat_setpoint` | Bump up by a delta |
| `decrease_heat_setpoint` | Bump down by a delta |
| `set_hvac_mode` | Off / heat / cool / auto / fan |

### Energy (4)
| Tool | Description |
|------|-------------|
| `energy_status` | Solar / battery / grid live |
| `energy_log_days` | List SigenEnergyManager log days |
| `energy_daily_summary` | Day's energy summary |
| `energy_compare` | Compare energy across days |

### Variables (5)
| Tool | Description |
|------|-------------|
| `list_variables` | List all Indigo variables |
| `list_variable_folders` | List variable folders |
| `get_variable_by_id` | Get a variable value |
| `variable_update` | Update a variable value |
| `variable_create` | Create a new variable |

### Action groups (3)
| Tool | Description |
|------|-------------|
| `list_action_groups` | List all action groups |
| `get_action_group_by_id` | Action-group detail |
| `action_execute_group` | Execute an action group |

### Triggers & schedules (8)
| Tool | Description |
|------|-------------|
| `list_triggers` | List all Indigo triggers |
| `list_schedules` | List all Indigo schedules |
| `enable_trigger` | Enable a trigger |
| `disable_trigger` | Disable a trigger |
| `enable_schedule` | Enable a schedule |
| `disable_schedule` | Disable a schedule |
| `fire_indigo_event` | Fire a custom Claude-Bridge → Indigo event with payload |
| `fire_trigger` | Execute an Indigo trigger directly by ID/name (`indigo.trigger.execute`) |

### Plugins (4)
| Tool | Description |
|------|-------------|
| `list_plugins` | List all installed plugins |
| `get_plugin_by_id` | Plugin detail |
| `get_plugin_status` | Enabled / running state |
| `restart_plugin` | Restart a plugin |

### Scripts (8)
| Tool | Description |
|------|-------------|
| `list_python_scripts` | List all scripts (both Python Scripts / and Scripts / folders) |
| `read_script` | Read a script by filename |
| `write_script` | Overwrite an existing script (auto-backup) |
| `create_script` | Create a new script |
| `delete_script` | Archive a script (move to `_backups/_archived/`) |
| `run_script` | Execute a script in the Indigo Python context |
| `list_script_backups` | List `_backups/` entries |
| `scaffold_automation_script` | Generate a templated automation script |

### Events & subscriptions (6)
| Tool | Description |
|------|-------------|
| `query_event_log` | Query the Indigo event log with time filters |
| `subscribe` | Subscribe to device or variable change events |
| `unsubscribe` | Remove a subscription |
| `list_subscriptions` | List active subscriptions |
| `get_events` | Retrieve buffered events |
| `clear_events` | Clear the event buffer |

### Memory (4)
| Tool | Description |
|------|-------------|
| `remember` | Store a persistent memory entry |
| `recall` | Retrieve memory entries by topic |
| `recall_topics` | List all memory topics |
| `forget` | Delete a memory entry |

### Audit, health, diagnostics (12)
| Tool | Description |
|------|-------------|
| `audit_home` | Full home configuration audit |
| `audit_variables` | Audit variable usage and references |
| `security_status` | Security sensor snapshot |
| `system_health` | Whole-system health summary |
| `find_devices_in_error` | Devices reporting error states |
| `find_low_battery` | Devices with low battery |
| `find_stale_devices` | Devices not updated recently |
| `find_orphaned_plugin_data` | Plugin prefs / data dirs with no installed plugin |
| `find_orphaned_scripts` | Scripts referenced nowhere |
| `find_large_files` | Outsized files in plugin data / logs |
| `find_conflicts` | Duplicate names, shared addresses, orphaned refs |
| `dependency_map` | Map dependencies between entities |

### Notifications & logging (3)
| Tool | Description |
|------|-------------|
| `send_email` | Send via Indigo's first SMTP device |
| `send_notification` | Send via Pushover (with priority / sound) |
| `log_message` | Write a line to the Indigo event log |

### Reporting & analysis (2)
| Tool | Description |
|------|-------------|
| `home_status_report` | Configurable prose-markdown narrative of the whole home |
| `analyze_historical_data` | Run historical device / variable analysis (uses InfluxDB if configured) |

### Folders & server info (3)
| Tool | Description |
|------|-------------|
| `create_device_folder` | Idempotent device-folder creation |
| `create_variable_folder` | Idempotent variable-folder creation |
| `get_reflector_url` | Indigo Reflector remote-access URL, if configured |

### Scripting shell (2) — ADMIN scope
| Tool | Description |
|------|-------------|
| `execute_indigo_python` | Run arbitrary Python in this plugin's Indigo context via in-process `exec()`. `mode='exec'` returns captured stdout/stderr; `mode='eval'` returns the expression's repr in `value`. Treat as full code execution on the Indigo server. |
| `execute_plugin_menu_item` | Click a plugin's menu item under the Indigo client's Plugins menu via AppleScript GUI scripting. Only way to fire a third-party plugin's `<MenuItem>` callback from outside. Requires the Indigo GUI to be running and System Events permission. |

---

## Why a Proxy Script?

Indigo's web server uses HTTP Bearer token authentication. Claude Code's MCP client (and `mcp-remote`) attempts OAuth discovery by default, which Indigo does not support. The proxy script:

1. Acts as a stdio MCP server (what Claude Code expects)
2. Translates the MCP protocol version (`2025-11-25` → `2025-06-18`)
3. Adds the Bearer token to every request
4. Maintains a persistent HTTP keep-alive connection to Indigo
5. Correctly coerces argument types (strings → ints/arrays where needed)

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
│           └── tools/                      # 17 tool handler modules (86 tools)
└── README.md

indigo_mcp_proxy.py                         # Claude Code stdio proxy script
README.md
```

---

## Changelog

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

## Licence

MIT — free to use, modify, and distribute. Attribution appreciated.
