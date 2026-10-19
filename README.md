# Claude Bridge for Indigo

**Ask Claude about your Indigo house in plain English, and have it check, switch and fix things for you.**

**Version:** 3.8.2
| **Author:** CliveS & Claude | **Needs:** Indigo 2023.2 or later, Claude Code and a paid Claude account

**[Read the full guide](https://highsteads.github.io/ClaudeBridge/)** — setting up, what everything means, and what to do when something goes wrong.

---

## What it does

This plugin lets [Claude](https://www.anthropic.com/claude), Anthropic's AI assistant, see and control your [Indigo](https://www.indigodomo.com) system from an ordinary conversation. You ask "which lights are on?", "turn the fan on for ten minutes" or "why didn't the bathroom light go off last night?", and Claude looks at the real state of your house, does what you asked, and reads the result back to check it worked. It gives Claude **71 tools** to do that with.

- **Answers questions about your house** from the live state of every device, variable, trigger, schedule and action group, and from the event log, including entries older than the Indigo window shows.
- **Controls your devices** — on, off, brightness, colour, thermostats, fans, sprinklers and locks — by name, and can switch something on for a set time and off again.
- **Writes and fixes scripts and plugins with you**, saving a backup of a script before every change, then running it and reading the event log to see whether it worked.
- **Finds what depends on what**, so you know which triggers, schedules and action groups use a device or variable before you change or delete it.
- **Checks the health of the system** — devices in error, low batteries, devices that have gone quiet, plugins with an update waiting.
- **Keeps a record of every change** made through it, which you can print from the Plugins menu.
- **Keeps each client to what you allow.** Every tool is marked read, write or admin, deleting needs a setting you switch on, and you can give a phone a read-only key.

Everything goes through Indigo's own web server, behind the access key Indigo already uses, so nothing new is opened on your network. The plugin needs no API key and no extra Python packages.

## What it works with

| You need | Notes |
|---|---|
| **Indigo 2023.2 or later** | I develop and test it on Indigo 2025.2. |
| **[Claude Code](https://claude.ai/download)** | Anthropic's app for working with Claude on a Mac, on the Mac that runs Indigo. The plugin sets it up for you. The Claude desktop app can connect too — the guide shows how. |
| **A paid Claude account** | Claude Code needs one, usually a Claude Pro or Max subscription from [claude.ai](https://claude.ai). If you already have one, there is nothing more to pay. |

Other plugins can add tools of their own to Claude Bridge — my [Dashboards](https://github.com/Highsteads/Dashboards) plugin does, for example.

## Installing

1. Go to the [Releases page](https://github.com/Highsteads/ClaudeBridge/releases/latest) and download `Claude.Bridge.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Claude Bridge.indigoPlugin`
3. Double-click `Claude Bridge.indigoPlugin` — Indigo will install it automatically

## Setting it up

1. When Indigo asks whether to enable the plugin, say yes. The plugin creates a **Claude Bridge** device, and sets Claude Code up to use it.
2. Check the Indigo Event Log says **Claude Code integration configured**. If it says **No bearer token available** instead, Indigo has no access key yet, and the [Getting started](https://highsteads.github.io/ClaudeBridge/getting-started.html) page shows how to make one.
3. Quit and restart Claude Code, type `/mcp`, and check **indigo-mcp** is listed as connected. Then ask it "which lights are on?"

The [full guide](https://highsteads.github.io/ClaudeBridge/) goes through each step, explains every setting and menu item, and covers what to do if something does not work.

## What's new

The three most recent releases, word for word. Every release before these is in
**[the version history](https://highsteads.github.io/ClaudeBridge/changelog.html)**.

### 3.8.2 (2026-10-19)
`device_history` and `variable_history` no longer give a wrong answer when the SQL Logger uses PostgreSQL.

- **A PostgreSQL SQL Logger now gets an error, not an empty answer.** The two tools read only the SQLite database. After a switch to PostgreSQL the old `indigo_history.sqlite` stays in the Logs folder, and the tools read that: they said "success" with no rows, so Claude took a device that had been changing for days to be still. The plugin now reads the SQL Logger's database type first, and when it is not SQLite it says so and reads nothing. The PostgreSQL password in those settings is never read or shown.
- **Every answer now says when the history file was last written** (`db_last_written`), and warns (`db_stale`) when that was more than an hour ago, so an empty window cannot pass for "nothing changed".

Still 71 tools, 30 of them read-only.

### 3.8.1 (2026-10-05)
Setting a thermostat's mode works again.

- **`thermostat_control` with `hvac_mode` never worked.** Every call failed, whatever mode you asked for, because the list of modes named `ProgramAuto`, which Indigo does not have. Indigo's mode for a programme that both heats and cools is `ProgramHeatCool`. Claude Bridge now sends that. You can ask for it as `programHeatCool`, and `programAuto` still works as another name for it.
- **A new check for this whole kind of slip.** A test now reads every `indigo.` name the plugin uses and fails if Indigo 2025.2 does not have it. It found this one, and nothing else.

Still 71 tools, 30 of them read-only.

### 3.8.0 (2026-09-29)
Claude Code can now connect straight to Indigo over HTTP, and so use the newest version of the protocol today.

- **A new setting, Connect Claude Code.** Through the go-between script, as before, or straight to Indigo over HTTP. Claude Code only uses the newest protocol over HTTP for now, so this is the way to have it. The script stays the default because it works with every Claude Code and waits for Indigo after the Mac restarts. Over HTTP, a Claude Code that starts first shows Indigo as failed until you reconnect it with `/mcp`.
- **Your access key stays out of Claude Code's settings.** Over HTTP, Claude Code runs the go-between script with `--headers` each time it connects, and the script hands it the key. The key stays in that one file, which only your account can read.
- **The setting applies when you click Save.** The plugin rewrites `.mcp.json` in your home folder at once, rather than at its next start. **Print MCP Client Connection Information** now ends with the two Terminal lines that change Claude Code's own list, which every other folder uses, to match.
- **The go-between script is version 1.10.**

Still 71 tools, 30 of them read-only.

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
