#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    IndigoSecrets_example.py
# Description: Template for IndigoSecrets.py — copy to IndigoSecrets.py and fill in your values.
#              IndigoSecrets.py lives at:
#                  /Library/Application Support/Perceptive Automation/IndigoSecrets.py
#              It is NEVER committed to git. Keep a backup in a password manager.
# Author:      CliveS & Claude Opus 4.8
# Date:        04-07-2026
# Version:     1.1

# ============================================================
# HOW THIS FILE WORKS
# ============================================================
#
# This is the MASTER credentials template for all CliveS Indigo plugins.
#
# WHY IT EXISTS
# Each plugin needs API keys and passwords to connect to external services.
# Rather than storing credentials separately in every plugin, or re-entering
# them each time via the Indigo config dialog, all plugins share a single
# IndigoSecrets.py at this version-stable path:
#
#     /Library/Application Support/Perceptive Automation/IndigoSecrets.py
#
# This path never changes when Indigo is upgraded — unlike paths inside the
# Indigo version folder (e.g. .../Indigo 2025.1/...) which change each release.
#
# HOW PLUGINS USE IT
# Each plugin does: sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
# then: from IndigoSecrets import KEY_NAME
# If IndigoSecrets.py is missing or a key is absent, the plugin falls back to the
# value entered in its own configuration dialog (Plugins → Plugin Name → Configure).
#
# NOTE: Indigo also has a built-in "secrets.json" in its Preferences folder,
# but that is only for authenticating HTTP requests to Indigo's own web server.
# It is a flat list of tokens with no names — not suitable for storing plugin
# credentials. Our IndigoSecrets.py is a separate, purpose-built solution.
#
# FIRST-TIME SETUP
# Copy this file into the folder:
#     /Library/Application Support/Perceptive Automation/
# then RENAME the copy from  IndigoSecrets_example.py  to  IndigoSecrets.py
# (the plugins import from IndigoSecrets, not from IndigoSecrets_example).
# Fill in the values for the plugins you use. You only need the sections for
# plugins you have installed.
#
# SECURITY
# IndigoSecrets.py is listed in .gitignore on every plugin repo and will NEVER be
# committed to git. Keep a backup copy in a password manager.
#
# ============================================================

# ============================
# Anthropic (Claude API)
# Required by: Claude Bridge plugin
# ============================
ANTHROPIC_API_KEY = "sk-ant-..."

# ============================
# Octopus Energy
# Required by: SigenEnergyManager (Kraken account economics) + the
#              octopus_tracker_rate.py rate script
# ============================
OCTOPUS_API_KEY = "sk_live_..."
OCTOPUS_ACCOUNT = "A-XXXXXXXX"
OCTOPUS_MPAN    = ""
OCTOPUS_SERIAL  = ""

# ============================
# Octopus Energy - Gas (optional)
# ============================
OCTOPUS_GAS_MPRN   = ""
OCTOPUS_GAS_SERIAL = ""

# ============================
# Octopus Energy - Export (optional)
#   Used by SigenEnergyManager v5.19+ for the Export Sync dashboard card
#   (compares Sigenergy daily export against settled Octopus readings).
# ============================
OCTOPUS_EXPORT_MPAN   = ""
OCTOPUS_EXPORT_SERIAL = ""

# ============================
# OpenWeatherMap (optional)
# ============================
OWM_API_KEY = ""

# ============================
# EvoHome (optional)
# ============================
EVOHOME_USER     = ""
EVOHOME_PASSWORD = ""

# ============================
# Pushover (optional)
# ============================
PUSHOVER_USER_TOKEN = ""

# ============================
# MQTT (optional)
# ============================
MQTT_BROKER   = "192.168.x.x"
MQTT_PORT     = 1883
MQTT_USERNAME = ""
MQTT_PASSWORD = ""

