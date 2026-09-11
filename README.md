# Claude Bridge — Indigo Plugin

**Claude Bridge** is an [Indigo](https://www.indigodomo.com) home automation plugin that lets [Claude](https://www.anthropic.com/claude) see and control your Indigo system — your own devices, your own variables, your own event log — from an ordinary conversation.

Once it's installed you just ask. "Which lights are on?" "Turn the fan on for ten minutes." "Why didn't the bathroom light go off last night?" Claude looks at your system, does the thing, and checks its own work — no scripting, no copying device IDs about, no screenshots.

**Platform:** Indigo 2023.2 or later, macOS
**Bundle ID:** `com.clives.indigoplugin.claudebridge`
**Version:** 2.26.0

*Developed and tested on Indigo 2025.2. Older Indigo releases back to 2023.2 should also work.*

---

## How it works

Claude Bridge runs quietly inside Indigo. When you use [Claude Code](https://claude.ai/download) (Anthropic's terminal app), a small go-between script — installed and wired up for you — passes Claude's requests to Indigo's own web server, where the plugin answers them. That gives Claude **168 tools** for reading and controlling your system.

```
┌─────────────────────┐         ┌──────────────────────┐         ┌──────────────┐
│  Claude Code        │         │  go-between script   │         │  Indigo web  │
│  (you, chatting)    │ ───────►│  (installed for you) │ ───────►│  server +    │
│                     │         │  adds your access    │         │  this plugin │
│                     │         │  key automatically   │         │  (168 tools) │
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

### 2.26.0 (2026-09-10)
Other plugins can now bring their own tools to Claude Bridge.

A plugin that ships a small JSON file in its bundle, `Contents/Resources/mcp-manifest.json`, has its tools listed to Claude under its own prefix and every call forwarded to it — no configuration here, no configuration there, and a plugin picked up the moment it starts. The format is the provider-manifest contract mlamoure published for his Indigo MCP Server, followed here from the published specification, so a plugin written for either server works with both. The first provider is the Dashboards plugin (from its 3.12.0), which offers eight `dashboards_` tools: its status, its setup check as data, the room folders read and set, the cameras listed, added and removed, and the last lines of its own log.

Tools a plugin marks as writes are governed by one new switch under Configure, *Allow plugin-provided tools to make changes*, on by default and honoured at once; read tools always work. Each provider tool is classified read or write for the per-token scopes as it is registered, and never admin — the plugin decided what it does. Two new menu items print the providers found and rescan them on demand; a provider that appears, changes or vanishes is also noticed at the next tool listing. A plugin's own stopping is reported as exactly that, a hung one as a timeout rather than a hang, and a reply that breaks the contract as a protocol violation naming the plugin.

The README's tool count read 167 in seven places while the generated table and the repo description said 168; it says 168 now. 54 tests for the new module; the built-in tool table is unchanged, because a plugin's tools are not built in.

### 2.25.1 (2026-09-07)
The settings dialog was stretched wider than its own window, so the help text beside each setting was cut off mid-sentence.

The short help that can be attached to a setting is drawn on a single line and never wraps, so the longest one in the dialog decides how wide every row is — and the window cannot be widened past a fixed maximum. All four long ones have moved into ordinary description paragraphs, which do wrap.

Two new checks fail the build if any help text or setting label grows long enough to do it again, and the same file also checks every dialog parses, that field ids are unique within each dialog and that every visibility binding resolves. No setting or behaviour changed.

### 2.25.0 (2026-09-06)
Claude can now run a plugin's own actions — the ones under Device -> Actions.

Until now every plugin feature ended the same way: Claude could design it, build it, lint it and reason about it, and then a human had to sit at the Indigo client and click Device -> Actions to see whether it worked. Nothing in the bridge could reach a plugin's own `Actions.xml` actions. `execute_device_action` closes that, and it turns out Indigo has taken exactly the right arguments all along — `executeAction(actionTypeId, deviceId, props)` — so the wrapper is thin.

What is not thin is the guard, because the underlying call fails silently in three separate ways and every one of them looks like success. A misspelt action id reaches no callback and returns nothing. An action declared with `deviceFilter` — a device action — called without a device does nothing whatsoever, again returning nothing. And a plugin that is installed but stopped swallows the action entirely while the caller sees no exception at all. So the tool reads the plugin's own `Actions.xml` first, checks the call against it, and refuses with the reason and a list of what it could have called instead. Where the XML cannot be read it says so and dispatches anyway, rather than blocking a call that would have worked.

The middle one is the one that catches people out, so it is worth being exact about it. A `props` dict crosses the plugin boundary intact — measured against Timers and Pesters, `setTimerStartValue` with the device id moved the timer from 60 seconds to 43, with both props honoured. The identical call without the device id returned `None` and left it at 60. So when a plugin action seems to ignore what you sent it, the props are almost never the problem. The missing device is, and nothing raises to say so.

Admin scope, since these actuate whatever the target plugin exposes: valves, locks, garage doors, sprinkler zones. Every dispatch is written to the Indigo event log with the device and the resolved props, so an action fired by an AI caller leaves the same trail as one fired by hand.

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

Claude Bridge gives Claude Code **168 MCP tools**, enough to read and change anything on a running
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
needs an InfluxDB database set up — a niche feature. **All 168 tools work
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

2. **Restart Claude Code** — you should see 168 `indigo-mcp` tools available

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
