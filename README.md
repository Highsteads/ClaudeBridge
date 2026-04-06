# Claude Bridge — Indigo Plugin

**Claude Bridge** is an [Indigo](https://www.indigodomo.com) home automation plugin that connects your Indigo system directly to [Claude AI](https://www.anthropic.com/claude) via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io).

Once installed, Claude can query device states, turn devices on and off, read and write variables, execute action groups, search your home's entity database, and query the Indigo event log — all in natural language, with no manual scripting required.

**Author:** CliveS & Claude Sonnet 4.6
**Platform:** Indigo 2025.1, macOS, Python 3.11
**Bundle ID:** `com.clives.indigoplugin.claudebridge`
**Version:** 2.0.0

---

## Features

- **64 MCP tools** — full read/write access to devices, variables, action groups, plugins, event log, scripts, memory, events, and home intelligence
- **`device_control` — single-call search + action** — find and control a device by name in one round trip (~1s)
- **Natural language entity search** — find devices by description ("conservatory lamp", "bedroom sensor")
- **Fast slim search** — returns lightweight results by default; use `detail="full"` only when deep config is needed
- **Claude-powered** — uses Anthropic's Claude API directly; no OpenAI or third-party embedding services
- **Local text search** — fast substring/fuzzy matching; no vector database required
- **Session management** — persistent MCP sessions with per-session access control
- **Secure** — Bearer token authentication on all requests; configurable access modes

---

## Requirements

- Indigo 2025.1 or later
- macOS (runs on the Indigo server machine)
- Python 3.11 (bundled with Indigo)
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

2. **Restart Claude Code** — you should see 64 `indigo-mcp` tools available

> **Anthropic API key:** If you have a `secrets.py` at
> `/Library/Application Support/Perceptive Automation/secrets.py`
> with `ANTHROPIC_API_KEY = "sk-ant-..."`, the plugin picks it up automatically.
> Otherwise go to **Plugins → Claude Bridge → Configure** and enter it there.

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
> `/Library/Application Support/Perceptive Automation/secrets.py` instead.
> The plugin checks for this file automatically on startup.
> A template (`secrets_example.py`) is included in the repository.

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

The `indigo-mcp` tools will appear on next session start. You should see 64 tools available.

</details>

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

### Devices (7)
| Tool | Description |
|------|-------------|
| `list_devices` | List all Indigo devices with states |
| `get_device_by_id` | Get full detail for a specific device |
| `get_devices_by_type` | Filter devices by type (relay, dimmer, sensor, etc.) |
| `get_devices_by_state` | Find devices matching a state condition |
| `device_turn_on` | Turn a device on |
| `device_turn_off` | Turn a device off |
| `device_set_brightness` | Set dimmer brightness (0–100) |

### Variables (5)
| Tool | Description |
|------|-------------|
| `list_variables` | List all Indigo variables |
| `list_variable_folders` | List variable folders |
| `get_variable_by_id` | Get a specific variable value |
| `variable_update` | Update a variable value |
| `variable_create` | Create a new variable |

### Action Groups (3)
| Tool | Description |
|------|-------------|
| `list_action_groups` | List all action groups |
| `get_action_group_by_id` | Get action group details |
| `action_execute_group` | Execute an action group |

### Plugins (4)
| Tool | Description |
|------|-------------|
| `list_plugins` | List all installed plugins |
| `get_plugin_by_id` | Get plugin details |
| `get_plugin_status` | Check if a plugin is enabled/running |
| `restart_plugin` | Restart an Indigo plugin |

### Search & Control (3)
| Tool | Description |
|------|-------------|
| `device_control` | Find device by name and turn on/off/toggle in one call |
| `search_entities` | Natural language search across all entities |
| `query_event_log` | Query the Indigo event log |
| `analyze_historical_data` | Analyse historical device/variable data |

### Scripts (5)
| Tool | Description |
|------|-------------|
| `list_script_backups` | List available script backups |
| `read_script` | Read an Indigo Python script |
| `write_script` | Write/update a script (auto-backup on write) |
| `create_script` | Create a new script |
| `delete_script` | Delete a script |

### Memory (4)
| Tool | Description |
|------|-------------|
| `remember` | Store a persistent memory entry |
| `recall` | Retrieve memory entries by topic |
| `recall_topics` | List all memory topics |
| `forget` | Delete a memory entry |

### Event Subscriptions (5)
| Tool | Description |
|------|-------------|
| `subscribe` | Subscribe to device or variable change events |
| `unsubscribe` | Remove a subscription |
| `get_events` | Retrieve buffered events |
| `list_subscriptions` | List active subscriptions |
| `clear_events` | Clear the event buffer |

### Audit (7)
| Tool | Description |
|------|-------------|
| `audit_home` | Full home configuration audit |
| `find_devices_in_error` | Find devices reporting error states |
| `find_low_battery` | Find devices with low battery |
| `find_stale_devices` | Find devices not updated recently |
| `audit_variables` | Audit variable usage |
| `dependency_map` | Map dependencies between entities |
| `find_conflicts` | Find duplicate names, shared addresses, orphaned refs |

### Home Intelligence (7)
| Tool | Description |
|------|-------------|
| `home_status` | Current home status summary |
| `energy_status` | Solar, battery, and grid energy status |
| `heating_status` | Heating zone status |
| `security_status` | Security sensor status |
| `home_status_report` | Configurable prose markdown narrative |
| `energy_log_days` | Read SigenEnergyManager daily log files |
| `energy_daily_summary` | Summarise energy for a day |
| `energy_compare` | Compare energy across days |

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
│           └── tools/                      # 22 MCP tool handlers
└── README.md

indigo_mcp_proxy.py                         # Claude Code stdio proxy script
README.md
```

---

## Changelog

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
- API key field can now be left blank if `secrets.py` provides `ANTHROPIC_API_KEY`
- Fixed config save erroring when API key field is blank but secrets.py has the key
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
