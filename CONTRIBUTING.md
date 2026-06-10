# Contributing to Claude Bridge

Thanks for having a look. This page tells you how to run the tests, what the
layout is, and — the most common change — how to add a new MCP tool without
tripping over the four places tool metadata lives.

## Running the tests

No Indigo install is needed — `tests/conftest.py` stubs the `indigo` module
and resolves the plugin bundle automatically (a live installed copy if one
exists, otherwise the bundle inside this repo).

```bash
pip install -r "Claude Bridge.indigoPlugin/Contents/Server Plugin/requirements.txt" pytest
python -m pytest tests -q
```

To force the suite to run against this repo's bundle even on a machine with a
live Indigo install:

```bash
CB_SP="$PWD/Claude Bridge.indigoPlugin/Contents/Server Plugin" python -m pytest tests -q
```

Lint (errors only — undefined names, unused imports; no style policing) and
the README tool-table staleness check:

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
    ├── mcp_handler.py      # MCP protocol dispatch + tool registry
    ├── tools/<category>/   # one handler module per tool category
    ├── security/           # scope manager, rate limiter, egress firewall
    ├── webhooks/           # outbound event webhook engine
    └── common/             # tool cache, search store, influxdb, helpers
tests/                      # pytest suite — runs standalone, <10 s
scripts/generate_tool_doc.py # regenerates the README tool table from the registry
```

Two files exist in two copies — the repo root and the bundle — and must stay
byte-identical: `indigo_mcp_proxy.py` and `IndigoSecrets_example.py`.
`tests/test_bundle_sync.py` fails if they drift; edit both.

## Adding a new MCP tool

Tool metadata lives in **four places**. Miss one and a test (or the startup
audit) will tell you, but here is the full recipe so you don't have to find
out the hard way:

1. **Implement** the behaviour in the right handler under
   `mcp_server/tools/<category>/` (or add a new category module and wire it
   in `MCPHandler._init_handlers()`).
2. **Register** it in `MCPHandler._register_tools()`
   (`mcp_server/mcp_handler.py`): a `self._tools["your_tool"] = {...}` entry
   with `description`, `inputSchema` (declare `required` args — dispatch
   validates them for you) and `function`.
3. **Classify** it in `mcp_server/security/scope_manager.py` — add the name to
   exactly one of `READ_TOOLS` / `WRITE_TOOLS` / `ADMIN_TOOLS`. Unclassified
   tools fail closed to admin and log an ERROR at startup;
   `tests/test_tool_registry_consistency.py` fails too.
   Rule of thumb: pure query → read; changes Indigo state → write;
   destructive / irreversible / code execution / physical security / data
   leaving the house → admin.
4. **Cache behaviour** (read tools only) in
   `mcp_server/common/tool_cache.py`: if the result is worth caching, add the
   name to `CACHEABLE_TOOLS` *and* make sure every mutator that would stale it
   maps to a bucket containing it in `_INVALIDATION_MAP` — or, if only the TTL
   can keep it fresh, add it to `TTL_ONLY_CACHEABLE` in
   `tests/test_tool_registry_consistency.py` (a conscious decision, not a
   default). Mutating tools that stale cached reads get an `_INVALIDATION_MAP`
   entry of their own.
5. **Docs**: regenerate the README table —
   `python3 scripts/generate_tool_doc.py --write` — and add the tool to the
   matching category in `CAPABILITY_SUMMARY.md`.
6. **Test**: add a behavioural test (see `tests/test_dispatch.py` for the
   skeletal-handler pattern that needs no Indigo server), then run the full
   suite.

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
