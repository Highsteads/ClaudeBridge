---
title: Security
nav_order: 7
---

# Security

The short version: the work happens on your Mac, nothing new is opened to the internet, every tool
is classed read, write or admin and a key gets only the class it was given, and the things that
cannot be undone are off until you turn them on.

- **The work stays local.** Searching and control all happen on your own
  Mac. What leaves it is your conversation with Claude, and anything you ask
  Claude to send out: an e-mail (admin keys only), a Pushover notification to
  your own devices, and event webhooks, which are off until you turn them on
  and can only reach the addresses you allow.
- **No extra doors into your network.** Everything travels through Indigo's
  own web server on its existing port, protected by Indigo's own access key,
  and the Reflector gives you secure remote access for free.
- **Permission levels.** Every tool is classed as read, write, or admin. A
  read-only key really is read-only. Deleting things, running code, locking
  and unlocking, sending e-mail, zeroing an energy total and the other things
  that cannot be taken back need the admin level. Anything not explicitly
  classified is locked down, not waved through. But a **write** key can run
  any action group and fire any trigger or schedule, and those run whatever
  they contain, including unlocking a door or an embedded script. See
  [what a write key can do](#what-a-write-key-can-do).
- **Careful by default.** Dangerous operations refuse ambiguous input rather
  than guessing, deletes that can cascade make you say so explicitly, and
  the plugin checks its own permission setup every time it starts.

---

## Scopes

Every tool is in exactly one of three sets in the plugin's own source: **read** (pure queries),
**write** (changes Indigo state) and **admin** (destructive, irreversible, code execution, plugin
lifecycle, physical security, data leaving the house). A tool that is in none of them is treated as
admin — locked down, not waved through — and the plugin checks that classification against its
registry every time it starts. One action of a tool can need more than the tool itself:
`device_control` is a write tool, but its `reset_energy` action, which zeroes a kWh total for good,
needs admin. Which key has which scopes is `scopes.json` under Preferences; see
[Configuration](configuration.md#per-token-scopes--scopesjson). **Without a `scopes.json`, every
key has every scope**, admin included. The full list is the [Tool reference](tools.md).

## What a write key can do

A write key changes things in the house: it switches devices, sets variables and thermostats, and
enables and disables automations. It can also run any action group, fire any trigger and run any
schedule now. Claude Bridge cannot see inside those to judge them: an action group that unlocks
the front door, opens the garage or runs an embedded Python script does exactly that when a write
key runs it, although the lock tool and the script tools themselves need admin.

So give a phone, a tablet or anything you would not trust with the front door a **read** key, or
keep the automations that open the house out of its reach (a separate Indigo install is the only
hard boundary; Claude Bridge cannot hide one action group from a key that may run action groups).

## Deletes

Deleting a device, a variable, an automation or a folder needs two things at once: the tool call
must say `confirm=true`, and *Allow Claude to delete devices, variables and automations* must be on
under Configure. It is off by default. A folder with things still in it is refused unless the call
says the contents are to go too. Putting the Z-Wave controller into exclusion mode
(`zwave` with `action="enter_exclusion"`) is behind the same two conditions: it removes the next
device whose button is pressed from the network, and getting it back means pairing it again.

## Running code

`execute_indigo_python` runs arbitrary Python inside the plugin's Indigo context. It is admin scope,
and it is full code execution on the Indigo server: give an admin key only to a client you would
trust with a terminal on that Mac.

When `execute_indigo_python` or `run_script` fails, the reply keeps its traceback, output and
error text, so Claude can see what went wrong without going to the event log. Any credential
value that appears in them is replaced with a marker such as `[redacted MQTT_PASSWORD]`. Claude
Bridge knows the values from the settings in `IndigoSecrets.py` whose names mark them as
credentials (KEY, TOKEN, PASSWORD, PASS, SECRET, PIN and so on), from Indigo's own API keys, and
from its own credential settings. Addresses, usernames and email addresses are left alone, as
are values shorter than six characters. If the values cannot be read, the reply falls back to a
bare "see the event log". The other sensitive tools (email, notifications, webhooks, script
creation) always return that bare message on failure.

## What a read-only key can see

A read key can see everything in the house that Claude Bridge can read, which is more than device
states:

- **Scripts.** `read_script` and `list_python_scripts` reach every `.py` file in both of Indigo's
  script folders, `Python Scripts` and `Scripts`. The one exception is the go-between script the
  plugin deploys into `Scripts` (`indigo_mcp_proxy.py`): it holds the access key, so no script
  tool will read, list, write, archive or run it, whatever the key.
- **Automations.** `get_automation` returns a trigger's, schedule's or action group's steps,
  including the source of any embedded script.
- **The event log.** `query_event_log`, `investigate_event` and the recent-log resource return
  the event log, which can hold whatever a plugin or script chose to write to it.
- **Device history.** `device_history` reads the SQL Logger's history database. It works only
  with the SQLite SQL Logger; an install that logs to PostgreSQL gets an error instead.

For a key **without admin**, the script text, the embedded automation scripts and the event log
lines have every credential value Claude Bridge knows about replaced with a marker such as
`[redacted IWS_API_KEY]`: the same values it removes from failure output (see
[Running code](#running-code)). If those values cannot be read, the reply is withheld rather than
sent unredacted. An admin key sees the text as it is. A secret Claude Bridge does not know about,
typed straight into a script, is not caught, so keep secrets in `IndigoSecrets.py`.

The `/health` address shows the configured key names, their scopes and recent tool calls to an
admin key only; any other key gets the basic status and its own rate limits.

**A note on variable values.** The Read tools that return variables (`get_variable_by_id`,
`list_variables`, `home_status` and the like) return each variable's value in full, so any
token with the `read` scope can see them. If you keep a secret in an Indigo variable — an API
token, a password — bear in mind that a read-only Claude Bridge token can read it, the same way
any Indigo script or control page can. Keep genuine secrets in `IndigoSecrets.py` rather than in
a variable, and don't hand a read token to anyone you wouldn't trust with those values. (Claude
Bridge no longer writes a variable's full value into the event log either — long values are
shortened in the log line, though they're still returned to the caller as normal.)

## Web pages cannot use it

A web page on any site can make your browser send a request to a device on your home network.
The MCP endpoint refuses any request whose `Origin` header names a site other than this Mac or
the Indigo server itself (its own address and its Reflector), with HTTP 403, so a page you happen
to open cannot drive your house through a browser that is already signed in. Requests with no
`Origin`, which is every client that is not a browser, are unaffected.

## Event webhooks — the outbound firewall

A webhook lets the home post a signed event to a URL you run. That is an outbound channel, so it
is guarded like one: the feature is off by default; every destination has to be on an allow-list
you write (blank means deny all); anything pointing back inside your own network — the Indigo
server, the router, the cloud-metadata address — is refused unless you name it with an explicit
CIDR; plain HTTP needs its own allow-list and is meant for LAN receivers only; every destination is
checked twice, when the subscription is created and again at send time, because a name can
re-resolve between the two; and every message carries an HMAC-SHA256 signature over a per-
subscription key, so your receiver can be certain it came from your system. The three webhook
tools are admin scope. `examples/webhook_receiver.py` verifies the signature and prints each event;
`examples/webhook_pushover_relay.py` turns one into a Pushover alert that works even if Indigo's
own notifications are stuck. A webhook host with several addresses is tried address by address,
every one of them checked against the firewall.