# ============================
# Location
# Required by: SigenEnergyManager (solar forecast), other weather integrations
# Leave at 0.0 to fall back to PluginConfig values; the SigenEnergyManager
# plugin's built-in fallback is Big Ben, London (51.5007, -0.1246).
# ============================
LATITUDE  = 0.0
LONGITUDE = 0.0

# ============================
# Dashboards plugin (optional)
# Required by: Dashboards plugin (com.clives.indigoplugin.dashboards)
# SIGEN_DASHBOARD_URL  — URL of an external Sigenergy mini-dashboard reached
#                        via the "Open Legacy Sigen Dashboard" menu item.
#                        Leave blank to disable the menu item.
# DASHBOARDS_CAMERAS   — JSON string OR python list of camera dicts. Each
#                        dict needs host, name, vendor ("dahua" or "hikvision").
#                        Leave blank to disable the cameras grid + MJPEG
#                        proxy + go2rtc. All cams share DAHUA_USER /
#                        DAHUA_PASS (despite the name, those work for
#                        Hikvision too).
# ============================
SIGEN_DASHBOARD_URL = ""
DASHBOARDS_CAMERAS  = ""  # e.g. '[{"host":"192.168.1.50","name":"Door","vendor":"dahua"}]'
# DASHBOARDS_HIDDEN_SCENES — action groups hidden from the Scenes page.
#                        Entries match a group name, a group ID (string), or
#                        "folder:Folder Name" to hide a whole folder.
DASHBOARDS_HIDDEN_SCENES = []  # e.g. ["Internal Reset", "folder:Maintenance"]

# ============================
# ShellyDirect plugin (optional)
# Required by: ShellyDirect plugin (com.clives.indigoplugin.shellydirect)
# INDIGO_SERVER_IP         — LAN IP Shelly devices use to reach Indigo for
#                            webhook callbacks (e.g. 192.168.1.10)
# SHELLY_USERNAME          — optional, only if your Shelly devices have auth
# SHELLY_PASSWORD          — optional, only if your Shelly devices have auth
# SHELLY_DISCOVERY_SUBNETS — first three octets, comma-separated for multiple
#                            subnets (e.g. "192.168.1" or "192.168.1, 10.0.1")
# ============================
INDIGO_SERVER_IP         = ""
SHELLY_USERNAME          = ""
SHELLY_PASSWORD          = ""
SHELLY_DISCOVERY_SUBNETS = ""

# ============================
# Sigenergy Inverter (Modbus TCP)
# Required by: SigenEnergyManager plugin
# ============================
SIGENERGY_IP               = ""        # e.g. 192.168.x.x
SIGENERGY_PORT             = 502
SIGENERGY_ADDRESS          = 247
SIGENERGY_INVERTER_ADDRESS = 1

# ============================
# Solcast (Solar Forecast API)
# Required by: SigenEnergyManager plugin
# ============================
SOLCAST_API_KEY = ""

SOLCAST_SITES = [
    {"name": "Site1", "resource_id": ""},
    {"name": "Site2", "resource_id": ""},
]

# ============================
# Octopus Energy - Export rates
# ============================
EXPORT_RATE_P = 15.0    # p/kWh flat export rate

# ============================
# Axle VPP (optional)
# Required by: SigenEnergyManager plugin (Axle VPP feature)
# ============================
AXLE_API_TOKEN = ""

# ============================
# Sigenergy Energy Manager — extras (optional)
# Required by: SigenEnergyManager plugin
# ============================
# DASHBOARD_HOST       — host shown in the "[Web] Dashboard at http://..." log
#                        line.  Leave blank to auto-detect the LAN IP.
# AXLE_SUPPORT_EMAIL   — email address used by the VPP "inverter not released"
#                        escalation alert (sent if Axle has not returned the
#                        inverter to self-consumption mode 45 minutes after a
#                        VPP event ends).
DASHBOARD_HOST     = ""
AXLE_SUPPORT_EMAIL = ""

