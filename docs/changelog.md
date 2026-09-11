---
title: Version history
nav_order: 11
---

# Version history

Every release, newest first. The three most recent also appear under **What's new** in the
[README](https://github.com/Highsteads/ClaudeBridge#whats-new); this page is the whole record.

### 2.26.0 (2026-09-10)
Other plugins can now bring their own tools to Claude Bridge.

A plugin that ships a small JSON file in its bundle, `Contents/Resources/mcp-manifest.json`, has its tools listed to Claude under its own prefix and every call forwarded to it — no configuration here, no configuration there, and a plugin picked up the moment it starts. The format is the provider-manifest contract mlamoure published for his Indigo MCP Server, followed here from the published specification, so a plugin written for either server works with both. The first provider is the Dashboards plugin (from its 3.12.0), which offers eight `dashboards_` tools: its status, its setup check as data, the room folders read and set, the cameras listed, added and removed, and the last lines of its own log.

Tools a plugin marks as writes are governed by one new switch under Configure, *Allow plugin-provided tools to make changes*, on by default and honoured at once; read tools always work. Each provider tool is classified read or write for the per-token scopes as it is registered, and never admin — the plugin decided what it does. Two new menu items print the providers found and rescan them on demand; a provider that appears, changes or vanishes is also noticed at the next tool listing. A plugin's own stopping is reported as exactly that, a hung one as a timeout rather than a hang, and a reply that breaks the contract as a protocol violation naming the plugin.

The README's tool count read 167 in seven places while the generated table and the repo description said 168; it says 168 now. 54 tests for the new module; the built-in tool table is unchanged, because a plugin's tools are not built in.

### 2.25.1 (2026-09-07)
The settings dialog was stretched wider than its own window, so the help text beside each setting was cut off mid-sentence.

The short help that can be attached to a setting is drawn on a single line and never wraps, so the longest one in the dialog decides how wide every row is — and the window cannot be widened past a fixed maximum. All four long ones have moved into ordinary description paragraphs, which do wrap.

Two new checks fail the build if any help text or setting label grows long enough to do it again, and the same file also checks every dialog parses, that field ids are unique within each dialog and that every visibility binding resolves. No setting or behaviour changed.

### 2.25.0 (2026-09-06)
Claude can now run a plugin's own actions — the ones under Device -> Actions.

Until now every plugin feature ended the same way: Claude could design it, build it, lint it and reason about it, and then a human had to sit at the Indigo client and click Device -> Actions to see whether it worked. Nothing in the bridge could reach a plugin's own `Actions.xml` actions. `execute_device_action` closes that, and it turns out Indigo has taken exactly the right arguments all along — `executeAction(actionTypeId, deviceId, props)` — so the wrapper is thin.

What is not thin is the guard, because the underlying call fails silently in three separate ways and every one of them looks like success. A misspelt action id reaches no callback and returns nothing. An action declared with `deviceFilter` — a device action — called without a device does nothing whatsoever, again returning nothing. And a plugin that is installed but stopped swallows the action entirely while the caller sees no exception at all. So the tool reads the plugin's own `Actions.xml` first, checks the call against it, and refuses with the reason and a list of what it could have called instead. Where the XML cannot be read it says so and dispatches anyway, rather than blocking a call that would have worked.

The middle one is the one that catches people out, so it is worth being exact about it. A `props` dict crosses the plugin boundary intact — measured against Timers and Pesters, `setTimerStartValue` with the device id moved the timer from 60 seconds to 43, with both props honoured. The identical call without the device id returned `None` and left it at 60. So when a plugin action seems to ignore what you sent it, the props are almost never the problem. The missing device is, and nothing raises to say so.

Admin scope, since these actuate whatever the target plugin exposes: valves, locks, garage doors, sprinkler zones. Every dispatch is written to the Indigo event log with the device and the resolved props, so an action fired by an AI caller leaves the same trail as one fired by hand.

### 2.24.4 (2026-09-02)
The plugin-development tools can find your source repos again.

`plugin_diff_source_vs_installed` and the other plugin-dev tools looked for the GitHub clones in one fixed place, `~/Documents/GitHub`. On this machine the clones moved to `~/GitHub` two weeks ago, and every drift check since has answered "no source repo matches" for every plugin — the tool built to catch drift could not see any repo to compare against. It now looks in `~/GitHub` first and falls back to `~/Documents/GitHub`, so either layout works.

### 2.24.3 (2026-08-30)
The plugin no longer claims it will tell your client when its tools change, because it never could.

Every connection was answered with a promise to send a notification whenever the list of tools, resources or prompts changed — and there is no way for this plugin to send one. Indigo's web server answers a request with a response and then the conversation is over. There is no open line to talk down.

That promise cost real time yesterday. A client that has been told it will hear about changes has no reason to go and look, so a session connected before the delete confirmation was added kept quietly dropping the new argument, and every delete was refused for missing something that had in fact been sent. The plugin was right each time and the caller had no way to know why.

It now declares only what it can do: the tools, resources and prompts it serves, and an honest note that resource subscription is unsupported. Clients decide for themselves when to re-read, which is what they were doing anyway. The `logging` claim went for the same reason — it needs the same missing channel, and the one method behind it was never implemented.

Seven tests hold the line, including one that fails if a capability is ever advertised without the methods to back it.


### 2.24.2 (2026-08-29)
If a delete is refused for a missing confirmation you did actually send, the message now tells you why.

An MCP client reads the list of tools once, when it connects, and quietly drops any argument that list does not mention. So a client that was already connected when you upgraded to 2.24.0 strips the new `confirm` argument on its way to the plugin, and the delete is refused for leaving out something you included. The old wording answered that with "pass confirm=true", which is advice you cannot act on — exactly the loop the gate's name-every-reason rule was written to avoid. It now says to reconnect the client so it re-reads the tools.

Worth knowing after any upgrade that adds or changes a tool: reconnect before the new arguments will reach the plugin.


### 2.24.1 (2026-08-29)
A scripted condition whose script has been emptied now says what it is instead of reporting an unknown code.

The condition type Indigo stores for a scripted condition is not written down anywhere first-party, so this plugin has always identified one by the presence of its source rather than by the number — which is right whatever the number happens to be, and stays right if it ever changes. That leaves one gap: a scripted condition with nothing in it has no source to go on, and read as "unknown".

The number has now been measured here rather than taken from a forum post, so that case is labelled properly. Detection still works from the source, not the code. Two tests, one for the empty case and one proving a scripted condition under an unexpected code is still decoded.


### 2.24.0 (2026-08-29)
Deleting something that cannot be brought back now takes two deliberate acts, not one.

Until now an admin token was the only thing standing between a request and a deleted trigger. That is the wrong shape of protection: a token is given admin rights so it can write scripts and restart plugins, and the same grant quietly carried the power to destroy a device, a variable or an automation in a single call. Scope can say whether a caller is trusted. It cannot say whether anyone meant to delete this particular thing.

So there is now a preference — off by default, and off is where it should stay unless you are actively tidying up — and on top of that every such call must pass `confirm=true`. Both, or the request is refused and the log says which one was missing. Refusing on only the first would send you round the loop twice. Admin scope stays as a third boundary rather than the only one. Deleting a script is deliberately not included, because that archives to `_backups/_archived/` and can be fetched back.

Triggers and schedules are now MCP resources in their own right — `indigo://triggers`, `indigo://triggers/{id}`, and the same pair for schedules. They were reachable only through tools, so a client had a stable read path for the objects it could not change and none for the ones it could. They go through the same handlers the tools use, because a resource that renders an automation its own way is just a second contract to keep in step.

Embedded script source is capped at 4,000 characters, and says so when it cuts. An action group can hold hundreds of lines and every step gets rendered, so an uncapped answer could be far larger than the question deserved. When you ask for details without the scripts you now get the opening line of each rather than a bare line count, which is usually enough to tell what it does.

Forty new tests, taking the suite to 586, and one of them now runs the tool-table generator in check mode so the published table cannot quietly fall behind the code. Ten deliberate sabotages, each one confirmed to turn the suite red before the code was trusted.

### 2.23.0 (2026-08-29)
`find_automation_references` now reads the Python hidden inside triggers, schedules and action groups, and `get_trigger_details` will show you a scripted condition instead of pretending there isn't one.

A condition written as Python on the Condition tab keeps its code inside the automation itself. Nothing here had ever read it, so a trigger with a perfectly good scripted condition reported having no condition at all, and a variable used only by that script came back with nothing against its name. That is the same shape of mistake as the last two releases, one layer further in, and it is the one that matters most, because "nothing references this" is the question you ask just before you delete something.

Embedded scripts are scanned in all three places they hide — scripted conditions, the script steps on a trigger or schedule, and the ones in an action group — by numeric ID and by quoted name, so `indigo.variables["holiday_mode"]` counts as a reference too. Every one of those hits says `confidence: heuristic` and names the token that matched, so you can tell a text match from something read straight out of the structure. It is a text scan and not a Python parser, so an ID built up with an f-string will still slip past. For a question about deleting things, matching too much is the safe way to be wrong.

Indigo IDs are only unique within a class, which Jay pointed out on the forum while this was being written. The reverse lookup used to keep one entity per ID and quietly throw the other away. It now reports both, and says so in the reply whenever a heuristic match is involved.

Where a condition is read both from the structure and from a script beside it, the decoded answer wins, whichever order they were found in.

Thirteen new tests, taking the suite to 546.

### 2.22.0 (2026-08-26)
`find_automation_references` now reads the script folders, which its own description had been claiming it did all along.

It answered from two places — the action steps in Indigo's database file, and the server's own dependency graph — and neither of those knows the first thing about the Python scripts sitting on disk. So a device driven entirely from a script came back with nothing against its name, which reads as "nothing touches this" rather than "I never looked there". That is the worst way for a tool people use for safe-delete checks to be wrong. The kitchen spot lights here reported one trigger and no scripts at all, while five scripts were driving them by ID, and `dependency_map` had been quietly finding all five the whole time.

Both script folders are scanned now, by numeric ID and by quoted name, and every hit carries its line numbers so you can go and look. No role is guessed for a script hit, because a script that mentions an ID might read it, write it, or only log it, and a confident wrong answer would be worse than none at all.

Plugins that hard-code a device ID in their own source are still not covered by any of this. The reply now says so on every call rather than leaving you to assume the list in front of you is the whole story.

The folder walk moved into one shared module, so `dependency_map` and `audit_variables` share a single copy instead of each carrying its own.

Fifteen new tests, taking the suite to 533.

### 2.21.0 (2026-08-20)
`find_orphaned_plugin_data` now finds the leftovers it always claimed to.

It looked at the subdirectories in Preferences/Plugins and nowhere else. Most plugins never create a subdirectory — everything they save goes in a single `.indiPref` file beside it — so the tool reported a clean sweep over a folder full of dead plugin data. A sweep here turned up thirteen orphan prefs files, two of which held a password in plain text, and the tool had never mentioned one of them. Prefs files are now scanned alongside the directories, and each entry says which kind it is.

Indigo's own built-ins — Z-Wave, the web server, the script executors — keep prefs without ever having a bundle in the Plugins folder, so they are listed separately instead of being called orphans.

It also reports stale launch agents. A plugin that runs a helper process installs one, and removing the plugin does not remove the agent: on this server a helper had been running for fifteen days with nothing left to talk to. An agent is only reported when a path it needs is genuinely missing, so a working one is never flagged.

One warning worth repeating, which is now in the tool's own output: read a prefs file before you delete it. Plugins have been found keeping API keys and passwords in there in plain text.

Seven new tests, taking the suite to 518.

### 2.20.2 (2026-08-09)
The smaller findings from the same review, taking the ones that touch your credentials or quietly tell you something untrue.

The diagnostic snapshot of the plugin's settings handed back your Anthropic key and your InfluxDB password in plain text. It now says whether each is set and nothing more. The InfluxDB on/off setting read the word "false" as on, which is how a checkbox comes back once the dialog has been saved, so switching it off and saving did not switch it off.

Battery reporting had two faults pulling in opposite directions. A sensor that reports a separate "battery low" flag as the word "False" was read as flat, because any non-empty word counts as true — so healthy sensors appeared in the low-battery list. Meanwhile a reading of 255, which is the usual way hardware says "I don't know", was passed along as 255%, sorting comfortably at the healthy end of the same list. Both now read as unknown, which is what they are.

Saved notes could collide. The id was the clock in milliseconds, so two notes written in the same millisecond shared one, and deleting either deleted both.

The house audit counted every variable sitting at "false" as an empty variable. Since roughly half the flags in a house are false at any moment, that number moved with the weather rather than with anything needing attention.

If you use the optional per-token permissions file, writing `"scopes": "admin"` rather than `["admin"]` used to give that token five permissions named a, d, m, i and n — which is to say none at all, silently. It now reads what you plainly meant and says so in the log.

Eight new tests, taking the suite to 511.

### 2.20.1 (2026-08-09)
The middle tier of the same review. Nothing here is dramatic on its own, but a few would have been baffling to run into.

If you use InfluxDB, the settings dialog was close to unusable. The port field did nothing at all — the value was read from your secrets file first, and that read fell back to 8086 rather than to nothing, so it always had an answer and never got as far as the dialog. Anyone running InfluxDB on another port was quietly connected to the wrong one. The host field, meanwhile, insisted on an `http://` prefix that its own description tells you to leave off and that the code strips again a moment later, so entering the example given on screen made the dialog refuse to save.

A stray `true` or `false` where an ID belonged was being accepted as ID 1 or 0 in three more places. That matters most for folders, where 0 is a real destination rather than an obvious mistake.

A mistyped comparison in a state filter — `gte_` for `gte`, say — used to match everything rather than nothing, because there was nothing left to fail. It now matches nothing and says so.

When a tool that handles credentials failed, the error text was replaced with a pointer to the log, but the traceback beside it carried the same text word for word. The reply is now built from a short list of safe fields rather than by painting over the original.

Also: the go-between script no longer writes an HTML error page into the stream Claude reads, and answers the request properly when Indigo returns a 401 or a 500. A deleted webhook stops delivering events that were already queued. Readings of zero — a flat battery, no sun, nothing crossing the meter — are reported as zero rather than as "unavailable". And if the search index fails to build at startup it now retries, where before it stayed empty and silent until the plugin was reloaded.

Fourteen new tests, taking the suite to 503.

### 2.20.0 (2026-08-09)
Three real faults, all turned up by a full review of every module rather than by anything going wrong in front of anyone.

The first will have affected anybody who installed this plugin and was not me. The Anthropic API key is optional — the field says so, the tooltip says so, the help text underneath says so, and the plugin only warns when it is absent — and yet the Configure dialog would not save without one. So to switch on webhooks, or change the log level, or adjust anything whatsoever, you first had to invent a key for a feature you were not using. The check simply predated the key becoming optional and nobody had been back to it since.

The second is the sort of fault that hides behind its own documentation. When a script sent to Indigo never finishes, the plugin abandons it and is meant to turn away later script calls until it ends, with a message naming the one that is stuck. It never turned away anything. The lock it leans on is reentrant, and because Indigo runs every plugin call on a single thread, the next caller was always the same thread that got stuck, so it sailed straight through, took the output stream out from under the runaway still writing to it, and the plugin's real output could be lost until a reload. It now checks whether the abandoned script is genuinely still going, which means it says no while it is, and lets go by itself the moment it ends rather than staying stuck for good.

The third only bites if you use the InfluxDB history tools, but there it bites hard. When the check that confirms your device names exist ran into trouble, it announced that every name was fine and passed them straight into the query. The fix for exactly that had been written months ago and applied to a near-identical function that nothing calls, which is a neat reminder that a fix is only a fix where the code actually runs.

Eight new tests, taking the suite to 489.

### 2.19.2 (2026-08-07)
A toggle was reporting `value: 0`, which reads as "toggle to nought" and is nothing of the sort. The control-pages skill tells authors to put a `DeviceActionValue` of zero on every device action, so every generated page carries one on its toggles, and yesterday's release dutifully reported it. Only the brightness-style actions actually use that field, so the value now appears solely for those. Presentation rather than correctness, but a number that means nothing is worse than no number at all, because the reader quite reasonably assumes it means something.

### 2.19.1 (2026-08-07)
Yesterday's release could tell you what was on a control page but not what any of it did, which is really only half the question. Every element came back reporting no action whatsoever, including a light that plainly toggles when you tap it.

The culprit was Indigo's own constant. `FULL_PAGE_FLAGS` sounds like it asks for everything, but the second argument behind it is `ignore_actions` and it is set to true, so the server politely withholds the lot. Asking with different flags returns them. Each element now reports what tapping it does — the action, the device it targets, and the level for a set-brightness step — decoded through the same code tables the automation tools use, which were checked against live runtime dumps a few weeks back, so there is no second copy here to drift out of step.

It also now reports the client-side action. `1014` is how a thermostat or dimmer gets its popup, and without it a setpoint control looked exactly like a read-only sensor tile.

Worth saying how this was found, since it says something about the limits of a green test suite: the tests passed throughout, because they checked that the code used a particular constant rather than checking what came back. It only surfaced by generating a page, importing it, and reading it back to find a light that insisted it did nothing. One of the new tests then promptly found a bug in the fix itself, where a malformed action list arriving as text was being read one character at a time into ten imaginary actions.

### 2.19.0 (2026-08-06)
If you have control pages, Claude can now tell you what is on them. It could not before, and worse, it had been quietly implying it could — `get_control_page` carried a hopeful little branch that went looking for a page's controls "if this version of Indigo exposes them", and no version of Indigo ever has. So it returned an empty list every single time, and an empty list looks exactly like a page with nothing on it. You would have been told your page was bare and had no way of knowing you had been told nothing at all.

The cause is not a missing accessor, it is that control pages are the one part of Indigo the object model never reached. Indigo's own scripting guide is refreshingly blunt about it, saying they "didn't make it into v1", and the page object has carried its name, size and background but nothing about its contents ever since. The layout only became reachable through the raw server request added in 2.18.0, which is exactly what Indigo's own code uses to draw a page in the first place.

So the tool now returns the real thing: every element on the page with its type, position, size, caption, image, the live value it is displaying, and the device or variable or action group it points at. Anything pointing at something that no longer exists is flagged and counted, which is the genuinely useful part. A control left behind by a deleted device carries on drawing quite happily and nothing in Indigo will ever mention it to you. Page width and height had gone missing from the tool as well, and are back.

This tool only *reads* pages, and no plugin can write one, because Indigo has no API for creating page contents. It does not follow that nothing can, and an earlier draft of this note said so rather too confidently. A control page is XML underneath, so a coding agent can generate that XML, save it as a `.textClipping`, and you drag it onto Control Pages in the Indigo Mac client, which takes it in perfectly happily. Simon has already built a Claude skill that does exactly this — [indigo-control-pages-skill](https://github.com/simons-plugins/indigo-control-pages-skill), also bundled in his [indigo-claude-plugin](https://github.com/simons-plugins/indigo-claude-plugin) — so if you want a page *built*, that is where to go. This is the other half: reading the ones you already have, so you can ask which devices a page uses and what on it is now pointing at nothing.

### 2.18.0 (2026-08-06)
There is a tool in here whose whole job is to notice when Indigo grows a bit of API we have not wrapped yet, and for months it has been reporting "nothing new, nothing missing" with total confidence. It was telling the truth about the places it looked. It simply never looked everywhere. Indigo keeps most of its commands inside namespaces, `indigo.device` and `indigo.server` and a couple of dozen more, and those are what the audit walked. Five functions sit outside all of them, right at the top, so they were never once counted. A clean report meant "nothing has changed in the namespaces", which is a far smaller claim than the one I had been cheerfully reading it as.

The audit now walks the top level too, and all seven of the callables living up there are written into the frozen baseline, so if a future Indigo adds another one it will actually show up. Classes and modules are left out, or the reader would drown in churn from `indigo.Dict` and a handful of stray standard-library imports.

Closing the gap was worth doing on its own, but measuring it answered a larger question. Of the 448 callables across the namespaces, this plugin already used 446 — everything bar `indigo.host.browserOpen` and the `indigo.utils` helpers. There is no harvest left in the documented API. Those five top-level functions are the entire remainder.

So there is a new tool, `raw_server_request`, which opens the read side of them. It reaches Indigo's own internal command set, which is how Perceptive Automation's own code fetches the layout of a control page. It is undocumented and unsupported, and it may well stop working on a future Indigo, so it is fenced in accordingly: only names beginning with "Get" are allowed through, the mutating half of that API is not reachable from the tool at all, and a name that is not a Get is refused outright rather than tried to see what happens. Guessing at undocumented command names on a live server is not a game worth playing. It needs admin scope even though it only reads, because the right way to judge a tool is by what it can reach rather than by what today's guard happens to permit.

### 2.17.1 (2026-08-04)
If you restart your Mac, there is a moment where Claude is running and Indigo is not, and until now Claude used that moment to decide the plugin was unreachable. It would knock on the door, find nobody in, and put up "Could not attach to MCP server indigo-mcp" — and there it stayed until you noticed and dismissed it, even though Indigo had come up perfectly well twenty seconds later. On this machine the gap was twenty-three seconds, which is a very small window in which to be permanently wrong about something.

The proxy now waits. When it finds nothing listening it holds the door open for up to forty-five seconds, checking every couple of seconds, and connects the moment Indigo's web server appears. It only waits for that one thing — if the token is wrong, or Indigo answers with an error, or the connection hangs, it fails straight away as it always did, and an ordinary request never waits at all. A note goes into the log while it waits, so if it ever does give up you can see what it was waiting for.

### 2.17.0 (2026-07-25)
Nothing was reported broken. This came out of a systematic sweep of the whole plugin, and it turned up rather more than expected, so it lands as one batch in three parts.

The first part is answers that were quietly wrong. `log_message` had never worked: Indigo wants the log level as a number, a word is ignored without complaint, and the plugin had been sending the word — so every warning and error raised through that tool had been going into the log as an ordinary Info line, while the reply cheerfully said it had logged a warning. Worse, the changelog has claimed since 2.10.1 that this was fixed. It wasn't. The fix went into a copy of the function that nothing calls, and the test that was meant to guard it only ever checked that dead copy, so the suite stayed green for six versions over a live bug. There is now one place where levels are mapped, the unused copy is gone, and the test checks what Indigo is actually handed — confirmed by running it against the old code and watching it fail. The same broken helper was being written into every script `scaffold_automation_script` generated, including in the catch-all error handler, so a scaffolded script logged its own crash as Info. `query_event_log` would answer "everything before last Tuesday" with an empty list and a cheerful success, because it started looking from today and never got as far as last Tuesday. Renaming a device, enabling one, or resetting an energy total all reported back the value you asked for rather than the value the server ended up with, which is not the same thing when another plugin owns the device. And asking to optimise a single Z-Wave node would, for most devices on a typical system, quietly optimise the entire mesh instead and tell you it had done the one node.

The second part is calls that could freeze the plugin. Everything Indigo hands a plugin arrives on one thread, so a slow tool doesn't hold up its own request — it holds up all of them, and every device update too. The unhappiest case was a runaway script: the old code left a lock held forever, so every later attempt to run anything waited out its full minute or two and then blamed the innocent script that came next. That now fails immediately and says which run is actually stuck, and the health page reports it. Several other tools that could run for minutes have been given budgets, and where a budget cuts a job short they now say so plainly rather than returning a short answer that looks complete.

The third part is staleness. The cache only ever noticed changes Claude Bridge made itself, so a lamp switched at the wall, or by a schedule, or by another plugin, went on reading as its old state for up to five minutes — even though the plugin had been told about the change and had it in hand at the time. It now notices.

My thanks to the sweep for finding the `log_message` business, which I had believed fixed for a month.

166 tools. 439 tests.

### 2.16.2 (2026-07-25)
A fix for the fix below. The new reading of the machine's installed memory never actually ran inside Indigo, because the plugin runs with a trimmed-down PATH that doesn't include the folder `sysctl` lives in — so the call failed, was quietly swallowed, and the figure fell back to the estimate. `system_health` still read 7.5 GB on an 8 GB Mac. The three system commands are now called by full path. The reason it slipped through is worth recording: the 2.16.1 check was run outside the plugin, where the PATH is normal, so it passed while the shipped code did not.

166 tools. 424 tests.

### 2.16.1 (2026-07-25)
A fix for `system_health`, which had been getting memory wrong. It worked out total RAM by adding up some of the buckets `vm_stat` prints, and that sum leaves out compressed memory, so an 8 GB Mac was reported as 4.7 GB — and the gap widened the busier the machine got, because macOS compresses more under pressure. Wrong at exactly the moment you want the number. Free memory was off in its own way, reporting the free list rather than what is actually available, which made a healthy Mac look like it had 0.1 GB left and nowhere to go.

Total now comes straight from the machine, and used memory follows the same formula Activity Monitor uses, so the two agree. There is a new `used_pct` to save you the division. All of this came to light while working out why the server had rebooted, with the tool understating the Mac by nearly half in the middle of a conversation about whether to buy a bigger one.

166 tools. 422 tests.

### 2.16.0 (2026-07-23)
A simplification of the capability awareness from 2.14.0/2.15.0. Indigo already tells us what a device can do as a live property of the device itself, so Claude Bridge now reads that directly instead of carrying a pre-built catalogue. Same helpful behaviour — a "warm white" command to a plain dimmer is still refused with a plain reason — but it now works on any server for any device, is always current, and needs no data to maintain. It's also more accurate: where one plugin uses a single device type for both colour and white bulbs, the live reading tells them apart per device, which a type-level catalogue couldn't. The `list_uncataloged_devices` tool is retired along with the catalogue it reported on.

166 tools. 408 tests.

### 2.15.0 (2026-07-23)
A new `list_uncataloged_devices` tool — the companion to v2.14.0's capability awareness. It reports the plugin-owned device *types* on your server that have no profile in the catalogue yet, collapsing duplicates (nineteen Shelly plugs of one type show as a single uncatalogued type with a count and an example), so it's a tidy to-do list for keeping the catalogue current. Built-in and interface devices are left out.

167 tools. 413 → 414 tests.

### 2.14.0 (2026-07-23)
Claude now knows what your devices can actually do.

Indigo's scripting API tells an assistant a device's type and states, but not its capabilities. Ask to set a plain on/off dimmer to "warm white" and the old behaviour was to fire the command and relay a cryptic failure. Now Claude Bridge carries a capability catalogue — generated from your own estate — and two things follow. Asking about a device includes what it supports (colour, white, white temperature, setpoints). And a command the catalogue says can't work is refused up front with a plain-English reason: ask for RGB on a Fibaro dimmer and you get back "it supports on/off, status requests" instead of a mystery error. The refusal only ever fires when the catalogue positively knows a device lacks a capability — an uncatalogued device is never blocked, so control is never taken away, only made more honest.

Nothing to install and nothing leaves your Mac — the catalogue rides along inside the plugin as plain data.

396 → 413 tests.

### 2.13.2 (2026-07-23)
Battery readings that were never percentages are no longer read as percentages. Ecowitt sensors and the Universal Z-Wave Sensor report battery as a simple OK/LOW flag, and USB-powered presence sensors report a bare zero — the low-battery tools took all of these at face value and cried wolf about five healthy devices while the genuinely dying ones queued behind them. The tools now honour the OK/LOW flag and ignore a bare zero, so a low-battery alert once again means what it says.

396 → 401 tests.

### 2.13.1 (2026-07-23)
A one-line kindness. The `device_history` tool now warns you up front that SQL Logger column names are stored lowercase (`batterysoc`, not `batterySoc`) and that rows are sparse, so the first query lands right instead of returning a wall of bare timestamps.

### 2.13.0 (2026-07-23)
Search that speaks human.

Search now understands everyday words: "telly" finds the TV plug, "lounge" finds Living Room devices, "rad" finds the radiator TRVs, "socket" finds the plugs. Around thirty word groups, matched locally with no cloud service and nothing extra installed, and a device literally matching what you typed always still comes top.

`device_history` grew up too. Asking for a column that doesn't exist is now a clear error listing the real column names, where before it silently dropped them and handed back rows of bare timestamps. Under the bonnet the queries now range on the table's primary key instead of scanning an un-indexed timestamp column — the old way held a read lock for the whole scan and could stall the SQL Logger on the big tables. And if any records in Indigo's database file fail to parse, the automation tools now say how many were skipped instead of quietly under-reporting.

380 → 396 tests.

### 2.12.4 (2026-07-23)
Corrections to the automation decoder, settled by dumping Indigo's own runtime enums.

The word shown for a compound condition was inverted — what Indigo stores as 1 means "all must match" and 0 means "any may match", and the tool had them the other way round. Lock and unlock codes were also swapped (a trigger named "Lock … Front Door Unlock Code" turns out to unlock, which in hindsight the name was trying to tell us). And thermostat setpoint steps and utility steps (beep, energy reset) now decode properly — before this they showed as "unknown" and a trigger whose only job was a setpoint change looked like it touched nothing at all.

### 2.12.3 (2026-07-21)
A subtle one with wide reach. Read from inside this plugin, `dev.pluginProps` comes back empty for devices owned by *other* plugins — 197 of the 221 devices in this house. Every tool that serialised a device inherited that hole, and an empty read looks identical to "no properties set". Device serialisation now reads through `globalProps` first and says where the answer came from, and `find_conflicts` is no longer blind to the 137 devices whose address lives in plugin properties rather than the native field.

352 → 377 tests.

### 2.12.2 (2026-07-21)
Housekeeping to the shared `plugin_utils.py` (v1.3), refreshed across the estate: calling the timestamp filter twice no longer double-stamps every log line, the module imports cleanly outside Indigo, and a new shared `as_bool()` stops the string `"false"` counting as true.

### 2.12.1 (2026-07-17)
A small fix with sharp teeth. If a client sent a tool an argument it didn't recognise, the plugin used to ignore it and carry on with the default. That bit here: `enable_device` called with `enable=false` quietly re-enabled the device. Unknown arguments are now refused outright, with an error naming the ones the tool does accept, and `enable_device` takes `enable` as an alias for `value`.

349 → 352 tests.

### 2.12.0 (2026-07-03)
The big one — Claude can now read your automations, not just your devices.

Until this release a Trigger was barely more than a name. Claude could see one existed and what it was called, and that was all. Three new tools — `get_trigger_details`, `get_schedule_details` and `get_action_group_details` — now return the whole thing: the event settings, the conditions, and every action step in order, embedded scripts included. Where a step runs a linked script file, the path comes back decoded as well.

Two more build on that. `find_automation_references` answers "what actually uses this device?" by cross-checking Indigo's own dependency list against a scan of the automations themselves, and labels where each answer came from. `investigate_event` takes a device that changed and ranks what probably caused it, weighing how close each candidate was in time against whether it genuinely acts on that device. It gives you evidence and an order of likelihood, never a verdict.

You can make limited changes too. `update_trigger` edits a trigger's name, description and device or variable event settings, and `update_schedule` and `update_action_group` cover name and description. Schedule timing turns out to be read-only on Indigo 2025.2, so the tool tells you that instead of failing quietly. Enabling or disabling a trigger or schedule now takes an optional delay and duration as well, so "silence the motion trigger for half an hour" is one call and Indigo reverts it on its own.

All of it reads Indigo's own database file directly, read-only, and never writes to it. Parsing this house — 73 triggers, 38 schedules and 48 action groups — takes 32ms.

158 → 166 tools. 309 → 349 tests.

### 2.11.1 (2026-07-03)
A tidy-up pass that cleared the lower-priority items parked from the big reviews. All under-the-hood, nothing you need to do.

The ones worth knowing: searching or filtering on a numeric value now matches even when Indigo stored that reading as text (it usually does), so "find me thermostats set to 21" behaves as you'd expect. A runaway snippet of code — an accidental infinite loop — now times out and frees the web server instead of tying up a thread until the next reload. The short-term cache can no longer briefly hand back a stale answer if something changed at the exact moment it was fetching. Search results now update straight away after you add, remove or rename a device rather than waiting for the next refresh. And a couple of quiet edge cases: script backups can't tread on a similarly-named script's backups, and asking for "all devices of type X" now caps its answer on a very large house.

304 → 309 tests.

### 2.11.0 (2026-07-03)
This one came from holding the plugin up against the *whole* of Indigo's own API and asking what Claude still couldn't reach. Eleven new tools and a couple of things the plugin had been promising but not delivering.

The headline is **Z-Wave management**. Claude can now set a device's configuration parameters directly — the fiddly numbered settings that normally mean digging through the Indigo GUI and a device manual — so "make that motion sensor less trigger-happy" is a conversation, not a chore. It can also heal the mesh network, and (carefully, because these physically pair hardware) put the controller into inclusion or exclusion mode to add or remove a device. All of these are admin-only.

The rest fill in gaps: nudging a cooling setpoint up or down (heating already had this), asking what depends on a **trigger** before you delete it (schedules and action groups already had it), the full reflector status, and a tool that just tells Claude where your logs and history database actually live so it stops guessing.

Two nice extras. Claude Bridge now ships **quick-start prompts** — pick "how's the house right now", "review today's energy", "sweep the batteries", "something's stuck, help me fix it", or "tune a Z-Wave sensor" and Claude knows exactly where to begin. And your recent event log is now readable as a resource, so Claude can glance at what the whole house has been logging without a special request.

166 tools now, 304 tests.

### 2.10.1 (2026-07-03)
A follow-up batch working through the medium-priority findings from the same review. Fourteen were real and are fixed (about half of what was flagged turned out to be already-handled or harmless, and was left alone).

The one you'd actually notice: **low-battery alerts now see your whole house.** They only ever looked at one of the three places Indigo can store a battery level, which happened to be the one your Zigbee sensors don't use — so 43 of the 55 battery devices here were invisible to the alert. All three places are checked now.

The rest are the quiet sort: two on/off settings that could switch themselves back on when saved (a blank-looking value reading as "yes"), the log tool honouring the level you ask for instead of always saying "info", writing an empty value instead of the word "None" when you clear a variable, a couple of tools that used to claim success on input Indigo can't actually do (delaying an action group, looking up a plugin that isn't installed) now saying so plainly, the plugin-restart tool no longer freezing the web server while it waits, a week-vs-week energy comparison refusing a silly date range, the "is this variable still used" check erring on the side of caution when it can't tell, and the cache noticing a few more changes so it doesn't hand back stale lists.

299 tests.

### 2.10.0 (2026-07-03)
A deep-review fix batch — a full multi-agent bug hunt of the plugin, with every finding verified against the live system before anything was touched. Nine genuine faults came out of it, several of them tools that had never actually worked.

The headline one is subtle but mattered. When a tool hit an error it handed the failure back as a tidy little result rather than raising it, and the plumbing behind the scenes took that at face value — so an error could sit in the read-cache and be served back as a fresh answer for a minute, the health counters cheerfully recorded it as a success, and the careful "don't echo a sensitive tool's raw error to the client" safeguard never fired because there was no exception for it to catch. All three now do the right thing — errors are spotted, never cached, counted honestly, and a mail or webhook failure no longer leaks its host and login into a reply that can travel out over the reflector.

The `/health` page had a related slip — it listed live usage keyed by the raw bearer token, so anyone who could read it could read everyone else's token. Those are now shown as a short one-way fingerprint instead.

Four tools that looked fine but never worked are now fixed or gone. Nudging a dimmer up or down by a few percent called an Indigo method that does not exist — it now uses the real one. Asking "what depends on this schedule or action group before I delete it" always came back empty, which is exactly the wrong answer for a safety check — it now lists the real dependants. The two "enable / disable an action group" tools have been removed altogether, because Indigo simply has no such thing for action groups and they failed every single time (147 tools now, down from 149). And the energy summary tools used to invent a tidy row of zeros when the figures they wanted were not in the logs at all — they now say so plainly and point you at the live figures instead.

A few more: firing a Claude Event now actually delivers its data to the trigger (and the setup notes give the correct way to read it), the "refresh dependencies" tool no longer offers to restart Claude Bridge from inside itself (which would cut its own line mid-sentence), running two bits of Python at once can no longer scramble the plugin's output, and the installer now finds your Indigo version on its own rather than assuming one, and refuses to run from a copy that would delete itself. 292 tests.

### 2.9.1 (2026-06-15)
- **History timestamps now come back in your own time.** Indigo's SQL Logger stores every history row in UTC, while everything else you see — a device's last-changed time, the server clock — is local. So through the summer a `device_history` row read an hour early, which is exactly the sort of quiet error that turns into a wrong answer about when something happened. The tool now converts each row's timestamp to local time on the way out (daylight saving included) and says so in the result with `"ts_timezone": "local"`. The time window you ask for is unaffected — that still filters on the stored column.

### 2.9.0 (2026-06-10)
Ten new tools, all surfacing Indigo capabilities found by walking the live API namespace by namespace — plus the walker itself is now a tool, so the question "has an Indigo upgrade added anything we haven't bridged?" answers itself from now on (`audit_api_coverage` diffs the running server against a frozen baseline of 362 callables).

The one you'll actually use daily: **timed device actions**. `device_turn_on` and `device_turn_off` now take optional `delay` and `duration` arguments, so "fan on for ten minutes" or "turn that off in half an hour" is a single call using Indigo's own delayed-action engine — no scripts, no timers. A companion `device_remove_delayed_actions` cancels a pending timed action on one device without touching anything else's.

The rest: `reset_energy_accumulator` zeroes the lifetime kWh count on an energy-metering plug, `beep_device` and `ping_device` give you physical identification and reachability checks, `all_lights_off` / `all_lights_on` / `all_devices_off` expose Indigo's native broadcast commands (clearly labelled as reaching Z-Wave/Insteon/X10 devices only — plugin-owned devices don't hear broadcasts), and `delete_device_folder` / `delete_variable_folder` complete the folder lifecycle, refusing to delete a non-empty folder unless you explicitly say otherwise.

