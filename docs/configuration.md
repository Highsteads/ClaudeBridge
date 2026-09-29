---
title: Settings
nav_order: 7
---

# Settings

Most people never need to change anything here. The plugin sets up the connection to Claude Code by itself, needs no API key, and starts with the safe choice for every setting.

## The plugin settings

Open **Plugins → Claude Bridge → Configure**. Every setting takes effect when you click **Save**, with no restart.

### Limits and speed

| Setting | What it does |
|---|---|
| **Rate limit (per minute)** | How many requests each access key may make in a minute. The default is 120, and it can be anything from 1 to 100,000. |
| **Rate limit (per day)** | How many requests each access key may make in a day. The default is 5,000, and it can be anything from 1 to 10,000,000. |
| **Read-cache TTL (seconds)** | How long the plugin keeps the answer to a question that only reads, so the same question asked again comes back at once. The default is 60 seconds, 0 turns it off, and the most is 300. Anything that changes — through Claude or in Indigo — clears the answers it affects straight away. |

Both limits count each access key separately, not each conversation. A key with the **admin** permission gets ten times both figures, and until you create a `scopes.json` (below) every key has admin, so on a new install the limits in force are 1,200 a minute and 50,000 a day. **Plugins → Claude Bridge → Print Plugin Health** shows the limits each key is held to.

### Tools from other plugins

| Setting | What it does |
|---|---|
| **Allow plugin-provided tools to make changes** | Ticked when you install the plugin. Untick it to stop any tool that another plugin adds from changing anything. Their tools that only read always work. |

### Event webhooks

| Setting | What it does |
|---|---|
| **Enable Event Webhooks** | Off when you install the plugin. Tick it to let Claude set up event webhooks, which send a message to a web address you run when something happens in the house. |
| **Egress allow-list** | The only places a webhook may send to, separated by commas or on separate lines. You can give a name such as `hooks.example.com`, every name under one with `*.example.com`, or an address such as `203.0.113.5`. Left blank, nothing is allowed. A receiver on your own home network is refused unless you write its address with `/32` on the end, such as `192.168.1.50/32`. |
| **Plain-HTTP allow-list** | Places that may be sent to over plain `http`, which is not encrypted. It is meant for a receiver on your own home network. Every place on the allow-list above may always be reached over `https`. |

Only a key with **admin** can create, list or delete webhooks. The [Security](security.md#event-webhooks--the-outbound-firewall) page describes the safeguards in full.

### Logging

| Setting | What it does |
|---|---|
| **Event Logging Level** | How much the plugin writes to the Indigo Event Log: **Extra Debugging Messages**, **Debugging Messages**, **Informational Messages** (the default), **Warning Messages**, **Error Messages** or **Critical Errors Only**. |

### Deleting

| Setting | What it does |
|---|---|
| **Allow Claude to delete devices, variables and automations** | Off when you install the plugin. While it is off, Claude cannot delete a device, variable, trigger, schedule, action group or folder, whatever key it has, and the refusal goes in the Event Log. Turning it on is not enough by itself — each delete must also be confirmed in the request. Leave it off unless you are tidying up, and turn it off again afterwards. Deleting a script is not covered, because that only moves the script to a `_backups/_archived` folder, where you can get it back. |

### Claude Code

| Setting | What it does |
|---|---|
| **Auto-configure Claude Code** | Ticked when you install the plugin. Each time the plugin starts, it copies the go-between script `indigo_mcp_proxy.py` into Indigo's `Scripts` folder, writes your access key into it, and adds an **indigo-mcp** entry to `.mcp.json` and `.claude/settings.json` in your home folder, so Claude Code can connect without you setting anything up. Untick it if you would rather look after those files yourself — [Getting started](getting-started.md#setting-claude-code-up-by-hand) shows how. |
| **Connect Claude Code** | **Through the go-between script** (the default) or **Straight to Indigo over HTTP**. The script works with every Claude Code and waits for Indigo after the Mac restarts. Over HTTP, Claude Code uses the newest version of the protocol, but if it starts before Indigo's web server it shows **indigo-mcp** as failed until you reconnect it with `/mcp`. Either way your access key stays in the script, which only your account can read: over HTTP, Claude Code asks the script for it each time it connects. This setting changes `.mcp.json` in your home folder. Claude Code's own list, which every other folder uses, is Claude Code's file, so the plugin does not edit it: **Plugins → Claude Bridge → Print MCP Client Connection Information** prints the two Terminal lines that change it to match. |

## Giving each key its own permissions

Indigo's web server checks the access key before a request reaches the plugin. On top of that, the plugin can give each key its own set of permissions — **read**, **write** and **admin**, explained on the [How it works](how-it-works.md#read-write-and-admin) page. Those live in a small file, `scopes.json`.

1. Choose **Plugins → Claude Bridge → Create Starter scopes.json**. The plugin writes a starter file and puts its location in the Event Log. It is in the `Preferences/Plugins/com.clives.indigoplugin.claudebridge` folder inside your Indigo folder, and **Show Plugin Info** also prints the path.
2. Open it in a text editor. It looks like this:

   ```json
   {
     "default_scopes": ["read"],
     "tokens": {
       "REPLACE_WITH_FULL_BEARER_TOKEN_FOR_CLAUDE_CODE": {
         "name": "claude-code",
         "scopes": ["read", "write", "admin"]
       },
       "REPLACE_WITH_BEARER_FOR_PHONE_OR_OTHER_CLIENT": {
         "name": "phone-readonly",
         "scopes": ["read"]
       }
     }
   }
   ```

3. Replace each placeholder with a real access key, the same one that client uses. Give each key a **name** you will recognise — it is what the change record shows, never the key itself. Add or remove entries as you need.
4. Save the file and choose **Plugins → Claude Bridge → Reload scopes.json**. No restart is needed.

Until the file exists, every key has every permission. Once it exists, a key the file does not name gets only what `default_scopes` says, which is read-only in the starter file. The [Tool reference](tools.md) lists which tools need which permission.

## The credentials file

Every one of my Indigo plugins can read private values from one shared file, `IndigoSecrets.py`, so you keep them in one place. Claude Bridge has no password fields of its own and reads just two values from that file, both optional:

| Name in the file | What it is for |
|---|---|
| `CLAUDEBRIDGE_BEARER_TOKEN` | The access key to write into the go-between script. The plugin uses it only when Indigo's own `secrets.json` has no key in it, because that file is read first. |
| `WEBHOOK_ALLOWLIST` | Extra places event webhooks may send to, as a list such as `["hooks.example.com"]`. They are added to the **Egress allow-list** in the settings, not used instead of it. |

If you do not have the file yet:

1. Right-click `Claude Bridge.indigoPlugin`, choose **Show Package Contents**, and open `Contents/Server Plugin`.
2. Copy `IndigoSecrets_example.py` into `/Library/Application Support/Perceptive Automation/`.
3. Rename the copy to `IndigoSecrets.py`.
4. Open it in a text editor, fill in the names you need, and leave the rest empty.
5. Restart the plugin with **Plugins → Claude Bridge → Reload**, because it reads the file only when it starts.

Keep a copy of the file somewhere safe, such as a password manager, and never share it — it holds your keys.

## The Claude Bridge device

The device the plugin creates has one setting, **Server Name**, which is a label and changes nothing. The [device page](devices-and-triggers.md) explains what the device shows.
