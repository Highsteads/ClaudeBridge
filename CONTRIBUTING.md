# Contributing to Claude Bridge

Thanks for having a look. This page tells you how to run the tests, what the
layout is, and — the most common change — how to add a new MCP tool, which is
now one decorated function.

## Running the tests

No Indigo install is needed — `tests/conftest.py` stubs the `indigo` module
and tests the plugin bundle in this repo. From the repo root:

```bash
pip install pytest
python3 -m pytest -q
```

`pytest.ini` points pytest at `tests/`. The plugin needs nothing beyond the
standard library and Indigo itself, so pytest is the only thing to install.
`tests/test_no_third_party_deps.py` fails the suite if a module in the bundle
ever imports anything else.

To run the suite against another copy of the bundle, such as the one Indigo
has installed, point `CB_SP` at its `Server Plugin` folder:

```bash
CB_SP="/Library/Application Support/Perceptive Automation/Indigo 2025.2/Plugins/Claude Bridge.indigoPlugin/Contents/Server Plugin" python3 -m pytest -q
```

Lint (errors only — undefined names, unused imports; no style policing):

```bash
pip install ruff
ruff check .
```

The suite also runs `scripts/generate_tool_doc.py --check`
(`tests/test_version_consistency.py`), so a stale `docs/tools.md` or tool
count fails it. CI (`.github/workflows/test.yml`) runs pytest and ruff on every
push and pull request, and both must be green.

Tests are named for what they test (`test_device_battery.py`,
`test_tool_cache.py`, `test_webhooks.py`), not for the release that added
them. Shared doubles — `FakeDevice`, `FakeIndigoDict`, `FakeIndigoList` — and
`load_plugin_module()`, which imports `plugin.py` itself against the stub, live
in `tests/conftest.py`. Test what the code does: run it and check the result,
rather than reading its source text for a pattern.

## Repo layout

```
Claude Bridge.indigoPlugin/Contents/Server Plugin/
├── plugin.py               # Indigo plugin lifecycle + IWS endpoints + change callbacks
├── indigo_mcp_proxy.py     # stdio→HTTP bridge that Claude Code launches
└── mcp_server/
    ├── mcp_handler.py      # MCP protocol dispatch (rate limit, scopes, gate, cache)
    ├── registry.py         # the @tool decorator and everything derived from it
    ├── toolsets/           # every built-in tool, one module per domain
    ├── tools/<category>/   # the handler classes the tools call
    ├── client_setup.py     # Claude Code auto-setup, run at plugin start
    ├── orphan_prefs.py     # deletes settings of removed Configure fields
    ├── security/           # scope manager, rate limiter, egress firewall
    ├── webhooks/           # outbound event webhook engine
    └── common/             # tool cache, entity (search) index, helpers
tests/                      # pytest suite — runs standalone, about 10 s
scripts/generate_tool_doc.py # writes docs/tools.md and every tool count from the registry
docs/                        # the documentation site; docs/changelog.md is the version history
```

`indigo_mcp_proxy.py` and `IndigoSecrets_example.py` exist only inside the
bundle (`Contents/Server Plugin/`). There is no installer script: a user
double-clicks the bundle, and the plugin deploys the proxy and sets Claude
Code up itself when it starts (`mcp_server/client_setup.py`).

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
   delete preference; for a tool that takes several actions,
   `destructive_actions={"enter_exclusion"}` gates only those actions and
   `action_scopes={"reset_energy": "admin"}` makes one action need a higher
   scope than the tool's own; `sensitive=True` to scrub a failure whole;
   `redact=True` to keep a failure but blank secret values;
   `redact_output=True` for a read that can show file or log text (a script,
   an automation's embedded script, the event log), so a key without admin
   gets every known secret value blanked from the reply;
   `refresh_search=True` when it adds, removes or renames devices, variables
   or action groups, so search sees the change at once. (A change made any
   other way — in the Indigo client, or by `execute_indigo_python` — reaches
   the index through the plugin's Indigo change callbacks, which mark it for a
   rebuild on the next search.) The buckets are listed in `registry.py`.
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
- New `.py` files carry the standard header (Filename, Description, Author,
  Date, Version). History lives in `docs/changelog.md`, not in file headers.

## Version bumps

A change inside the `.indigoPlugin` bundle gets a version bump. A change only
to tests, docs, CI or the README does not: none of those reach Indigo, and
bumping for them would leave the installed bundle looking out of date.

A bump touches, together:

1. `Contents/Info.plist` — `PluginVersion` only (leave `CFBundleVersion` at
   `1.0.0`; it describes the bundle layout, not the release)
2. the `# Version:` line of the `plugin.py` header
3. the README's `**Version:**` line
4. a `### X.Y.Z (YYYY-MM-DD)` entry at the top of `docs/changelog.md`, in
   plain English, and the same text word for word under the README's
   **What's new**, which keeps the newest three
5. `python3 scripts/generate_tool_doc.py --write` if any tool changed

Then run the suite. `tests/test_version_consistency.py` fails when those
places disagree, so run it after the bump, not before.

## Releases

Releases are cut from `main` as `Claude.Bridge.indigoPlugin.zip`, built from
the committed tree so nothing untracked (caches, local notes) can slip in:

```bash
git archive --format=zip -o Claude.Bridge.indigoPlugin.zip HEAD "Claude Bridge.indigoPlugin"
```

Never zip the working tree. Attach the zip to a GitHub release. See the
README's installation section for what users do with it.
