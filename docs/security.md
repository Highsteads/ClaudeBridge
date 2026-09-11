---
title: Security
nav_order: 7
---

# Security

The short version: everything stays on your Mac, nothing new is opened to the internet, every tool
is classed read, write or admin and a key gets only the class it was given, and the things that
cannot be undone are off until you turn them on.

- **Everything stays local.** Searching and control all happen on your own
  Mac. The only thing that ever leaves the machine is your conversation with
  Claude itself.
- **No extra doors into your network.** Everything travels through Indigo's
  own web server on its existing port, protected by Indigo's own access key,
  and the Reflector gives you secure remote access for free.
- **Permission levels.** Every tool is classed as read, write, or admin. If
  you hand out a read-only key it really is read-only — and anything
  destructive (deleting things, running code, unlocking a door, the new
  folder deletes) needs the admin level. Anything not explicitly classified
  is locked down, not waved through.
- **Careful by default.** Dangerous operations refuse ambiguous input rather
  than guessing, deletes that can cascade make you say so explicitly, and
  the plugin checks its own permission setup every time it starts.

---

## Scopes

Every tool is in exactly one of three sets in the plugin's own source: **read** (pure queries),
**write** (changes Indigo state) and **admin** (destructive, irreversible, code execution, plugin
lifecycle, physical security). A tool that is in none of them is treated as admin — locked down,
not waved through — and the plugin checks that classification against its registry every time it
starts. Which key has which scopes is `scopes.json` under Preferences; see
[Configuration](configuration.md#per-token-scopes--scopesjson). The full list is the
[Tool reference](tools.md).

## Deletes

Deleting a device, a variable, an automation or a folder needs two things at once: the tool call
must say `confirm=true`, and *Allow Claude to delete devices, variables and automations* must be on
under Configure. It is off by default. A folder with things still in it is refused unless the call
says the contents are to go too.

## Running code

`execute_indigo_python` runs arbitrary Python inside the plugin's Indigo context. It is admin scope,
and it is full code execution on the Indigo server: give an admin key only to a client you would
trust with a terminal on that Mac.

## What a read-only key can see

**A note on variable values.** The Read tools that return variables (`get_variable_by_id`,
`list_variables`, `home_status` and the like) return each variable's value in full, so any
token with the `read` scope can see them. If you keep a secret in an Indigo variable — an API
token, a password — bear in mind that a read-only Claude Bridge token can read it, the same way
any Indigo script or control page can. Keep genuine secrets in `IndigoSecrets.py` rather than in
a variable, and don't hand a read token to anyone you wouldn't trust with those values. (Claude
Bridge no longer writes a variable's full value into the event log either — long values are
shortened in the log line, though they're still returned to the caller as normal.)

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
own notifications are stuck.