Under the bonnet, the `/health` endpoint now reports average and maximum **response size per tool** alongside latency — because the real cost of a chatty tool is how much Claude has to read, not how fast the server answers. 283 tests.

### 2.8.6 (2026-06-10)
A housekeeping release off the back of a full repo audit — nothing about how the plugin behaves day-to-day changes, but quite a lot about how safely it can be changed in future does.

The thing users will actually notice: **installs are much lighter**. The plugin's `requirements.txt` had accumulated around twenty packages over its life, of which the code only ever imported four — the rest (pandas and numpy among them, tens of megabytes of compiled code) were downloaded onto every machine for nothing. The list is now exactly the four that are used: `anthropic`, `pydantic`, `influxdb` and `jinja2`. Fewer packages means faster installs, fewer ways for the pip step to go wrong, and less third-party code sitting inside your Indigo folder.

The rest is guard-rails for development. The repo now runs its full test suite (grown from 176 to 213 tests), an errors-only lint pass and a docs-staleness check automatically on every push via GitHub Actions — so a change that breaks a tool, leaves a new tool unclassified in the security scopes, forgets a cache-invalidation entry or lets the README drift out of date now fails loudly instead of shipping. There's a new `CONTRIBUTING.md` with the full recipe for adding a tool, a couple of genuinely dead stub modules have been removed, the documentation now consistently says 139 tools (the capability summary had been stuck on 136 since before the webhooks release), the tool cache no longer keeps expired entries around for keys that are never asked for again, the webhook store re-asserts its owner-only file permissions when loaded (in case it was ever restored from a backup with looser ones), and `setup.py` is now called `install.py` — it was always a one-shot installer, never a Python packaging file, and the old name invited a `pip install .` that could never work.

