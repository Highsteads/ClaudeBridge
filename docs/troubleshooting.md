---
title: Troubleshooting
nav_order: 10
---

# Troubleshooting

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

**A leftover `Contents/Packages` folder from an older version**
→ Claude Bridge needs no extra Python packages any more: the bundle ships no
`requirements.txt`, so Indigo installs nothing for it. Versions before the
September 2026 spring clean pulled in `anthropic`, `pydantic`, `influxdb` and
`jinja2`, and an install upgraded in place may still carry them in
`Contents/Packages/`. Nothing imports them, so they do no harm, and the folder
can be deleted while the plugin is stopped.

---

**Asking Claude to restart Claude Bridge itself**
→ The plugin refuses, on purpose. A plugin cannot restart itself while it is still answering the
request that asked it to — the reply would never get back. Restart it from Indigo instead:
**Plugins → Claude Bridge → Reload**. Every other plugin can be restarted through Claude.

**Where to look**
→ **Plugins → Claude Bridge → Show Plugin Info** logs the environment, and **Print Plugin Health**
the uptime, sessions and per-tool latencies. Both are what to paste into an
[issue](https://github.com/Highsteads/ClaudeBridge/issues).
