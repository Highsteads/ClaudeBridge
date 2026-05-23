#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin_utils.py
# Description: Shared utilities for all Indigo plugins (CliveS / Highsteads)
#              Bundled inside every plugin at Contents/Server Plugin/.
# Author:      CliveS & Claude Opus 4.7
# Date:        23-05-2026
# Version:     1.2
#
# v1.2 (23-05-2026): Added install_timestamp_filter() — a logging.Filter that
# prepends [HH:MM:SS.mmm] to every self.logger record. Toggle at runtime via
# the returned filter's .enabled flag. Matches the timestamp convention used
# by Device Activity Monitor across all CliveS plugins.
#
# v1.1 (10-05-2026): Banner width reduced 110 -> 60 chars and label column
# tightened 28 -> 20 chars.  Indigo prefixes every log line with the plugin
# name (~30 chars), so a 110-char banner total exceeded most terminal widths
# and wrapped to two lines per row.

import indigo
import logging
import platform
from datetime import datetime


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
    """
    title = f"Starting {display_name} Plugin"
    width = 60
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


class MillisecondTimestampFilter(logging.Filter):
    """
    Logging filter that prepends '[HH:MM:SS.mmm] ' to every log record's
    message. Matches the timestamp convention used by Device Activity Monitor
    so every CliveS plugin produces a consistent format in the event log.

    The filter has a mutable .enabled flag so the plugin can toggle timestamps
    on and off at runtime without removing/re-adding the filter.
    """

    def __init__(self, enabled=True):
        super().__init__()
        self.enabled = enabled

    def filter(self, record):
        if self.enabled:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            try:
                formatted = record.getMessage()
            except Exception:
                formatted = str(record.msg)
            record.msg  = f"[{ts}] {formatted}"
            record.args = None
        return True


def install_timestamp_filter(plugin, enabled=True):
    """
    Install a MillisecondTimestampFilter on the plugin's logger so every
    self.logger.info/warning/error/debug call gets a '[HH:MM:SS.mmm] ' prefix.

    Args:
        plugin   The Indigo plugin instance (must expose .logger).
        enabled  (bool) Initial on/off state — defaults to True.

    Returns:
        The installed filter. Flip filter.enabled to toggle at runtime.

    Usage in plugin __init__() (after super().__init__):
        self.timestamp_enabled = bool(pluginPrefs.get("timestampEnabled", True))
        if install_timestamp_filter:
            self._ts_filter = install_timestamp_filter(self, enabled=self.timestamp_enabled)
        else:
            self._ts_filter = None

    Toggle from a menu callback:
        def menuToggleTimestamps(self):
            self.timestamp_enabled = not self.timestamp_enabled
            self.pluginPrefs["timestampEnabled"] = self.timestamp_enabled
            if self._ts_filter:
                self._ts_filter.enabled = self.timestamp_enabled
            state = "ON" if self.timestamp_enabled else "OFF"
            indigo.server.log(f"[{self.pluginDisplayName}] Timestamps in Log -> {state}")
    """
    f = MillisecondTimestampFilter(enabled=enabled)
    plugin.logger.addFilter(f)
    return f