### 2.8.5 (2026-06-09)
The follow-on to the reliability fix in 2.8.3, closing the last two ways the bridge connection could drop out from under you. The first was a near-cousin of the one already dealt with. A connection that has gone stale while sitting idle does not always fail the moment a request is sent, it sometimes fails a fraction later when the reply is read back, and the earlier fix only caught the first of those. Now both are handled. When Indigo's web server has clearly closed an idle connection and sent nothing back at all, the request plainly never ran, so it is safe to reconnect and send it again whatever it was. On top of that the proxy now does the sensible thing pre-emptively and opens a fresh connection if the old one has been sitting unused for more than ten seconds, so most of these never get the chance to happen in the first place.

The second was a different beast. After Indigo's web server reloads, the bridge's session can be quietly invalidated, and every request after that would come back with a "missing or invalid session" error until the connection was restarted by hand. The proxy now spots that particular error, quietly re-introduces itself to get a fresh session, and replays your original request, so instead of a wall of session errors you simply get your answer.

As before, none of this ever blindly repeats an action that might already have gone through — a failure that happens *after* a request was genuinely sent is still left well alone, so a light is never toggled twice or an event fired twice. It rides along inside the plugin but it is really a change to the little stdio proxy, so it takes effect the next time the bridge connection is started up, not on a plugin reload.

