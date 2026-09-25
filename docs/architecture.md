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
└── Contents/
    ├── Info.plist                          # plugin metadata, version and bundle id
    └── Server Plugin/
        ├── plugin.py                       # Indigo lifecycle, web endpoints, change callbacks
        ├── plugin_utils.py                 # shared helpers (log timestamps, as_bool, banner)
        ├── indigo_mcp_proxy.py             # Claude Code go-between script
        ├── IndigoSecrets_example.py        # template for the credentials file
        ├── Actions.xml  Devices.xml  Events.xml  MenuItems.xml  PluginConfig.xml
        └── mcp_server/
            ├── mcp_handler.py              # MCP protocol and dispatch
            ├── registry.py                 # the @tool decorator; all tool metadata
            ├── toolsets/                   # every built-in tool (71 tools), by domain
            ├── tools/                      # handler classes the tools call
            ├── client_setup.py             # sets Claude Code up at plugin start
            ├── orphan_prefs.py             # drops settings of removed Configure fields
            ├── adapters/                   # Indigo data provider, .indiDb reader
            ├── common/                     # tool cache, search index, run jobs, helpers
            ├── security/                   # scopes, rate limit, delete gate, egress guard, redaction
            ├── external_tools/             # other plugins' mcp-manifest.json tools
            ├── webhooks/                   # outbound event webhooks
            └── handlers/                   # list and resource helpers
```

---

`mcp_server/` is the whole of the server. Each tool is one decorated function in `toolsets/`, and
`registry.py` holds what the decorator declares — the schema, the scope, what the tool caches and
what it invalidates, whether it is a gated delete, how its failures are scrubbed — so every other
part reads it from there rather than keeping its own copy. `mcp_handler.py` builds the tool list
from the registry and dispatches calls; `tools/` holds the handler classes that do the work;
`security/` is the scope manager,
the rate limiter, the delete gate, the webhook egress guard and the secret redactor; `external_tools/` reads other plugins' manifests;
`adapters/` reads Indigo's own database file for the trigger and action-group detail the API does
not expose; `handlers/`, `common/` and `webhooks/` are the plumbing.

## Keeping search current

`search_entities` answers from an index held in memory: every device, variable and action group,
with its name, description and model. Indigo tells the plugin when one of them is added, removed,
renamed, moved to another folder, enabled or disabled, and the plugin marks the index out of date.
The next search rebuilds it before answering. A plain state change, such as a lamp switching on,
does not count, and that is most of what Indigo reports. The tools that delete, rename or duplicate
things rebuild it as soon as they finish, and the whole index is rebuilt every five minutes in case
anything slipped past. The states and values a search result shows come from the index too, so
they can be up to five minutes old: ask for the device or variable itself for a live reading.

## Long runs

`execute_indigo_python` and `run_script` run as jobs. A run that finishes inside `wait_seconds`
(5 by default, at most 20) answers straight away. A longer one carries on in the background and the reply
carries a `job_id`. Calling the tool again with that id waits a little longer and returns the
result. Only one run can capture output at a time, so a second is refused and names the job in the
way, and a finished result is kept for ten minutes.

## Setting up Claude Code

When it starts, and unless **Auto-configure Claude Code** is unticked, the plugin copies the
go-between script into Indigo's `Scripts` folder, writes the Indigo access key into it, makes it
readable by its owner only, and adds an `indigo-mcp` entry to `~/.mcp.json` and
`~/.claude/settings.json`, leaving everything else in those files alone. It also deletes any stored
setting whose Configure field no longer exists, such as the Anthropic key and InfluxDB login that
versions before 3.0 kept, and logs only how many it removed.

## Tests

The whole test suite runs without an Indigo install — `tests/conftest.py` stubs the
`indigo` module and tests the bundle in the repo, so `python3 -m pytest -q` from the repo root
is all it takes — plus a lint pass and a check that the
generated [tool reference](tools.md) and every tool count in the docs match the code. CI runs
all of it on every push.
[CONTRIBUTING](https://github.com/Highsteads/ClaudeBridge/blob/main/CONTRIBUTING.md) has the
commands and the recipe for adding a tool, which is one decorated function.
