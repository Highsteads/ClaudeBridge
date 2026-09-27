---
title: How it works
nav_order: 5
---

# How it works

None of this is needed to use the plugin. It is here for anyone who wants to know what goes on when they ask Claude a question about the house.

## Three pieces, all on your Mac

```
┌─────────────────────┐         ┌──────────────────────┐         ┌──────────────┐
│  Claude Code        │         │  go-between script   │         │  Indigo web  │
│  (you, chatting)    │ ───────►│  (installed for you) │ ───────►│  server +    │
│                     │         │  adds your access    │         │  this plugin │
│                     │         │  key automatically   │         │  (71 tools)  │
└─────────────────────┘         └──────────────────────┘         └──────────────┘
```

1. **Claude Code** is where you type. When Claude wants to look at something or change something, it picks one of the plugin's tools — "list the devices", "switch this on", "read the event log" — and asks for it.
2. **The go-between script**, `indigo_mcp_proxy.py`, is a small program Claude Code starts for itself. It adds your Indigo access key to each request and passes it to Indigo's web server. If Indigo restarts, or the connection sits idle, it reconnects without Claude noticing.
3. **The plugin** answers inside Indigo, through Indigo's own web server on its usual port. The web server checks the access key before the plugin sees anything.

So the plugin opens no new door on your network. The work happens on your own Mac. What leaves it is your conversation with Claude, which goes to Anthropic like any other Claude conversation, and anything you ask Claude to send out: an e-mail, a Pushover notification to your own devices, or an event webhook if you have turned those on.

## Read, write and admin

Every one of the plugin's tools is marked as one of three kinds:

- **Read** tools only look. They list, search and report, and change nothing.
- **Write** tools change things in the house: switch devices, set variables and thermostats, run action groups, fire triggers, enable and disable automations.
- **Admin** tools do things that cannot be taken back, or that reach outside the house: deleting, writing and running scripts and Python code, locking and unlocking doors, restarting plugins, sending e-mail, event webhooks and changing the Z-Wave network.

Out of the box, every access key may use all three. You can change that with a small settings file, `scopes.json`, which gives each key its own kinds — for example everything for Claude Code on your Mac and read-only for a phone. The [Settings](configuration.md#giving-each-key-its-own-permissions) page shows how.

A write key can run any action group and fire any trigger, and those do whatever they contain — including unlocking a door, if one of yours does that. So give a phone, a tablet or anything you would not trust with the front door a read key. The [Security](security.md) page has the full detail.

## Deleting needs two yeses

Claude cannot delete a device, variable, trigger, schedule, action group or folder unless **Allow Claude to delete devices, variables and automations** is ticked in the plugin's settings, and each request also says in so many words that the delete is meant. The setting is off when you install the plugin. Putting the Z-Wave network into exclusion mode, which removes the next device whose button is pressed, needs the same two yeses. Deleting a script is different: it moves the script to a `_backups/_archived` folder inside your scripts folder, so you can get it back.

## Every change is written down

The plugin keeps a permanent record of every request that needs a write or admin key, whether it worked, failed or was refused: when, which key (by the name you gave it, never the key itself), what was asked for, what happened and how long it took. Passwords and keys are blanked out before anything is written. **Plugins → Claude Bridge → Print Recent Changes** shows the last 20, and Claude can search the whole record. Nothing deletes it.

## Keeping answers quick

- **Recent answers are kept for a short while.** When Claude asks the same question twice within a minute, the plugin answers from memory. When something changes — through Claude or in Indigo — it drops the answers that change affects, so Claude does not see an out-of-date state. **Read-cache TTL** in the settings sets the minute.
- **Search uses its own index** of every device, variable and action group. Adding, removing, renaming or moving one is picked up by the next search, and the whole index is rebuilt every five minutes. The states a search shows can be up to five minutes old, so Claude asks for the device itself when it needs a live reading.
- **Long script runs carry on in the background.** A script, or a block of Python, that takes longer than a few seconds keeps running while Claude gets a ticket to collect the result with. The web server is never held up waiting for it, so your control pages and dashboards carry on working. A finished result is kept for ten minutes.
- **Each key has a limit** — 120 requests a minute and 5,000 a day, ten times that for a key with admin, which means every key when there is no `scopes.json`.

## Tools from other plugins

Any Indigo plugin can add tools of its own to Claude Bridge. The plugin finds them by itself when that plugin starts, and lists them to Claude under that plugin's name, so the Dashboards plugin's tools appear as `dashboards_get_status` and so on. **Allow plugin-provided tools to make changes** in the settings decides whether those tools may change anything. Their read tools always work. Plugin authors will find the details under [Letting your plugin add tools](providers.md).

## Event webhooks

If you turn them on, event webhooks let Indigo send a signed message to a web address you run the moment something happens — a leak sensor trips, a battery drops below a level, the garage has been open for ten minutes. They are off when you install the plugin, and even when on they can only reach the addresses you list in the settings. The [Security](security.md#event-webhooks--the-outbound-firewall) page describes the safeguards.