176 tests now.

### 2.8.4 (2026-06-09)
A tidy-up release off the back of the deep review — the lower-priority findings that were worth doing, none of them urgent. The biggest single change is a clear-out: about 1,700 lines of dead code have gone, including three "vector store" modules that hadn't been wired into anything for a good while (the search has been plain keyword matching for ages), a token-validation helper that was created at startup and then never actually used, and a phantom "access mode" setting that was read from a config field that doesn't exist, so it could never be anything other than its default. None of it was doing anything, and carrying dormant code around just makes the place harder to read — it's all recoverable from git history if it's ever wanted again.

Alongside that, a handful of small correctness and safety fixes:

- **TLS verification can only be turned off deliberately.** When you register a webhook, switching off certificate checking now requires a genuine "off" — a stray empty or oddly-typed value can no longer quietly disable it.
- **Boolean values behave.** A device on/off-style flag passed as a real true/false is now handled properly rather than slipping through and being read as a device ID, the enable/disable-a-device tool no longer treats the word "false" as "on", and a variable set to a boolean is now stored Indigo's way (lowercase `true`/`false`) so your triggers and conditions compare it the way you'd expect.
- **The read-only "resources" view now respects scopes.** It exposes the same read-only data as the read tools, so it now needs the same `read` permission rather than being reachable by a token with none.
- **A couple of smaller niggles** — the cache now refreshes after a schedule is fired directly (a fired schedule can move devices), and a strong exact-match search no longer claims it "truncated" results when it didn't.
- **Secrets in variables are treated more carefully.** If you keep a token or password in an Indigo variable, its full value is no longer written into the event log (the log line is shortened) — though do note the read tools still return variable values in full, so a read-only token can see them. There's a short note about this under [what a read-only key can see](security.md#what-a-read-only-key-can-see); the proper home for a real secret is `IndigoSecrets.py`.

