# Claude Bridge — Indigo Plugin

**Claude Bridge** is an [Indigo](https://www.indigodomo.com) home automation plugin that lets [Claude](https://www.anthropic.com/claude) see and control your Indigo system — your own devices, your own variables, your own event log — from an ordinary conversation.

Once it's installed you just ask. "Which lights are on?" "Turn the fan on for ten minutes." "Why didn't the bathroom light go off last night?" Claude looks at your system, does the thing, and checks its own work — no scripting, no copying device IDs about, no screenshots.

**Platform:** Indigo 2023.2 or later, macOS
**Bundle ID:** `com.clives.indigoplugin.claudebridge`
**Version:** 2.27.2

*Developed and tested on Indigo 2025.2. Older Indigo releases back to 2023.2 should also work.*

---

## How it works

Claude Bridge runs quietly inside Indigo. When you use [Claude Code](https://claude.ai/download) (Anthropic's terminal app), a small go-between script — installed and wired up for you — passes Claude's requests to Indigo's own web server, where the plugin answers them. That gives Claude **169 tools** for reading and controlling your system.

```
┌─────────────────────┐         ┌──────────────────────┐         ┌──────────────┐
│  Claude Code        │         │  go-between script   │         │  Indigo web  │
│  (you, chatting)    │ ───────►│  (installed for you) │ ───────►│  server +    │
│                     │         │  adds your access    │         │  this plugin │
│                     │         │  key automatically   │         │  (169 tools) │
└─────────────────────┘         └──────────────────────┘         └──────────────┘
```

None of that shows from where you sit — you open a Claude Code session and the Indigo tools are there. Everything stays on your own machine and goes through Indigo's existing web server, behind the same access key Indigo already uses.

### Why this matters

Before Claude Bridge, asking AI to help with Indigo meant pasting
screenshots, copying device IDs by hand, and hoping the AI remembered
what state your Hall PIR was in three messages ago. Claude was guessing.

With Claude Bridge, Claude can:

- **Read your actual Indigo state, live.** Not a description of it —
  the real device states, plugin states, variable values, event log,
  and trigger configurations as they are right now.
- **Make changes and verify them.** Turn a device on, then read its
  state back to confirm. Edit a script, restart the plugin that uses
  it, query the log to see if it loaded cleanly — all in one
  conversation.
- **Reason about your home.** "Which sensors haven't reported in 24
  hours?" "Does any script depend on variable ID 12345?" "What plugins
  are disabled that shouldn't be?" Claude uses the audit and
  diagnostic tools and answers.

---

---

**Documentation:** **[highsteads.github.io/ClaudeBridge](https://highsteads.github.io/ClaudeBridge/)** —
getting started, what every tool does, worked examples of a session, configuration, security, the
provider how-to for plugin authors, troubleshooting, and the full version history. This README is
the short version.

### Jump to

**[What's new](#whats-new)** &nbsp;·&nbsp;
**[Vibe coding](#vibe-coding-for-indigo)** &nbsp;·&nbsp;
**[What it does](#what-it-does)** &nbsp;·&nbsp;
**[Safety](#how-it-keeps-your-house-safe)** &nbsp;·&nbsp;
**[Requirements](#requirements)** &nbsp;·&nbsp;
**[Installation](#installation)** &nbsp;·&nbsp;
**[Your plugin's tools](#letting-your-plugin-add-tools)** &nbsp;·&nbsp;
**[Troubleshooting](#troubleshooting)**

---

## What's new

The three most recent releases, word for word. Every release before these is in
**[the version history](docs/changelog.md)**, which the documentation site also carries.

### 2.27.2 (2026-09-23)
When Claude's own code fails inside Indigo, it now gets told why.

A failed `execute_indigo_python` or `run_script` used to hand back nothing but "see the Claude Bridge event log for details", and the event log held only the error's name, never the traceback or whatever the code had printed first. Claude then had to go and read the log, and over ten weeks that happened 85 times. The reply now keeps the traceback, the output and the error text, and any password, key or token that turns up in them is replaced with a marker such as `[redacted MQTT_PASSWORD]`. Claude Bridge knows which values to hide from the settings in `IndigoSecrets.py` whose names mark them as credentials, from Indigo's own API keys and from its own settings, and it reads the file afresh whenever it changes, so a new key is covered without a restart. If it cannot read those values it goes back to the old bare message rather than risk sending one. A very long traceback also used to be cut from the end, which threw away the one line that says what went wrong. It now keeps the end.

`search_entities` accepts `devices`, `variables` and `action_groups` as well as the singular names it always wanted, and its description now lists the valid values. One search in seven had been failing on exactly that.

34 new tests. I broke each of the six changes on purpose, and a test went red every time.

### 2.27.1 (2026-09-23)
Clicking a plugin's menu item no longer fails when the reply contains an accent or a dash.

Asking Claude to run *Scan Now* on Device Health Monitor came back with `'ascii' codec can't decode byte 0xe2`, which is the first byte of an em-dash. Inside an Indigo plugin host the text encoding defaults to plain ASCII, so any output from the Indigo client that was not plain ASCII broke the tool reading it, even though the click itself had worked. Every place Claude Bridge runs another program now reads its output as UTF-8: both menu tools, the `du` and `ps` readings behind `system_health` and `find_large_files`, and the `node` check behind `plugin_node_check_html`. A byte that still makes no sense is replaced rather than allowed to stop the tool.

Five new tests. Four run a real child process under the same ASCII default the plugin host uses, and were watched failing on the old code with the exact error from the log. The fifth reads the whole bundle and fails if anything ever again runs a program as text without saying which encoding.

### 2.27.0 (2026-09-14)
Claude can now use any of the Indigo client's own menus, not just a plugin's.

Claude Bridge could already click a plugin's menu item, because Indigo offers no other way to fire one from outside. That same gap turns out to run through a good deal of the client itself. `indigo.zwave` has an `isEnabled()` and nothing that sets it, so *Interfaces, Z-Wave, Disable* is the only way to make Indigo let go of the Z-Wave stick, and letting go of the stick is exactly what a controller backup needs before it can read it. The new `execute_client_menu_item` takes the whole path, so `['Interfaces', 'Z-Wave', 'Disable']` does what a person would do, and a backup, a verify and switching the interface back on afterwards now run with nobody at the keyboard.

It reads menus as well as clicking them. Passing `list_only` returns the item names under any menu or submenu, which matters more than it sounds: several of these labels are toggles that rename themselves, and the Z-Wave one reads *Disable* while the interface is on and *Enable* while it is off, so anything that clicks a fixed label will sooner or later click the wrong one. Listing leaves the client where it is. Clicking brings it to the front, because System Events needs it there.

Two things it will not do. It refuses any path through Claude Bridge's own submenu, however it is spelt, because reloading the bridge kills the session that asked for it. The plugin-menu tool already refused that by name, and a tool that takes a whole path reaches the identical item by another road, so the guard had to be built again here rather than inherited. It also refuses to quit the client, that being the one click nothing on this side could undo.

15 tests, each guard checked by breaking it first and watching the suite go red. The tool table is generated, and it now keeps the sentence above itself current too: adding this tool moved the table and the generated marker to 169 and left the headline reading 168, which is the same fault the 2.26.0 note records finding in seven places at once.

## Vibe coding for Indigo

["Vibe coding"](https://en.wikipedia.org/wiki/Vibe_coding) is a term
coined by Andrej Karpathy in early 2025 for a particular style of
working with AI coding agents: you describe what you want in plain
language, the AI writes the code, you describe what you want changed,
the AI iterates. You guide by intent rather than by syntax. The "vibe"
is the back-and-forth itself — fewer keystrokes, more conversation.
Done well it produces working code far quicker than writing it line by
line, done carelessly it produces code that looks plausible and doesn't
run. What separates the two is a feedback loop that lets the AI
**verify** what it just wrote.

Claude Bridge turns the Indigo system itself into that feedback loop.

A confession, which I offer as the best evidence I have: **this plugin was
itself written by vibe coding.** Every version of Claude Bridge came out of a
conversation with Claude — described in plain English, written by Claude, and
tested by Claude against the live Indigo server, using the previous version of
this very plugin to see and act. The twenty-odd other plugins on this GitHub
account were built and are maintained the same way, with Claude Bridge as the
feedback loop, and the git history backs every word of that if you fancy
checking. So the examples below aren't speculation about what you could do.
They describe how the thing you are reading about came to exist.

Examples of how a session might go:

One example of how a session goes — there are three, with what you get out of it, on the
[Working with Claude](https://highsteads.github.io/ClaudeBridge/working-with-claude.html) page:

### Example 1 — write a Python script in one prompt

> **You:** "Write me a script that runs at sunset, turns on the porch
> light, and sends me a Pushover notification if the front door is
> currently open."

Claude Code:
1. Calls `search_entities` to find your porch light and front door sensor
2. Calls `get_device_by_name` to confirm IDs and states
3. Writes the script via `scaffold_automation_script` with the correct
   IDs baked in and a `log()` helper
4. Writes the file via `create_script`
5. Tells you the script name and tells you to schedule it for sunset

You read the result, hit Enter to commit, done. No Googling
`indigo.device.turnOn()`. No copy-pasting device IDs.

### Honest limits

- **Claude can't create Triggers, and can't enable or disable a
  plugin** — Indigo keeps those to the UI. You get a scaffolded
  `.indigoPlugin` bundle and instructions, then you do the enable
  click yourself.
- **Claude reads your automations, it doesn't rewrite them blind.**
  Trigger conditions and Action Group steps used to be invisible.
  They aren't any more — `get_trigger_details`, `get_action_group_details`
  and `find_automation_references` read them straight out of Indigo's
  own database, embedded scripts included. Editing them still goes
  through `update_trigger` and `update_schedule`, which cover the
  firing configuration rather than every step.
- **Vibe coding speeds you up, it doesn't think for you.** Read what
  has been written. Test the changes. The point of Claude Bridge is
  that checking is one tool call away — so use it.

---

---

## What it does

Claude Bridge gives Claude Code **169 MCP tools**, enough to read and change anything on a running
Indigo server: **70 read** tools (pure queries), **68 write** tools (they change Indigo state) and
**30 admin** tools (deletes, code execution, plugin lifecycle, physical security). By area:

- **Devices** — list, search and inspect by id, name, type or state; plain-English search; on, off,
  toggle, brightness, colour, fan speed, lock and unlock; timed actions that Indigo's own engine
  carries out; beep and ping to find a device.
- **Heating** — per-zone snapshots, setpoints, bumps and HVAC modes on any Indigo thermostat.
- **Energy** — live solar, battery and grid, day-by-day analysis and comparisons.
- **Variables, action groups, triggers and schedules** — create, read, update, organise, enable,
  disable, run and fire; read a trigger's conditions and an action group's steps out of Indigo's
  own database; find everything that references a device or variable before you touch it.
- **Plugins** — enumerate, inspect, restart, and run any plugin's own actions.
- **Scripts** — read, write with automatic backups, create, archive and run, in both script folders;
  a scaffolder that writes a script in the house style with every id resolved live.
- **The event log** — search it by keyword, device, plugin or time, including entries older than
  the Indigo window shows; watch a device or variable for its next change.
- **Event webhooks** — the home posts a signed event to a URL you run, behind a default-deny
  firewall. Off until you turn it on.
- **Plugin-provided tools** — any plugin that ships a manifest brings its own tools, listed under
  its prefix and forwarded to it.
- **Memory, audits, health, reporting and notifications** — cross-session memory; whole-system
  audits and finders for what is in error, quiet, orphaned or oversized; a prose status report;
  e-mail, Pushover and log lines.
- **A scripting shell** — arbitrary Python in Indigo's context, admin scope only.

Every tool by name, with the scope it needs, is in the
[Tool reference](https://highsteads.github.io/ClaudeBridge/tools.html), generated from the code and
checked on every push. The fuller tour by area is
[What it does](https://highsteads.github.io/ClaudeBridge/what-it-does.html).

## How it keeps your house safe
- **Everything stays local.** Searching and control all happen on your own
  Mac. The only thing that ever leaves the machine is your conversation with
  Claude itself.
- **No extra doors into your network.** Everything travels through Indigo's
  own web server on its existing port, protected by Indigo's own access key,
  and the Reflector gives you secure remote access for free.
- **Permission levels.** Every tool is classed as read, write, or admin. If
  you hand out a read-only key it really is read-only — and anything
  destructive (deleting things, running code, unlocking a door, the new
  folder deletes) needs the admin level. Anything not explicitly classified
  is locked down, not waved through.
- **Careful by default.** Dangerous operations refuse ambiguous input rather
  than guessing, deletes that can cascade make you say so explicitly, and
  the plugin checks its own permission setup every time it starts.

---

---

## Requirements

- Indigo 2023.2 or later, on macOS (the plugin runs on your Indigo server machine)
- [Claude Code](https://claude.ai/download) — the free Anthropic app you talk to Claude through
- A **paid Claude account** — see below

### What this costs — read this before installing

There are two Anthropic things people mix up, and only ONE of them is required:

**1. A Claude subscription — required.** Claude Code (the app you chat in) needs a
paid Claude account: a **Claude Pro or Max subscription** from
[claude.ai](https://claude.ai) is the usual route. This is the monthly plan that
pays for your conversations — every question you ask and every answer Claude
gives. If you already pay for Claude Pro or Max, you're done — this plugin adds
nothing to that bill. (The alternative for the technically inclined is an
Anthropic API account with pay-as-you-go billing instead of a subscription.)

**2. An Anthropic API key for the plugin itself — optional, most people can skip
it.** The plugin can hold its own API key from
[console.anthropic.com](https://console.anthropic.com), but it only uses it for
one thing: writing AI summaries inside the historical-analysis tool, which also
needs an InfluxDB database set up — a niche feature. **All 169 tools work
without this key.** If you do set one up, it bills per use (pennies a month,
as a rule), separately from your subscription.

In short: **pay for Claude Pro or Max, skip the API key**, and everything in
this README works.

---

---

## Installation

### Quick install (recommended)

Clone the repo and run the installer — it handles everything except enabling the plugin in Indigo:

```bash
git clone https://github.com/Highsteads/ClaudeBridge.git
cd ClaudeBridge
python3 "Claude Bridge.indigoPlugin/Contents/Server Plugin/install.py"
```

The script:
- Copies the plugin bundle to Indigo's Plugins directory
- Copies the proxy script to Indigo's `Scripts` directory
- Reads your Bearer token from Indigo's `secrets.json` and patches the proxy automatically
- Creates/updates `~/.mcp.json` and `~/.claude/settings.json`

Then do these two final steps manually:

1. **Indigo → Plugins → Manage Plugins → Enable Claude Bridge**
   *(The plugin auto-creates its device on first enable — no "New Device" step needed)*

2. **Restart Claude Code** — you should see 169 `indigo-mcp` tools available

> **Credentials policy:** All sensitive values are read from
> `/Library/Application Support/Perceptive Automation/IndigoSecrets.py` first, and
> the plugin's PluginConfig dialog is a fallback only. Keys this plugin reads:
> `ANTHROPIC_API_KEY` (optional — see "What this costs" above),
> `CLAUDEBRIDGE_BEARER_TOKEN`, and (optional) `INFLUXDB_HOST`,
> `INFLUXDB_PORT`, `INFLUXDB_USERNAME`, `INFLUXDB_PASSWORD`, `INFLUXDB_DATABASE`.
> If a value is missing from BOTH sources, the plugin logs an ERROR pointing
> here and skips that feature. See `IndigoSecrets_example.py` for the template.

---

The manual route — download the release, double-click the bundle, install the go-between script
and register it with Claude Code by hand — is on the
[Getting started](https://highsteads.github.io/ClaudeBridge/getting-started.html) page, along
with connecting the Claude desktop app and what to ask first.

---

## Letting your plugin add tools

Any Indigo plugin can add tools of its own to Claude Bridge by shipping one JSON file,
`Contents/Resources/mcp-manifest.json`, a hidden action that answers the calls, and one guarded
broadcast line at startup. Claude Bridge finds the file on its own, lists the tools under that
plugin's prefix, and forwards each call. The format is the provider-manifest contract published by
[mlamoure's Indigo MCP Server](https://github.com/mlamoure/indigo-mcp-server), so a plugin written
for either server works with both. The full how-to, with the manifest, the action and the callback
spelled out, is [Letting your plugin add tools](https://highsteads.github.io/ClaudeBridge/providers.html);
the [Dashboards plugin](https://github.com/Highsteads/Dashboards) is a complete worked example.

---

## Troubleshooting

The errors people actually see — "Could not attach to MCP server", "Unsupported protocol version",
401s, empty searches, a plugin that will not start after a pip loop — with what each one means and
the fix, are on the [Troubleshooting](https://highsteads.github.io/ClaudeBridge/troubleshooting.html)
page. Two that are worth knowing before you need them: new tools appear only after Claude Code is
restarted, because it caches the tool list; and asking Claude to restart Claude Bridge itself is
refused on purpose — use **Plugins → Claude Bridge → Reload**.

---

## Claude Code skills that complement this plugin

Claude Bridge is the **runtime** bridge. For the **design-time** side — the Indigo SDK docs,
lifecycle reference, sixteen example plugins and the IOM — the companion is Simon's `indigo:dev`
skill from [simons-plugins/indigo-claude-plugin](https://github.com/simons-plugins/indigo-claude-plugin).
Neither needs the other; together they give Claude Code the complete loop. How they fit is on the
[Working with Claude](https://highsteads.github.io/ClaudeBridge/working-with-claude.html#claude-code-skills-that-complement-this-plugin)
page.

## Logging

Every log line carries a millisecond timestamp `[HH:MM:SS.mmm]`, so you can
line events up precisely against the other CliveS plugins — Device Activity
Monitor uses the same format.

To turn the prefix off, or back on, at any time:

**Plugins → Claude Bridge → Toggle Timestamps in Log (on/off)**

The plugin stores the setting in `pluginPrefs` (`timestampEnabled`) and it
survives a restart. It defaults to ON.

---

## Contributing

Pull requests welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for how to run
the test suite (no Indigo install needed) and the recipe for adding a new MCP
tool. Every push and pull request runs the tests, lint and a docs-staleness
check automatically.

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

Built conversationally — CliveS describing what the plugin should do and keeping it honest, Claude writing the code and testing it against the live system, each new version developed through the one before it. Which, fittingly, is exactly the way of working this plugin exists to give you. The proof is the plugin itself.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
