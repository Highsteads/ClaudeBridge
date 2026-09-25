# Claude Bridge — Indigo Plugin

**Claude Bridge** is an [Indigo](https://www.indigodomo.com) home automation plugin that lets [Claude](https://www.anthropic.com/claude) see and control your Indigo system — your own devices, your own variables, your own event log — from an ordinary conversation.

Once it's installed you just ask. "Which lights are on?" "Turn the fan on for ten minutes." "Why didn't the bathroom light go off last night?" Claude looks at your system, does the thing, and checks its own work — no scripting, no copying device IDs about, no screenshots.

**Platform:** Indigo 2023.2 or later, macOS
**Bundle ID:** `com.clives.indigoplugin.claudebridge`
**Version:** 3.4.0

*Developed and tested on Indigo 2025.2. Older Indigo releases back to 2023.2 should also work.*

---

## How it works

Claude Bridge runs quietly inside Indigo. When you use [Claude Code](https://claude.ai/download) (Anthropic's terminal app), a small go-between script — installed and wired up for you — passes Claude's requests to Indigo's own web server, where the plugin answers them. That gives Claude **70 tools** for reading and controlling your system.

```
┌─────────────────────┐         ┌──────────────────────┐         ┌──────────────┐
│  Claude Code        │         │  go-between script   │         │  Indigo web  │
│  (you, chatting)    │ ───────►│  (installed for you) │ ───────►│  server +    │
│                     │         │  adds your access    │         │  this plugin │
│                     │         │  key automatically   │         │  (70 tools)  │
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

### 3.4.0 (2026-09-25)
Claude Bridge now keeps a permanent record of every change made through it: each call that needs the write or admin scope, whether it worked, failed or was refused.

- **What each entry says.** When, which access key (by its name from `scopes.json`, never the key itself), the tool, its arguments including the full Python or script it ran, what happened, and how long it took. A background run that outlives its call gets a second entry when it finishes. The tool's reply is never kept.
- **Secrets are blanked first.** An argument named like a credential, such as a lock's `pin`, is replaced outright, and every credential value Claude Bridge knows about is blanked wherever it appears, inside Python too. If those values cannot be read, the entry leaves the arguments out rather than write them unredacted.
- **Where it lives.** One file a month in the plugin's folder under Indigo's `Preferences/Plugins`, readable only by the Mac user that runs Indigo. Nothing deletes it. Writing happens on a thread of its own, so it never slows a reply.
- **Reading it.** Plugins > Claude Bridge > Print Recent Changes puts the last 20 in the event log as plain lines. The new `change_log` tool lets Claude search it by time, tool, key or outcome. It is a read tool, and a key without admin sees it with credential values blanked.

The Security page describes it in full. 70 tools now, 29 of them read-only.

### 3.3.1 (2026-09-25)
Every new Claude session left an error in the Indigo log. Since 3.3.0 the plugin answers a notification with an empty 202 reply, as the MCP rules ask, but Indigo's web server refuses an empty reply from a plugin: it logged `internal server error` for `/mcp/` and sent the client a 500 instead. Nothing stopped working, because the go-between script ignores the answer to a notification. The reply now carries a single space, which the web server passes through and every MCP client ignores.

### 3.3.0 (2026-09-25)
A security review of 3.2, and every finding it confirmed is fixed. The first four change what a key may do.

- **A read-only key can no longer read the admin key.** The go-between script the plugin puts in Indigo's `Scripts` folder holds the web server's access key, and `read_script` could read it. No script tool will now read, list, change or run that file, whatever the key. For a key without admin, scripts, the scripts inside automations and the event log also come back with every known password and key blanked out.
- **Sending e-mail needs an admin key.** It can go to any address, so it counts as data leaving the house. Pushover notifications, which only reach your own devices, still need write.
- **Zeroing an energy total needs an admin key**, because the old figure cannot be put back. `device_control` itself is still a write tool.
- **Z-Wave exclusion is behind the delete switch.** `zwave` with `enter_exclusion` removes the next device whose button is pressed from the network, so it now needs `confirm=true` and *Allow Claude to delete devices, variables and automations* switched on, like a delete.
- **A plugin action cannot hold up the web server.** `execute_device_action` stops waiting after 20 seconds and says the action may still be running. It also refuses Claude Bridge's own actions.
- **The rate limits shown are the ones applied.** Limits count per access key, and an admin key gets ten times the figures. Without a `scopes.json` every key is admin, so a stock install allows 1,200 calls a minute and 50,000 a day, not the 120 and 5,000 on show. The limits themselves have not changed; Configure and `/health` now say what they are, and `/health` shows each key its own.
- **`/health` shows key names, scopes and recent calls to admin keys only.** Other keys get the basic status. Without a `scopes.json` every key is admin, so nothing changes there.
- **The connection follows the MCP rules.** An unknown session gets HTTP 404, a missing one 400, and a notification 202 with no body, where all three got 200 before. The go-between script (now 1.8) copes with each of these and starts a fresh session by itself, including after a plugin restart. A request from a web page on another site is refused with 403.
- **The go-between script finds the web server.** It used to assume `http://localhost:8176`. It now uses the address Indigo reports, so HTTPS and another port work.
- **Smaller fixes.** Trigger and schedule lists are no longer cached, so a change made in Indigo shows at once, and the home audit sees an automation enabled or disabled straight away. A webhook whose first address does not answer tries the next. Asking for a prompt without a detail it needs is refused by name instead of filled with a placeholder.
- **The documentation is honest about keys.** A write key can run any action group, trigger or schedule, including ones that unlock doors or run scripts, so give a phone a read key. The Security page lists everything a read key can see.

89 new tests, 1,520 in all.

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

Claude Bridge gives Claude Code **70 MCP tools**, enough to read and change anything on a running
Indigo server: **29 read** tools (pure queries), **20 write** tools (they change Indigo state) and
**21 admin** tools (deletes, code execution, plugin lifecycle, physical security, e-mail). By area:

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
- **The work stays local.** Searching and control all happen on your own
  Mac. What leaves it is your conversation with Claude, and anything you ask
  Claude to send out: an e-mail (admin keys only), a Pushover notification to
  your own devices, and event webhooks, which are off until you turn them on
  and can only reach the addresses you allow.
- **No extra doors into your network.** Everything travels through Indigo's
  own web server on its existing port, protected by Indigo's own access key,
  and the Reflector gives you secure remote access for free.
- **Permission levels.** Every tool is classed as read, write, or admin. A
  read-only key really is read-only. Deleting things, running code, locking
  and unlocking, sending e-mail, zeroing an energy total and the other things
  that cannot be taken back need the admin level. Anything not explicitly
  classified is locked down, not waved through. But a **write** key can run
  any action group and fire any trigger or schedule, and those run whatever
  they contain, including unlocking a door or an embedded script, so give a
  phone a read key. The [Security](https://highsteads.github.io/ClaudeBridge/security.html)
  page has the detail.
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
5. **Restart Claude Code** — you should see 70 `indigo-mcp` tools available

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
