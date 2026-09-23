#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    __init__.py
# Description: Importing this package registers every built-in tool (see
#              mcp_server/registry.py). One module per domain.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from . import automations, devices, notify, organise, plugins, scripts, server  # noqa: F401
from . import variables, webhooks, zwave  # noqa: F401
