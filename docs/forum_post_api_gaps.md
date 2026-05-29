# Forum post draft — Indigo API additions that would help MCP / scripting clients

**Status:** draft for CliveS to review and post on the Indigo Plugin Developer
forum when ready. Written in CliveS's voice. No AI attribution — for posting
on an Indigo-owned property.

**Suggested forum:** Plugin Developer Forum, possibly with `@matt` and `@jay`
tags.

**Suggested title:** "A handful of IOM additions that would unlock a lot of MCP
/ scripting work"

---

Hello chaps,

A few of us are now building MCP-style bridges that expose Indigo to LLM
clients (Claude Code, Cursor, Continue, that sort of thing). Working on Claude
Bridge over the past few months I've ended up bumping into the same small set
of API edges over and over, and I thought it was worth listing them in one
place rather than dribbling out individual questions. Every one of these has a
workaround today, so none of them are blockers, but they all add friction
that's increasingly visible as the MCP tooling matures.

Posting in the hope that some of these are easier to land than they look from
the outside, and to gather thoughts from other plugin developers on whether
they'd find them useful too.

## 1. Read-only `pluginPrefs` access via `getPlugin()`

The `indigo.server.getPlugin(pluginId)` wrapper exposes a lovely set of fields
— `pluginVersion`, `isEnabled`, `latestCompatibleVers`, `executeAction` and so
on — but `pluginPrefs` isn't among them. Editing the on-disk `.indiPref` file
gets reverted by `IndigoServer` on next restart because the in-memory copy
takes precedence. That's perfectly sensible from a data-integrity angle, but
it means any tool that wants to ask "is plugin X actually configured?" or
"what broker is MQTT Connector pointing at?" has to either restart the plugin
to read the new prefs, or drive the Configure dialog through AppleScript GUI
scripting. Both are heavy compared to a `plugin.pluginPrefs` read.

**Useful for:**
- Pre-flight checks before running plugin actions ("is the API key set?")
- MCP audits across all installed plugins
- Bulk-update tools that need to see current state

Read-only would be a huge win even without write access. Write access would be
even better but I appreciate that opens questions about validation and live
notifications.

## 2. `getPlugin().executeMenuItem(menuId)`

The same wrapper has no programmatic route to fire a plugin's `<MenuItem>`
callbacks. Today the only way is AppleScript driving the macOS menu bar,
which means the Indigo GUI client has to be running, with Accessibility
permission granted, and the menu path has to be discovered by inspection.

Adding `plugin.executeMenuItem("menuId")` would mean menu items become
properly headless — a server-only Indigo install (no client logged in) could
fire diagnostics and one-shot maintenance items from scripts.

Bonus if there's an introspection method to list a plugin's menu items
(`plugin.getMenuItems()` returning name + id pairs), since today MenuItems.xml
has to be read off disk to discover them.

## 3. Native `indigo.server.fireEvent("eventId")`

Today firing a plugin-defined custom event from outside that plugin means
iterating `triggerStartProcessing`-registered triggers, matching on
`pluginTypeId`, and calling `indigo.trigger.execute()` per match — which only
works if a Trigger exists for the event. Pure "fire and forget" event
broadcasts aren't really possible.

The IOM already has `broadcastToSubscribers(messageName=...)` for plugin-to-
plugin comms, and I wonder if a sibling that uses the trigger / event
machinery rather than the broadcast bus might be a one-line addition. Or
whether the existing `broadcastToSubscribers` could be made callable from
outside plugin context.

## 4. Mutable `displayStateId` for existing devices

Confirmed back in May: `dev.displayStateId` is read-only, and
`stateListOrDisplayStateIdChanged()` refreshes the state list but doesn't
update the cached primary display state. The only fix for existing devices
when `<UiDisplayStateId>` changes in Devices.xml is delete + recreate, which
loses history and breaks references.

If there was a `dev.setDisplayStateId(newId)` or even just an option on
`stateListOrDisplayStateIdChanged()` that triggers a re-read of the XML
default, it would let plugin authors evolve their Devices.xml without orphaning
their users' existing devices.

## 5. Scoped API tokens

The single bearer token grants full server access. A read-only or
control-only token variant would let me hand an MCP client a much safer key
for production use, especially when other family members are looking over my
shoulder while it's running.

Even three coarse scopes would be huge:
- `read` — list/get/search across all object types
- `control` — read plus on/off/setpoint, executeAction, executeActionGroup
- `admin` — everything (current behaviour)

I'd keep the existing token as `admin` and only add new scoped tokens, so
existing integrations don't break.

---

## Half a dozen smaller asks worth mentioning

Not worth their own forum threads but useful while we're on the subject:

- **`indigo.server.backupDatabase()`** — programmatic snapshot trigger,
  matching what the GUI Backup menu does