# ============================
# Claude Bridge plugin (optional)
# Required by: Claude Bridge plugin (com.clives.indigoplugin.claudebridge)
# CLAUDEBRIDGE_BEARER_TOKEN - the IWS bearer token used by the stdio MCP proxy
# Get it from Indigo: copy the first entry of /Library/Application Support/
# Perceptive Automation/Indigo 2025.x/Preferences/secrets.json
# ============================
CLAUDEBRIDGE_BEARER_TOKEN = ""

# ============================
# Indigo REST API client config
# Required by: Dashboards plugin (HTML pages served from IWS).
# INDIGO_URL     - server URL the browser dashboards talk to.
# INDIGO_API_KEY - Bearer token for /v2/api requests. Same value as
#                  CLAUDEBRIDGE_BEARER_TOKEN (Indigo's first secrets.json entry).
# Leave blank to be prompted for them on first page visit.
# ============================
INDIGO_URL     = ""
INDIGO_API_KEY = ""

# ============================
# InfluxDB (optional)
# Required by: Claude Bridge plugin (historical_analysis MCP tools)
# ============================
INFLUXDB_HOST     = ""
INFLUXDB_PORT     = 8086
INFLUXDB_USERNAME = ""
INFLUXDB_PASSWORD = ""
INFLUXDB_DATABASE = ""

# ============================
# Alert email routing (per-plugin)
# Required by: WaterLeakMonitor (leak detection), EvoHomeControl (overheat),
#              SigenEnergyManager (power-cut grid lost/restored alerts)
# Each plugin will fall back to a PluginConfig field if these are blank.
# ============================
WATERLEAK_ALERT_EMAIL = ""
OVERHEAT_ALERT_EMAIL  = ""
POWERCUT_EMAIL        = ""

# ============================
# Dahua / Amcrest IP cameras
# Required by: Dashboards plugin (cameras.html snapshot page)
# DAHUA_USER/PASS is a single account used for all listed cameras.
# DAHUA_CAM_IPS lists every camera you own — the Dashboards plugin picks
# the subset to display from its own config; other plugins/scripts can
# iterate the full list.
# ============================
DAHUA_USER    = ""                          # camera admin username (e.g. "admin")
DAHUA_PASS    = ""                          # camera admin password
DAHUA_CAM_IPS = []                          # e.g. ["192.168.x.10", "192.168.x.11"]

# ============================
# Ecowitt Weather Station plugin
# Required by: Ecowitt plugin (optional PASSKEY routing).
# When set, the plugin only accepts pushes whose PASSKEY matches.
# Find your gateway's PASSKEY on the Main Gateway device's `passkey` state
# after the first push arrives. Leave blank to accept any.
# ============================
ECOWITT_PASSKEY = ""

# UniFi UDR / Network controller (read-only diagnostics)
UNIFI_HOST     = "192.168.1.1"
UNIFI_USERNAME = ""
UNIFI_PASSWORD = ""

# Command Centre dedicated console access token (optional; gates the web console)
COMMANDCENTRE_TOKEN = ""

# ============================
# ClaudeBridge — outbound webhook egress allow-list
# Required by: ClaudeBridge event-subscription webhooks (optional feature).
# Hosts/IPs/CIDRs the home is permitted to POST device state to. DEFAULT-DENY:
# an empty list means no webhook target can be registered at all. Forms:
#   "hooks.example.com"      exact host
#   "*.example.com"          any sub-domain (not the bare domain)
#   "203.0.113.5"            a specific PUBLIC IP
#   "192.168.1.50/32"        a private/LAN host — CIDR form is REQUIRED to opt a
#                            private/loopback range past the SSRF hard block
# ============================
WEBHOOK_ALLOWLIST = []

# Pushover application/API token (create at https://pushover.net/apps/build)
# Required by: ClaudeBridge webhook->Pushover relay (examples/webhook_pushover_relay.py)
PUSHOVER_APP_TOKEN = ""

# Weekly home digest recipient (weekly_home_digest.py)
DIGEST_EMAIL = ""
