---
title: Configuration
nav_order: 6
---

# Configuration

Most people never open the Configure dialog: the installer sets up the connection, every tool works
without an API key, and the defaults are the safe ones. This page is what each setting does when
you do.

## The Configure dialog

**Plugins → Claude Bridge → Configure.**

| Setting | What it does |
|---|---|
| Anthropic API Key | Optional. Only the AI summaries in the historical-analysis tool use it; Claude Code uses your own Claude account for everything else. Leave it blank unless you use that tool |
| Large model / Small model | Which Claude models the historical-analysis summaries call, when a key is set |
| Enable InfluxDB Historical Data, host, port, username, password, database | The optional InfluxDB backend for `analyze_historical_data`. `IndigoSecrets.py`'s `INFLUXDB_*` keys take priority over these fields |
| Rate limit (per minute / per day) | How many tool calls a token may make. Defaults 120 a minute, 5,000 a day |
| Read-cache TTL (seconds) | How long a read answer is served from cache. Mutating tools invalidate the related cache buckets themselves, and a client can send `Cache-Control: no-cache` |
| Allow plugin-provided tools to make changes | The one switch over other plugins' write tools (see [Letting your plugin add tools](providers.md)). On by default; read tools always work |
| Enable Event Webhooks, egress allow-list, plain-HTTP allow-list | The "home calls out" feature, off by default, and the only destinations it may ever post to. See [Security](security.md) |
| Event Logging Level | How much the plugin says in the Indigo event log |
| Allow Claude to delete devices, variables and automations | Off by default. While off, every delete is refused whatever token is in use |
| Auto-configure Claude Code | On by default: at startup the plugin copies the go-between script into Indigo's `Scripts` folder, patches the access key into it, and keeps `~/.mcp.json` current |
| Test Connections | Tries the Anthropic API and InfluxDB with the current settings and logs the result |

## Per-token scopes — `scopes.json`

Indigo's web server already checks the access key before a request reaches the plugin. Scopes are
a second layer on top: which tools each key may use. They live in `scopes.json` under the plugin's
Preferences folder, and **Plugins → Claude Bridge → Create Starter scopes.json** writes one for you.

```json
{
    "default_scopes": ["read"],
    "tokens": {
        "<bearer-token>": {"name": "claude-code", "scopes": ["read", "write", "admin"]},
        "<other-token>": {"name": "phone-app",   "scopes": ["read"]}
    }
}
```

Without a `scopes.json`, every authenticated key gets every scope. Once the file exists it fails
closed: a key it does not name gets `default_scopes` only. Edit it and use **Reload scopes.json**;
no restart needed. Which tools sit in which scope is the [Tool reference](tools.md).

## Credentials — `IndigoSecrets.py` and `IndigoSecrets_example.py`

This plugin, like every CliveS Indigo plugin, reads sensitive values from one
shared master file:

`/Library/Application Support/Perceptive Automation/IndigoSecrets.py`

| File | Purpose | Real data? | Committed to GitHub? |
|------|---------|------------|----------------------|
| `IndigoSecrets.py` | Working file the plugin reads at runtime. Keep a backup in a password manager. | YES | **NO** — listed in `.gitignore` |
| `IndigoSecrets_example.py` | Template only — empty placeholders. Shipped in the plugin bundle. | NO | YES |

If you don't have `IndigoSecrets.py`, copy `IndigoSecrets_example.py` out of
the plugin bundle into `/Library/Application Support/Perceptive Automation/`,
rename it to `IndigoSecrets.py`, and fill in your values. Or skip the file
altogether and type the values into the plugin's configuration dialog — where
both are set, `IndigoSecrets.py` wins.

If neither source supplies a value the plugin needs, it logs an ERROR naming
the key and telling you to either fill in the matching field or add the key to
`IndigoSecrets.py`.

**Keys read by this plugin**: `ANTHROPIC_API_KEY` (optional — used only for
the AI summaries in the historical-analysis tool, every other tool works
without it), `CLAUDEBRIDGE_BEARER_TOKEN` (fallback for the web-server access
key — first preference is Indigo's own `Preferences/secrets.json`), and the
optional `INFLUXDB_*` keys for the historical-analysis tools.

---

## The menu items

| Item | What it does |
|---|---|
| Print MCP Client Connection Information | The endpoint URLs, local and on the network |
| Print Plugin Health | Uptime, sessions and per-tool latencies |
| Print Tool Explorer URL | A page listing every tool with its schema |
| Create Starter scopes.json / Reload scopes.json | Per-token scopes, above |
| Clear Read-Cache | Forget every cached read answer |
| Print / Clear All Event Webhook Subscriptions | What the home has been told to call out about |
| Print / Rescan Plugin-Provided MCP Tools | The providers found, and a rescan on demand |
| Toggle Timestamps in Log | The millisecond prefix on the plugin's log lines |
| Show Plugin Info | The environment banner — versions, architecture, Python — for a support post |
