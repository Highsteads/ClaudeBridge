---
title: Getting started
nav_order: 2
---

# Getting started

Ten minutes, and most of it is waiting for a download. If words like "MCP server" are new to you,
here is the whole of it: Claude on its own can only talk. An MCP server is a small program that
gives it hands — in this case, a plugin inside Indigo that answers Claude's questions about your
devices and carries out its requests. Once it is in, you open Claude Code and just ask.

## What you need

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
needs an InfluxDB database set up — a niche feature. **All 168 tools work
without this key.** If you do set one up, it bills per use (pennies a month,
as a rule), separately from your subscription.

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

2. **Restart Claude Code** — you should see 168 `indigo-mcp` tools available

> **Credentials policy:** All sensitive values are read from
> `/Library/Application Support/Perceptive Automation/IndigoSecrets.py` first, and
> the plugin's PluginConfig dialog is a fallback only. Keys this plugin reads:
> `ANTHROPIC_API_KEY` (optional — see "What this costs" above),
> `CLAUDEBRIDGE_BEARER_TOKEN`, and (optional) `INFLUXDB_HOST`,
> `INFLUXDB_PORT`, `INFLUXDB_USERNAME`, `INFLUXDB_PASSWORD`, `INFLUXDB_DATABASE`.
> If a value is missing from BOTH sources, the plugin logs an ERROR pointing
> here and skips that feature. See `IndigoSecrets_example.py` for the template.

---

### Manual Install

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

The `indigo-mcp` tools will appear on next session start. You should see 168 tools available.


---

## Connecting the Claude desktop app instead

The go-between script speaks the standard MCP protocol over stdio, so any client that can run a
local MCP server can use it. The Claude desktop app's local-connector configuration takes the same
command and arguments the installer writes into `~/.mcp.json`. Claude Code is what the plugin is
developed and tested with; the desktop app has not been through the same testing here, so treat it
as "should work" rather than "known to work", and say so in an issue if it does not.

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

## The first five minutes

Ask it things you already know the answer to, so you learn what it can see:

- *"Which lights are on?"*
- *"What is the temperature in the hall, and when did it last change?"*
- *"List every device that has not reported in a day."*
- *"Turn the landing light on for ten minutes."* — then watch it go off on its own.
- *"What happened in the event log in the last hour?"*

Then ask for something you have been putting off — a script, a report, a question about why a
trigger did not fire. [Working with Claude](working-with-claude.md) has worked examples of each.
