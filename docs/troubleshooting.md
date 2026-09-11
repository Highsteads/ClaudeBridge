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

**Plugin fails to start after a pip-install loop (`anthropic`/`influxdb`/etc. `__init__.py` missing)**
→ Indigo's per-restart pip step occasionally leaves `Contents/Packages/` in a
half-installed state: the package directory exists but the top-level
`__init__.py` (and most other `.py` files) are gone, so every import fails with
"cannot import name X from Y (unknown location)". `--force-reinstall` against
the same target doesn't fix it — pip skips because the directory is "already
present". The reliable recovery is to wipe and let Indigo re-install on the
next start:
```bash
# Finds your installed bundle whatever Indigo version you are on
DST=$(ls -d "/Library/Application Support/Perceptive Automation/Indigo "*/Plugins/"Claude Bridge.indigoPlugin" | tail -1)
rm -rf "$DST/Contents/Packages"
mkdir -p "$DST/Contents/Packages"
# Then reload Claude Bridge via the Plugins menu (or the Indigo GUI), which
# triggers a clean pip install from requirements.txt.
```
Confirmed 2026-05-23 — every package directory in Packages/ was missing its
`__init__.py` after a routine restart, and clearing the whole tree restored a
fully-working install. This can happen to any plugin that ships a
`requirements.txt`, so treat it as the standard recovery if a restart suddenly
starts logging `module 'X' has no attribute 'Y'` for imports that worked
yesterday.

---

**Asking Claude to restart Claude Bridge itself**
→ The plugin refuses, on purpose. A plugin cannot restart itself while it is still answering the
request that asked it to — the reply would never get back. Restart it from Indigo instead:
**Plugins → Claude Bridge → Reload**. Every other plugin can be restarted through Claude.

**Where to look**
→ **Plugins → Claude Bridge → Show Plugin Info** logs the environment, and **Print Plugin Health**
the uptime, sessions and per-tool latencies. Both are what to paste into an
[issue](https://github.com/Highsteads/ClaudeBridge/issues).