- **Control page XML accessible to scripting** — read-only would be fine, just
  so MCP / scripting can answer "what's on page X?"
- **`indigo.server.getDeprecatedElems()` documentation** — the method works
  beautifully but isn't in the published IOM reference, which made it hard
  to know it existed
- **Live log subscription from non-plugin context** — `subscribeToLogBroadcasts()`
  exists but only inside a plugin host. A scripting-level equivalent would
  let MCP servers offer tail-style log endpoints
- **PyPI shared package cache across plugins** — every plugin re-installing
  `requests` and `pymodbus` into its own `Contents/Packages/` adds up. A
  shared cache (with per-plugin manifests pointing into it) would save disk
  and install time
- **Hot plugin reload** — would close the dev loop quite a bit

---

## One more — IWS goes silent for ~4m 37s, but only when Claude Bridge restarts

I had this one filed as a Reflector problem, and I want to correct myself before
that spreads, because I finally sat down and measured it properly this morning
and the Reflector turns out to be innocent.

The symptom is real enough. After I restart Claude Bridge, Indigo's entire IWS
stops responding for almost exactly 4 minutes 37 seconds. Not just Claude
Bridge's own endpoint but everything IWS serves, the plain web root included. It
then recovers on its own, bang on the 4m37s mark, very consistently.

What threw me was the Reflector noise in the log during that window, the
`reflector connection test failed: local server unreachable` and
`reconnection scheduled in 15 minutes` lines, which made it look like a
Reflector poll was holding up the IWS event loop. So I measured IWS liveness
independently of the MCP path, by curling the local web root
`http://127.0.0.1:8176/` once a second (a 302 means alive, a refused connection
means dead), and ran three small experiments:

- Restarting any OTHER plugin only blips IWS for about a second. I tried Humax,
  and separately a batch of seven of my own plugins, and in every case the web
  root stayed up and the MCP endpoint kept answering throughout. No dead zone.
- Restarting Claude Bridge takes the whole IWS down for ~4m37s every time.
- Doing that Claude Bridge restart with the Reflector connected, and then again
  with the Reflector disconnected, gives an identical ~4m37s either way.

So it is not the Reflector. The clincher is that in the Reflector-connected run
the IWS stayed dead for nearly three minutes AFTER the Reflector had already
given up and rescheduled itself fifteen minutes out. If the Reflector poll were
holding the loop, IWS would have freed the moment it stopped polling, and it
didn't. Those `local server unreachable` lines are the Reflector failing to
reach an IWS that is already wedged, rather than the thing doing the wedging. My
apologies for the earlier misdiagnosis.

What I can say with confidence now is that it is specific to Claude Bridge
restarting, not plugin restarts in general, so it is presumably something in my
own plugin's restart path that stalls the shared web server. A couple of clues
in case they ring a bell: Claude Bridge's shutdown hangs for about 21 seconds
every single time ("process failed to quit after polite request, forcing it to
quit now"), and the plugin does a fair bit on startup (a vector-store warmup of
roughly 60 to 90 seconds, plus some heavy imports), though none of that
obviously adds up to 277 seconds, and none of it explains why the WHOLE web
server goes quiet rather than just my own endpoint.

One related gotcha for anyone chasing something similar. If a request lands on
the `/message/.../mcp/` handler at the precise moment IWS comes back, it logs
`message handler failed` and Indigo sometimes reloads the plugin, which restarts
the whole 4m37s clock. I spent a fair while last night accidentally extending my
own dead zone by impatiently retrying, and the lesson was to probe only the
plain web root while waiting and never the message endpoint.

If this is a known characteristic of heavier plugins, or if there is something
obvious I'm doing in shutdown or startup that would block IWS like this, I'd be
very grateful for a pointer. And if it's worth raising as a proper bug with a
minimal reproducer, just say the word and I'll put one together.

---

## What I'm doing in the meantime

For folks running Claude Bridge or similar, the workarounds I've settled on
are documented in the repo CLAUDE.md and the global Indigo-development
CLAUDE.md, but the short version is:

- **pluginPrefs read** → disable plugin, read `.indiPref`, re-enable. Not
  pretty but reliable
- **executeMenuItem** → AppleScript via System Events, requires GUI client
  running
- **fireEvent** → register a hidden Trigger per event you want to be able to
  fire, store the trigger ID, call `indigo.trigger.execute()` on demand
- **displayStateId** → log a WARNING in `deviceStartComm` naming any device
  whose displayStateId doesn't match the current Devices.xml, telling the user
  to recreate

Happy to share more detail on any of these if it helps. And as always, huge
thanks for the recent clarifications on plugin conventions (licence files,
single README at repo root, the AI attribution rules for indigodomo-owned
repos). Genuinely useful to have those nailed down.

Cheers,
Clive