171 tests now.

### 2.8.3 (2026-06-09)
A reliability fix for the bridge connection itself. Every so often the very first request after a long quiet spell — or the first one straight after the plugin had been reloaded — would come back with a "Connection error … broken pipe" rather than doing the job, and you'd have to ask again. The cause was in the little stdio proxy that carries requests to Indigo: it keeps one connection open and reuses it, which is the right thing to do for speed, but Indigo's web server is entitled to quietly close that connection once it has been sitting idle for a while (and a plugin reload closes it outright). When that had happened, the next request hit a dead line. The proxy already knew to reconnect and try again for harmless read-only calls, but it deliberately would not replay an action that might change something, in case it had already half-happened. The fix is to tell the two situations apart: if the request never actually made it onto the wire — which is exactly the case when the connection has gone stale — then nothing happened at the other end, so it is completely safe to reconnect and send it again, whatever the request was. Only a failure *after* the request had already been sent is now left un-retried. The upshot is that those occasional first-call hiccups simply heal themselves. It rides along inside the plugin but it's really a proxy change, so it takes effect the next time the connection is started up.

### 2.8.2 (2026-06-09)
A deep multi-agent review, run fresh against the new Claude release, going right through the plugin one lens at a time and then having a second set of agents try to knock down every finding before anything was acted on. The reassuring headline first — the security-critical core was gone over hard and held up. The SSRF firewall on the new webhooks, the connection pinning, the per-token scope layer and the secret-handling all stood up to a determined look, which is exactly what you want to hear about a plugin that can be reached from the internet.

