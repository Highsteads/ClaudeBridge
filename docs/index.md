---
title: Home
nav_order: 1
---

# Claude Bridge

**Claude Bridge** is an [Indigo](https://www.indigodomo.com) home automation plugin that lets [Claude](https://www.anthropic.com/claude) see and control your Indigo system — your own devices, your own variables, your own event log — from an ordinary conversation.

Once it's installed you just ask. "Which lights are on?" "Turn the fan on for ten minutes." "Why didn't the bathroom light go off last night?" Claude looks at your system, does the thing, and checks its own work — no scripting, no copying device IDs about, no screenshots.


*Developed and tested on Indigo 2025.2. Older Indigo releases back to 2023.2 should also work.*


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

## Start here

| | |
|---|---|
| **[Getting started](getting-started.md)** | What you need, what it costs, the one-command install, and connecting Claude Code |
| **[What it does](what-it-does.md)** | The 168 tools by what they let Claude do — devices, heating, energy, scripts, the event log, webhooks, memory, audits |
| **[Working with Claude](working-with-claude.md)** | How a session goes: a script in one prompt, a plugin from a description, a bug found by reading the log. And the honest limits |
| **[Tool reference](tools.md)** | Every tool by name, grouped by the permission it needs. Generated from the code, checked on every push |
| **[Configuration](configuration.md)** | The Configure dialog, credentials, per-token scopes, the menu items |
| **[Security](security.md)** | Read, write and admin; the delete switch; the webhook firewall; what a read-only key can see |
| **[Letting your plugin add tools](providers.md)** | The manifest, the hidden action and the broadcast — three things and your plugin is a provider |
| **[How it is built](architecture.md)** | The transport, the go-between script, the package layout, the tests |
| **[Troubleshooting](troubleshooting.md)** | The errors people actually see, and what each one means |
| **[Version history](changelog.md)** | Every release, newest first |

Download the plugin from the [Releases page](https://github.com/Highsteads/ClaudeBridge/releases);
the source is on [GitHub](https://github.com/Highsteads/ClaudeBridge).

## Built by the thing it describes

Every version of Claude Bridge came out of a conversation with Claude — described in plain English,
written by Claude, and tested by Claude against a live Indigo server, using the previous version of
this very plugin to see and act. The twenty-odd other plugins on the same GitHub account were built
the same way, with Claude Bridge as the feedback loop. So nothing on this site is speculation about
what you could do with it. It is a description of how the thing you are reading about came to exist.

If you have never done anything like this, the Dashboards plugin's
[Start with nothing but Claude](https://highsteads.github.io/Dashboards/no-coding-needed.html) walks
a complete beginner from a bare Mac to a working setup, and Claude Bridge is one of the steps.
