---
title: Working with Claude
nav_order: 4
---

# Working with Claude

["Vibe coding"](https://en.wikipedia.org/wiki/Vibe_coding) is a term
coined by Andrej Karpathy in early 2025 for a particular style of
working with AI coding agents: you describe what you want in plain
language, the AI writes the code, you describe what you want changed,
the AI iterates. You guide by intent rather than by syntax. The "vibe"
is the back-and-forth itself — fewer keystrokes, more conversation.
Done well it produces working code far quicker than writing it line by
line, done carelessly it produces code that looks plausible and doesn't
run. What separates the two is a feedback loop that lets the AI
**verify** what it just wrote.

Claude Bridge turns the Indigo system itself into that feedback loop.

A confession, which I offer as the best evidence I have: **this plugin was
itself written by vibe coding.** Every version of Claude Bridge came out of a
conversation with Claude — described in plain English, written by Claude, and
tested by Claude against the live Indigo server, using the previous version of
this very plugin to see and act. The twenty-odd other plugins on this GitHub
account were built and are maintained the same way, with Claude Bridge as the
feedback loop, and the git history backs every word of that if you fancy
checking. So the examples below aren't speculation about what you could do.
They describe how the thing you are reading about came to exist.

Examples of how a session might go:

### Example 1 — write a Python script in one prompt

> **You:** "Write me a script that runs at sunset, turns on the porch
> light, and sends me a Pushover notification if the front door is
> currently open."

Claude Code:
1. Calls `search_entities` to find your porch light and front door sensor
2. Calls `get_device_by_name` to confirm IDs and states
3. Writes the script via `scaffold_automation_script` with the correct
   IDs baked in and a `log()` helper
4. Writes the file via `create_script`
5. Tells you the script name and tells you to schedule it for sunset

You read the result, hit Enter to commit, done. No Googling
`indigo.device.turnOn()`. No copy-pasting device IDs.

### Example 2 — write an Indigo plugin from a description

> **You:** "Build me a plugin that listens to my Tuya Zigbee thermostat
> via the Z2M bridge, exposes setpoint changes as states, and fires a
> trigger when the schedule kicks in."

Claude Code:
1. Reads your existing Zigbee2MQTTBridge plugin's device list to find
   the thermostat and discover its state names
2. Inspects similar plugins in your `Indigo 2025.2/Plugins/` folder
   for the conventions you use (Devices.xml structure, log format,
   header style)
3. Scaffolds the new plugin bundle with `Info.plist`, `Devices.xml`,
   `Events.xml`, and `plugin.py`
4. Restarts the plugin via `restart_plugin`
5. Queries the event log via `query_event_log` to confirm it started
   cleanly
6. Asks you to trigger a setpoint change and watches the events via
   `subscribe` + `get_events` to verify the state updates flow

When something fails, Claude sees the error in your log at once and
fixes it. Each turn of the loop takes seconds, not minutes.

### Example 3 — debug something weird

> **You:** "My bathroom light hasn't been turning off after the motion
> sensor clears for a week. Find out why."

Claude Code:
1. `query_event_log` for recent bathroom motion events
2. `dependency_map` for the bathroom motion sensor → which scripts and
   action groups reference it
3. `read_script` on each candidate
4. Spots a script that compares `var.value` to `"true"` (string) when
   the variable was set as `True` (bool, coerced to `"True"`)
5. Proposes the fix, you say yes, Claude `write_script`s the change
   and tells you it's done

That kind of cross-referencing would take me 20-30 minutes, Claude does
it in a couple of round-trips.

### What you get out of it

- **Plugin work goes from days to hours.** Claude generates most of the
  scaffolding (Devices.xml, action callbacks, MenuItems.xml, file
  headers). You bring the design and the review.
- **Scripts you'd put off get written.** A 50-line automation that
  would cost you an evening digging through Indigo's IOM docs becomes a
  five-minute prompt.
- **Debugging is faster.** Claude holds the whole log, the whole device
  tree, every script and every plugin's state at once, so you never
  have to load that context by hand.
- **You can be sloppy in your prompt.** "The hall light isn't doing
  the thing" works, because Claude can look at the hall light, see
  what it's doing, and work out what "the thing" might be.

### Honest limits

- **Claude can't create Triggers, and can't enable or disable a
  plugin** — Indigo keeps those to the UI. You get a scaffolded
  `.indigoPlugin` bundle and instructions, then you do the enable
  click yourself.
- **Claude reads your automations, it doesn't rewrite them blind.**
  Trigger conditions and Action Group steps used to be invisible.
  They aren't any more — `get_trigger_details`, `get_action_group_details`
  and `find_automation_references` read them straight out of Indigo's
  own database, embedded scripts included. Editing them still goes
  through `update_trigger` and `update_schedule`, which cover the
  firing configuration rather than every step.
- **Vibe coding speeds you up, it doesn't think for you.** Read what
  has been written. Test the changes. The point of Claude Bridge is
  that checking is one tool call away — so use it.

---

## Claude Code skills that complement this plugin

Claude Bridge is the **runtime** bridge — it lets Claude Code talk to a live
Indigo server (read state, control devices, query history). For the
**design-time** side — Indigo SDK docs, plugin lifecycle reference, 16 example
plugins, the IOM, and troubleshooting recipes — the companion is Simon's
`indigo:dev` Claude Code skill, distributed via
[simons-plugins/indigo-claude-plugin](https://github.com/simons-plugins/indigo-claude-plugin).

Loaded with `/indigo:dev`, it provides ~40 KB of curated SDK references for
Claude Code to draw on while writing new plugins or debugging existing ones,
without ballooning the context window.

How the two fit together:

| Layer        | Tool                    | Provided by    | What it gives Claude Code |
|--------------|-------------------------|----------------|---------------------------|
| Design-time  | `indigo:dev` skill      | simons-plugins | SDK docs, example plugins, lifecycle reference, IOM, troubleshooting |
| Runtime      | Claude Bridge MCP       | this plugin    | Live device control, variable / schedule access, event log, scripts, history |

Typical workflow:

1. **`/indigo:dev`** — Claude Code loads SDK context, scaffolds new plugin
   code, looks up correct API signatures.
2. **Claude Bridge** — Claude Code reads live device states via MCP to verify
   the new code is doing what's expected, fires triggers / runs scripts /
   updates variables to test integration end-to-end.

Other related Claude Code skills published in the same repo
(`indigo:api`, `indigo:control-pages`, `indigo:html-pages`, `indigo:update-plugins`,
`indigo:debug-sqllogger`) follow the same pattern: design-time docs and
guided workflows in the skill, runtime data and control via Claude Bridge.
Neither side requires the other to function — Claude Bridge works fine
without the skills installed, and the skills work fine without a live Indigo
server — but together they give Claude Code a complete end-to-end loop for
Indigo development.

---

## Claude chat instead of Claude Code?

The chat version of Claude — claude.ai or the Chat tab of the desktop app — can use this plugin
too, through the desktop app's local-connector setting, and connectors are on every Claude plan,
the free one included. What it cannot do is act on the Mac: it will not install anything, edit a
file, or run a command. So chat plus Claude Bridge answers questions about the house and controls
devices; Claude Code plus Claude Bridge also writes the scripts and plugins, and checks its own
work. The comparison is laid out on the Dashboards site's
[beginner's page](https://highsteads.github.io/Dashboards/no-coding-needed.html#can-i-use-claude-chat-instead-of-claude-code).
