# Contributing to Claude Bridge

Thanks for having a look. This page tells you how to run the tests, what the
layout is, and — the most common change — how to add a new MCP tool, which is
now one decorated function.

## Running the tests

No Indigo install is needed — `tests/conftest.py` stubs the `indigo` module
and resolves the plugin bundle automatically (a live installed copy if one
exists, otherwise the bundle inside this repo).

```bash
pip install pytest
python -m pytest tests -q
```

The plugin needs nothing beyond the standard library and Indigo itself, so
pytest is the only thing to install. `tests/test_no_third_party_deps.py` fails
the suite if a module in the bundle ever imports anything else.

To force the suite to run against this repo's bundle even on a machine with a
live Indigo install:

```bash
CB_SP="$PWD/Claude Bridge.indigoPlugin/Contents/Server Plugin" python -m pytest tests -q
```

Lint (errors only — undefined names, unused imports; no style policing) and
the tool-reference and tool-count staleness check:

```bash
pip install ruff
ruff check .
python3 scripts/generate_tool_doc.py --check
```

All three run in CI on every push and pull request
(`.github/workflows/test.yml`) and must be green.

## Repo layout

```
Claude Bridge.indigoPlugin/Contents/Server Plugin/
├── plugin.py               # Indigo plugin lifecycle + IWS endpoints + secrets loading
├── indigo_mcp_proxy.py     # stdio→HTTP bridge that Claude Code launches
└── mcp_server/
    ├── mcp_handler.py      # MCP protocol dispatch (rate limit, scopes, gate, cache)
    ├── registry.py         # the @tool decorator and everything derived from it
    ├── toolsets/           # every built-in tool, one module per domain
    ├── tools/<category>/   # the handler classes the tools call
    ├── security/           # scope manager, rate limiter, egress firewall
    ├── webhooks/           # outbound event webhook engine
    └── common/             # tool cache, entity (search) index, helpers
tests/                      # pytest suite — runs standalone, <10 s
scripts/generate_tool_doc.py # writes docs/tools.md and every tool count from the registry
```

The canonical copies of `indigo_mcp_proxy.py` and `IndigoSecrets_example.py`
live inside the bundle (`Contents/Server Plugin/`) — edit those. Unpublished
root-level working copies may exist on a maintainer's machine;
`tests/test_bundle_sync.py` keeps them honest where present and skips on a
fresh clone.

## Adding a new MCP tool

A tool is **one decorated function** in the right module under
`mcp_server/toolsets/` (devices, variables, automations, organise, server,
scripts, plugins, notify, webhooks, zwave). Everything else — the schema
clients see, the scope check, caching and cache invalidation, the delete
gate, error scrubbing, search-index refresh and the docs — is derived from it.

```python
@tool("list_widgets", scope="read", cacheable=True, reads={"device"},
      description="List the widgets, newest first.",
      properties={"limit": number("Most widgets to return (default 50)")})
def list_widgets(ctx, limit=50):
    return ctx.extended_tools_handler.list_widgets(limit)
```

1. **Scope** — `read` (pure query), `write` (changes Indigo state) or `admin`
   (destructive, irreversible, code execution, plugin lifecycle, physical
   security, data leaving the house).
2. **Arguments** — `properties` and `required` become the input schema, and
   the function's parameters must match them exactly (`tests/test_registry.py`
   checks). Reuse the fragments in `toolsets/_schema.py`: `DEVICE` for a device
   by id or name (resolve it with `devices.resolve_device`, which refuses an
   ambiguous name), `AUTOMATION_KIND`, `enum()`, `number()` and so on. If one
   tool takes several actions, refuse arguments the chosen action does not use
   with `unused_args()` — silently ignoring one is the bug the dispatcher's
   unknown-argument check exists to stop.
3. **Behaviour** — `ctx` is the `MCPHandler`: call the handler objects it holds
   (`ctx.device_control_handler`, `ctx.extended_tools_handler`, …) or `indigo`
   directly. Return a dict; `{"success": False, "error": ...}` for a refusal.
   An exception becomes a failure payload for you.
4. **Metadata** — `cacheable=True` with `reads={...}` for a read worth
   caching; `invalidates={...}` on anything that changes what a cached read
   shows (`{"*"}` clears the lot); `destructive=True` for a delete with no way
   back, which adds the `confirm` argument and puts the call behind the
   delete preference; `sensitive=True` to scrub a failure whole;
   `redact=True` to keep a failure but blank secret values;
   `refresh_search=True` when it adds, removes or renames devices, variables
   or action groups. The buckets are listed in `registry.py`.
5. **Docs** — `python3 scripts/generate_tool_doc.py --write` rewrites the
   table in `docs/tools.md` **and every tool count written in prose** across
   `README.md`, `docs/*.md` and the site description in `docs/_config.yml`.
   `--check` fails on a stale count, and also on a count written in a phrasing
   it does not know how to rewrite. It never touches `docs/changelog.md` or the
   README's "What's new", which record what was true at the time. Mention the
   tool in `docs/what-it-does.md` if it is user-visible.
6. **Test** — add a behavioural test. `tests/conftest.py` has `call_tool(ctx,
   name, **args)`, which runs a tool through the real wrapper against a
   context you build from mocks, and `tests/test_dispatch.py` shows the
   skeletal-handler pattern for the full dispatch path. Then run the suite.

## Conventions

- Python 3.13 (Indigo 2025.2's embedded interpreter), 4-space indent,
  snake_case, f-strings, UK English in user-facing text.
- Never hardcode credentials, private hostnames/IPs, or an Indigo version
  number in a path — see the secrets policy in the README
  (`IndigoSecrets.py` first, PluginConfig fallback).
- Maximum error checking: guard `int()`/`float()` coercions of config values,
  never assume an Indigo API call succeeds.
- Version bumps touch `Contents/Info.plist` (`PluginVersion` — leave
  `CFBundleVersion` alone), the `plugin.py` header, and the README changelog.

## Releases

Releases are cut from `main` as `Claude.Bridge.indigoPlugin.zip` (zip the
bundle from the repo root) and attached to a GitHub release. See the README's
installation section for what users do with it.
