#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: Claude Bridge Plugin — exposes Indigo devices, variables and actions
#              to Claude AI via the Model Context Protocol (MCP)
# Author:      CliveS & Claude Opus 4.7
# Date:        28-05-2026
# Version:     2.6.4
#
# v2.6.4 (28-05-2026): plugin_node_check_html now resolves the node binary via
# an absolute path (_resolve_node: shutil.which, then /opt/homebrew/bin etc.).
# Indigo's plugin-host PATH omits Homebrew dirs on Apple Silicon, so the bare
# ["node", ...] lookup always failed with "node not found on PATH" even though
# node was installed. Tool now works.
#
# v2.6.3 (27-05-2026): Added prepare_to_sleep / wake_up observability hooks
# harvested from the 27-May plugin_base.py sweep. ClaudeBridge is
# request/response over IWS with no persistent connections to manage, so
# these hooks log only — no operational change. Value is diagnostic: future
# "MCP unreachable between X and Y" investigations can correlate the gap
# with the Mac sleeping rather than hunting for a fault.
#
# v2.6.2 (27-05-2026): Defensive change. Vector store startup moved to a
# daemon thread via VectorStoreManager.start_async() so any future heavy work
# inside it can never block MCPHandler.__init__. NOT the fix for the
# post-restart MCP latency — investigation found VectorStore is a
# lightweight in-memory text-search store (no embeddings), so it was never
# the bottleneck. The 3-5 minute post-restart latency remains an open issue
# (cause appears to be IWS-layer or pre-startup() routing; no plugin log
# lines appear during the dead zone, including the very first one inside
# startup(), suggesting startup() either isn't running or its logger isn't
# routing). is_warming_up property exposed for diagnostics.
#
# v2.6.1 (27-05-2026): plugin_lint missing_loop_guard rule refined — no longer
# requires the `new_dev` exact identifier (now matches any param name including
# annotated `newDev: indigo.Device`), recognises three guard idioms (pluginId
# match, id-in-set, per-id equality), and only flags when deviceUpdated
# actually writes back to the device (replaceOnServer/updateStateOnServer/etc).
# Read-only mirrors no longer produce false positives. False positive against
# Claude Bridge itself (its own deviceUpdated is read-only and guarded) gone.
#
# v2.6.0 (27-05-2026): +7 plugin-development helper tools wrapping common dev
# workflows: plugin_diff_source_vs_installed (drift detection), plugin_refresh_deps
# (delete pip success marker, optional restart), plugin_show_packages_versions
# (read Contents/Packages/*.dist-info), plugin_validate_xml (Devices/Actions/
# Events/MenuItems/PluginConfig naming-rule check), plugin_node_check_html
# (node --check on inline JS in bundled HTML — catches stale-paste bugs),
# plugin_lint (CliveS-plugin convention sweep against plugin.py), device_history
# (focused SQL Logger sqlite query). Total tool count 129 → 136. New handler:
# mcp_server/tools/plugin_dev_tools/plugin_dev_tools_handler.py
#
# v2.5.0 (27-05-2026): +43 new MCP tools wrapping previously-unexposed IOM
# surface — device CRUD (delete/duplicate/move/enable/rename/toggle, dimmer
# brighten/dim), variable delete + move, schedule CRUD (delete/duplicate/
# execute_now/remove_delayed_actions/get_dependencies), trigger delete + move,
# action group CRUD (delete/duplicate/enable/disable/get_dependencies),
# sprinkler suite (7 tools), thermostat fan mode, speedcontrol index +/-,
# server tools (speak/sunrise/sunset/lat-lon/web-server-url/getDeprecatedElems/
# removeAllDelayedActions), control pages list+get, cross-plugin update sweep.
# Total tool count 86 → 129. All implementations in tools/extended_tools/.
#
# v2.4.2 (23-05-2026): Millisecond timestamp [HH:MM:SS.mmm] prefix on every
# log line via plugin_utils.install_timestamp_filter() — matches Device
# Activity Monitor convention. New "Toggle Timestamps in Log" menu item.
#
# v2.4.0 (22-05-2026):
# - New tools (6):
#   * fire_trigger              — execute an Indigo trigger directly by ID/name
#                                 (indigo.trigger.execute). Complements fire_indigo_event
#                                 which goes via the claudeEvent plugin-event channel.
#   * get_reflector_url         — return Indigo Reflector remote-access URL
#   * create_device_folder      — idempotent device folder creation
#   * create_variable_folder    — idempotent variable folder creation
#   * execute_indigo_python     — run arbitrary Python in this plugin's context
#                                 via in-process exec() (same pattern as run_script
#                                 but for ad-hoc code strings). ADMIN scope.
#   * execute_plugin_menu_item  — click a plugin's menu item via AppleScript GUI
#                                 scripting (the only known way to drive a third-
#                                 party plugin's <MenuItem> from outside). ADMIN scope.
# - scope_manager: fire_trigger / create_*_folder classified as WRITE;
#   execute_indigo_python / execute_plugin_menu_item classified as ADMIN.
#
# v2.3.3 (18-05-2026):
# - run_script now pre-injects `indigo` into the script's globals before exec,
#   matching Indigo's own GUI action runner. Scripts no longer need an explicit
#   `import indigo` at the top — bare references like `indigo.devices.iter(...)`
#   work directly. (Discovered while running an ad-hoc device-create script
#   for the MQTTExplorerBridge plugin.)
#
# v2.3.0 (10-05-2026):
# - Version is now read dynamically from Info.plist via self.pluginVersion
#   (no separate Python constant — Info.plist is the single source of truth)
# - Added log_startup_banner() via bundled plugin_utils.py
# - Added showPluginInfo menu item + callback
# - Implemented triggerStartProcessing / triggerStopProcessing lifecycle and
#   fixed two broken self.triggerEvent() call sites (the method does not exist
#   on PluginBase — was raising AttributeError, swallowed silently).  Indigo
#   custom 'claudeEvent' triggers now actually fire.
# - Added deviceUpdated self-loop guard at top (loop risk: plugin
#   subscribeToChanges + writes own mcpServer device states)
# - Bearer token rotated out of indigo_mcp_proxy.py source — replaced with
#   placeholder; real value now in IndigoSecrets.py CLAUDEBRIDGE_BEARER_TOKEN
# - Standardised secrets handling: per-key try/except for ANTHROPIC_API_KEY,
#   CLAUDEBRIDGE_BEARER_TOKEN, INFLUXDB_*; PluginConfig fallback per key;
#   ERROR-log if neither source set
# - PluginConfig.xml: help-text labels explaining IndigoSecrets.py policy added to
#   every credentials section; auto_configure_claude_code checkbox added
# - fire_claude_event data serialisation fixed (was collapsing 0/False to "")
# - vector_store/validation.py: bare except: -> except Exception:

try:
    import indigo
except ImportError:
    pass

import json
import logging
import os
import platform
import socket
import time

import anthropic

# Master credentials file: IndigoSecrets.py at
# /Library/Application Support/Perceptive Automation/IndigoSecrets.py
# (renamed from secrets.py on 10-May-2026 — the old name shadowed Python's
# stdlib `secrets` module which mcp_handler uses for token_urlsafe().)
#
# We still use the importlib pattern (rather than putting the parent dir on
# sys.path) for two reasons: (1) belt-and-braces against any future stdlib
# collision, (2) lets us load plugin_utils.py from the same directory under a
# unique module name without registering "plugin_utils" globally.
import os as _os
import sys as _sys
import importlib.util as _ilu

def _load_module_by_path(name: str, path: str):
    """Load a Python file as a module by an arbitrary name, without polluting sys.path."""
    if not _os.path.exists(path):
        return None
    try:
        spec = _ilu.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None

