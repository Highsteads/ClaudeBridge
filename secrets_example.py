#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    secrets_example.py
# Description: Template for secrets.py — copy to secrets.py and fill in your values.
#              secrets.py lives at:
#                  /Library/Application Support/Perceptive Automation/secrets.py
#              It is NEVER committed to git. Keep a backup in a password manager.
# Author:      CliveS & Claude Sonnet 4.6
# Date:        24-03-2026
# Version:     1.0

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
# Required by: SigenEnergyManager plugin
# ============================
SOLCAST_API_KEY   = ""
SOLCAST_SITE_1_ID = ""   # East + South arrays
SOLCAST_SITE_2_ID = ""   # West + Garage NE arrays

# ============================
# Octopus Energy - Export rates
# ============================
EXPORT_RATE_P = 15.0    # p/kWh flat export rate

# ============================
# Axle VPP (optional)
# Required by: SigenEnergyManager plugin (Axle VPP feature)
# ============================
AXLE_API_KEY   = ""
AXLE_CLIENT_ID = ""
