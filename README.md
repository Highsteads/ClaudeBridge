# Claude Bridge — Indigo Plugin

**Claude Bridge** is an [Indigo](https://www.indigodomo.com) home automation plugin that connects your Indigo system directly to [Claude AI](https://www.anthropic.com/claude) via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io).

Once installed, Claude can query device states, turn devices on and off, read and write variables, execute action groups, search your home's entity database, and query the Indigo event log — all in natural language, with no manual scripting required.

**Author:** CliveS & Claude Sonnet 4.6
**Platform:** Indigo 2025.1, macOS, Python 3.11
**Bundle ID:** `com.clives.indigoplugin.claudebridge`
**Version:** 2025.0.2

---

## Features

- **22 MCP tools** — full read/write access to devices, variables, action groups, plugins, and event log
- **Natural language entity search** — find devices by description ("conservatory lamp", "bedroom sensor")
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

### 1. Install the Plugin

1. Go to the [Releases page](https://github.com/Highsteads/ClaudeBridge/releases) and download `Claude.Bridge.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Claude Bridge.indigoPlugin`
3. Double-click `Claude Bridge.indigoPlugin` — Indigo will install it automatically

   *Alternatively*, drag it manually into:
   ```
   /Library/Application Support/Perceptive Automation/Indigo 2025.1/Plugins/
   ```

4. In the Indigo client: **Plugins → Manage Plugins → Enable** Claude Bridge

### 2. Configure the Plugin

**Plugins → Claude Bridge → Configure:**

| Field | Value |
|-------|-------|
| Anthropic API Key | Your `sk-ant-...` key from console.anthropic.com |
| Access Mode | Read/Write (recommended) |

Click **Test** to verify the API connection, then **Save**.

### 3. Create a Device

In Indigo: **Devices → New Device → Plugin: Claude Bridge → Type: Claude Bridge**

Give it any name (e.g. "Claude Bridge"). This activates the MCP endpoint.

### 4. Find Your Endpoint URL

**Plugins → Claude Bridge → Print MCP Client Connection Information**

The endpoint will be shown in the Indigo event log, e.g.:
```
Local:   http://localhost:8176/message/com.clives.indigoplugin.claudebridge/mcp/
Network: http://192.168.100.160:8176/message/com.clives.indigoplugin.claudebridge/mcp/
```

---

## Connecting Claude Code

Claude Code connects via a lightweight Python proxy script that handles authentication and protocol translation.

### 1. Install the Proxy Script

Save `indigo_mcp_proxy.py` (from this repo) to:
```
/Library/Application Support/Perceptive Automation/Python Scripts/indigo_mcp_proxy.py
```

Edit the constants at the top of the script:
```python
INDIGO_MCP_PATH = "/message/com.clives.indigoplugin.claudebridge/mcp/"
BEARER_TOKEN    = "your-indigo-api-key"
```

Your Indigo API key is in:
```
/Library/Application Support/Perceptive Automation/Indigo 2025.1/Preferences/secrets.json
```
(use the first value in the array)

### 2. Register with Claude Code

Add to `~/.mcp.json`:
```json
{
  "mcpServers": {
    "indigo-mcp": {
      "command": "python3",
      "args": ["/Library/Application Support/Perceptive Automation/Python Scripts/indigo_mcp_proxy.py"]
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

Add to `~/.claude.json` under your project's `mcpServers`:
```json
"indigo-mcp": {
  "command": "python3",
  "args": ["/Library/Application Support/Perceptive Automation/Python Scripts/indigo_mcp_proxy.py"]
}
```

### 3. Restart Claude Code

The `indigo-mcp` tools will appear on next session start. You should see 22 tools available.

---

## Available Tools

| Tool | Description |
|------|-------------|
| `list_devices` | List all Indigo devices with states |
| `get_device_by_id` | Get full detail for a specific device |
| `get_devices_by_type` | Filter devices by type (relay, dimmer, sensor, etc.) |
| `get_devices_by_state` | Find devices matching a state condition |
| `device_turn_on` | Turn a device on |
| `device_turn_off` | Turn a device off |
| `device_set_brightness` | Set dimmer brightness (0–100) |
| `list_variables` | List all Indigo variables |
| `list_variable_folders` | List variable folders |
| `get_variable_by_id` | Get a specific variable value |
| `variable_update` | Update a variable value |
| `variable_create` | Create a new variable |
| `list_action_groups` | List all action groups |
| `get_action_group_by_id` | Get action group details |
| `action_execute_group` | Execute an action group |
| `list_plugins` | List all installed plugins |
| `get_plugin_by_id` | Get plugin details |
| `get_plugin_status` | Check if a plugin is enabled/running |
| `restart_plugin` | Restart an Indigo plugin |
| `search_entities` | Natural language search across all entities |
| `query_event_log` | Query the Indigo event log |
| `analyze_historical_data` | Analyse historical device/variable data |

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
│           │   ├── openai_client/          # Claude API client (Anthropic)
│           │   └── vector_store/           # Text search store
│           ├── handlers/                   # List/resource handlers
│           ├── security/                   # Auth manager
│           └── tools/                      # 22 MCP tool handlers
└── README.md

indigo_mcp_proxy.py                         # Claude Code proxy script
```

---

## Changelog

### 2025.0.2 (2026-03-24)
- Renamed from "MCP Server" to "Claude Bridge"
- Replaced OpenAI/Voyage AI with Anthropic Claude API throughout
- Fixed text search: LLM query expansion disabled (broke substring matching)
- Proxy: persistent HTTP keep-alive connection
- Proxy: automatic type coercion (string → int/float/array)
- Proxy: MCP protocol version translation (2025-11-25 → 2025-06-18)
- Removed all third-party AI service dependencies

### 2025.0.1
- Initial release with OpenAI + Voyage AI embeddings

---

## Licence

MIT — free to use, modify, and distribute. Attribution appreciated.