# Startup banner — shared master first, bundled fallback second.
_pu = (_load_module_by_path("clives_plugin_utils",
                            "/Library/Application Support/Perceptive Automation/plugin_utils.py")
       or _load_module_by_path("clives_plugin_utils",
                               _os.path.join(_os.getcwd(), "plugin_utils.py")))
log_startup_banner      = getattr(_pu, "log_startup_banner",      None) if _pu else None
install_timestamp_filter = getattr(_pu, "install_timestamp_filter", None) if _pu else None

# Master IndigoSecrets.py.  Any KEY not present falls back to default ("").
# Resolution order at runtime is: IndigoSecrets.py first, PluginConfig fallback.
_secrets_mod = _load_module_by_path(
    "indigo_user_secrets",
    "/Library/Application Support/Perceptive Automation/IndigoSecrets.py",
)
def _get_secret(name: str, default=""):
    return getattr(_secrets_mod, name, default) if _secrets_mod else default

ANTHROPIC_API_KEY         = _get_secret("ANTHROPIC_API_KEY")
CLAUDEBRIDGE_BEARER_TOKEN = _get_secret("CLAUDEBRIDGE_BEARER_TOKEN")
INFLUXDB_HOST             = _get_secret("INFLUXDB_HOST")
INFLUXDB_PORT             = _get_secret("INFLUXDB_PORT", 8086)
INFLUXDB_USERNAME         = _get_secret("INFLUXDB_USERNAME")
INFLUXDB_PASSWORD         = _get_secret("INFLUXDB_PASSWORD")
INFLUXDB_DATABASE         = _get_secret("INFLUXDB_DATABASE")

# Import our modules
from mcp_server import runtime_config
from mcp_server.adapters.indigo_data_provider import IndigoDataProvider
from mcp_server.common.openai_client.langsmith_config import get_langsmith_config
from mcp_server.mcp_handler import MCPHandler
from mcp_server.security import AuthManager, AccessMode


