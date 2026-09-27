---
title: The plugin menu
nav_order: 8
---

# The plugin menu

Everything below is under **Plugins → Claude Bridge** in Indigo. Each item writes its answer to the Indigo Event Log, unless it says otherwise.

## Connecting

| Menu item | What it does |
|---|---|
| **Print MCP Client Connection Information** | Writes ready-made settings for the Claude desktop app, three ways: through your Indigo Reflector for use away from home, and on your home network over `https` or plain `http`. It also says where Indigo keeps its local secrets file. The addresses the plugin answers on are logged every time it starts, too. |

## Checking on the plugin

| Menu item | What it does |
|---|---|
| **Print Plugin Health (uptime / sessions / tool latencies)** | How long the plugin has been running, how many Claude sessions are connected, how long each tool takes to answer, and the request limits each access key is held to. |
| **Print Tool Explorer URL** | The web address of a page that lists every tool and what each one takes. Open it in any web browser. It asks for your Indigo login or access key, like any other page from Indigo's web server. |

## Permissions and the change record

| Menu item | What it does |
|---|---|
| **Create Starter scopes.json (per-token Read/Write/Admin)** | Writes a starter `scopes.json`, the file that gives each access key its own permissions, and says where it is. If you already have one, it tells you where and leaves it alone. The [Settings](configuration.md#giving-each-key-its-own-permissions) page explains how to fill it in. |
| **Reload scopes.json** | Reads `scopes.json` again after you have edited it, and says how many keys it names. No restart is needed. |
| **Print Recent Changes** | The last 20 changes made through Claude, newest first — when, which key by name, what was asked for and what happened — and the folder where the whole record is kept. |
| **Clear Read-Cache** | Forgets every answer the plugin is holding on to, so the next question is answered fresh. You rarely need it, because the plugin drops an answer as soon as something it depends on changes. |

## Event webhooks

| Menu item | What it does |
|---|---|
| **Print Event Webhook Subscriptions** | Every webhook, with what it watches, where it sends, whether it is switched on, how many messages it has sent and its last error. It never shows the signing key. |
| **Re-enable Quarantined Event Webhooks** | A webhook whose receiver fails five times in a row is switched off, so it does not keep retrying. Once the receiver is working again, this switches those webhooks back on. |
| **Clear All Event Webhook Subscriptions** | Deletes every webhook. It cannot be undone. |

## Tools from other plugins

| Menu item | What it does |
|---|---|
| **Print Plugin-Provided MCP Tools** | Every installed plugin that adds tools of its own, the tools it adds, and whether those tools are allowed to make changes. |
| **Rescan Plugin-Provided MCP Tools** | Looks for other plugins' tools again, straight away. A Claude session that is already open sees a new tool only when you start a new session. |

## Log and support

| Menu item | What it does |
|---|---|
| **Toggle Timestamps in Log (on/off)** | Turns on or off the time, to the thousandth of a second, at the start of each of the plugin's lines in the Event Log. It is on when you install the plugin, and the plugin remembers your choice. |
| **Show Plugin Info** | The plugin's version, Indigo's version, the macOS version, the Mac's processor type, the Python version, the plugin's local address, how many tools it has, where `scopes.json` lives, and whether timestamps are on. Paste this into any [issue](https://github.com/Highsteads/ClaudeBridge/issues) you open. |

## Indigo's own items

**Configure** opens the plugin's settings, which the [Settings](configuration.md) page explains. **Reload** restarts the plugin. Use **Reload** when you want to restart Claude Bridge — a request from Claude to restart it is refused, because the plugin cannot restart itself while it is still answering that request.