What the review did turn up was a genuine correctness bug in the housekeeping tools, plus a cluster of smaller fixes worth having. The honest improvements this release:

- **The audit tools now tell the truth.** `audit_variables` used to flag very nearly every variable as "unreferenced", which made it worse than useless — act on it and you could delete a variable that was quietly running half the house. The cause was twofold: it only ever looked in one of the two Indigo script folders (so everything in your main "Python Scripts" folder was invisible to it), and it only matched variables used by their numeric ID, never by name. It now reads both folders, matches by name as well as ID, and cross-checks Indigo's own dependency list, so a variable used by a trigger, a schedule or by name in a script is no longer wrongly called unused. It is also now clearly labelled a *candidate* list and not a "safe to delete" list — a plugin that hard-codes an ID in its own source still can't be seen, so it tells you to double-check before deleting. The same both-folders fix flows through `find_conflicts` and `dependency_map`.
- **`write_script` won't lose your work.** If it can't write the safety backup first — a full disk, a permissions snag — it now refuses to overwrite the existing script and tells you, rather than ploughing on and leaving you with nothing. The write itself is now atomic too, so an interrupted save can't leave a half-written file.
- **The self-sufficiency figure is honest about gaps.** The energy summary used to treat a missing reading on a partial day as a zero, which could quietly inflate the self-sufficiency percentage, and it had no floor so an odd day could even show a negative. It now works the figure out only from days where it actually has both numbers, tells you how many days it used, and is clamped to a sensible range.
- **Searches return what you asked for.** A "minimal" device search was accidentally stripping out the device's own sensor readings, so a temperature sensor could come back with no temperature. And filtering a search by device type could come up short because the filter ran after the results had already been trimmed. Both fixed.
- **A few tidies on the new webhooks and config.** A busy webhook target can no longer cause a healthy one to be switched off, a corrupt saved entry can't turn a single-device watch into a firehose, the feature now defaults to off in every code path, and the InfluxDB toggle behaves itself when you open and save the config.

Two findings were deliberately left for a later release rather than rushed — a re-check on duration-gated webhooks at the moment they fire, and a tightening of the no-token case — both written up so they're not forgotten. 165 tests now.

### 2.8.1 (2026-06-09)
Hardening pass on the new Event Webhooks, off the back of a multi-agent adversarial review that tried hard to break it. The good news first — the egress firewall itself held: no way was found to make it POST to the LAN, loopback, the cloud-metadata address or the Indigo box itself, across sixteen different attack angles, and the signing and secret-handling stood up too. What the review did turn up was a handful of robustness foot-guns, all now fixed: `any_change` can no longer be quietly combined with a state condition (it would have ignored the condition); `max_fires` now counts only successful deliveries, so a flapping receiver can't make a subscription delete itself; the delivery queue is bounded so a storm of changes against a slow receiver can't grow memory without limit; the store is no longer rewritten on every dropped event; shutting down or disabling the feature now cleans up its timers properly (no orphaned worker on reload, no stale event after a disable/re-enable); and turning off TLS verification now logs a clear warning about the risk. None of these were security holes — the feature ships off by default and the tools are admin-only — but they're worth having right before anyone leans on it. 63 tests now, including the adversarial battery.

### 2.8.0 (2026-06-09)
The big one — **Event Webhooks**, the feature that lets the home call out rather than only ever answering when you ask. You register a subscription ("the next time the front door opens", "if the battery drops below 20%", "when the garage stays open for ten minutes") and the plugin POSTs a signed JSON event to a web address you run, the instant the condition is met. That turns Claude Bridge from something you consult into something that can be wired into the loop — point the events at a little listener and have it act, notify, or hand the moment to Claude with the full context.

It ships **switched off**, and it is deliberately careful about where it is allowed to send. Webhook targets are **default-deny**: nothing can be registered until you add an approved host to the allow-list (in the plugin config, or `IndigoSecrets.py` `WEBHOOK_ALLOWLIST`, which is read first). Anything pointing at the Indigo box itself, your router, the rest of the LAN, or a cloud metadata address is refused outright — a private or loopback address can only ever be reached if you knowingly opt its range in as a CIDR (e.g. `192.168.1.50/32`). Every delivery is checked again at send time (so a target can't quietly re-point itself at something internal after the fact), the connection is pinned to the address that was checked, redirects are never followed, and every event is signed with HMAC-SHA256 so your receiver can be sure it really came from your plugin. The three new tools (`webhook_create`, `webhook_list`, `webhook_delete`) are all admin-scope.

There's a small reference receiver in `examples/webhook_receiver.py` that verifies the signature and prints each event, so you can see the whole thing working in a couple of minutes. To turn it on: Plugins → Claude Bridge → Configure → tick **Enable Event Webhooks** and fill in an allow-list. (Concept inspired by mlamoure's indigo-mcp-server, but written from scratch — that project ships no licence, so nothing was copied from it.)

