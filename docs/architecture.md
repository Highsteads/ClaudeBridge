---
title: How it is built
nav_order: 9
---

# How it is built

## The transport

Claude Code speaks MCP over stdio to the go-between script, `indigo_mcp_proxy.py`. The script
turns each request into an HTTPS call to Indigo's own web server, at
`/message/com.clives.indigoplugin.claudebridge/mcp/`, with your Indigo access key as a Bearer
token; the plugin answers there. So there is no port of its own, no second door: Indigo's web
server authenticates every request before the plugin sees it, and the Reflector carries the same
endpoint for remote use. Every reply is a single JSON body.

Claude Code and Indigo's web server expect slightly different things of each other, so a small script sits between them and translates. It answers Claude Code in the form it expects, attaches your Indigo access key to every request so you never have to think about it, holds the connection open and rebuilds it quietly if Indigo restarts, and irons out the formatting differences between the two sides. It is installed and configured for you, and the only time you would ever open it is if something in Troubleshooting below sends you there.

---

Three things the script does that you would otherwise meet as errors: it reconnects quietly
after an idle gap or an Indigo restart rather than surfacing a broken pipe; it re-does the
session handshake when the web server has forgotten the session; and at boot it waits for the web
server to start listening, because after a reboot Claude Code can be up seconds before Indigo is.

## Project structure

```
Claude Bridge.indigoPlugin/
├── Contents/
│   ├── Info.plist                          # Plugin metadata & bundle ID
│   └── Server Plugin/
│       ├── plugin.py                       # Indigo plugin lifecycle
│       ├── Actions.xml
│       ├── Devices.xml
│       ├── MenuItems.xml
│       ├── PluginConfig.xml
│       └── mcp_server/
│           ├── mcp_handler.py              # MCP protocol and dispatch
│           ├── registry.py                 # the @tool decorator; all tool metadata
│           ├── toolsets/                   # every built-in tool (69 tools), by domain
│           ├── adapters/                   # Indigo data provider
│           ├── common/
│           │   └── entity_index/           # In-memory fuzzy search index
│           ├── handlers/                   # List/resource handlers
│           ├── security/                   # Auth manager
│           └── tools/                      # handler classes the tools call
│       ├── indigo_mcp_proxy.py             # Claude Code go-between script
│       └── install.py                      # one-shot installer
└── README.md
```

---

`mcp_server/` is the whole of the server. Each tool is one decorated function in `toolsets/`, and
`registry.py` holds what the decorator declares — the schema, the scope, what the tool caches and
what it invalidates, whether it is a gated delete, how its failures are scrubbed — so every other
part reads it from there rather than keeping its own copy. `mcp_handler.py` builds the tool list
from the registry and dispatches calls; `tools/` holds the handler classes that do the work;
`security/` is the scope manager,
the delete gate and the webhook egress guard; `external_tools/` reads other plugins' manifests;
`adapters/` reads Indigo's own database file for the trigger and action-group detail the API does
not expose; `handlers/`, `common/` and `webhooks/` are the plumbing.

## Tests

The whole test suite runs without an Indigo install — `tests/conftest.py` stubs the
`indigo` module and resolves the bundle automatically — plus a lint pass and a check that the
generated [tool reference](tools.md) and every tool count in the docs match the code. CI runs
all of it on every push.
[CONTRIBUTING](https://github.com/Highsteads/ClaudeBridge/blob/main/CONTRIBUTING.md) has the
commands and the recipe for adding a tool, which is one decorated function.
