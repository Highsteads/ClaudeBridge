# Claude Bridge for Indigo

**Ask Claude about your Indigo house in plain English, and have it check, switch and fix things for you.**

**Version:** 3.10.0
| **Author:** CliveS & Claude | **Needs:** Indigo 2023.2 or later, Claude Code and a paid Claude account

**[Read the full guide](https://highsteads.github.io/ClaudeBridge/)** — setting up, what everything means, and what to do when something goes wrong.

---

## What it does

This plugin lets [Claude](https://www.anthropic.com/claude), Anthropic's AI assistant, see and control your [Indigo](https://www.indigodomo.com) system from an ordinary conversation. You ask "which lights are on?", "turn the fan on for ten minutes" or "why didn't the bathroom light go off last night?", and Claude looks at the real state of your house, does what you asked, and reads the result back to check it worked. It gives Claude **73 tools** to do that with.

- **Answers questions about your house** from the live state of every device, variable, trigger, schedule and action group, and from the event log, including entries older than the Indigo window shows.
- **Controls your devices** — on, off, brightness, colour, thermostats, fans, sprinklers and locks — by name, and can switch something on for a set time and off again.
- **Writes and fixes scripts and plugins with you**, saving a backup of a script before every change, then running it and reading the event log to see whether it worked.
- **Finds what depends on what**, so you know which triggers, schedules and action groups use a device or variable before you change or delete it.
- **Tells you what switches a device and when**, and, for each time it changed in the last fortnight, what most likely did it.
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

### 3.10.0 (2026-11-21)
Two new tools answer "what turns this on?" and "what did turn it on, and when?" in one call each.

- **`who_controls` lists everything that can change a device.** Every schedule, trigger and action group that acts on it, directly or through action groups that run other action groups, each with when it fires (a schedule's time and next run, a trigger's event), its conditions, whether it is enabled, and what it does to the device, such as "turn off after 120 seconds". It also looks where no lookup did before: control page buttons that act on the device, script files that mention it together with the schedules that run them as linked scripts, other devices whose settings hold its id (a group or a watchdog, say), and plugin settings files that hold it. What only watches the device, or checks it in a condition, is listed apart. Anything found by matching the id or name as text is marked heuristic.
- **`explain_device_changes` gives each change its likely cause.** It reads up to a fortnight of the event log for one device, lists each change with its day and what happened, names the trigger, schedule or action group most likely behind it, and sums them up by cause with the times. Only an automation linked to the device is named as a cause, never one that merely ran nearby. Where the automation is set to stay out of the event log, a script's own line naming the device counts as the evidence, and the reply names the hidden automations that could have run it. A change with neither is counted as manual or outside Indigo. `between` ("19:30-20:30", which may cross midnight) and `contains` ("on", "off") narrow it down, and the paired "sent" and "received" lines of one change count once.
- **Devices whose plugin never logs them by name still work.** When the event log has no change lines for a device, `explain_device_changes` reads its on/off and brightness from the SQL Logger history instead, and says so.
- **What neither can see is said in the reply**: a plugin that keeps the id in its own code, HomeKit, Alexa, Apple Shortcuts, apps and the switch on the wall.

Now 73 tools, 32 of them read-only.

### 3.9.2 (2026-11-20)
`zwave` now reads what Indigo really answers, and says plainly when Z-Wave is turned off.

- **A waited configuration set reports its acknowledgement.** With `wait_for_ack` on, `zwave(action="set_config_parameter")` looked for a `Success` flag, but Indigo answers a waited set with `cmdSuccess`, `endpoint`, `nodeId` and `queuedForNextWake` (measured against a real Z-Wave stick), so the tool reported "Indigo returned no acknowledgement flag". It now reads `cmdSuccess` and passes Indigo's own reply back in `detail`. If Indigo reports a set as queued for a sleeping device's next wake (`queuedForNextWake`, not yet seen on a real device), the tool says `queued`. A `Success` reply is still read, and that is what Indigo answers for a ping.
- **Z-Wave turned off is a refusal, not a red Error.** With Interfaces > Z-Wave turned off, Indigo refused each call we measured (a configuration set, a raw send, and the calls behind `stop_optimize` and `exit_inclusion_exclusion`) with an `InterfaceError` "interface Z-Wave is not enabled", and sent nothing. Claude Bridge logged that as an Error and passed back Indigo's bare words. Now any tool that meets exactly that error says the interface is turned off and where to turn it back on, carries `refused`, and logs a warning. Only `set_config_parameter`, `stop_optimize` and `exit_inclusion_exclusion` also say nothing was sent, as the others were not measured. Any other `InterfaceError`, a database one included, is still an Error.

Still 71 tools, 30 of them read-only.

### 3.9.1 (2026-10-19)
`device_history` and `variable_history` now read the SQLite file you chose.

- **A custom SQLite file is followed.** If you set the SQL Logger's **SQLite file** to another name, or to a full path, the tools still read `Logs/indigo_history.sqlite`. They now work out the file the way the logger does: a name is a file in the Logs folder, and a path that starts with `/` is used as it stands. Thanks to Jon for spotting it.

Still 71 tools, 30 of them read-only.

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
