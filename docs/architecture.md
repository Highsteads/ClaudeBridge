---
title: How it is built
nav_order: 15
parent: Technical notes
---

# How it is built

## The transport

Claude Code speaks MCP over stdio to the go-between script, `indigo_mcp_proxy.py`. The script
turns each request into a web request to Indigo's own web server, at
`/message/com.clives.indigoplugin.claudebridge/mcp/`, with your Indigo access key as a Bearer
token, and the plugin answers there. The script uses the address Indigo reports for its web
server, so HTTPS and a port other than 8176 work too. So there is no port of its own, no second door: Indigo's web
server authenticates every request before the plugin sees it, and the Reflector carries the same
endpoint for remote use. Every reply is a single JSON body.

Claude Code and Indigo's web server expect slightly different things of each other, so a small script sits between them and translates. It answers Claude Code in the form it expects, attaches your Indigo access key to every request so you never have to think about it, holds the connection open and rebuilds it quietly if Indigo restarts, and irons out the formatting differences between the two sides. It is installed and configured for you, and you only open it if you [set Claude Code up by hand](getting-started.md#setting-claude-code-up-by-hand).

---

Three things the script does that you would otherwise meet as errors: it reconnects quietly
after an idle gap or an Indigo restart rather than surfacing a broken pipe, it re-does the
session handshake when the web server has forgotten the session, and at boot it waits up to 45
seconds for the web server to start listening, because after a reboot Claude Code can be up seconds before Indigo is.

## Two versions of the protocol

From 3.7.0 Claude Bridge speaks both the 2025-06-18 version of MCP and the 2026-07-28 one, on the
same endpoint, and a client gets whichever it asks for.

- **2025-06-18** starts with an `initialize` handshake and gives the client a session, carried in
  the `Mcp-Session-Id` header. Everything before 3.7.0 worked this way, and it still does.
- **2026-07-28** has no handshake and no session. Every request names its protocol version and
  the client's capabilities in `params._meta`, and carries the same version in an
  `MCP-Protocol-Version` header, the method in `Mcp-Method`, and for `tools/call`,
  `resources/read` and `prompts/get` the tool, resource or prompt in `Mcp-Name`. A client can
  first ask `server/discover`, which answers with both versions, the same capabilities
  `initialize` offers, and the server's name and version.

A request is 2026-07-28 when its `_meta` names a protocol version, and 2025-06-18 otherwise. The
2026-07-28 rules Claude Bridge follows:

| Case | Reply |
|---|---|
| A version it does not speak in `_meta` | HTTP 400, error -32022, with the versions it does speak |
| No `clientCapabilities` in `_meta` | HTTP 400, error -32602 |
| A header missing, or not matching the body | HTTP 400, error -32020 |
| A method 2026-07-28 does not have here, `ping` and `initialize` among them | HTTP 404, error -32601 |
| A tool call refused for the rate limit, the access key's scope or the delete gate | a tool result marked as an error, so Claude reads why |
| A resource that does not exist | error -32602 (2025-06-18 clients still get -32002) |

Every 2026-07-28 result carries `resultType: "complete"` and the server's name and version in
`_meta`. Lists and `server/discover` say how long a client may keep them (`ttlMs`: five minutes
for the lists, none for a resource read, which is live house data) and that no shared cache may
serve them to anybody else (`cacheScope: "private"`).

The go-between script follows the same split. It adds the three headers to a 2026-07-28 request,
sends no session, and passes Claude Bridge's error codes to Claude Code unchanged, because
-32022 carries the versions to retry with.

Whether Claude Code uses 2026-07-28 is Claude Code's choice, and it turns it on one kind of
connection at a time. On 29 September 2026 it used it for a server reached over HTTP but not yet
for one reached through a script like the go-between. So from 3.8.0 Claude Code can be pointed
straight at the web server (the **Connect Claude Code** setting). It then sends each request
itself, and runs the go-between script only as a `headersHelper`, `indigo_mcp_proxy.py --headers`,
which prints the Authorization header and exits. The access key stays in that one owner-only
file rather than in `~/.claude.json` or `~/.mcp.json`, which any account on the Mac can read.

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
            ├── protocol_era.py             # the rules of MCP 2026-07-28 beside 2025-06-18
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
from the registry and dispatches calls. `tools/` holds the handler classes that do the work.
`security/` is the scope manager, the rate limiter, the delete gate, the webhook egress guard,
the secret redactor and the change log. `external_tools/` reads other plugins' manifests.
`adapters/` reads Indigo's own database file for the trigger and action-group detail the API does
not expose. `handlers/`, `common/` and `webhooks/` are the plumbing.

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