### 2.7.3 (2026-06-08)
A small but genuinely handy search improvement. Asking Claude to "find all the lights" now turns up your dimmers and bulbs even when they're named "Lamp" rather than "Light", "find the plugs" turns up your Shelly and Tasmota sockets, "motion" finds the occupancy sensors, and "radiator" or "trv" finds the heating zones — the search now understands the *kind* of device, not just the words in its name. It's a curated set of synonyms matched to the device types you actually have here, and it only ever *adds* matches, so a proper name match always still comes top. Worth a note for anyone reading the code — the folder is called `vector_store` but there are no embeddings and no OpenAI key involved, it has been plain in-memory keyword search for a while now, and this just makes it a bit cleverer.

### 2.7.2 (2026-06-08)
- **Colours by name.** `set_color` now takes a colour as a hex code (`#FF8000`) or a plain name (`dodgerblue`, `tomato`, and 146 others, British "grey" spellings included), so you no longer have to work out three 0–255 numbers. The individual red/green/blue channels still work exactly as before.
- **The tool list documents itself.** The table of all 136 tools further up this README is now generated straight from the plugin's own code and grouped by what each tool is allowed to do (read, write or admin), so it can't drift out of date.

### 2.7.1 (2026-06-08)
- **Plugin versions report correctly.** `get_plugin_status` and `list_plugins` were showing `1.0.0` for every plugin (they were reading the wrong field). They now show the real version.

### 2.7.0 (2026-06-06)
A thorough security and robustness pass off the back of a full multi-agent review. The headline is that the optional per-token scope layer now does what it says on the tin.

