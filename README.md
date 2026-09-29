# Claude Bridge for Indigo

**Ask Claude about your Indigo house in plain English, and have it check, switch and fix things for you.**

**Version:** 3.7.0
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

### 3.7.0 (2026-09-29)
Claude Bridge now speaks the newest version of the protocol Claude uses to talk to it, as well as the one before.

- **MCP 2026-07-28.** The newest version has no opening handshake and no session: every request says which version it speaks and what the client can do. Claude Bridge answers those requests as the new version requires, and still answers the older kind exactly as before, so every existing setup carries on unchanged. A client asks first with `server/discover` and is told both versions, what Claude Bridge offers, and its name and version.
- **Tested with Claude Code itself.** Pointed at Claude Bridge over HTTP, Claude Code 2.1.284 chose the new version and used tools, prompts and resources with it. Through the go-between script it still chose the older one on the day, which is Claude Code's decision. The script is ready for the day that changes.
- **What a new-version client is told when something is wrong.** A version Claude Bridge does not speak comes back with the versions it does, a request missing what the new version requires says so, and a tool call refused by the rate limit, the access key or the delete gate comes back as a tool result marked as an error, so Claude can read why. The [technical notes](https://highsteads.github.io/ClaudeBridge/architecture.html#two-versions-of-the-protocol) list every case.
- **Plugin Health** now lists the protocol versions and, because new-version clients have no session to count, each one by the name it gives.
- **The go-between script is version 1.9.** It adds the headers the new version needs, sends no session with it, and hands Claude Code the real error codes rather than a general one.

Still 71 tools, 30 of them read-only.

### 3.6.1 (2026-09-29)
One fewer warning in the Indigo event log every time a Claude session starts.

- **Claude Code's new first question gets a plain answer.** Newer Claude Code asks every server `server/discover` before it does anything else, a question from the next version of the protocol that Claude Bridge does not speak yet. Claude Bridge turned it away as a request with no session, and Indigo's web server logged `HTTP 400 error for request /message/com.clives.indigoplugin.claudebridge/mcp/` for it, about a dozen times a day here. It now answers "Method not found", the reply that tells Claude Code to carry on the usual way. Nothing else changes: Claude connected fine before and connects the same way now.

Still 71 tools, 30 of them read-only.

### 3.6.0 (2026-09-27)
The descriptions Claude reads to learn each tool are written without semicolons now.

- **Plainer tool descriptions.** The descriptions of twenty-one tools, `device_history`, `device_control`, `thermostat_control`, `restart_plugin` and `zwave` among them, had twenty-six semicolons between them. They are now full stops, commas or "and". Nothing about what a tool does or needs has changed, and the [Tool reference](https://highsteads.github.io/ClaudeBridge/tools.html), which is built from the same descriptions, reads the same way.

Still 71 tools, 30 of them read-only.

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
