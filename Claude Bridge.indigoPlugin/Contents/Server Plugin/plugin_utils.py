#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin_utils.py
# Description: Shared utilities for all Indigo plugins (CliveS / Highsteads)
#              Bundled in Contents/Server Plugin/ and imported via os.getcwd()
# Author:      CliveS & Claude Opus 4.8
# Date:        02-08-2026
# Version:     1.5
#
# v1.4 (02-08-2026): as_bool() returns the DEFAULT for a string it does not
# recognise, rather than False. Returning False silently flipped every
# default=True caller off whenever a pref held junk — the opposite of what the
# helper exists to prevent. Shipped in the code on 31-07-2026 during the
# Dashboards deep review but the header was never bumped, so the file claimed
# to be 1.3 while behaving as 1.4; this corrects the record and propagates the
# same file to every bundle.
#
# v1.3 (21-07-2026): Four fixes found by the Appliance Monitor deep review,
# propagated to every CliveS plugin bundle on the same day.
# * install_timestamp_filter() is now idempotent. Calling it twice used to add
#   a second filter, and every log line came out with two timestamps.
# * `import indigo` is now soft, so the module can be imported outside the
#   Indigo host (offline tests). log_startup_banner returns early without it.
# * The filter's fallback branch kept the broken log call's arguments, so a
#   %-placeholder mismatch is visible in the log rather than silently dropped.
# * New as_bool() helper — a pluginPrefs value re-serialised as the string
#   "false" is truthy, which is exactly the wrong answer.
# Also folded in the Device Activity Monitor docstring corrections: the banner
# is called from MENU callbacks, never from __init__/startup, and the import
# pattern is the bundle-local os.getcwd() form.
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

try:
    import indigo
except ImportError:      # importable outside the Indigo host, e.g. under pytest
    indigo = None

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

    Called from MENU callbacks only (showPluginInfo, Test Connection etc.) —
    never from __init__/startup (trimmed-boot convention, Jay 25-May-2026).

    Import at module level in plugin.py (cwd is Server Plugin/ at runtime):
        import os as _os
        import sys as _sys
        _sys.path.insert(0, _os.getcwd())
        try:
            from plugin_utils import log_startup_banner
        except ImportError:
            log_startup_banner = None

    Usage in showPluginInfo():
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName,
                               self.pluginVersion)
        else:
            indigo.server.log(f"{self.pluginDisplayName} v{self.pluginVersion}")
    """
    if indigo is None:
        return
    # The name and version inside the bar (v1.5) — this banner has only been
    # emitted from Show Plugin Info / Test Connection since 25-May-2026, so
    # "Starting ..." timestamped hours after boot read as a restart.
    title = f"{display_name} v{version}"
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
        if self.enabled and not getattr(record, "_ts_stamped", False):
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            try:
                formatted = record.getMessage()
            except Exception as exc:
                # Keep the evidence. A %-placeholder mismatch used to vanish,
                # leaving a half-formatted line and no clue why.
                formatted = f"{record.msg!r} args={record.args!r} (log format error: {exc})"
            record.msg  = f"[{ts}] {formatted}"
            record.args = None
            record._ts_stamped = True
        return True


_LOG_LEVEL_NAMES = {
    "DEBUG":    logging.DEBUG,
    "INFO":     logging.INFO,
    "WARNING":  logging.WARNING,
    "ERROR":    logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def log_level(level, default=logging.INFO):
    """Map a level NAME ("WARNING") or int to the logging int that
    indigo.server.log(level=...) wants (v1.5). A STRING passed straight
    through is silently ignored by Indigo and the line logs as plain Info —
    the bug that hid every WARNING and ERROR raised through the house log()
    helper until 21-Jul-2026, and that the template re-introduced for six
    weeks because every file carried its own copy of this map. Junk maps to
    `default` rather than raising."""
    if isinstance(level, bool):
        return default
    if isinstance(level, int):
        return level
    return _LOG_LEVEL_NAMES.get(str(level).strip().upper(), default)


def as_bool(value, default=False):
    """Coerce an Indigo value to a bool without being fooled by "false".

    pluginPrefs and device states can both come back as strings — Indigo
    re-serialises a saved dialog value, and another plugin may publish a state
    as text. bool("false") is True, which is exactly the wrong answer.
    """
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    # "t" / "f" are what psql prints for a PostgreSQL boolean column (v1.5) —
    # unambiguous, and a history bool read through here returned the DEFAULT.
    if s in ("true", "1", "yes", "on", "t"):
        return True
    if s in ("false", "0", "no", "off", "f"):
        return False
    # An UNRECOGNISED string is unknown, not False — returning False here
    # silently flipped default=True callers off whenever a pref held junk.
    return default


def install_timestamp_filter(plugin, enabled=True):
    """
    Install a MillisecondTimestampFilter on the plugin's logger so every
    self.logger.info/warning/error/debug call gets a '[HH:MM:SS.mmm] ' prefix.

    Args:
        plugin   The Indigo plugin instance (must expose .logger).
        enabled  (bool) Initial on/off state — defaults to True.

    Returns:
        The installed filter. Flip filter.enabled to toggle at runtime.

    A pluginPrefs write from a menu callback only reaches disk on a graceful
    shutdown, so call plugin.savePluginPrefs() straight after toggling.

    Usage in plugin __init__() (after super().__init__):
        self.timestamp_enabled = as_bool(pluginPrefs.get("timestampEnabled"), True)
        if install_timestamp_filter:
            self._ts_filter = install_timestamp_filter(self, enabled=self.timestamp_enabled)
        else:
            self._ts_filter = None

    Toggle from a menu callback:
        def menuToggleTimestamps(self):
            self.timestamp_enabled = not self.timestamp_enabled
            self.pluginPrefs["timestampEnabled"] = self.timestamp_enabled
            self.savePluginPrefs()          # a menu-callback pref write only reaches disk on a graceful shutdown otherwise
            if self._ts_filter:
                self._ts_filter.enabled = self.timestamp_enabled
            state = "ON" if self.timestamp_enabled else "OFF"
            indigo.server.log(f"[{self.pluginDisplayName}] Timestamps in Log -> {state}")
    """
    logger = getattr(plugin, "logger", None)
    if logger is None:
        return None
    # Idempotent: a second call used to add a second filter, and every line
    # then came out with two timestamps.
    # NB: attached at LOGGER level, so records from child loggers
    # (logger.getChild()) bypass it — fine for CliveS plugins, which log on
    # self.logger directly. SigenEnergyManager needs module-logger records
    # stamped too and carries a handler-walking variant of this function.
    for existing in getattr(logger, "filters", []):
        if isinstance(existing, MillisecondTimestampFilter):
            existing.enabled = enabled
            return existing
    f = MillisecondTimestampFilter(enabled=enabled)
    logger.addFilter(f)
    return f
