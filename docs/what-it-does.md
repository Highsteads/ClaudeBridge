---
title: What it does
nav_order: 3
---

# What it does

Claude Bridge gives Claude **71 tools**, enough to read and change almost anything on your Indigo server. This page goes through them by what they let Claude do. You never need to name a tool — you ask in your own words and Claude picks the right one. Every tool is listed by name in the [Tool reference](tools.md), and the [How it works](how-it-works.md#read-write-and-admin) page explains the read, write and admin permissions mentioned below.

## Devices

- **Find any device** by name (whole or part, capitals optional), by id, by type — relay, dimmer, sensor, thermostat, fan, sprinkler — by the plugin it belongs to, by folder, or by its current state. Asking for "light" finds your lamps and dimmers, and "plug" finds your sockets. Long lists come a page at a time, sorted by name.
- **Read a device in full** — every state and setting, as it is right now.
- **Switch devices** on, off or over, set brightness, brighten and dim, set a colour or colour temperature, ask a device for its status, and beep or ping it. Claude can use the device's name, and if a name could mean two devices, nothing is switched and Claude is shown both instead.
- **Switch something for a set time** — "turn the fan on for ten minutes" or "switch that off in half an hour" is one request. Indigo's own timer does the timing, so it happens even after the conversation has ended, and Claude can cancel a waiting one on a single device without disturbing anything else.
- **Fans, sprinklers and locks** — fan speeds, a sprinkler's programme and zones, and locking and unlocking. Locks need **admin**, because they are the security of the house.
- **Turn a device's communication off and on**, rename it, copy it and move it to another folder.
- **Zero the energy total** on a plug that measures energy, to start a fresh measurement. This needs **admin**, because the old figure cannot be put back.
- **Run a plugin's own device actions**, the ones under **Device → Actions** in Indigo that belong to a particular plugin. This needs **admin**.
- **Whole-house commands** — Indigo's own all-lights-on, all-lights-off and all-off. These reach only devices Indigo talks to directly, such as Z-Wave. Devices that belong to plugins, such as Zigbee2MQTT or Shelly ones, do not hear them, and Claude tells you so.

## Heating

- **Every thermostat and radiator valve at a glance**, with setpoints, temperatures and modes.
- **Change a thermostat** — set a temperature, step it up or down, and change the heating, cooling and fan modes, in any combination in one request. It works with any Indigo thermostat, including Evohome, RAMSES and Z-Wave ones.

## The whole house

- **A summary of the house** — every device grouped by type, key variables, alerts such as errors and low batteries, and how many automations you have.
- **What is open and moving** — open doors and windows, active motion, and leak, smoke and carbon monoxide alarms.
- **A written report** of the house, which Claude can show you as it stands, covering energy, heating, security, devices, alerts and automations.
- **Energy**, if you use my Sigenergy Energy Manager plugin — the battery, solar and grid right now, day-by-day totals, and one period compared with another.

## Variables, action groups, triggers and schedules

- **Variables** — list, read, create and change them, and organise them into folders.
- **Action groups** — list them, read every step, and run them.
- **Triggers and schedules** — list them, read every detail including conditions and steps, and switch them on or off, if you like for a set time ("silence the hall motion trigger for half an hour"). Claude can run a schedule or trigger straight away, and change an automation's name and description, and what a device or variable trigger watches.
- **What uses what** — for any device, variable or action group, every trigger, schedule and action group that refers to it, so you know what you would break before you change or delete it.
- **What caused that?** — for a device that changed, Claude looks at the event log and the automations that ran around that time and says which most likely did it, with the evidence.

## Scripts

- **Read, write, create and run** the Python scripts in both of Indigo's script folders, `Python Scripts` and `Scripts`. Writing and running scripts needs **admin**.
- **A backup before every change.** Each time Claude changes a script, the old version is saved first, and the five most recent backups of each script are kept. Deleting a script only moves it to an `_archived` folder.
- **Long runs carry on in the background.** A script that takes more than a few seconds keeps running while Claude collects the result later, so Indigo's web server — and your control pages and dashboards — never wait for it.

## Plugins

- **Every installed plugin** with its version and whether it is running, and which plugins have an update waiting.
- **Restart a plugin** and report whether it came back, which version is running, and what it logged on the way. This needs **admin**.
- **Check a plugin you are writing** — its XML files against Indigo's naming rules, its JavaScript, its Python, the differences between your working copy and the installed one, and the versions of the libraries it bundles, in one request.
- **Click a plugin's menu item**, or any item in the Indigo client's own menus. This needs **admin**, and the Indigo client must be open on the Mac.

## The event log and history

- **Search the event log** by words, by plugin, by errors or warnings, or by time — including entries older than the Indigo window shows, because it reads the log files themselves.
- **A device's history**, and **a variable's history**, from Indigo's SQL Logger when it uses SQLite, its standard database. For a variable Claude can say how long each value held, which answers questions such as "how long was the heating on today".

## Checking the system

- **Health checks** — devices in error, low batteries, devices that have not changed for days, variables no script uses, duplicate names, scripts that name deleted devices, settings left behind by removed plugins, very large files, and, after an Indigo upgrade, anything new in Indigo worth using.
- **The Mac itself** — disk space, memory and how long it has been running.
- **Your Indigo server** — its folders, web server and Reflector addresses, location and today's sunrise and sunset.
- **Control pages** — every page and every control on it, with any control whose device or variable no longer exists picked out.

## Messages

- **Pushover notifications** to your own devices, through the Pushover account set up in Indigo, and **lines in the Indigo Event Log**.
- **E-mail** through the e-mail account set up in Indigo. This needs **admin**, because it can go to any address.

## Z-Wave

With **admin**, Claude can set a Z-Wave device's configuration parameters from the numbers in its manual, heal the network, and start adding or removing a device. Removing needs the same two yeses as a delete, because a removed device has to be paired again.

## Running Python

With **admin**, Claude can run any Python inside Indigo, for the rare job no tool covers. That is full control of your Indigo server, so give an admin key only to a client you would trust with the Mac itself.

## Event webhooks

When you turn them on, event webhooks let Indigo send a signed message to a web address you run the moment something happens — "when a leak sensor trips", "if the battery drops below 20%", "when the garage has been open for ten minutes". They are off when you install the plugin, and can only reach the addresses you allow. Creating one needs **admin**. There are two small example receivers in the [examples folder](https://github.com/Highsteads/ClaudeBridge/tree/main/examples) on GitHub.

## Tools from other plugins

Any Indigo plugin can add tools of its own. The plugin finds them by itself and lists them to Claude under that plugin's name — the Dashboards plugin's appear as `dashboards_get_status`, `dashboards_set_camera` and so on. **Allow plugin-provided tools to make changes** in the [settings](configuration.md#tools-from-other-plugins) decides whether they may change anything.

## What it cannot do

- **Claude cannot create a trigger or a schedule**, or change the steps and conditions of an existing one. It can read them all, and change an automation's name and description and what a trigger watches. The rest you do in Indigo.
- **It cannot see inside an action group to judge it.** A write key can run any action group, whatever that group does.
- **It reads the SQL Logger only when that uses SQLite.**
- **It deletes nothing unless you let it.** Deleting a device, variable, automation or folder needs **admin** and the delete setting switched on — see [How it works](how-it-works.md#deleting-needs-two-yeses).
- **It checks, but you decide.** Read what Claude has written and try the change. The point of the plugin is that checking is one question away.
