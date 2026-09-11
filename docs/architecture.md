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
endpoint for remote use. Long-running tools report progress as buffered server-sent events over
the same reply.

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
│           └── tools/                      # 21 tool handler modules (168 tools)
│       ├── indigo_mcp_proxy.py             # Claude Code go-between script
│       └── install.py                      # one-shot installer
└── README.md
```

---

`mcp_server/` is the whole of the server: `mcp_handler.py` registers every tool and dispatches
calls; `tools/` holds twenty-one handler packages, one per area; `security/` is the scope manager,
the delete gate and the webhook egress guard; `external_tools/` reads other plugins' manifests;
`adapters/` reads Indigo's own database file for the trigger and action-group detail the API does
not expose; `handlers/`, `common/` and `webhooks/` are the plumbing.

## Tests

Six hundred and eighty tests run without an Indigo install — `tests/conftest.py` stubs the
`indigo` module and resolves the bundle automatically — plus a lint pass and a check that the
generated [tool reference](tools.md) matches the code. CI runs all of it on every push.
[CONTRIBUTING](https://github.com/Highsteads/ClaudeBridge/blob/main/CONTRIBUTING.md) has the
commands and the recipe for adding a tool without tripping over the four places tool metadata
lives.
