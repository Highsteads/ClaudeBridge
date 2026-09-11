---
title: Letting your plugin add tools
nav_order: 8
---

# Letting your plugin add tools

A plugin becomes a provider with three things, and stays perfectly usable for people who have no MCP server at all: the manifest is inert data, the hidden action is only ever called by a server, and the broadcast is a no-op when nobody is listening.

**1. The manifest**, at `Contents/Resources/mcp-manifest.json`:

```json
{
  "manifest_version": 1,
  "provider": {"plugin_id": "com.example.myplugin", "display_name": "My Plugin"},
  "tools": [
    {
      "name": "get_status",
      "description": "Say what the plugin is doing. Read-only.",
      "write": false,
      "timeout_seconds": 15,
      "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    {
      "name": "set_mode",
      "description": "Change the operating mode. Saves the plugin's preferences.",
      "write": true,
      "inputSchema": {
        "type": "object",
        "properties": {"mode": {"type": "string", "enum": ["auto", "manual"]}},
        "required": ["mode"]
      }
    }
  ]
}
```

`provider.plugin_id` must equal your bundle's `CFBundleIdentifier`, or the whole file is refused. Tool names are `^[a-z][a-z0-9_]{0,40}$` and unique; the AI sees them as `{prefix}_{name}`, where the prefix is the last dot-segment of your plugin id (an optional `tool_prefix` overrides it, `^[a-z][a-z0-9_]{0,31}$`). Prefixes are first come, first served across plugins. `write` defaults to `true`, so an undeclared tool is treated as a write and refused when the switch is off. `timeout_seconds` is clamped to 5–120, default 30. The description is what the AI decides from, so say whether the tool is read-only and what a write changes.

**2. The hidden action** in `Actions.xml`, which Claude Bridge calls with `executeAction`:

```xml
<Action id="mcp_tool_invoke" uiPath="hidden">
    <Name>MCP Tool Invocation Endpoint</Name>
    <CallbackMethod>handle_mcp_tool_invoke</CallbackMethod>
</Action>
```

Its callback receives `action.props["tool"]` (the bare name) and `action.props["arguments"]` (a JSON string, never an `indigo.Dict`), and must return a JSON string: `{"status": "ok", "result": ...}` on success, or `{"status": "error", "error": {"type": "validation"|"not_found"|"conflict"|"internal", "message": "...", "details": ...}}` on failure. Return errors in the envelope rather than raising; validate every argument yourself, because the call does not pass through your ConfigUI. Import the code that does the work inside the callback, so a fault in it can never stop your plugin starting. Note that every hidden action is also reachable over the Indigo web server with an API key; answer a request that arrives that way (it carries `request_body` and no `tool`) with an HTTP reply dict, not a tool.

```python
def handle_mcp_tool_invoke(self, action, dev=None, callerWaitingForResult=True):
    import json
    try:
        from my_tools import dispatch            # lazy, on purpose
        tool = action.props.get("tool", "")
        arguments = json.loads(action.props.get("arguments", "{}"))
        return dispatch(self, tool, arguments)   # returns the JSON-string envelope
    except Exception as e:
        return json.dumps({"status": "error", "error": {"type": "internal", "message": str(e)}})
```

**3. The broadcast**, one guarded line at the end of `startup()`, so your tools register the moment your plugin starts rather than at the server's next scan:

```python
try:
    indigo.server.broadcastToSubscribers("mcp_tools_updated")
except Exception:
    pass
```

Keep the handler quick: it runs on your plugin's single callback thread, so a slow tool freezes your own plugin, and a call that overruns its timeout is abandoned and reported to the AI as a timeout. Never call back into Claude Bridge from a tool handler with `waitUntilDone=True`; the two plugins would wait on each other for ever. A client that was already connected sees a new provider's tools only when it starts a fresh session, because MCP clients cache the tool list at connect. The [Dashboards plugin](https://github.com/Highsteads/Dashboards) is a complete worked example, eight tools with tests.

The Dashboards plugin's own notes on building a provider — what the manifest contract looks like
from the plugin's side, and the traps met on the way — are on
[its documentation site](https://highsteads.github.io/Dashboards/claude-code.html).