- **Per-token scopes are properly enforced now (deny-by-default).** If you hand out a `scopes.json` token marked read-only, it really is read-only. Before this, a good number of the device, variable, schedule and script tools weren't classified and quietly fell through to the read bucket, so a read-only token could still change things. Every one of the 136 tools is now sorted into read, write or admin, anything destructive (deleting, running scripts, unlocking a lock, restarting a plugin) needs admin, and a token with an empty scope list or one that isn't listed at all is denied rather than waved through. There is also a startup self-check that shouts in the log if a newly added tool ever slips through unclassified. If you don't use `scopes.json` at all then nothing changes for you — your single Indigo bearer token still has full access exactly as before, gated by Indigo's own web-server authentication.
- **The file-handling tools now stay where they belong.** The script tools, the plugin-dev helpers and `find_large_files` are confined to the Indigo and script folders, so a stray or mistyped name can't wander off elsewhere on the Mac.
- **The proxy is gentler with your arguments.** A value like `true`, `null` or a code with a leading zero is left exactly as you typed it rather than being turned into something else, the connection timeout is more generous for long-running tools, and a dropped connection no longer risks running the same action twice.
- **`restart_plugin` will no longer restart Claude Bridge itself** — that only ever pulled the rug out from under the live session. Use the Indigo Plugins menu for that.
- **A long tail of smaller robustness fixes** — guarded number handling throughout (a blank or odd config field can't crash startup any more), a couple of threading tidy-ups, a brightness request of 1 now means 1 per cent rather than full, and the historical-analysis property suggestion talks to Claude properly (it had been silently falling back).
- **New test suite** — 75 tests covering the scope model, the proxy coercion, the state filters and the script-path safety, so these don't quietly regress.

No action needed on your part — update the plugin and carry on as before.

### 2.6.7 (2026-06-05)
- **A malformed argument can no longer stop the go-between script.** The proxy turns numeric-looking arguments into real numbers before passing them on, and its check for "is this a number?" accepted a value like `--5`, which then failed on conversion and took the script down with it. Odd values now fall through and are passed on as they are.

### 2.6.6 (2026-05-29)
- **`check_plugin_updates` works again.** It was handing Indigo the wrong kind of thing when asking about each installed plugin, so the call failed and the plugin id came back empty. It now reads the plugin records Indigo actually gives it.

### 2.6.5 (2026-05-29)
- **Restarting the plugin is cleaner.** Stopping mid-warm-up used to leave the text-search index's background worker running on its own, because the stop check looked at a flag that is only set once warm-up has finished — and mid-warm-up is the usual moment a restart lands. The worker is now signalled and waited for whatever state it is in, and it gives up early if a stop has already been asked for.
- **The Claude connection test at startup is now bounded.** It was an unlimited network call on the startup path, and could sit there for minutes. It gets ten seconds and no retries.

### 2.6.4 (2026-05-28)
- **`plugin_node_check_html` finds `node` again.** The plugin host runs with a short search path that doesn't include the folder Node is usually installed in, so the check couldn't start.

### 2.6.3 (2026-05-28)
- **Sleep and wake are noted in the log.** Claude Bridge answers requests one at a time and holds nothing open, so there is nothing to tear down when the Mac sleeps. The lines are there so a future "the tools went quiet between four and seven" can be matched against a sleep rather than hunted as a fault.

### 2.6.2 (2026-05-27)
Tool count 86 → 136. Three batches of work and one security fix, released together.

- **43 new tools covering the gaps in what Indigo already offers.** You can now delete, duplicate, rename, enable and re-file a device, delete and re-file a variable, and do the same round of housekeeping on schedules, triggers and action groups — each with a dependency check, so you can see what would break before you break it. The full sprinkler set arrives too (run, stop, pause, resume, next zone, previous zone), along with thermostat fan mode and fan-speed control by index or by step. Then a run of server-level odds and ends: speak, sunrise and sunset times, your latitude and longitude, the web-server address, deprecated elements, and cancelling every pending delayed action at once. Control pages can now be listed and read, and other plugins can be checked for updates.
- **7 plugin-development helpers.** Compare a plugin's installed copy against its source to catch a half-finished sync, force its dependencies to reinstall, read the versions of the libraries it bundles, check its XML against Indigo's naming rules, run `node --check` over the scripts inside its HTML, sweep its `plugin.py` for convention slips, and query the SQL Logger history for one device.
- **Fewer false alarms from the convention sweep.** The missing-loop-guard rule read the parameter name literally, missed annotated signatures, and knew only one way of writing the guard. It now recognises three, and only complains when the callback actually writes something back — a read-only mirror can't loop, so it no longer gets flagged.
- **A credential could reach the log.** Fixed.

### 2.4.3 (2026-05-25)
- **The plugin's own device no longer restarts for nothing.** It was re-establishing communication on any edit to the device, when the server name is the only field you can actually change.

### 2.4.2 (2026-05-23)
- **Every log line is stamped to the millisecond.** `[HH:MM:SS.mmm]` now leads each line, matching the rest of the CliveS plugins, which makes lining two plugins' logs up against each other far easier. There's a **Toggle Timestamps in Log** menu item if you would rather not have them, and Show Plugin Info tells you which way it is set.

### 2.4.1 (2026-05-23)
- **Credentials no longer leaked to subprocesses (secrets-policy compliance).**
  Up to v2.4.0 the plugin wrote `ANTHROPIC_API_KEY` plus the full InfluxDB
  credential set (host / port / username / password / database) into
  `os.environ` so the MCP server modules could read them via `os.environ.get(...)`.
  Two tool handlers shell out without an explicit `env=` (`system_tools_handler.py`
  and `scripting_shell_handler.py`), inheriting those credentials into every
  child process — a real leak.
- New `mcp_server/runtime_config.py` in-process config store. `plugin.py`
  populates it at startup and on every PluginConfig save; downstream modules
  (`influxdb/client.py`, `openai_client/main.py`, `tools/historical_analysis/main.py`,
  `mcp_handler.py`) read via `runtime_config.get(...)` instead of `os.environ`.
- No behaviour change for users — the plugin starts, MCP tools work, etc.
  exactly as before. Subprocess leak gone.

### 2.4.0 (2026-05-22)
- **Six new MCP tools** exposing recently-verified Indigo APIs:
  - `fire_trigger` — execute an Indigo trigger directly by ID/name
    (`indigo.trigger.execute`). Complements `fire_indigo_event` which fires
    custom Claude-Bridge plugin events via the `claudeEvent` channel.
  - `get_reflector_url` — return `indigo.server.getReflectorURL()`.
  - `create_device_folder` / `create_variable_folder` — idempotent folder
    creation via `indigo.devices.folder.create()` /
    `indigo.variables.folder.create()`.
  - `execute_indigo_python` — run arbitrary Python in the plugin's Indigo
    context via in-process `exec()` (same pattern as `run_script` but for
    ad-hoc code strings). `mode='exec'` returns captured stdout/stderr;
    `mode='eval'` returns the expression's repr in `value`. **ADMIN scope.**
  - `execute_plugin_menu_item` — click a plugin's menu item under the
    Indigo client's **Plugins** menu via AppleScript GUI scripting.
    The only known way to fire a third-party plugin's `<MenuItem>`
    callback from outside (the `indigo.server.getPlugin()` wrapper has
    no menu API). Requires the Indigo GUI running on the host.
    **ADMIN scope.**
- New tool package `mcp_server/tools/scripting_shell/`.
- `scope_manager`: `fire_trigger`, `create_device_folder`,
  `create_variable_folder` classified WRITE; `execute_indigo_python` and
  `execute_plugin_menu_item` classified ADMIN.

### 2.3.3 (2026-05-18)
- **`run_script` now pre-injects `indigo` into the exec globals**, matching
  Indigo's GUI action runner. Scripts run via this tool no longer need an
  explicit `import indigo` at the top — bare `indigo.devices.iter(...)` works.
  Discovered when an ad-hoc device-create script for MQTTExplorerBridge
  failed with `name 'indigo' is not defined`. Fix in
  `mcp_server/tools/script_tools/script_tools_handler.py:run_script`.

### 2.3.2 (2026-05-12)
- **`ServerApiVersion` lowered 3.6 → 3.4.** Plugin uses `requirements.txt`
  auto-install (introduced API 3.4) but does NOT use the API 3.6 feature
  (`dict(indigo.triggers[id])`-style iteration on Trigger/Schedule objects);
  it serialises those by reading attributes one-by-one. Lowering the API
  floor extends compatibility down to Indigo 2023.2 / Python 3.11
  (was Indigo 2024.2). Verified by grep — no `dict()` calls on
  trigger/schedule objects anywhere in the codebase.
- README "Platform" / "Requirements" lines corrected: was overstated as
  "Indigo 2025.2 / Python 3.13" (which is just the dev environment); now
  honestly reflects the API floor of 3.4 → Indigo 2023.2 / Python 3.11+.

### 2.3.1 (2026-05-12)
- **Docs sync** — README and `CAPABILITY_SUMMARY.md` brought up to date with the
  current tool surface. Tool count corrected from the stale "64" reference to
  the real 80. Categories expanded to cover the heating, energy, triggers /
  schedules, notifications, audit, and reporting groups that had drifted out of
  the previous categorisation. All log strings and config-dialog labels
  updated from `secrets.py` → `IndigoSecrets.py` to match the May-2026 rename
  policy.

### 2.3.0 (2026-05-10)
- **Standards-compliance pass** following the audit applied to all CliveS plugins
- **Version is now read dynamically from Info.plist** via `self.pluginVersion` (no separate Python constant)
- **Startup banner** via bundled `plugin_utils.py` — shows plugin name, version, ID, Indigo version, API version, architecture, Python version, macOS version
- **Show Plugin Info** menu item — re-runs the banner on demand with extras (MCP URL, Anthropic key status, InfluxDB status, access mode)
- **Trigger lifecycle fixed** — implemented `triggerStartProcessing` / `triggerStopProcessing` and rewrote `fire_claude_event()`. Previously called the non-existent `self.triggerEvent()` method which raised `AttributeError` silently, so `claudeEvent` triggers never actually fired
- **`deviceUpdated` self-loop guard** — plugin both `subscribeToChanges()` and writes its own `mcpServer` device states; without the guard a future state write inside the callback could loop
- **Bearer token rotated out of source** — `indigo_mcp_proxy.py` now ships with a deliberately invalid placeholder. Real value comes from Indigo's IWS `Preferences/secrets.json` first, with `CLAUDEBRIDGE_BEARER_TOKEN` in `IndigoSecrets.py` as a fallback. Plugin patches the deployed copy at install time
- **Secrets handling rebuilt** using `importlib` pattern with `clives_secrets` module name to avoid shadowing Python's stdlib `secrets` module (used by `mcp_handler` for `token_urlsafe()`). Also now correctly sources `INFLUXDB_*` from `IndigoSecrets.py` (was PluginConfig-only)
- **PluginConfig.xml policy banner** at the top — explicit explanation of IndigoSecrets.py vs PluginConfig precedence + the keys this plugin reads
- **Auto-configure Claude Code opt-out** — new checkbox so users can disable silent rewriting of `~/.mcp.json` and `~/.claude/settings.json`
- `fire_claude_event` data serialisation fixed (was collapsing `0` and `False` to `""`)
- Bare `except:` in `mcp_server/common/vector_store/validation.py` changed to `except Exception:`

### 2.2.0
- Prior release.

### 2.0.0 (2026-04-05)
- **64 MCP tools** (up from 23): added Scripts (5), Memory (4), Event Subscriptions (5), Audit (7), Home Intelligence (7), plus `find_conflicts` and `home_status_report`
- Script tools with auto-backup on write
- Persistent memory store (memory.json) — `remember` / `recall` / `forget`
- Push-model event subscriptions via ring-buffer fed by `deviceUpdated` / `variableUpdated` callbacks
- Audit tools: `audit_home`, `find_devices_in_error`, `find_low_battery`, `find_stale_devices`, `audit_variables`, `dependency_map`, `find_conflicts`
- Home intelligence: `home_status`, `energy_status`, `heating_status`, `security_status`, `home_status_report`
- Energy intelligence: reads SigenEnergyManager daily log files (`energy_log_days`, `energy_daily_summary`, `energy_compare`)
- `variableUpdated()` callback added; `deviceUpdated()` extended to queue all non-mcpServer state changes
- Fixed `Scripts` folder resolution — prefers `Scripts` over legacy `Python Scripts`

### 1.2.0 (2026-04-02)
- Zero-config install: plugin self-configures Claude Code on first enable
- `_setup_claude_code_integration()` in `startup()`: copies bundled proxy to `Scripts/`, patches Bearer token, updates `~/.mcp.json` and `~/.claude/settings.json`
- `setup.py` at repo root for CLI/advanced users
- Proxy (`indigo_mcp_proxy.py`) now lives inside bundle — single source of truth
- Auto-creates Claude Bridge device on first startup — no manual "New Device" step

### 1.1.1 (2026-03-24)
- Fixed `get_devices_by_state`: now searches full device data including top-level properties (e.g. `heatIsOn`, `onState`)
- Fixed `get_devices_by_state` crashing when proxy coerces `state_value` from string to bool
- `get_devices_by_state` schema changed to flat `state_key` + `state_value` string params (avoids object type validation issues)

### 1.1.0 (2026-03-24)
- Added `device_control` tool: find and control a device by name in a single MCP call (~1s vs ~5s)
- Search results now slim by default (id, name, state, score only); use `detail="full"` for complete config
- Fixed `get_device_by_id`, `get_variable_by_id`, `get_action_group_by_id` rejecting numeric IDs
- Proxy: added `proxy_elapsed_ms` timing to all tool call responses
- Reduced vector store sync log verbosity

### 1.0.3 (2026-03-24)
- API key field can now be left blank if `IndigoSecrets.py` provides `ANTHROPIC_API_KEY`
- Fixed config save erroring when API key field is blank but IndigoSecrets.py has the key
- Added `indigo_mcp_proxy.py` to repository

### 1.0.2 (2026-03-24)
- Renamed from "MCP Server" to "Claude Bridge"
- Replaced OpenAI/Voyage AI with Anthropic Claude API throughout
- Fixed text search: LLM query expansion disabled (broke substring matching)
- Proxy: persistent HTTP keep-alive connection
- Proxy: automatic type coercion (string → int/float/array)
- Proxy: MCP protocol version translation (2025-11-25 → 2025-06-18)
- Removed all third-party AI service dependencies

### 1.0.1
- Initial release with OpenAI + Voyage AI embeddings

---
