---
title: Home
nav_order: 1
---

# Claude Bridge for Indigo

This plugin lets [Claude](https://www.anthropic.com/claude), Anthropic's AI assistant, see and control your [Indigo](https://www.indigodomo.com) system from an ordinary conversation — your devices, your variables, your triggers and schedules, your scripts and your event log, as they are right now.

Once it is installed you just ask. "Which lights are on?" "Turn the fan on for ten minutes." "Why didn't the bathroom light go off last night?" Claude looks at your system, does what you asked, and reads the result back to check it worked.

Everything goes through Indigo's own web server, behind the access key Indigo already uses, so the plugin opens nothing new on your network. The plugin itself needs no API key and no extra software, and there is no second bill, because Claude runs on your own Claude account.

## What it does for you

- **Answers questions about your house** from the real, live state of every device, variable, trigger, schedule and action group, and from the event log, including entries older than the Indigo window shows.
- **Controls your devices** — on, off, brightness, colour, thermostats, fans, sprinklers and locks — by name or by id, and can switch something on for a set time and off again.
- **Writes and fixes scripts and plugins with you**, saving a backup of a script before every change, then running it and reading the event log to see whether it worked.
- **Finds what depends on what** — every trigger, schedule and action group that uses a device or variable — before you change or delete it.
- **Checks the health of the whole system** — devices in error, low batteries, devices that have gone quiet, plugins with updates waiting.
- **Keeps a record of every change** it makes, which you can print from the Plugins menu at any time.
- **Keeps each client to what you allow** — every one of its **71 tools** is marked read, write or admin, and you can give a phone a read-only key.

## Where to go next

| If you want to... | Read |
|---|---|
| Install the plugin and connect Claude | [Getting started](getting-started.md) |
| Know what Claude can see and do in your house | [What it does](what-it-does.md) |
| See how a real session with Claude goes | [Working with Claude](working-with-claude.md) |
| Understand what the plugin is doing behind the scenes | [How it works](how-it-works.md) |
| Use the Claude Bridge device or run a trigger from Claude | [The device and the trigger](devices-and-triggers.md) |
| Know what every setting does | [Settings](configuration.md) |
| Know what each item in the Plugins menu does | [The plugin menu](plugin-menu.md) |
| Sort out a problem | [When something goes wrong](troubleshooting.md) |
| See what changed in each version | [Version history](changelog.md) |
| Read the full tool list, the security detail or the developer notes | [Technical notes](technical-notes.md) |

## Built with the thing it describes

Every version of Claude Bridge came out of a conversation with Claude — described in plain English, written by Claude, and tested by Claude against my own Indigo server, using the previous version of this plugin to see and act. The other plugins on the same GitHub account were built the same way.

If you have never done anything like this, the Dashboards plugin's [Start with nothing but Claude](https://highsteads.github.io/Dashboards/no-coding-needed.html) takes a complete beginner from a bare Mac to a working setup, and Claude Bridge is one of the steps.

## Download

The latest version is always on the [Releases page](https://github.com/Highsteads/ClaudeBridge/releases/latest).
