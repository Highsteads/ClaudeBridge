#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    IndigoSecrets_example.py
# Description: Template for IndigoSecrets.py — copy to IndigoSecrets.py and fill in your values.
#              IndigoSecrets.py lives at:
#                  /Library/Application Support/Perceptive Automation/IndigoSecrets.py
#              It is NEVER committed to git. Keep a backup in a password manager.
# Author:      CliveS & Claude Sonnet 4.6
# Date:        24-03-2026
# Version:     1.0

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
# Copy this file to:
#     /Library/Application Support/Perceptive Automation/IndigoSecrets.py
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
# Required by: OctopusAccountReader plugin
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
# Octopus Energy - Export (optional, add when known)
# ============================
# OCTOPUS_EXPORT_MPAN   = ""
# OCTOPUS_EXPORT_SERIAL = ""

# ============================
# Home Assistant
# ============================
HA_URL   = "http://192.168.x.x:8123"
HA_TOKEN = ""

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
# Required by: SigenergySolar, weather integrations
# ============================
LATITUDE  = 0.0
LONGITUDE = 0.0

# ============================
# Sigenergy Inverter (Modbus TCP)
# Required by: SigenergySolar plugin
# ============================
SIGENERGY_IP               = ""        # e.g. 192.168.x.x
SIGENERGY_PORT             = 502
SIGENERGY_ADDRESS          = 247
SIGENERGY_INVERTER_ADDRESS = 1

# ============================
# Solcast (Solar Forecast API)
# Required by: SigenergySolar plugin
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
# Required by: SigenergySolar plugin (Axle VPP feature)
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
# InfluxDB (optional)
# Required by: Claude Bridge plugin (historical_analysis MCP tools)
# ============================
INFLUXDB_HOST     = ""
INFLUXDB_PORT     = 8086
INFLUXDB_USERNAME = ""
INFLUXDB_PASSWORD = ""
INFLUXDB_DATABASE = ""
