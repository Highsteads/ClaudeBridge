---
title: Getting started
nav_order: 2
---

# Getting started

This takes about ten minutes, and most of it is waiting for downloads. If the words "MCP server" are new to you, here is all you need to know: Claude on its own can only talk. An MCP server is a small program that lets it look at things and do things — in this case a plugin inside Indigo that answers Claude's questions about your house and carries out its requests.

## What you need

- **Indigo 2023.2 or later** on your Mac. I develop and test it on Indigo 2025.2.
- **[Claude Code](https://claude.ai/download)**, Anthropic's app for working with Claude on a Mac, installed on the Mac that runs Indigo and used from the same Mac user account that Indigo runs under.
- **A paid Claude account.** Claude Code needs one, and a **Claude Pro or Max** subscription from [claude.ai](https://claude.ai) is the usual choice. That monthly plan pays for your conversations. If you already have one, there is nothing more to pay. An Anthropic API account, which you pay for as you use it, works instead.
- **An Indigo access key.** This is the key Indigo's web server asks for before it answers anything. Most people already have one — see step 3 below.

The plugin itself needs no API key and no extra Python packages. It runs on what Indigo already has, so it downloads nothing when you install it.

## 1. Install the plugin

1. Go to the [Releases page](https://github.com/Highsteads/ClaudeBridge/releases/latest) and download `Claude.Bridge.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Claude Bridge.indigoPlugin`
3. Double-click `Claude Bridge.indigoPlugin` — Indigo will install it automatically

Indigo asks whether to enable the plugin. Say yes. If you missed that, use **Plugins → Manage Plugins** and enable **Claude Bridge** there.

## 2. What the plugin does by itself

There is nothing to fill in. Every time it starts, the plugin:

- creates a device called **Claude Bridge**, if you do not already have one, which shows whether the plugin is running (see [The device and the trigger](devices-and-triggers.md))
- copies a small go-between program, `indigo_mcp_proxy.py`, into Indigo's `Scripts` folder, and writes your Indigo access key and the web server's address into it
- adds an entry called **indigo-mcp** to the two files Claude Code reads its settings from, `.mcp.json` and `.claude/settings.json` in your home folder, and leaves everything else in them alone

The Indigo Event Log then says **Claude Code integration configured**, followed by **Restart Claude Code to activate the indigo-mcp tools**, or, on later starts, **Claude Code integration already up to date**.

If you would rather look after those files yourself, untick **Auto-configure Claude Code** in the plugin's settings and follow [Setting Claude Code up by hand](#setting-claude-code-up-by-hand) below.

## 3. Make sure Indigo has an access key

The plugin takes the access key from Indigo's own list of **local secrets** — a file called `secrets.json` in the `Preferences` folder inside your Indigo folder. It uses the first key in that list.

If the Event Log shows an error starting **No bearer token available to patch into the MCP proxy**, you do not have one yet. Do either of these:

- **Make a local secret.** Create a plain text file called `secrets.json` in
  `/Library/Application Support/Perceptive Automation/Indigo <your version>/Preferences/`
  holding a list with one made-up key in it, such as `["a-long-random-phrase-of-your-own"]`. Restart the Indigo Server so its web server reads the file. The plugin picks the key up as it starts again. Indigo's own guide to local secrets is on the [Indigo web server page](https://docs.indigodomo.com/2025.2/user/remote-access/web-server/#authentication).
- **Use an API key from your Indigo account.** Make one in the [Authorizations section of your Indigo account](https://www.indigodomo.com/account/authorizations), put it in the shared credentials file as `CLAUDEBRIDGE_BEARER_TOKEN`, and reload the plugin. The [Settings](configuration.md#the-credentials-file) page explains that file.

The key in `secrets.json` wins if both are there.

## 4. Check it works

Quit Claude Code and start it again — it reads its list of tools only when it starts. Then type `/mcp` in Claude Code. **indigo-mcp** should be listed as connected, and you should see 71 tools when you select it.

Now ask it things you already know the answer to, so you learn what it can see:

- *"Which lights are on?"*
- *"What is the temperature in the hall, and when did it last change?"*
- *"List every device that has not reported in a day."*
- *"Turn the landing light on for ten minutes."* — then watch it go off by itself.
- *"What happened in the event log in the last hour?"*

Then ask for something you have been putting off — a script, a report, or why a trigger did not fire. [Working with Claude](working-with-claude.md) has worked examples.

If **indigo-mcp** is missing or will not connect, the [When something goes wrong](troubleshooting.md) page goes through the usual causes.

## Using the Claude desktop app instead

The go-between program works with any Claude app that can run a local MCP server, including the chat side of the Claude desktop app. Give the desktop app's MCP server settings (the file `claude_desktop_config.json`) the same entry the plugin writes for Claude Code:

```json
{
  "mcpServers": {
    "indigo-mcp": {
      "command": "python3",
      "args": ["/Library/Application Support/Perceptive Automation/Scripts/indigo_mcp_proxy.py"]
    }
  }
}
```

I develop and test with Claude Code. The desktop app should work the same way, but it has not had the same testing here, so please [open an issue](https://github.com/Highsteads/ClaudeBridge/issues) if it does not.

Chat can answer questions about the house and control devices, but it cannot act on the Mac itself, so it will not write a script to disk or check its own work the way Claude Code does. The comparison is on the Dashboards site's [beginner's page](https://highsteads.github.io/Dashboards/no-coding-needed.html#can-i-use-claude-chat-instead-of-claude-code).

**Plugins → Claude Bridge → Print MCP Client Connection Information** writes three more ready-made desktop-app settings to the Event Log — one through your Indigo Reflector for use away from home, and two for your home network. Those use a helper called `mcp-remote`, which needs Node.js installed on the Mac, and they take the access key in the settings themselves.

## Setting Claude Code up by hand

You only need this if you unticked **Auto-configure Claude Code**, or you run Claude Code on another Mac or as another Mac user.

1. Copy `indigo_mcp_proxy.py` out of the plugin (right-click `Claude Bridge.indigoPlugin`, choose **Show Package Contents**, and open `Contents/Server Plugin`) into
   `/Library/Application Support/Perceptive Automation/Scripts/` — on another Mac, any folder will do, as long as you use that path in step 3.
2. Open the copy in a text editor and put your access key between the quotes on the line that starts `BEARER_TOKEN`. On another Mac, also change `INDIGO_HOST` from `localhost` to the Indigo Mac's network address — the four numbers such as `192.168.1.20` — and change `INDIGO_SCHEME` and `INDIGO_PORT` if your web server does not use plain `http` on port 8176.
3. Tell Claude Code about it. This command, typed in Terminal, makes it available in every folder you start Claude Code from:

   ```
   claude mcp add --scope user indigo-mcp -- python3 "/Library/Application Support/Perceptive Automation/Scripts/indigo_mcp_proxy.py"
   ```

4. Start Claude Code again and check with `/mcp`, as in step 4 above.
