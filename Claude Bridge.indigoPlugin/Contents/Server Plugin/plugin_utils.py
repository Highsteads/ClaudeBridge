#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin_utils.py
# Description: Shared utilities for all Indigo plugins (CliveS / Highsteads)
#              Import via sys.path.insert using the same pattern as IndigoSecrets.py
# Author:      CliveS & Claude Sonnet 4.6
# Date:        10-05-2026
# Version:     1.1
#
# v1.1 (10-05-2026): Banner width reduced 110 -> 60 chars and label column
# tightened 28 -> 20 chars.  Indigo prefixes every log line with the plugin
# name (~30 chars), so a 110-char banner total exceeded most terminal widths
# and wrapped to two lines per row.

import indigo
import platform


def log_startup_banner(plugin_id, display_name, version, extras=None):
    """
    Print a standardised startup banner to the Indigo event log.

    Args:
        plugin_id       (str)  Plugin bundle identifier (e.g. com.clives.indigoplugin.ecowitt)
        display_name    (str)  Human-readable plugin name (e.g. Ecowitt Weather Station)
        version         (str)  Plugin version string (e.g. 2.0.0)
        extras          (list) Optional list of (label, value) tuples for plugin-specific
                               extra lines appended after the standard block.
                               e.g. [("Compatible Hardware:", "Ecowitt / Fine Offset")]

    Usage in plugin __init__():
        import sys as _sys
        _sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
        try:
            from plugin_utils import log_startup_banner
        except ImportError:
            log_startup_banner = None

        # ... all other __init__ setup ...

        if log_startup_banner:
            log_startup_banner(pluginId, pluginDisplayName, pluginVersion)
        else:
            indigo.server.log(f"{pluginDisplayName} v{pluginVersion} starting")
    """
    title = f"Starting {display_name} Plugin"
    width = 60
    # Centre the title within the bar; if title is longer than the bar (very
    # long plugin names) just emit the title on its own line.
    if len(title) + 4 <= width:
        pad   = (width - len(title) - 2) // 2
        mid   = f"{'=' * pad} {title} {'=' * (width - pad - len(title) - 2)}"
    else:
        mid   = title
    bar   = "=" * width
    label_w = 20

    indigo.server.log(bar)
    indigo.server.log(mid)
    indigo.server.log(bar)
    indigo.server.log(f"  {'Plugin Name:':<{label_w}} {display_name}")
    indigo.server.log(f"  {'Plugin Version:':<{label_w}} {version}")
    indigo.server.log(f"  {'Plugin ID:':<{label_w}} {plugin_id}")
    indigo.server.log(f"  {'Indigo Version:':<{label_w}} {indigo.server.version}")
    indigo.server.log(f"  {'Indigo API Version:':<{label_w}} {indigo.server.apiVersion}")
    indigo.server.log(f"  {'Architecture:':<{label_w}} {platform.machine()}")
    indigo.server.log(f"  {'Python Version:':<{label_w}} {platform.python_version()}")
    indigo.server.log(f"  {'macOS Version:':<{label_w}} {platform.mac_ver()[0]}")

    if extras:
        for label, value in extras:
            indigo.server.log(f"  {label:<{label_w}} {value}")

    indigo.server.log(bar)
