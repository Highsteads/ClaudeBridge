---
title: When something goes wrong
nav_order: 9
---

# When something goes wrong

Start with the Indigo Event Log. The plugin says there what it did at startup and why it refused anything. **Plugins → Claude Bridge → Show Plugin Info** and **Print Plugin Health** add the details worth pasting into an [issue](https://github.com/Highsteads/ClaudeBridge/issues).

## Connecting

| What you see | What it means | What to do |
|---|---|---|
| Claude Code says **Could not attach to MCP server indigo-mcp** | Claude Code started the go-between script, but it could not reach the plugin. | Check **Plugins → Manage Plugins** shows Claude Bridge enabled, and that the **Claude Bridge** device says **Running**. Then quit and restart Claude Code. After the Mac restarts, the script waits up to 45 seconds for Indigo's web server, so if Claude Code opened before Indigo was ready, restarting Claude Code is enough. |
| **indigo-mcp** is not listed at all when you type `/mcp` | Claude Code has not been told about the plugin, or has not re-read its settings. | Restart Claude Code. If it is still missing, check the Event Log for **Claude Code integration configured** or **already up to date**, and that **Auto-configure Claude Code** is ticked in the settings. If you start Claude Code from a folder other than your home folder, add it for every folder with the command under [Setting Claude Code up by hand](getting-started.md#setting-claude-code-up-by-hand). |
| The Event Log says **No bearer token available to patch into the MCP proxy** | Indigo has no local secret, and the credentials file has no `CLAUDEBRIDGE_BEARER_TOKEN`, so there is no key to give Claude Code. | Follow step 3 of [Getting started](getting-started.md#3-make-sure-indigo-has-an-access-key). |
| **401 Unauthorized** | Indigo's web server did not accept the key in the go-between script. | If you changed `secrets.json`, restart the Indigo Server so the web server reads it, which also restarts the plugin and writes the new key into the script. If you set Claude Code up by hand, check the key on the `BEARER_TOKEN` line of your copy of the script. |
| **Unsupported protocol version** | Claude Code is still running an old copy of the go-between script. | Quit and restart Claude Code. |
| The Event Log warns **Could not update ~/.mcp.json** or **Could not update ~/.claude/settings.json** | The plugin could not write to Claude Code's settings files, usually because of their permissions. The plugin itself is running. | Fix the file's permissions and use **Plugins → Claude Bridge → Reload**, or [set Claude Code up by hand](getting-started.md#setting-claude-code-up-by-hand). |

## The plugin

| What you see | What it means | What to do |
|---|---|---|
| The **Claude Bridge** device says **Unavailable** | The plugin started, but its server part could not. The Event Log has an error starting **MCP handler initialization failed** with the reason. | Use **Plugins → Claude Bridge → Reload**. If it happens again, open an issue with that error and the output of **Show Plugin Info**. |
| Claude says it cannot restart Claude Bridge | That is deliberate. The plugin cannot restart itself while it is still answering the request that asked it to. | Use **Plugins → Claude Bridge → Reload**. Claude can restart any other plugin. |
| New tools you read about in a newer version do not appear | Claude Code reads the list of tools only when it starts. | Restart Claude Code once after updating the plugin. A fix to an existing tool needs no restart of Claude Code. |
| A device control fails with **expected number** | Claude Code is working from an old list of tools. | Restart Claude Code. |
| A folder called `Packages` inside the plugin, left from an older version | Versions before 3.0 installed extra Python packages. Nothing uses them now. | Leave it, or delete `Contents/Packages` inside the plugin while the plugin is stopped. |

## Asking Claude to do things

| What you see | What it means | What to do |
|---|---|---|
| A search finds nothing | The search matches words in names. | Use a simple word from the name, such as "conservatory" or "lamp". A device renamed a moment ago is found under its new name at the next search. |
| A search shows an out-of-date state | Search results can be up to five minutes old. | Ask for the device itself, which is always read live. |
| A delete is refused | **Allow Claude to delete devices, variables and automations** is off, which is how it starts. | Tick it in the [settings](configuration.md#deleting) while you tidy up, and untick it afterwards. |
| A request is refused for lack of permission | The access key does not have the read, write or admin permission that tool needs. | Change the key's entry in `scopes.json` and use **Reload scopes.json** — see [Settings](configuration.md#giving-each-key-its-own-permissions). |
| Requests are refused as over the limit | The access key has made more requests this minute or today than **Rate limit (per minute)** or **Rate limit (per day)** allow. | Wait, or raise the limits in the [settings](configuration.md#limits-and-speed). |
| A script run comes back as still running | It took longer than a few seconds, so it carries on in the background. | Nothing — Claude collects the result when it is ready. A finished result is kept for ten minutes. |
| Asking for a device's or a variable's history gives an error | History comes from Indigo's SQL Logger, and the plugin can read it only when the SQL Logger writes to SQLite, its standard database. | If your SQL Logger uses PostgreSQL, the history tools cannot read it. Check the SQL Logger is enabled and logging that device or variable. |
| An e-mail, a lock or a script fails with a permission error | Sending e-mail, locking and unlocking, and writing or running scripts need a key with **admin**. | Give the key admin in `scopes.json` if you trust that client with those. |

## Event webhooks

| What you see | What it means | What to do |
|---|---|---|
| A webhook stops sending | Its receiver failed five times in a row, so the plugin switched it off. | Fix the receiver, then use **Plugins → Claude Bridge → Re-enable Quarantined Event Webhooks**. |
| Claude cannot create a webhook | **Enable Event Webhooks** is off, the address is not on the **Egress allow-list**, or the key does not have admin. | See the [event webhook settings](configuration.md#event-webhooks). |