################################################################################
class Plugin(indigo.PluginBase):
    ########################################
    def __init__(
        self,
        plugin_id: str,
        plugin_display_name: str,
        plugin_version: str,
        plugin_prefs: indigo.Dict,
        **kwargs: dict,
    ) -> None:
        """
        Initialize the MCP Server plugin.

        :param plugin_id: the ID string of the plugin from Info.plist
        :param plugin_display_name: the name string of the plugin from Info.plist
        :param plugin_version: the version string from Info.plist
        :param plugin_prefs: an indigo.Dict containing the prefs for the plugin
        :param kwargs: passthrough for any other keyword args
        """
        super().__init__(
            plugin_id, plugin_display_name, plugin_version, plugin_prefs, **kwargs
        )

        self.timestamp_enabled = bool(plugin_prefs.get("timestampEnabled", True))
        if install_timestamp_filter:
            self._ts_filter = install_timestamp_filter(self, enabled=self.timestamp_enabled)
        else:
            self._ts_filter = None

        # Startup banner moved to showPluginInfo on demand (revised 25-May-2026 per Jay).

        # Indigo trigger registry — populated by triggerStartProcessing/Stop.
        # Maps trigger.id -> trigger object so _fire_claude_event can find
        # triggers whose pluginTypeId matches the event being fired.
        self.event_triggers = {}

        # Plugin configuration — credentials follow the standard resolution
        # order: IndigoSecrets.py first, then PluginConfig (pluginPrefs) as fallback.
        # See feedback_secrets_policy.md for the rule.
        self.anthropic_api_key = ANTHROPIC_API_KEY or plugin_prefs.get("anthropic_api_key", "")
        self.large_model       = plugin_prefs.get("large_model", "claude-sonnet-4-6")
        self.small_model       = plugin_prefs.get("small_model", "claude-haiku-4-5-20251001")

        # InfluxDB configuration — same resolution pattern
        self.enable_influxdb   = plugin_prefs.get("enable_influxdb", False)
        # Strip protocol from host (clients add their own) — accept either form in config
        _influx_url            = (INFLUXDB_HOST or plugin_prefs.get("influx_url", "")).strip()
        self.influx_url        = _influx_url.replace("http://", "").replace("https://", "") or "localhost"
        self.influx_port       = str(INFLUXDB_PORT or plugin_prefs.get("influx_port", "8086"))
        self.influx_login      = INFLUXDB_USERNAME or plugin_prefs.get("influx_login", "")
        self.influx_password   = INFLUXDB_PASSWORD or plugin_prefs.get("influx_password", "")
        self.influx_database   = INFLUXDB_DATABASE or plugin_prefs.get("influx_database", "indigo")

        # Security configuration
        self.access_mode = plugin_prefs.get("access_mode", "local_only")

        # Phase 2: rate limit / cache (with safe parsing)
        try:
            self.rate_limit_per_minute = max(1, int(plugin_prefs.get("rate_limit_per_minute", 120)))
        except (TypeError, ValueError):
            self.rate_limit_per_minute = 120
        try:
            self.rate_limit_per_day = max(1, int(plugin_prefs.get("rate_limit_per_day", 5000)))
        except (TypeError, ValueError):
            self.rate_limit_per_day = 5000
        try:
            self.cache_ttl_seconds = max(0, min(300, int(plugin_prefs.get("cache_ttl_seconds", 60))))
        except (TypeError, ValueError):
            self.cache_ttl_seconds = 60

        # Component instances
        self.data_provider = None
        self.mcp_handler = None
        self.auth_manager = AuthManager(logger=self.logger)

        # Device management
        self.mcp_server_device = None

        # Plugin start time (used by /health endpoint)
        self._start_time = time.time()

        # Set up logging properly
        self.log_level = int(plugin_prefs.get("log_level", logging.INFO))
        self.indigo_log_handler.setLevel(self.log_level)
        self.plugin_file_handler.setLevel(self.log_level)
        logging.getLogger("Plugin").setLevel(self.log_level)

    def test_connections(self) -> bool:
        """
        Test connections to required and optional services.

        Returns:
            True if all required connections are successful, False otherwise
        """
        all_required_connections_ok = True

        # Test Anthropic API key (required)
        try:
            if not self.anthropic_api_key:
                self.logger.error("\t❌ Anthropic API key not configured")
                all_required_connections_ok = False
            else:
                test_client = anthropic.Anthropic(api_key=self.anthropic_api_key)
                try:
                    resp = test_client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=10,
                        messages=[{"role": "user", "content": "Hi"}]
                    )
                    if resp and resp.content:
                        self.logger.info("\t✅ Anthropic API connected")
                    else:
                        self.logger.error("\t❌ Anthropic API returned invalid response")
                        all_required_connections_ok = False
                except Exception as api_error:
                    self.logger.error(f"\t❌ Anthropic API failed: {api_error}")
                    all_required_connections_ok = False

        except Exception as e:
            self.logger.error(f"\t❌ Anthropic connection failed: {e}")
            all_required_connections_ok = False

        # Test InfluxDB connection (optional, only if enabled)
        if self.enable_influxdb:
            try:
                from influxdb import InfluxDBClient

                # Validate InfluxDB configuration
                if not self.influx_url or not self.influx_port:
                    self.logger.warning("\t⚠️ InfluxDB enabled but not configured")
                else:
                    try:
                        port = int(self.influx_port)
                        client = InfluxDBClient(
                            host=self.influx_url.replace("http://", "").replace(
                                "https://", ""
                            ),
                            port=port,
                            username=self.influx_login if self.influx_login else None,
                            password=(
                                self.influx_password if self.influx_password else None
                            ),
                            database=self.influx_database,
                            timeout=10,
                        )

                        # Test connection with ping
                        result = client.ping()
                        if result:
                            self.logger.info("\t✅ InfluxDB connected (historical data available)")
                        else:
                            self.logger.warning("\t⚠️ InfluxDB ping failed")

                        client.close()

                    except ValueError as ve:
                        self.logger.warning(f"\t⚠️ InfluxDB port error: {ve}")
                    except Exception as influx_error:
                        self.logger.warning(f"\t⚠️ InfluxDB connection failed: {influx_error}")

            except ImportError:
                self.logger.warning("\t⚠️ InfluxDB library not available")
            except Exception as e:
                self.logger.warning(f"\t⚠️ InfluxDB connection failed: {e}")

        return all_required_connections_ok

    def check_cpu_compatibility(self) -> bool:
        """
        Check and log CPU architecture information.

        Note: LanceDB requires Intel Haswell (2013+) or Apple Silicon processors with AVX2 support.
        However, this check is informational only - the plugin will attempt to start regardless.

        Returns:
            Always returns True to allow plugin to start
        """
        machine = platform.machine()

        # Apple Silicon Macs are always compatible
        if machine == 'arm64':
            self.logger.debug("✅ Apple Silicon detected (M1/M2/M3/M4)")
            return True

        # Log info for Intel Macs
        if machine == 'x86_64':
            self.logger.info("Intel Mac detected - LanceDB requires AVX2 CPU support (Intel Haswell 2013+ or newer)")
            self.logger.info("If the plugin fails to start, your CPU may not support AVX2 instructions")
            return True

        # Unknown architecture - log warning but continue
        self.logger.warning(f"⚠️ Unknown CPU architecture: {machine}")
        self.logger.warning("   Plugin will attempt to start. If it fails, check system requirements.")
        return True

    def _get_mcp_client_urls(self) -> list:
        """
        Detect and return all available URLs for MCP client connections.

        Returns a list of dicts with 'label', 'url', and 'config' keys for each access method:
        - localhost URL (always available)
        - hostname-based URL (if detectable)
        - IP address-based URLs (all non-localhost IPs)
        - Indigo Reflector URL (if configured)

        :return: List of URL dicts [{"label": "...", "url": "...", "config": {...}}, ...]
        """
        urls = []
        indigo_port = 8176  # Default Indigo web server port
        path = "/message/com.clives.indigoplugin.claudebridge/mcp/"

        # Helper function to generate Claude Desktop config for a given URL
        def make_config(url):
            return {
                "mcpServers": {
                    "indigo": {
                        "command": "npx",
                        "args": [
                            "mcp-remote",
                            url
                        ]
                    }
                }
            }

        # Always add localhost URL
        localhost_url = f"http://localhost:{indigo_port}{path}"
        urls.append({
            "label": "Local",
            "url": localhost_url,
            "config": make_config(localhost_url)
        })

        try:
            # Get hostname and add hostname-based URL
            hostname = socket.gethostname()
            if hostname and hostname != "localhost":
                hostname_url = f"http://{hostname}:{indigo_port}{path}"
                urls.append({
                    "label": "Network (hostname)",
                    "url": hostname_url,
                    "config": make_config(hostname_url)
                })

            # Get all non-localhost IP addresses
            try:
                addr_info = socket.getaddrinfo(hostname, None, socket.AF_INET)
                seen_ips = set()
                for info in addr_info:
                    ip = info[4][0]
                    # Skip localhost IPs and duplicates
                    if not ip.startswith('127.') and ip not in seen_ips:
                        seen_ips.add(ip)
                        ip_url = f"http://{ip}:{indigo_port}{path}"
                        urls.append({
                            "label": "Network (IP)",
                            "url": ip_url,
                            "config": make_config(ip_url)
                        })
            except Exception as e:
                self.logger.debug(f"Could not detect network IPs: {e}")

        except Exception as e:
            self.logger.debug(f"Could not detect hostname: {e}")

        # Try to get Indigo Reflector URL if configured
        try:
            reflector_url = indigo.server.getReflectorURL()
            if reflector_url:
                # Remove trailing slash if present
                reflector_base = reflector_url.rstrip('/')
                reflector_full_url = f"{reflector_base}{path}"
                urls.append({
                    "label": "Remote (Reflector)",
                    "url": reflector_full_url,
                    "config": make_config(reflector_full_url)
                })
        except Exception as e:
            self.logger.debug(f"Could not detect Indigo Reflector URL: {e}")

        return urls

    ########################################
    def startup(self) -> None:
        """
        Called after __init__ when the plugin is starting up.
        """
        self.logger.info(f"Claude Bridge v{self.pluginVersion} ready")

        # Anthropic API key is already resolved in __init__ via ANTHROPIC_API_KEY
        # (IndigoSecrets.py) -> pluginPrefs.  If still empty, log an ERROR pointing the
        # user to either source — but don't crash; the plugin still hosts the MCP
        # endpoint, just refuses requests until the key is set.
        if not self.anthropic_api_key:
            self.logger.error(
                "[Config] No Anthropic API key configured. Set ANTHROPIC_API_KEY in "
                "/Library/Application Support/Perceptive Automation/IndigoSecrets.py "
                "OR fill in 'Anthropic API Key' under Plugins -> Claude Bridge -> "
                "Configure. Plugin will not be able to call Claude until this is set."
            )

        # Test connections (skips Anthropic test if key is empty)
        if self.anthropic_api_key and not self.test_connections():
            self.logger.error("\tRequired service connections failed - continuing in degraded mode")

        # Log CPU architecture information
        self.check_cpu_compatibility()

        # Publish runtime config to the in-process store so downstream MCP
        # modules can read credentials without us having to write them into
        # os.environ (which would leak to every subprocess we spawn — see
        # mcp_server/runtime_config.py for the full reasoning).
        db_path = os.path.join(
            indigo.server.getInstallFolderPath(),
            "Preferences/Plugins/com.clives.indigoplugin.claudebridge/vector_db",
        )
        runtime_config.configure(
            anthropic_api_key = self.anthropic_api_key,
            large_model       = self.large_model,
            small_model       = self.small_model,
            influxdb_enabled  = bool(self.enable_influxdb),
            influxdb_host     = self.influx_url.replace("http://", "").replace("https://", ""),
            influxdb_port     = int(self.influx_port) if str(self.influx_port).isdigit() else 8086,
            influxdb_username = self.influx_login,
            influxdb_password = self.influx_password,
            influxdb_database = self.influx_database,
            db_file           = db_path,
        )

        # Initialize data provider
        try:
            self.data_provider = IndigoDataProvider(logger=self.logger)
        except Exception as e:
            self.logger.error(f"\t❌ Data provider initialization failed: {e}")
            return

        # Initialize MCP handler (includes vector store initialization)
        try:
            scopes_file = os.path.join(
                indigo.server.getInstallFolderPath(),
                "Preferences/Plugins/com.clives.indigoplugin.claudebridge/scopes.json",
            )
            self.mcp_handler = MCPHandler(
                data_provider=self.data_provider,
                logger=self.logger,
                plugin=self,
                rate_limit_per_minute=self.rate_limit_per_minute,
                rate_limit_per_day=self.rate_limit_per_day,
                cache_ttl_seconds=self.cache_ttl_seconds,
                scopes_file=scopes_file,
            )

            # Log MCP client connection information
            self.logger.info("🌐 MCP Client Connection Information:")
            urls = self._get_mcp_client_urls()
            for url_info in urls:
                self.logger.info(f"   {url_info['label']}: {url_info['url']}")

            # Auto-create device if none exists — removes the manual "New Device" step
            try:
                existing = [d for d in indigo.devices.iter("self") if d.deviceTypeId == "mcpServer"]
                if not existing:
                    indigo.device.create(
                        protocol=indigo.kProtocol.Plugin,
                        name="Claude Bridge",
                        deviceTypeId="mcpServer",
                        pluginId=self.pluginId,
                        props={"serverName": "Claude Bridge"}
                    )
                    self.logger.info("\t✅ Claude Bridge device auto-created")
            except Exception as _dev_e:
                self.logger.warning(f"\t⚠️  Could not auto-create device: {_dev_e}")

            # Auto-configure Claude Code integration (proxy + ~/.mcp.json +
            # ~/.claude/settings.json edits).  Opt-in via PluginConfig — defaults
            # to True so existing users keep their current setup, but lets a user
            # disable silent dotfile rewriting if they manage these themselves.
            if self.pluginPrefs.get("auto_configure_claude_code", True):
                self._setup_claude_code_integration()
            else:
                self.logger.info("Claude Code auto-configure disabled in PluginConfig — skipping ~/.mcp.json and ~/.claude/settings.json updates")

            # Subscribe to device and variable changes for the events system
            try:
                indigo.devices.subscribeToChanges()
                indigo.variables.subscribeToChanges()
                self.logger.info("\t✅ Subscribed to device and variable change events")
            except Exception as _sub_e:
                self.logger.warning(f"\t⚠️  Could not subscribe to changes: {_sub_e}")

        except Exception as e:
            self.logger.error(f"\t❌ MCP handler initialization failed: {e}")
            self.mcp_handler = None
            self.logger.error("\t❌ MCP server unavailable - plugin restart required")
            return

    def _setup_claude_code_integration(self) -> None:
        """
        Copy the bundled proxy script to the standard Indigo Scripts directory,
        patch the Bearer token, and update ~/.mcp.json and ~/.claude/settings.json
        so Claude Code can connect without any manual Terminal steps.
        Called from startup() after MCP handler is ready.
        """
        import json as _json
        import re as _re
        import shutil as _shutil
        from pathlib import Path as _Path

        # Standard Indigo scripts directory — created if it doesn't exist
        scripts_dir = _Path("/Library/Application Support/Perceptive Automation/Scripts")

        bundle_proxy  = _Path(os.getcwd()) / "indigo_mcp_proxy.py"
        dest_proxy    = scripts_dir / "indigo_mcp_proxy.py"
        secrets_path  = _Path(indigo.server.getInstallFolderPath()) / "Preferences/secrets.json"
        mcp_json_path = _Path.home() / ".mcp.json"
        settings_path = _Path.home() / ".claude/settings.json"

        server_entry  = {"command": "python3", "args": [str(dest_proxy)]}
        changed       = []

        # 1. Copy proxy script from bundle and patch Bearer token
        # Token resolution order: Indigo IWS Preferences/secrets.json (master,
        # written by Indigo) -> CLAUDEBRIDGE_BEARER_TOKEN from IndigoSecrets.py.
        if bundle_proxy.exists():
            scripts_dir.mkdir(parents=True, exist_ok=True)
            _shutil.copy2(bundle_proxy, dest_proxy)

            token = ""
            if secrets_path.exists():
                try:
                    iws_secrets = _json.loads(secrets_path.read_text())
                    if isinstance(iws_secrets, list) and iws_secrets:
                        token = iws_secrets[0]
                except Exception as _e:
                    self.logger.warning(f"\tIWS secrets.json read failed: {_e}")
            if not token:
                token = CLAUDEBRIDGE_BEARER_TOKEN
            if not token:
                self.logger.error(
                    "[Config] No bearer token available to patch into the MCP proxy. "
                    "Indigo IWS Preferences/secrets.json is empty AND "
                    "CLAUDEBRIDGE_BEARER_TOKEN is not set in IndigoSecrets.py. "
                    "Claude Code will not be able to authenticate. "
                    "Generate an IWS bearer token in Indigo (Server -> Web Server -> "
                    "Manage Authentication) or add CLAUDEBRIDGE_BEARER_TOKEN to "
                    "/Library/Application Support/Perceptive Automation/IndigoSecrets.py."
                )
            else:
                try:
                    text     = dest_proxy.read_text(encoding="utf-8")
                    new_text = _re.sub(
                        r'^(BEARER_TOKEN\s*=\s*")[^"]*(")',
                        rf'\g<1>{token}\g<2>',
                        text, flags=_re.MULTILINE
                    )
                    dest_proxy.write_text(new_text, encoding="utf-8")
                except Exception as _e:
                    self.logger.error(f"[Config] Bearer token patch failed: {_e}")

            changed.append("proxy script")
        else:
            self.logger.warning("\tindigo_mcp_proxy.py not found in bundle — skipping proxy setup")

        # 2. Update ~/.mcp.json
        try:
            mcp_data = _json.loads(mcp_json_path.read_text()) if mcp_json_path.exists() else {}
            if mcp_data.get("mcpServers", {}).get("indigo-mcp") != server_entry:
                mcp_data.setdefault("mcpServers", {})["indigo-mcp"] = server_entry
                mcp_json_path.write_text(_json.dumps(mcp_data, indent=2) + "\n")
                changed.append("~/.mcp.json")
        except Exception as _e:
            self.logger.warning(f"\t⚠️  Could not update ~/.mcp.json: {_e}")

        # 3. Update ~/.claude/settings.json
        try:
            settings_data = _json.loads(settings_path.read_text()) if settings_path.exists() else {}
            enabled = settings_data.get("enabledMcpjsonServers", [])
            if "indigo-mcp" not in enabled:
                enabled.append("indigo-mcp")
                settings_data["enabledMcpjsonServers"] = enabled
                settings_path.parent.mkdir(parents=True, exist_ok=True)
                settings_path.write_text(_json.dumps(settings_data, indent=2) + "\n")
                changed.append("~/.claude/settings.json")
        except Exception as _e:
            self.logger.warning(f"\t⚠️  Could not update ~/.claude/settings.json: {_e}")

        if changed:
            self.logger.info(f"\t✅ Claude Code integration configured: {', '.join(changed)}")
            self.logger.info("\t   Restart Claude Code to activate the indigo-mcp tools")
        else:
            self.logger.info("\t✅ Claude Code integration already up to date")

    def shutdown(self) -> None:
        """
        Called when the plugin is being shut down.
        """
        self.logger.info("Stopping plugin...")

        # Clean up MCP handler
        if self.mcp_handler:
            try:
                self.mcp_handler.stop()
                self.logger.info("\t✅ MCP handler stopped")
            except Exception as e:
                self.logger.error(f"\t❌ Error stopping MCP handler: {e}")
            finally:
                self.mcp_handler = None

    # ────────────────────────────────────────────────────────────────────────
    # Mac sleep / wake — lightweight observability hooks.
    #
    # ClaudeBridge is request/response over IWS, with no persistent client
    # connections to manage (each MCP request opens its own HTTP transaction
    # via Indigo's web server). Sleep/wake therefore needs no operational
    # cleanup — IWS itself goes dark on sleep and comes back on wake. The
    # value here is purely diagnostic: a clear log marker so future
    # "claude-code couldn't reach the server between X and Y" investigations
    # can correlate the gap with the Mac sleeping rather than hunting for
    # a fault. Vector store manager is left running (its SQLite backend
    # survives sleep fine; no background thread holds external resources).
    # ────────────────────────────────────────────────────────────────────────
    def prepare_to_sleep(self) -> None:
        self.logger.info("Mac going to sleep — MCP endpoint will be unreachable until wake")
        super().prepare_to_sleep()
    prepareToSleep = prepare_to_sleep

    def wake_up(self) -> None:
        super().wake_up()
        self.logger.info("Mac woke — MCP endpoint reachable again")
    wakeUp = wake_up

    ########################################
    # MCP Endpoint Handler for IWS
    ########################################
    
    def handle_mcp_endpoint(self, action, dev=None, callerWaitingForResult=True):
        """
        Handle MCP requests through Indigo IWS.
        This method is called when the /message/<plugin_id>/mcp/ endpoint is accessed.

        Args:
            action: Indigo action containing request details
            dev: Optional device reference
            callerWaitingForResult: Whether caller is waiting for result

        Returns:
            Dict with status, headers, and content for IWS response
        """
        # Extract request details
        method = (action.props.get("incoming_request_method") or "").upper()
        headers = dict(action.props.get("headers", {}))
        body = action.props.get("request_body") or ""

        # Validate MCP handler is available
        if not self.mcp_handler:
            self.logger.error("❌ MCP handler not initialized")
            return {
                "status": 503,  # Service Unavailable
                "headers": {"Content-Type": "application/json"},
                "content": json.dumps({
                    "error": "MCP server unavailable - plugin initialization failed"
                })
            }

        # Delegate to MCP handler (it will handle logging)
        try:
            response = self.mcp_handler.handle_request(method, headers, body)
            return response

        except Exception as e:
            self.logger.error(f"❌ MCP endpoint error: {e}")
            return {
                "status": 500,
                "content": json.dumps({"error": str(e)})
            }

    ########################################
    # Health / Diagnostics IWS endpoint
    ########################################

    def handle_health_endpoint(self, action, dev=None, callerWaitingForResult=True):
        """
        GET /message/com.clives.indigoplugin.claudebridge/health/
        Returns plugin uptime, session count, tool inventory and recent
        tool-call latencies as JSON. Cheap to call — safe for monitors.
        """
        if not self.mcp_handler:
            return {
                "status": 503,
                "headers": {"Content-Type": "application/json"},
                "content": json.dumps({
                    "status": "unavailable",
                    "error":  "MCP handler not initialized",
                }),
            }
        try:
            data = self.mcp_handler.get_health_data(plugin_start_time=self._start_time)
            return {
                "status":  200,
                "headers": {"Content-Type": "application/json; charset=utf-8"},
                "content": json.dumps(data, default=str, indent=2),
            }
        except Exception as e:
            self.logger.error(f"❌ Health endpoint error: {e}")
            return {
                "status":  500,
                "headers": {"Content-Type": "application/json"},
                "content": json.dumps({"status": "error", "error": str(e)}),
            }

    ########################################
    # Tool Explorer IWS endpoint (HTML)
    ########################################

    def handle_explorer_endpoint(self, action, dev=None, callerWaitingForResult=True):
        """
        GET /message/com.clives.indigoplugin.claudebridge/explorer/
        Returns an interactive HTML page documenting every registered MCP tool
        — its description, arguments, and required fields. Useful for users,
        plugin testers, and debugging during development.
        """
        if not self.mcp_handler:
            return {
                "status":  503,
                "headers": {"Content-Type": "text/html"},
                "content": "<h1>Claude Bridge unavailable</h1><p>MCP handler not initialized.</p>",
            }
        try:
            mcp_endpoint = "/message/com.clives.indigoplugin.claudebridge/mcp/"
            html = self.mcp_handler.get_tool_explorer_html(endpoint_url=mcp_endpoint)
            return {
                "status":  200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "content": html,
            }
        except Exception as e:
            self.logger.error(f"❌ Explorer endpoint error: {e}")
            return {
                "status":  500,
                "headers": {"Content-Type": "text/html"},
                "content": f"<h1>Internal error</h1><pre>{e}</pre>",
            }

    ########################################
    # Menu Actions
    ########################################

    def scaffold_scopes_menu(self) -> None:
        """Create a starter scopes.json next to the plugin Preferences. Idempotent."""
        from pathlib import Path as _Path
        scopes_path = _Path(indigo.server.getInstallFolderPath()) / (
            "Preferences/Plugins/com.clives.indigoplugin.claudebridge/scopes.json"
        )
        if scopes_path.exists():
            indigo.server.log(f"Claude Bridge: scopes.json already exists at: {scopes_path}")
            return
        starter = {
            "default_scopes": ["read", "write", "admin"],
            "tokens": {
                "REPLACE_WITH_FULL_BEARER_TOKEN_FOR_CLAUDE_CODE": {
                    "name":   "claude-code",
                    "scopes": ["read", "write", "admin"]
                },
                "REPLACE_WITH_BEARER_FOR_PHONE_OR_OTHER_CLIENT": {
                    "name":   "phone-readonly",
                    "scopes": ["read"]
                }
            }
        }
        try:
            scopes_path.parent.mkdir(parents=True, exist_ok=True)
            scopes_path.write_text(json.dumps(starter, indent=2) + "\n")
            indigo.server.log(f"Claude Bridge: Wrote starter scopes.json to: {scopes_path}")
            indigo.server.log("Claude Bridge: Edit the token strings to match your IWS bearer "
                              "tokens, then use 'Reload scopes.json' to apply.")
        except Exception as e:
            indigo.server.log(f"Claude Bridge: Could not create scopes.json: {e}", isError=True)

    def reload_scopes_menu(self) -> None:
        """Reload scopes.json without restarting the plugin."""
        if not self.mcp_handler:
            indigo.server.log("Claude Bridge: MCP handler not initialized", isError=True)
            return
        ok = self.mcp_handler.scope_manager.reload()
        if ok:
            summary = self.mcp_handler.scope_manager.summary()
            indigo.server.log(
                f"Claude Bridge: scopes.json reloaded — {summary['tokens_configured']} token(s), "
                f"default={summary['default_scopes']}"
            )
        else:
            indigo.server.log("Claude Bridge: scopes.json missing or invalid — using defaults")

    def clear_cache_menu(self) -> None:
        """Drop every cached read-tool result."""
        if not self.mcp_handler:
            indigo.server.log("Claude Bridge: MCP handler not initialized", isError=True)
            return
        n = self.mcp_handler.tool_cache.clear()
        indigo.server.log(f"Claude Bridge: Cleared {n} cached tool result(s)")

    def show_health_menu(self) -> None:
        """Menu action: print health snapshot to the Indigo log."""
        if not self.mcp_handler:
            indigo.server.log("Claude Bridge: MCP handler not initialized", isError=True)
            return
        try:
            data = self.mcp_handler.get_health_data(plugin_start_time=self._start_time)
            indigo.server.log("Claude Bridge — Health Snapshot:\n" +
                              json.dumps(data, default=str, indent=2))
        except Exception as e:
            indigo.server.log(f"Claude Bridge: Health snapshot failed: {e}", isError=True)

    def show_explorer_url_menu(self) -> None:
        """Menu action: print the tool explorer URL(s) to the Indigo log."""
        urls = self._get_mcp_client_urls()
        explorer_path = "/message/com.clives.indigoplugin.claudebridge/explorer/"
        lines = ["Claude Bridge — Tool Explorer URLs:", ""]
        for u in urls:
            base = u["url"].rsplit("/message/", 1)[0]
            lines.append(f"   {u['label']}: {base}{explorer_path}")
        lines += [
            "",
            "Open in any browser. IWS authentication required (your IWS credentials or local secret).",
        ]
        indigo.server.log("\n".join(lines))

    def show_mcp_client_info_menu(self) -> None:
        """Menu action to show Claude Desktop MCP client connection information."""
        # Get all available connection URLs
        urls = self._get_mcp_client_urls()

        config_lines = [
            "🌐 Claude Desktop MCP Client Connection Information:",
            "",
            "⚠️  AUTHENTICATION REQUIRED: All configurations require a Bearer token with an Indigo API key.",
            "",
            "📚 In all cases, you will need an API Key. For this, you have two choices:",
            "  • Indigo Reflector API Key: Obtained from your Reflector settings",
            "  • Local Secret: Created in secrets.json file",
            "    Location: /Library/Application Support/Perceptive Automation/Indigo [VERSION]/Preferences/secrets.json",
            "    Details: https://wiki.indigodomo.com/doku.php?id=indigo_2024.2_documentation:indigo_web_server#local_secrets",
            "    Note: Restart Indigo Web Server after creating/modifying this file",
            "",
            "=" * 80,
            "",
            "🔧 SCENARIO 1: HTTPS via Reflector (Most Common, Enables remote access outside your home)",
            "   • Use when: Accessing Indigo from outside your local network",
            "   • Security: Encrypted connection with valid SSL certificate",
            ""
        ]

        # Find reflector URL for Scenario 1
        reflector_url = next((u for u in urls if u['label'] == 'Remote (Reflector)'), None)
        if reflector_url:
            scenario1_config = {
                "mcpServers": {
                    "indigo": {
                        "command": "npx",
                        "args": [
                            "-y",
                            "mcp-remote",
                            reflector_url['url'],
                            "--header",
                            "Authorization:Bearer YOUR_REFLECTOR_API_KEY"
                        ]
                    }
                }
            }
            config_lines.append(json.dumps(scenario1_config, indent=2))
            config_lines.extend(["", "Setup:", "  1. Configure Indigo Reflector in Web Server Settings", "  2. Use your Reflector API key", "  3. Replace YOUR_REFLECTOR_API_KEY with your Reflector API key", ""])
        else:
            config_lines.extend([
                "⚠️  Reflector not configured. Configure at Indigo > Web Server Settings > Reflector",
                "   Example URL: https://your-reflector-url.indigodomo.net/message/com.clives.indigoplugin.claudebridge/mcp/"
            ])
        config_lines.extend(["", ""])

        config_lines.extend([
            "=" * 80,
            "",
            "🔧 SCENARIO 2: HTTPS on LAN with Self-Signed Certificate",
            ""
        ])

        # Find IP or hostname URL for Scenario 2
        network_url = next((u for u in urls if u['label'] in ['Network (IP)', 'Network (hostname)']), None)
        if network_url:
            # Convert HTTP URL to HTTPS for this scenario
            https_url = network_url['url'].replace('http://', 'https://')
            scenario2_config = {
                "mcpServers": {
                    "indigo": {
                        "command": "npx",
                        "args": [
                            "-y",
                            "mcp-remote",
                            https_url,
                            "--header",
                            "Authorization:Bearer YOUR_LOCAL_SECRET_KEY"
                        ],
                        "env": {
                            "NODE_TLS_REJECT_UNAUTHORIZED": "0"
                        }
                    }
                }
            }
            config_lines.append(json.dumps(scenario2_config, indent=2))
            config_lines.extend(["", "Setup:", "  1. Create a local secret (see documentation link above)", "  2. Replace your-local-hostname-or-ip with your Indigo server IP/hostname", "  3. Replace YOUR_LOCAL_SECRET_KEY with your generated local secret", "  4. NODE_TLS_REJECT_UNAUTHORIZED=0 disables certificate validation (required)", "  5. Replace port 8176 if you are not using the default Indigo Web Server port", ""])
        config_lines.extend(["", ""])

        config_lines.extend([
            "=" * 80,
            "",
            "🔧 SCENARIO 3: HTTP on Local/LAN",
            "   • Use when: HTTPS is disabled on your Indigo Web Server",
            ""
        ])

        # Find IP or hostname URL for Scenario 3 (use same network_url as Scenario 2)
        if network_url:
            scenario3_config = {
                "mcpServers": {
                    "indigo": {
                        "command": "npx",
                        "args": [
                            "-y",
                            "mcp-remote",
                            network_url['url'],
                            "--allow-http",
                            "--header",
                            "Authorization:Bearer YOUR_LOCAL_SECRET_KEY"
                        ]
                    }
                }
            }
            config_lines.append(json.dumps(scenario3_config, indent=2))
            config_lines.extend(["", "Setup:", "  1. Create a local secret (see documentation link above)", "  2. Replace YOUR_LOCAL_SECRET_KEY with your generated local secret", "  3. Replace your-local-hostname-or-ip with your server IP/hostname for LAN access", "  4. Replace port 8176 if you are not using the default Indigo Web Server port", ""])
        config_lines.extend(["", ""])

        indigo.server.log("\n".join(config_lines))

    def test_connections_button(self, values_dict: indigo.Dict) -> indigo.Dict:
        """Button action to test connections with current configuration values."""
        self.logger.info("Testing connections with current configuration...")

        # Temporarily update instance variables with dialog values for testing
        old_api_key = self.anthropic_api_key
        old_enable_influxdb = self.enable_influxdb
        old_influx_url = self.influx_url
        old_influx_port = self.influx_port
        old_influx_login = self.influx_login
        old_influx_password = self.influx_password
        old_influx_database = self.influx_database

        try:
            # Apply dialog values, falling back to IndigoSecrets.py for empty fields
            # (matches the resolution order used everywhere else in the plugin).
            self.anthropic_api_key = ANTHROPIC_API_KEY or values_dict.get("anthropic_api_key", "")
            self.enable_influxdb   = values_dict.get("enable_influxdb", False)
            _influx_url            = (INFLUXDB_HOST or values_dict.get("influx_url", "")).strip()
            self.influx_url        = _influx_url.replace("http://", "").replace("https://", "") or "localhost"
            self.influx_port       = str(INFLUXDB_PORT or values_dict.get("influx_port", "8086"))
            self.influx_login      = INFLUXDB_USERNAME or values_dict.get("influx_login", "")
            self.influx_password   = INFLUXDB_PASSWORD or values_dict.get("influx_password", "")
            self.influx_database   = INFLUXDB_DATABASE or values_dict.get("influx_database", "indigo")

            # Test connections
            connections_ok = self.test_connections()

            if connections_ok:
                self.logger.info("✅ All required connections tested successfully!")
            else:
                self.logger.error(
                    "❌ Some required connections failed. Please check the logs above."
                )

        finally:
            # Restore original values
            self.anthropic_api_key = old_api_key
            self.enable_influxdb = old_enable_influxdb
            self.influx_url = old_influx_url
            self.influx_port = old_influx_port
            self.influx_login = old_influx_login
            self.influx_password = old_influx_password
            self.influx_database = old_influx_database

        return values_dict

    ########################################
    # Configuration UI Validation
    ########################################

    def validatePrefsConfigUi(self, values_dict: indigo.Dict) -> tuple:
        """
        Validate plugin configuration.

        :param values_dict: the values dictionary to validate
        :return: (True/False, values_dict, errors_dict)
        """
        errors_dict = indigo.Dict()

        # Validate Anthropic API key — blank is OK if IndigoSecrets.py provides it
        api_key = values_dict.get("anthropic_api_key", "")
        if not api_key and not ANTHROPIC_API_KEY:
            errors_dict["anthropic_api_key"] = "Enter an Anthropic API key (or add ANTHROPIC_API_KEY to IndigoSecrets.py)"


        # Validate log level
        try:
            log_level = int(values_dict.get("log_level", 20))
            if log_level not in [5, 10, 20, 30, 40, 50]:
                errors_dict["log_level"] = "Invalid log level"
        except (ValueError, TypeError):
            errors_dict["log_level"] = "Log level must be a valid number"

        # Phase 2 — rate limit / cache TTL bounds
        for fld, lo, hi, default in (
            ("rate_limit_per_minute", 1,    100_000, 120),
            ("rate_limit_per_day",    1, 10_000_000, 5_000),
            ("cache_ttl_seconds",     0,        300, 60),
        ):
            try:
                v = int(values_dict.get(fld, default))
                if v < lo or v > hi:
                    errors_dict[fld] = f"Must be between {lo} and {hi}"
            except (ValueError, TypeError):
                errors_dict[fld] = "Must be a whole number"

        # Validate InfluxDB configuration if enabled
        if values_dict.get("enable_influxdb", False):
            influx_url = values_dict.get("influx_url", "").strip()
            influx_port = values_dict.get("influx_port", "").strip()
            influx_database = values_dict.get("influx_database", "").strip()

            if not influx_url:
                errors_dict["influx_url"] = (
                    "InfluxDB URL is required when InfluxDB is enabled"
                )
            elif not (
                influx_url.startswith("http://") or influx_url.startswith("https://")
            ):
                errors_dict["influx_url"] = (
                    "InfluxDB URL must start with http:// or https://"
                )

            if not influx_port:
                errors_dict["influx_port"] = (
                    "InfluxDB port is required when InfluxDB is enabled"
                )
            else:
                try:
                    port = int(influx_port)
                    if port < 1 or port > 65535:
                        errors_dict["influx_port"] = (
                            "InfluxDB port must be between 1 and 65535"
                        )
                except (ValueError, TypeError):
                    errors_dict["influx_port"] = "InfluxDB port must be a valid number"

            if not influx_database:
                errors_dict["influx_database"] = (
                    "InfluxDB database name is required when InfluxDB is enabled"
                )

        return (len(errors_dict) == 0, values_dict, errors_dict)

    ########################################
    # Plugin Event System (claudeEvent triggers)
    ########################################

    def triggerStartProcessing(self, trigger):
        """Indigo lifecycle: a trigger configured against this plugin was enabled.

        Store the trigger object so fire_claude_event() can fire it via
        indigo.trigger.execute() — that API requires a trigger OBJECT, not a
        string event ID.  Neither indigo.server.fireEvent() nor
        self.triggerEvent() exist on PluginBase; both raise AttributeError.
        """
        self.event_triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        """Indigo lifecycle: trigger disabled or deleted."""
        self.event_triggers.pop(trigger.id, None)

    def fire_claude_event(self, event_name: str, data=None, source: str = "claude") -> dict:
        """
        Fire all claudeEvent triggers via the standard PluginBase lifecycle:
        iterate self.event_triggers (populated by triggerStartProcessing) and
        execute every trigger whose pluginTypeId matches the Events.xml event ID.

        Inside the user's Trigger actions, the payload is accessible as:
            %%eventData:name%%   %%eventData:data%%   %%eventData:source%%
        Per-trigger filtering is done via Trigger Conditions checking those
        substitutions (Indigo's standard mechanism — no custom code needed).

        Returns a small dict the MCP tool serialises back to Claude.
        """
        # data: serialise dicts/lists; preserve falsy non-None scalars (0, False)
        if isinstance(data, (dict, list)):
            data_str = json.dumps(data)
        elif data is None:
            data_str = ""
        else:
            data_str = str(data)

        payload = {
            "name":   event_name or "",
            "data":   data_str,
            "source": source or "claude",
        }

        fired = 0
        for trigger in self.event_triggers.values():
            if trigger.pluginTypeId == "claudeEvent":
                try:
                    indigo.trigger.execute(trigger)
                    fired += 1
                except Exception as e:
                    self.logger.error(f"[Trigger] execute failed for claudeEvent (id={trigger.id}): {e}")

        if fired:
            self.logger.info(f"fire_claude_event '{event_name}' fired {fired} trigger(s) (source={source})")
        else:
            self.logger.info(f"fire_claude_event '{event_name}' — no Indigo triggers configured for claudeEvent")
        return {"event": event_name, "payload": payload, "triggers_fired": fired}

    ########################################
    # Device Management
    ########################################

    def deviceStartComm(self, device: indigo.Device) -> None:
        """
        Called when a device should start communication.
        """
        if device.deviceTypeId == "mcpServer":
            self.logger.info(f"MCP Server device started: {device.name}")
            # Store reference to device
            self.mcp_server_device = device

            # Update device states only if changed — avoids Event Log spam and DB churn
            updates = []
            if device.states.get("serverStatus") != "Running":
                updates.append({"key": "serverStatus", "value": "Running"})
            if device.states.get("accessMode") != "IWS":
                updates.append({"key": "accessMode", "value": "IWS"})
            new_activity = str(indigo.server.getTime())
            if device.states.get("lastActivity") != new_activity:
                updates.append({"key": "lastActivity", "value": new_activity})
            if updates:
                device.updateStatesOnServer(updates)

    def deviceStopComm(self, device: indigo.Device) -> None:
        """
        Called when a device should stop communication.
        """
        if device.deviceTypeId == "mcpServer":
            self.logger.info(f"MCP Server device stopped: {device.name}")
            # Update device state only if changed
            if device.states.get("serverStatus") != "Stopped":
                device.updateStateOnServer(key="serverStatus", value="Stopped")

            # Clear device reference
            if self.mcp_server_device and self.mcp_server_device.id == device.id:
                self.mcp_server_device = None

    @staticmethod
    def didDeviceCommPropertyChange(oldDevice, newDevice):
        """Restart comm only when the MCP server identity changes.

        serverName is the only user-editable prop on the mcpServer device
        type; nothing else justifies a stop/start cycle.
        """
        return oldDevice.pluginProps.get("serverName") != newDevice.pluginProps.get("serverName")

    def variableUpdated(self, origVar: indigo.Variable, newVar: indigo.Variable) -> None:
        """
        Called when an Indigo variable value changes.
        Queues the event for any active Claude subscriptions.
        """
        if (
            self.mcp_handler
            and hasattr(self.mcp_handler, "events_handler")
            and origVar.value != newVar.value
        ):
            try:
                self.mcp_handler.events_handler.queue_event({
                    "type":      "variable_updated",
                    "id":        newVar.id,
                    "name":      newVar.name,
                    "old_value": origVar.value,
                    "new_value": newVar.value,
                })
            except Exception:
                pass

    def deviceUpdated(self, origDev: indigo.Device, newDev: indigo.Device) -> None:
        """
        Called when a device state or configuration is updated.
        Queues state-change events for any active Claude subscriptions,
        then handles mcpServer-specific configuration tracking.

        Loop-guard: this plugin both subscribeToChanges() AND writes to its own
        mcpServer device states (via deviceStartComm/deviceUpdated below).
        Without this guard, every state write fires deviceUpdated again -> any
        future state write inside the mcpServer branch would loop.  Per-device
        self-checks aren't sufficient if the plugin ever has more than one
        device — block the whole pluginId at the top.
        """
        if newDev.pluginId == self.pluginId:
            # Still process mcpServer config tracking for our own device, but
            # skip the events-queue path entirely (no MCP subscriber wants
            # change events from the bridge device itself).
            if newDev.deviceTypeId == "mcpServer":
                self._handle_mcp_server_device_update(origDev, newDev)
            return

        # Queue event for the events system (all non-plugin devices)
        if (
            self.mcp_handler
            and hasattr(self.mcp_handler, "events_handler")
            and newDev.deviceTypeId != "mcpServer"
        ):
            try:
                changed_states = {
                    k: {"old": origDev.states.get(k), "new": v}
                    for k, v in newDev.states.items()
                    if origDev.states.get(k) != v
                }
                if changed_states:
                    self.mcp_handler.events_handler.queue_event({
                        "type":           "device_updated",
                        "id":             newDev.id,
                        "name":           newDev.name,
                        "changed_states": changed_states,
                    })
            except Exception:
                pass

        if newDev.deviceTypeId == "mcpServer":
            self._handle_mcp_server_device_update(origDev, newDev)

    def _handle_mcp_server_device_update(self, origDev, newDev):
        """Track config changes on the plugin's own mcpServer device.

        Pulled out of deviceUpdated() so it can be called from the loop-guard
        early-return path too — see deviceUpdated() docstring.
        """
        changes = []

        # Check property changes (actual configuration)
        for key in newDev.pluginProps:
            old_val = origDev.pluginProps.get(key)
            new_val = newDev.pluginProps.get(key)
            if old_val != new_val:
                changes.append(f"property '{key}': '{old_val}' -> '{new_val}'")

        # Check state changes (runtime status)
        for key in newDev.states:
            if key in origDev.states:
                old_val = origDev.states[key]
                new_val = newDev.states[key]
                if old_val != new_val:
                    changes.append(f"state '{key}': '{old_val}' -> '{new_val}'")

        # Check device name change
        if origDev.name != newDev.name:
            changes.append(f"device name: '{origDev.name}' -> '{newDev.name}'")

        if changes:
            self.logger.debug(f"MCP Server device '{newDev.name}' updated: {', '.join(changes)}")

        # Access-mode change is important — log at INFO
        old_access_mode = origDev.pluginProps.get("server_access_mode", "local_only")
        new_access_mode = newDev.pluginProps.get("server_access_mode", "local_only")
        if old_access_mode != new_access_mode:
            self.logger.info(f"Access mode changed from {old_access_mode} to {new_access_mode}")

    def validateDeviceConfigUi(
        self, valuesDict: indigo.Dict, typeId: str, devId: int
    ) -> tuple:
        """
        Validate device configuration.
        """
        errors_dict = indigo.Dict()

        if typeId == "mcpServer":
            # Enforce single MCP Server device
            if self._count_mcp_server_devices(exclude_id=devId) > 0:
                errors_dict["serverName"] = (
                    "Only one MCP Server device is allowed per plugin"
                )

            # Validate server name
            server_name = valuesDict.get("serverName", "").strip()
            if not server_name:
                errors_dict["serverName"] = "Server name is required"

        return (len(errors_dict) == 0, valuesDict, errors_dict)

    def _count_mcp_server_devices(self, exclude_id: int = None) -> int:
        """
        Count the number of MCP Server devices, optionally excluding one by ID.
        """
        count = 0
        for device in indigo.devices.iter(filter="self"):
            if device.deviceTypeId == "mcpServer" and device.id != exclude_id:
                count += 1
        return count

    def _get_mcp_server_device(self) -> indigo.Device:
        """
        Get the single MCP Server device, if it exists.
        """
        for device in indigo.devices.iter(filter="self"):
            if device.deviceTypeId == "mcpServer":
                return device
        return None

    # Server management methods removed - MCP is always available via IWS
    

    def closedPrefsConfigUi(
        self, values_dict: indigo.Dict, user_cancelled: bool
    ) -> None:
        """
        Called when the plugin configuration dialog is closed.

        :param values_dict: the values dictionary
        :param user_cancelled: True if the user cancelled the dialog
        """
        if not user_cancelled:
            self.logger.info("Applying configuration changes...")

            # Update ALL configuration values from the dialog
            self.log_level = int(values_dict.get("log_level", 20))
            self.indigo_log_handler.setLevel(self.log_level)
            self.plugin_file_handler.setLevel(self.log_level)
            logging.getLogger("Plugin").setLevel(self.log_level)

            # Core configuration — IndigoSecrets.py first, dialog as fallback (matches
            # the standard resolution order documented in feedback_secrets_policy.md)
            self.anthropic_api_key = ANTHROPIC_API_KEY or values_dict.get("anthropic_api_key", "")
            self.large_model       = values_dict.get("large_model", "claude-sonnet-4-6")
            self.small_model       = values_dict.get("small_model", "claude-haiku-4-5-20251001")

            # Security configuration
            self.access_mode       = values_dict.get("access_mode", "local_only")

            # InfluxDB configuration — IndigoSecrets.py first, dialog fallback
            self.enable_influxdb   = values_dict.get("enable_influxdb", False)
            _influx_url            = (INFLUXDB_HOST or values_dict.get("influx_url", "")).strip()
            self.influx_url        = _influx_url.replace("http://", "").replace("https://", "") or "localhost"
            self.influx_port       = str(INFLUXDB_PORT or values_dict.get("influx_port", "8086"))
            self.influx_login      = INFLUXDB_USERNAME or values_dict.get("influx_login", "")
            self.influx_password   = INFLUXDB_PASSWORD or values_dict.get("influx_password", "")
            self.influx_database   = INFLUXDB_DATABASE or values_dict.get("influx_database", "indigo")

            # Phase 2 — apply rate-limit / cache changes live (no restart needed)
            try:
                self.rate_limit_per_minute = max(1, int(values_dict.get("rate_limit_per_minute", 120)))
                self.rate_limit_per_day    = max(1, int(values_dict.get("rate_limit_per_day", 5000)))
                self.cache_ttl_seconds     = max(0, min(300, int(values_dict.get("cache_ttl_seconds", 60))))
                if self.mcp_handler:
                    self.mcp_handler.rate_limiter.per_minute = self.rate_limit_per_minute
                    self.mcp_handler.rate_limiter.per_day    = self.rate_limit_per_day
                    self.mcp_handler.tool_cache.set_ttl(self.cache_ttl_seconds)
                    self.logger.info(
                        f"\t✅ Rate limits updated: {self.rate_limit_per_minute}/min, "
                        f"{self.rate_limit_per_day}/day; cache TTL {self.cache_ttl_seconds}s"
                    )
            except Exception as _e:
                self.logger.warning(f"\t⚠️  Could not apply Phase 2 settings: {_e}")


            # Republish runtime config (same as startup — see runtime_config.py
            # for why we avoid os.environ for credentials).
            db_path = os.path.join(
                indigo.server.getInstallFolderPath(),
                "Preferences/Plugins/com.clives.indigoplugin.claudebridge/vector_db",
            )
            runtime_config.configure(
                anthropic_api_key = self.anthropic_api_key,
                large_model       = self.large_model,
                small_model       = self.small_model,
                influxdb_enabled  = bool(self.enable_influxdb),
                influxdb_host     = self.influx_url.replace("http://", "").replace("https://", ""),
                influxdb_port     = int(self.influx_port) if str(self.influx_port).isdigit() else 8086,
                influxdb_username = self.influx_login,
                influxdb_password = self.influx_password,
                influxdb_database = self.influx_database,
                db_file           = db_path,
            )

            # Test connections with new configuration
            self.logger.info("Testing connections with new configuration...")
            connections_ok = self.test_connections()

            if not connections_ok:
                self.logger.error(
                    "⚠️ Some required connections failed. Configuration saved."
                )
                self.logger.error(
                    "Please check your configuration and restart the plugin manually."
                )
                return

            self.logger.info(
                "✅ Configuration updated successfully. Changes will take effect on next MCP request."
            )

            # No server restart needed - MCP runs via Indigo Web Server
            # Configuration changes (environment variables) are already applied above
            # and will be picked up by handlers on next request

    ########################################
    # Menu callbacks
    ########################################

    def showPluginInfo(self, valuesDict=None, typeId=None):
        """Re-run the startup banner on demand from the Plugins menu."""
        if log_startup_banner:
            extras = []
            try:
                urls = self._get_mcp_client_urls() if hasattr(self, "_get_mcp_client_urls") else []
                if urls:
                    extras.append(("MCP Local URL:", urls[0].get("url", "")))
            except Exception:
                pass
            extras.append(("Tools:", "64+"))
            extras.append(("Anthropic Key:", "configured" if self.anthropic_api_key else "MISSING"))
            extras.append(("InfluxDB:", "enabled" if self.enable_influxdb else "disabled"))
            extras.append(("Access Mode:", str(self.access_mode)))
            extras.append(("Timestamps in Log:", "ON" if self.timestamp_enabled else "OFF"))
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion, extras=extras)
        else:
            indigo.server.log(f"{self.pluginDisplayName} v{self.pluginVersion}")

    def menuToggleTimestamps(self):
        self.timestamp_enabled = not self.timestamp_enabled
        self.pluginPrefs["timestampEnabled"] = self.timestamp_enabled
        if self._ts_filter:
            self._ts_filter.enabled = self.timestamp_enabled
        state = "ON" if self.timestamp_enabled else "OFF"
        indigo.server.log(f"[{self.pluginDisplayName}] Timestamps in Log -> {state}")
