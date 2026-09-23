# Claude Bridge — Indigo Plugin

**Claude Bridge** is an [Indigo](https://www.indigodomo.com) home automation plugin that lets [Claude](https://www.anthropic.com/claude) see and control your Indigo system — your own devices, your own variables, your own event log — from an ordinary conversation.

Once it's installed you just ask. "Which lights are on?" "Turn the fan on for ten minutes." "Why didn't the bathroom light go off last night?" Claude looks at your system, does the thing, and checks its own work — no scripting, no copying device IDs about, no screenshots.

**Platform:** Indigo 2023.2 or later, macOS
**Bundle ID:** `com.clives.indigoplugin.claudebridge`
**Version:** 3.0.0

*Developed and tested on Indigo 2025.2. Older Indigo releases back to 2023.2 should also work.*

---

## How it works

Claude Bridge runs quietly inside Indigo. When you use [Claude Code](https://claude.ai/download) (Anthropic's terminal app), a small go-between script — installed and wired up for you — passes Claude's requests to Indigo's own web server, where the plugin answers them. That gives Claude **69 tools** for reading and controlling your system.

```
┌─────────────────────┐         ┌──────────────────────┐         ┌──────────────┐
│  Claude Code        │         │  go-between script   │         │  Indigo web  │
│  (you, chatting)    │ ───────►│  (installed for you) │ ───────►│  server +    │
│                     │         │  adds your access    │         │  this plugin │
│                     │         │  key automatically   │         │  (69 tools)  │
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

### 3.0.0 (2026-09-24)
A spring clean: 69 tools where there were 169, nothing to install, and a long piece of Python no longer freezes the web server.

- **Far fewer tools, nothing you could do has gone.** Most of the old list was families of near-identical tools, one per verb: seven for sprinklers, eight for thermostats, four for enabling and disabling. Each family is now one tool that takes an `action` or `kind`. The *Upgrading to 3.0* page of the documentation lists every old name against its new one, for anything you have written down that names a tool.
- **Long Python runs go into the background.** A 10-second `execute_indigo_python` was measured holding up a dashboard request for 9.9 seconds, because Indigo's web server waits on it. A run that takes longer than `wait_seconds` (8 by default) now carries on by itself and hands back a `job_id` at once; ask again with the `job_id` to collect the answer.
- **No API key, no extra packages.** The AI summaries in `analyze_historical_data` needed InfluxDB, an Anthropic key and four Python packages that made up 35 MB of a 39 MB plugin. That tool is gone and so are they; `device_history` reads the SQL Logger instead. Settings those features left behind, a stored API key included, are cleared the first time 3.0 starts.
- **Search shows how things are now.** It still finds matches in its own index, but the state of each device and the value of each variable in the answer come straight from Indigo, and the index is brought up to date the moment you add, delete or rename something.
- **Also gone:** the four `remember`/`recall` tools (Claude Code keeps its own memory) and the event queue, which no MCP client could read between messages. Outbound webhooks are unchanged.
- **Behind the scenes:** each tool is now written in one place, where it used to take changes in up to nine, and the plugin sets Claude Code up itself, so `install.py` is gone.

1,150 tests. Every new piece of logic was broken on purpose and a test caught it every time.

### 2.27.3 (2026-09-23)
A round of fixes from a full review of the plugin, most of them in the tools Claude uses every day.

- **Searching now finds everything that matches.** Asking for "kitchen" returned one device out of fourteen. Any name containing the search word scored as a perfect match, and a perfect match was taken to mean "this is the one", so the rest were thrown away. Only a name that is exactly what was asked for gets that treatment now.
- **Text you send is stored as you sent it.** Setting a variable to `21.50` stored `21.5`, and a value written as JSON came back as something JSON could not read, all while reporting success. The small program that carries Claude's requests to Indigo was guessing which words were numbers without knowing what each tool expected. Claude Bridge now does that itself, using each tool's own description of its arguments, and anything a tool expects as text arrives untouched.
- **"Turn on the hall lamp" will not guess.** If a name matches more than one device, nothing is switched and Claude gets the list to choose from.
- **Plugin status says whether a plugin is actually running**, not just whether it is enabled, so a plugin that falls over on start-up no longer looks healthy. A newly installed or updated plugin also shows up within half a minute rather than an hour, and restarting a mistyped plugin id now says "not found".
- **The daily energy summary and comparison work.** They were reading lines from SigenEnergyManager's logs that it has never written, so every total came back empty. They now read its own day-by-day record, and the summary adds today's running totals.
- **No paid API call when the plugin starts.** An Anthropic key in `IndigoSecrets.py` meant every start sent a message to Claude to check the key. The key is only used by the InfluxDB history tool, so it is now checked only when InfluxDB is switched on, or when you press Test Connections, and the check no longer spends anything.
- **Device history with no columns named is quicker**, and no longer lists columns that are empty in every row it returns.
- **Event log searches keep the first second of the window you ask for**, and are capped at 2,000 entries even when no count is given.
- **Shortened output says so**, and a failing script run with `run_script` reports the kind of error and its traceback, not just the message.

54 new tests. I broke each fix on purpose and watched a test fail every time.

### 2.27.2 (2026-09-23)
When Claude's own code fails inside Indigo, it now gets told why.

A failed `execute_indigo_python` or `run_script` used to hand back nothing but "see the Claude Bridge event log for details", and the event log held only the error's name, never the traceback or whatever the code had printed first. Claude then had to go and read the log, and over ten weeks that happened 85 times. The reply now keeps the traceback, the output and the error text, and any password, key or token that turns up in them is replaced with a marker such as `[redacted MQTT_PASSWORD]`. Claude Bridge knows which values to hide from the settings in `IndigoSecrets.py` whose names mark them as credentials, from Indigo's own API keys and from its own settings, and it reads the file afresh whenever it changes, so a new key is covered without a restart. If it cannot read those values it goes back to the old bare message rather than risk sending one. A very long traceback also used to be cut from the end, which threw away the one line that says what went wrong. It now keeps the end.

`search_entities` accepts `devices`, `variables` and `action_groups` as well as the singular names it always wanted, and its description now lists the valid values. One search in seven had been failing on exactly that.

34 new tests. I broke each of the six changes on purpose, and a test went red every time.

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
3. Writes the script with the correct IDs baked in and a `log()` helper
4. Saves it with `write_script` (`create=true`)
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
  They aren't any more — `get_automation` and `find_automation_references`
  read them straight out of Indigo's own database, embedded scripts
  included. Editing them still goes through `update_automation`, which
  covers names, descriptions and a trigger's event rather than every step.
- **Vibe coding speeds you up, it doesn't think for you.** Read what
  has been written. Test the changes. The point of Claude Bridge is
  that checking is one tool call away — so use it.

---

---

## What it does

Claude Bridge gives Claude Code **69 MCP tools**, enough to read and change anything on a running
Indigo server: **28 read** tools (pure queries), **21 write** tools (they change Indigo state) and
**20 admin** tools (deletes, code execution, plugin lifecycle, physical security). By area:

- **Devices** — list, search and inspect by id, name, type or state; plain-English search; one
  `device_control` tool for on, off, toggle, brightness, colour, status, beep and ping, by id or by
  name (an ambiguous name is refused, never guessed); fan speed, sprinklers, lock and unlock; timed
  actions that Indigo's own engine carries out.
- **Heating** — per-zone snapshots, and setpoints, steps, HVAC and fan modes in one
  `thermostat_control` call.
- **Energy** — live solar, battery and grid, day-by-day history and period comparisons.
- **Variables, action groups, triggers and schedules** — create, read, update, organise, enable,
  disable, run and fire; read a trigger's conditions and an action group's steps out of Indigo's
  own database; find everything that references a device or variable before you touch it.
- **Plugins** — enumerate, inspect, restart, and run any plugin's own actions.
- **Scripts** — read, write with automatic backups, create, archive and run, in both script folders.
  A long run carries on in the background and hands back a job to collect, so the web server is
  never held up waiting for it.
- **The event log** — search it by keyword, device, plugin or time, including entries older than
  the Indigo window shows.
- **Event webhooks** — the home posts a signed event to a URL you run, behind a default-deny
  firewall. Off until you turn it on.
- **Plugin-provided tools** — any plugin that ships a manifest brings its own tools, listed under
  its prefix and forwarded to it.
- **Audits, health, reporting and notifications** — one `audit` tool for whole-system checks and
  for what is in error, quiet, orphaned or oversized; a prose status report; e-mail, Pushover and
  log lines.
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

Claude Code (the app you chat in) needs a paid Claude account: a **Claude Pro or
Max subscription** from [claude.ai](https://claude.ai) is the usual route. This
is the monthly plan that pays for your conversations — every question you ask
and every answer Claude gives. If you already pay for Claude Pro or Max, you're
done — this plugin adds nothing to that bill. (The alternative for the
technically inclined is an Anthropic API account with pay-as-you-go billing
instead of a subscription.)

**The plugin itself needs no API key and no extra Python packages.** It runs on
what Indigo already ships, so there is nothing to download at install and no
second bill.

---

---

## Installation

1. Go to the [Releases page](https://github.com/Highsteads/ClaudeBridge/releases) and download `Claude.Bridge.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Claude Bridge.indigoPlugin`
3. Double-click `Claude Bridge.indigoPlugin` — Indigo will install it automatically
4. **Indigo → Plugins → Manage Plugins → Enable Claude Bridge**
   *(The plugin auto-creates its device on first enable — no "New Device" step needed)*
5. **Restart Claude Code** — you should see 69 `indigo-mcp` tools available

That is all. Each time it starts, the plugin sets Claude Code up for you: it copies the
go-between script into Indigo's `Scripts` folder, writes your Indigo access key into it (from
Indigo's own `secrets.json`, or `CLAUDEBRIDGE_BEARER_TOKEN` in `IndigoSecrets.py`), and adds an
`indigo-mcp` entry to `~/.mcp.json` and `~/.claude/settings.json`. It does this for the macOS user
Indigo runs as, which is the one you use Claude Code as on the Indigo Mac. If you would rather
manage those files yourself, untick **Auto-configure Claude Code** under
**Plugins → Claude Bridge → Configure**.

> **Credentials policy:** All sensitive values are read from
> `/Library/Application Support/Perceptive Automation/IndigoSecrets.py` first, and
> the plugin's PluginConfig dialog is a fallback only. Keys this plugin reads:
> `CLAUDEBRIDGE_BEARER_TOKEN` and (optional) `WEBHOOK_ALLOWLIST`.
> If a value is missing from BOTH sources, the plugin logs an ERROR pointing
> here and skips that feature. See `IndigoSecrets_example.py` for the template.

---

Setting Claude Code up by hand (with auto-configure off, or on another Mac), connecting the Claude
desktop app, and what to ask first are on the
[Getting started](https://highsteads.github.io/ClaudeBridge/getting-started.html) page.

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
