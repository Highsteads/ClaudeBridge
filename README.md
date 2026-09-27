# Claude Bridge for Indigo

**Ask Claude about your Indigo house in plain English, and have it check, switch and fix things for you.**

**Version:** 3.6.0
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

### 3.6.0 (2026-09-27)
The descriptions Claude reads to learn each tool are written without semicolons now.

- **Plainer tool descriptions.** The descriptions of twenty-one tools, `device_history`, `device_control`, `thermostat_control`, `restart_plugin` and `zwave` among them, had twenty-six semicolons between them. They are now full stops, commas or "and". Nothing about what a tool does or needs has changed, and the [Tool reference](https://highsteads.github.io/ClaudeBridge/tools.html), which is built from the same descriptions, reads the same way.

Still 71 tools, 30 of them read-only.

### 3.5.0 (2026-09-25)
Long lists now come a page at a time, and a new tool reads a variable's history.

- **Paging.** `list_devices` with no filter used to send every device in full, 245 KB on a house of 210 devices. It now sends 50 at a time. `list_devices`, `list_variables`, `list_triggers`, `list_schedules` and `list_action_groups` all sort by name, take `limit` and `offset`, and say how many there are in total and where the next page starts (`next_offset`, empty on the last page). With a filter, and for the other four lists, a page is 200, so on most houses they still arrive in one go. `list_devices` now also accepts `limit` without a filter, where it used to refuse it.
- **`variable_history`.** A variable's history from the SQL Logger, by id or name. The logger writes a row only when the value changes, so the reply also says what the value was when the window opened. With `summary=true` it says how many times the value changed and how long each value held (the way to answer "how long was the heating on today"), with a time-weighted average for a number. A deleted variable's history can still be read by its old id. It reads the database the same careful way `device_history` does, by id range, never scanning a whole table.

71 tools now, 30 of them read-only.

### 3.4.0 (2026-09-25)
Claude Bridge now keeps a permanent record of every change made through it: each call that needs the write or admin scope, whether it worked, failed or was refused.

- **What each entry says.** When, which access key (by its name from `scopes.json`, never the key itself), the tool, its arguments including the full Python or script it ran, what happened, and how long it took. A background run that outlives its call gets a second entry when it finishes. The tool's reply is never kept.
- **Secrets are blanked first.** An argument named like a credential, such as a lock's `pin`, is replaced outright, and every credential value Claude Bridge knows about is blanked wherever it appears, inside Python too. If those values cannot be read, the entry leaves the arguments out rather than write them unredacted.
- **Where it lives.** One file a month in the plugin's folder under Indigo's `Preferences/Plugins`, readable only by the Mac user that runs Indigo. Nothing deletes it. Writing happens on a thread of its own, so it never slows a reply.
- **Reading it.** Plugins > Claude Bridge > Print Recent Changes puts the last 20 in the event log as plain lines. The new `change_log` tool lets Claude search it by time, tool, key or outcome. It is a read tool, and a key without admin sees it with credential values blanked.

The Security page describes it in full. 70 tools now, 29 of them read-only.

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
