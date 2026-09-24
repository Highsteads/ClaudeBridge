#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: Claude Bridge - exposes Indigo to Claude over the Model Context Protocol (MCP)
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     3.2.1

try:
    import indigo
except ImportError:
    pass

import json
import logging
import os
import socket
import time

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

CLAUDEBRIDGE_BEARER_TOKEN = _get_secret("CLAUDEBRIDGE_BEARER_TOKEN")
WEBHOOK_ALLOWLIST         = _get_secret("WEBHOOK_ALLOWLIST", [])

# Import our modules
from mcp_server import client_setup, orphan_prefs, runtime_config
from mcp_server.adapters.indigo_data_provider import IndigoDataProvider
from mcp_server.common.entity_index import index_fields_changed
from mcp_server.mcp_handler import MCPHandler
from mcp_server.webhooks import SubscriptionStore, SubscriptionManager, WebhookDispatcher
from mcp_server.webhooks.allowlist_loader import load_allowlist
from mcp_server.tools.webhooks import WebhookHandler
# The bundled copy, imported directly: it always carries as_bool, whereas the
# shared master loaded above for the banner may be an older one on another Mac.
from plugin_utils import as_bool


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

        self.timestamp_enabled = as_bool(plugin_prefs.get("timestampEnabled"), True)
        if install_timestamp_filter:
            self._ts_filter = install_timestamp_filter(self, enabled=self.timestamp_enabled)
        else:
            self._ts_filter = None

        # Startup banner moved to showPluginInfo on demand (revised 25-May-2026
        # following Indigo's plugin-logging guidance).

        # Indigo trigger registry — populated by triggerStartProcessing/Stop.
        # Maps trigger.id -> trigger object so _fire_claude_event can find
        # triggers whose pluginTypeId matches the event being fired.
        self.event_triggers = {}

        # Default False and read the SAME way at every site — a pref that is
        # only refreshed on restart would let a Configure save appear to take
        # effect while the gate still held the old value.
        self.allow_destructive_delete = as_bool(
            plugin_prefs.get("allow_destructive_delete"), False)
        # Plugin-provided tools (v2.26.0): may the tools another plugin marks as
        # writes make changes? Read through the handler's supplier at every
        # call, so a Configure save applies at once. Default on, as the
        # provider contract documents.
        self.external_tools_allow_writes = as_bool(
            plugin_prefs.get("external_tools_allow_writes"), True)
        self._provider_broadcasts_subscribed = set()

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

        # Outbound webhook subsystem (built in startup(); ships dark)
        self.webhooks_enabled = False
        self.webhook_store = None
        self.webhook_manager = None
        self.webhook_dispatcher = None
        self.webhook_handler = None
        self._webhook_allowlist_path = None
        self._webhook_static_hosts = []
        self._webhook_static_http_hosts = []

        # Device management
        self.mcp_server_device = None

        # Plugin start time (used by /health endpoint)
        self._start_time = time.time()
        # When lastActivity was last written (monotonic). Written at most once a
        # minute: every write is an Indigo state change and a SQL Logger row.
        self._last_activity_write = 0.0

        # Set up logging properly — guard the coercion (a blank/non-numeric
        # stored value must not crash plugin start).
        try:
            self.log_level = int(plugin_prefs.get("log_level", logging.INFO))
        except (TypeError, ValueError):
            self.log_level = logging.INFO
            self.logger.warning("\tlog_level pref not numeric — defaulting to INFO")
        self.indigo_log_handler.setLevel(self.log_level)
        self.plugin_file_handler.setLevel(self.log_level)
        logging.getLogger("Plugin").setLevel(self.log_level)

    def _purge_orphan_prefs(self) -> None:
        """Drop stored settings whose Configure field no longer exists — the
        old Anthropic key and InfluxDB login among them. The allowed set comes
        from PluginConfig.xml; only the count is logged, never a value."""
        try:
            removed = orphan_prefs.purge_orphan_prefs(
                self.pluginPrefs, os.path.join(os.getcwd(), "PluginConfig.xml"))
        except Exception as exc:
            self.logger.warning(f"\tCould not tidy old settings: {exc}")
            return
        if removed:
            self.logger.info(f"Removed {len(removed)} stored setting(s) left over from "
                             f"Configure fields that no longer exist")

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
        self._purge_orphan_prefs()

        # Publish runtime config to the in-process store so downstream MCP
        # modules can read it without anything going through os.environ (see
        # mcp_server/runtime_config.py).
        runtime_config.configure(
            allow_destructive_delete = self.allow_destructive_delete,
        )

        # Initialize data provider
        try:
            self.data_provider = IndigoDataProvider(logger=self.logger)
        except Exception as e:
            self.logger.error(f"\t❌ Data provider initialization failed: {e}")
            return

        # Initialize MCP handler (includes the entity index)
        try:
            scopes_file = self._scopes_path()
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

            # Build the outbound webhook subsystem (ships dark — gated on the
            # 'Enable Event Webhooks' pref) before subscriptions go live.
            self._init_webhooks()

            # Subscribe to device, variable and action group changes: they feed
            # the webhooks, keep the tool cache honest (see _note_cache_change)
            # and tell the search index when it is out of date (see
            # _mark_index_dirty). Action groups change rarely, so that
            # subscription costs next to nothing.
            try:
                indigo.devices.subscribeToChanges()
                indigo.variables.subscribeToChanges()
                indigo.actionGroups.subscribeToChanges()
                self.logger.info("\t✅ Subscribed to device, variable and action group change events")
            except Exception as _sub_e:
                self.logger.warning(f"\t⚠️  Could not subscribe to changes: {_sub_e}")

        except Exception as e:
            self.logger.error(f"\t❌ MCP handler initialization failed: {e}")
            self.logger.error("\t❌ MCP server unavailable - plugin restart required")
            # Stop whatever did start, or its threads (the entity index, the
            # webhook worker) run on for the life of the process with nothing
            # able to reach them.
            self._stop_started_components()
            self._set_server_status("Unavailable")
            return

        # Claude Code integration LAST and on its own: it edits files outside
        # Indigo (Scripts/, ~/.mcp.json, ~/.claude/settings.json), and a
        # permissions error there used to abort startup half-way — no webhooks,
        # no change subscriptions, and the handler thrown away.
        self._configure_claude_code()

    def _configure_claude_code(self) -> None:
        """Deploy the proxy and register it with Claude Code, if the user has
        not turned that off. A failure is a WARNING: the MCP server itself is
        up and every other client still works."""
        # as_bool, not raw truthiness: a saved dialog stores this as the string
        # "false", which is truthy — so a user who unticked it would still get
        # their ~/.mcp.json / settings.json rewritten on every startup.
        if not as_bool(self.pluginPrefs.get("auto_configure_claude_code"), True):
            self.logger.info("Claude Code auto-configure disabled in PluginConfig — skipping "
                             "~/.mcp.json and ~/.claude/settings.json updates")
            return
        try:
            client_setup.setup_claude_code_integration(
                self.logger,
                bundle_dir     = os.getcwd(),
                install_folder = indigo.server.getInstallFolderPath(),
                home           = os.path.expanduser("~"),
                fallback_token = CLAUDEBRIDGE_BEARER_TOKEN,
            )
        except Exception as exc:
            self.logger.warning(f"\t⚠️  Claude Code auto-configure failed ({type(exc).__name__}: "
                                f"{exc}). The MCP server is running; set Claude Code up by hand "
                                f"or fix the permissions and restart the plugin.")

    def _stop_started_components(self) -> None:
        """Undo a half-finished startup: stop the webhook worker and the
        handler (its entity-index threads) if they were built."""
        for label, stop in (("webhook dwell timers", lambda: self.webhook_manager and self.webhook_manager.shutdown()),
                            ("webhook dispatcher", lambda: self.webhook_dispatcher and self.webhook_dispatcher.stop()),
                            ("MCP handler", lambda: self.mcp_handler and self.mcp_handler.stop())):
            try:
                stop()
            except Exception as exc:
                self.logger.warning(f"\t⚠️  Could not stop the {label}: {exc}")
        self.mcp_handler = None

    # ────────────────────────────────────────────────────────────────────────
    # Outbound webhook subsystem (event subscriptions). Ships dark — gated on the
    # 'Enable Event Webhooks' pref AND a default-deny egress allow-list.
    # ────────────────────────────────────────────────────────────────────────
    def _webhook_prefs_dir(self) -> str:
        return os.path.join(
            indigo.server.getInstallFolderPath(),
            "Preferences/Plugins/com.clives.indigoplugin.claudebridge",
        )

    def _read_webhook_config(self) -> None:
        """(Re)read the enabled flag + static allow-list from prefs and
        IndigoSecrets.WEBHOOK_ALLOWLIST. After a config-dialog save Indigo returns
        these as STRINGS, so coerce defensively (the standing pref-type gotcha)."""
        # as_bool, not bool(): after a config-dialog save Indigo re-serialises the
        # checkbox as the string "false", and bool("false") is True — which would
        # silently turn this dark-by-default egress feature ON.
        self.webhooks_enabled = as_bool(self.pluginPrefs.get("webhooks_enabled"), False)
        static = list(WEBHOOK_ALLOWLIST) if isinstance(WEBHOOK_ALLOWLIST, (list, tuple)) else []
        cfg = self.pluginPrefs.get("webhook_allowlist", "") or ""
        static += [h.strip() for h in str(cfg).replace("\n", ",").split(",") if h.strip()]
        http_cfg = self.pluginPrefs.get("webhook_http_allowlist", "") or ""
        http = [h.strip() for h in str(http_cfg).replace("\n", ",").split(",") if h.strip()]
        self._webhook_static_hosts = static
        self._webhook_static_http_hosts = http
        self._webhook_allowlist_path = os.path.join(self._webhook_prefs_dir(), "webhook_allowlist.json")

    def _webhook_allowlist_provider(self):
        """Build a fresh Allowlist on every call (re-reads the live JSON file so a
        target can be added without a plugin restart)."""
        return load_allowlist(self._webhook_static_hosts,
                              self._webhook_static_http_hosts,
                              self._webhook_allowlist_path)

    def _init_webhooks(self) -> None:
        try:
            self._read_webhook_config()
            store_path = os.path.join(self._webhook_prefs_dir(), "webhooks.json")
            self.webhook_store = SubscriptionStore(store_path, logger=self.logger)
            # Construct manager first (no dispatch callback yet), then the
            # dispatcher (which needs the manager for on_expired/persist), then
            # wire the dwell dispatch callback back — avoids a construction cycle.
            self.webhook_manager = SubscriptionManager(
                logger=self.logger, store=self.webhook_store)
            self.webhook_dispatcher = WebhookDispatcher(
                allowlist_provider=self._webhook_allowlist_provider,
                logger=self.logger,
                on_expired=lambda s: self.webhook_manager.delete(s.subscription_id),
                persist=self.webhook_manager.save,
            )
            self.webhook_manager.set_dispatch_callback(self.webhook_dispatcher.dispatch)
            self.webhook_handler = WebhookHandler(
                self.webhook_manager,
                self._webhook_allowlist_provider,
                enabled_provider=lambda: self.webhooks_enabled,
                logger=self.logger,
            )
            loaded = self.webhook_manager.load_from_store()
            if self.webhooks_enabled:
                self.webhook_dispatcher.start()
                self.logger.info(
                    f"\t✅ Event Webhooks ENABLED ({loaded} subscription(s), "
                    f"{len(self._webhook_static_hosts)} allow-list entr(ies))")
            else:
                self.logger.info("\tEvent Webhooks disabled (enable in plugin config to use)")
        except Exception as e:
            self.logger.error(f"\t❌ Webhook subsystem init failed: {e}")
            self.webhook_handler = None

    def _reconfigure_webhooks(self) -> None:
        """On a config save: re-read enabled + allow-list, start/stop the worker."""
        if self.webhook_dispatcher is None:
            self._init_webhooks()
            return
        was_enabled = self.webhooks_enabled
        self._read_webhook_config()
        if self.webhooks_enabled and not was_enabled:
            self.webhook_dispatcher.start()
            self.logger.info("\t✅ Event Webhooks enabled")
        elif was_enabled and not self.webhooks_enabled:
            # Cancel pending dwell timers too, or a disable->re-enable within the
            # dwell window could fire a stale event whose condition no longer holds.
            self.webhook_manager.shutdown()
            # wait=False: this runs on Indigo's dispatch thread (a Configure
            # save), which a join of up to 17 s would freeze. The worker is
            # signalled now and joined on a helper thread.
            self.webhook_dispatcher.stop(wait=False)
            self.logger.info("\tEvent Webhooks disabled")

    def _webhook_on_device_change(self, origDev, newDev) -> None:
        if not (self.webhooks_enabled and self.webhook_manager and self.webhook_dispatcher):
            return
        try:
            # dict(indigo.Device) copies every state and prop, and this runs on
            # every sensor event on the estate. Only pay for it when some
            # subscription watches this device (or all devices).
            if not self.webhook_manager.watches("device", newDev.id):
                return
            for sub, event in self.webhook_manager.evaluate_device_change(dict(origDev), dict(newDev)):
                self.webhook_dispatcher.dispatch(sub, event)
        except Exception:
            self.logger.exception("webhook device-change eval failed (contained)")

    def _webhook_on_variable_change(self, origVar, newVar) -> None:
        if not (self.webhooks_enabled and self.webhook_manager and self.webhook_dispatcher):
            return
        try:
            if not self.webhook_manager.watches("variable", newVar.id):
                return
            for sub, event in self.webhook_manager.evaluate_variable_change(dict(origVar), dict(newVar)):
                self.webhook_dispatcher.dispatch(sub, event)
        except Exception:
            self.logger.exception("webhook variable-change eval failed (contained)")

    def list_webhooks_menu(self) -> None:
        """Plugins menu: print the current webhook subscriptions (no secrets)."""
        if not self.webhook_manager:
            indigo.server.log("Webhook subsystem not initialised")
            return
        subs = self.webhook_manager.list_all()
        indigo.server.log(f"Event Webhook subscriptions: {len(subs)} (feature enabled={self.webhooks_enabled})")
        for s in subs:
            d = s.to_dict(include_secrets=False)
            tail = "" if d["entity_id"] is None else f":{d['entity_id']}"
            indigo.server.log(
                f"  {d['subscription_id']}  {d['entity_type']}{tail} -> {d['webhook_url']}  "
                f"enabled={d['enabled']} fires={d['stats']['fires']} "
                f"last={d['stats'].get('last_error') or 'ok'}")

    def reenable_webhooks_menu(self) -> None:
        """Plugins menu: switch back on every subscription the failure count
        quarantined. One switched off for another reason (a corrupt stored
        entity id) stays off."""
        if not self.webhook_manager:
            indigo.server.log("Webhook subsystem not initialised")
            return
        lifted = self.webhook_manager.reenable_quarantined()
        if lifted:
            indigo.server.log(f"Re-enabled {len(lifted)} quarantined webhook subscription(s): "
                              f"{', '.join(lifted)}")
        else:
            indigo.server.log("No webhook subscription is quarantined")

    def clear_webhooks_menu(self) -> None:
        """Plugins menu: delete ALL webhook subscriptions (idempotent)."""
        if not self.webhook_manager:
            indigo.server.log("Webhook subsystem not initialised")
            return
        subs = self.webhook_manager.list_all()
        for s in subs:
            self.webhook_manager.delete(s.subscription_id)
        indigo.server.log(f"Cleared {len(subs)} webhook subscription(s)")

    def shutdown(self) -> None:
        """
        Called when the plugin is being shut down.
        """
        self.logger.info("Stopping plugin...")

        # Stop the webhook subsystem first: cancel dwell timers, flush stats to
        # disk, then stop the delivery worker. The in-progress delivery finishes
        # (bounded by the socket timeouts); any still-queued events are dropped.
        if self.webhook_manager:
            try:
                self.webhook_manager.shutdown()
                self.webhook_manager.save()
            except Exception as e:
                self.logger.error(f"\t❌ Error saving webhook subscriptions: {e}")
        if self.webhook_dispatcher:
            try:
                self.webhook_dispatcher.stop()
            except Exception as e:
                self.logger.error(f"\t❌ Error stopping webhook dispatcher: {e}")

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
    # a fault. The entity index is left running (it is in memory and holds
    # no external resources).
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
            return self._jsonrpc_http_error(
                503, body, "MCP server unavailable - plugin initialization failed; "
                           "see the Indigo event log and reload the plugin")

        # Delegate to MCP handler (it will handle logging)
        try:
            response = self.mcp_handler.handle_request(method, headers, body)
        except Exception as e:
            self.logger.error(f"❌ MCP endpoint error: {e}")
            return self._jsonrpc_http_error(500, body, f"Claude Bridge internal error: {e}")
        self._note_activity()
        return response

    @staticmethod
    def _jsonrpc_http_error(status: int, body: str, message: str) -> dict:
        """An HTTP error whose body is still a JSON-RPC error for the request's
        id, so any client — the bundled proxy or another — can match it to the
        request it is waiting on. A bare {"error": ...} matched nothing."""
        try:
            request = json.loads(body) if body else None
        except (TypeError, ValueError):
            request = None
        request_id = request.get("id") if isinstance(request, dict) else None
        return {
            "status": status,
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "content": json.dumps({"jsonrpc": "2.0", "id": request_id,
                                   "error": {"code": -32603, "message": message}}),
        }

    def _note_activity(self) -> None:
        """Stamp lastActivity on the Claude Bridge device, at most once a
        minute. Never raises: it runs after every MCP request."""
        now = time.monotonic()
        if now - self._last_activity_write < 60:
            return
        self._last_activity_write = now
        try:
            dev = self.mcp_server_device
            if dev is not None:
                dev.updateStateOnServer(key="lastActivity", value=str(indigo.server.getTime()))
        except Exception as exc:
            self.logger.debug(f"Could not update lastActivity: {exc}")

    def _set_server_status(self, value: str) -> None:
        """Set serverStatus on the Claude Bridge device if it differs."""
        try:
            dev = self.mcp_server_device
            if dev is not None and dev.states.get("serverStatus") != value:
                dev.updateStateOnServer(key="serverStatus", value=value)
        except Exception as exc:
            self.logger.debug(f"Could not update serverStatus: {exc}")

    ########################################
    # Health / Diagnostics IWS endpoint
    ########################################

    def handle_health_endpoint(self, action, dev=None, callerWaitingForResult=True):
        """
        GET /message/com.clives.indigoplugin.claudebridge/health/
        Returns plugin uptime, session count, tool inventory and recent
        tool-call latencies as JSON. Cheap to call — safe for monitors.

        Auth: gated by IWS bearer auth only (like every /message/ endpoint) —
        it does NOT pass through the plugin's per-token scope layer. That is
        intentional: it performs no mutation, only read-only diagnostics, so a
        'read'-equivalent gate is sufficient. Rate-limiter keys (bearer tokens)
        are masked to a non-reversible digest before they reach this payload —
        see RateLimiter.snapshot() — so no token strings are exposed.
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

        Auth: gated by IWS bearer auth only (not the per-token scope layer).
        Intentional — the page is read-only tool documentation, no secrets and
        no mutation, so it carries no token strings or live data.
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
        # default_scopes is READ for a new file: a token nobody listed gets
        # read-only access, not everything. Only a NEW file gets this — an
        # existing scopes.json is never rewritten.
        starter = {
            "default_scopes": ["read"],
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
            scopes_path.write_text(json.dumps(starter, indent=2) + "\n", encoding="utf-8")
            # This file is KEYED BY FULL BEARER TOKENS once the user fills it in,
            # so it must not inherit a group/world-readable umask — same reasoning
            # as webhooks.json and the deployed proxy. ScopeManager re-asserts this
            # on every load in case the file is restored from a backup.
            try:
                _os.chmod(scopes_path, 0o600)
            except Exception as _e:
                indigo.server.log(f"Claude Bridge: could not chmod scopes.json to 0600: {_e}",
                                  isError=True)
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

    # ── Plugin-provided MCP tools (v2.26.0) ─────────────────────────────

    def subscribe_to_provider_broadcasts(self, provider_ids) -> None:
        """Subscribe once per provider to its "mcp_tools_updated" broadcast, so
        a provider that starts or updates re-registers its tools without a
        Claude Bridge restart. A provider is only known after discovery, which
        is why every rescan calls this rather than startup doing it once."""
        for pid in provider_ids or ():
            if pid in self._provider_broadcasts_subscribed:
                continue
            try:
                indigo.server.subscribeToBroadcast(pid, "mcp_tools_updated", "on_mcp_tools_updated")
                self._provider_broadcasts_subscribed.add(pid)
            except Exception as exc:
                self.logger.warning(f"\t⚠️  Could not subscribe to {pid} broadcasts: {exc}")

    def on_mcp_tools_updated(self, arg=None) -> None:
        """A provider says its tool set changed — usually it has just started."""
        if not self.mcp_handler:
            return
        try:
            result = self.mcp_handler.refresh_external_tools()
            self.logger.debug(f"Plugin-provided tools refreshed on broadcast: {result}")
        except Exception as exc:
            self.logger.error(f"\t❌ Plugin-provided tool refresh failed: {exc}")

    def print_external_tools_menu(self) -> None:
        """Menu action: every provider, its tools and the write gate, to the log."""
        if not self.mcp_handler:
            indigo.server.log("Claude Bridge: MCP handler not initialized", isError=True)
            return
        lines = self.mcp_handler.external_tools.summary()
        if not lines:
            indigo.server.log("Claude Bridge: no plugin-provided MCP tools — no installed plugin "
                              "ships Contents/Resources/mcp-manifest.json")
            return
        gate = ("allowed" if self.external_tools_allow_writes
                else "REFUSED — untick 'Allow plugin-provided tools to make changes' under Configure")
        indigo.server.log(f"Claude Bridge — plugin-provided MCP tools (writes {gate}):\n"
                          + "\n".join(lines))

    def rescan_external_tools_menu(self) -> None:
        """Menu action: re-read every provider manifest now."""
        if not self.mcp_handler:
            indigo.server.log("Claude Bridge: MCP handler not initialized", isError=True)
            return
        try:
            result = self.mcp_handler.refresh_external_tools()
            msg = (f"Claude Bridge: rescanned plugin-provided tools — {len(result['tools'])} "
                   f"tool(s) from {len(result['providers'])} provider(s)")
            if result["removed"]:
                msg += f", removed {', '.join(result['removed'])}"
            indigo.server.log(msg + ". A connected client sees a new tool only from its next session.")
        except Exception as e:
            indigo.server.log(f"Claude Bridge: plugin-provided tool rescan failed: {e}", isError=True)

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

        # The docs link and the secrets.json path follow the running server,
        # never a typed version number.
        try:
            install_folder = indigo.server.getInstallFolderPath()
            docs_version = ".".join(str(indigo.server.version).split(".")[:2])
        except Exception:
            install_folder = "/Library/Application Support/Perceptive Automation/Indigo <version>"
            docs_version = "2025.2"
        secrets_json = os.path.join(install_folder, "Preferences", "secrets.json")
        docs_url = (f"https://docs.indigodomo.com/{docs_version}/user/remote-access/"
                    f"web-server/#authentication")

        config_lines = [
            "🌐 Claude Desktop MCP Client Connection Information:",
            "",
            "⚠️  AUTHENTICATION REQUIRED: All configurations require a Bearer token with an Indigo API key.",
            "",
            "📚 In all cases, you will need an API Key. For this, you have two choices:",
            "  • Indigo Reflector API Key: Obtained from your Reflector settings",
            "  • Local Secret: Created in secrets.json file",
            f"    Location: {secrets_json}",
            f"    Details: {docs_url}",
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
                            "NODE_EXTRA_CA_CERTS": "/path/to/your-indigo-certificate.pem"
                        }
                    }
                }
            }
            config_lines.append(json.dumps(scenario2_config, indent=2))
            # Trust the one certificate rather than switching verification off:
            # NODE_TLS_REJECT_UNAUTHORIZED=0 turns off certificate checks for
            # every connection that Node process makes, which is exactly what
            # HTTPS is there to prevent.
            config_lines.extend(["", "Setup:", "  1. Create a local secret (see documentation link above)", "  2. Replace YOUR_LOCAL_SECRET_KEY with your generated local secret", "  3. Export the web server's self-signed certificate as a .pem file and point NODE_EXTRA_CA_CERTS at it, so Node trusts that one certificate", "  4. Do NOT set NODE_TLS_REJECT_UNAUTHORIZED=0 — it turns off certificate checks altogether", "  5. Replace port 8176 if you are not using the default Indigo Web Server port", ""])
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
        super().triggerStartProcessing(trigger)
        self.event_triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        """Indigo lifecycle: trigger disabled or deleted."""
        super().triggerStopProcessing(trigger)
        self.event_triggers.pop(trigger.id, None)

    def fire_claude_event(self, event_name: str, data=None, source: str = "claude") -> dict:
        """
        Fire all claudeEvent triggers via the standard PluginBase lifecycle:
        iterate self.event_triggers (populated by triggerStartProcessing) and
        execute every trigger whose pluginTypeId matches the Events.xml event ID.

        Inside the user's Trigger actions, the payload is accessible as
        (Indigo's event-data substitution, as Events.xml documents):
            %%e:"name"%%   %%e:"data"%%   %%e:"source"%%
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
                    # Pass the payload as trigger_data so it reaches condition/
                    # embedded scripts (event_data) and the %%e:"name"%% /
                    # %%e:"data"%% / %%e:"source"%% substitutions. Without this the
                    # payload is silently dropped and name-filtered triggers can't
                    # discriminate. (Signature confirmed live: execute(trigger,
                    # ignoreConditions=False, trigger_data=None).)
                    indigo.trigger.execute(trigger, trigger_data=payload)
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

            # Update device states only if changed — avoids Event Log spam and DB churn.
            # "Running" only when the MCP handler actually started: a device
            # that said Running over a plugin answering every request with 503
            # sent people looking everywhere but the startup error.
            status = "Running" if self.mcp_handler is not None else "Unavailable"
            updates = []
            if device.states.get("serverStatus") != status:
                updates.append({"key": "serverStatus", "value": status})
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

    def _note_cache_change(self, domain: str) -> None:
        """Mark a tool-cache domain dirty after a real-world change.

        Wrapped because it runs on the hottest callback path in the plugin: it
        must never raise (a cache bookkeeping failure must not break device
        event handling) and must never be expensive.
        """
        try:
            handler = self.mcp_handler
            if handler is not None and getattr(handler, "tool_cache", None) is not None:
                handler.tool_cache.note_external_change(domain)
        except Exception:
            pass   # deliberately silent: worst case is a stale read, not a fault

    def _mark_index_dirty(self) -> None:
        """Tell the search index it no longer matches Indigo; the next search
        rebuilds it. Same rules as _note_cache_change: never raises, never
        expensive. This replaced a full rebuild after every
        execute_indigo_python and run_script call (about 1,600 in ten weeks),
        almost none of which had changed a name."""
        try:
            handler = self.mcp_handler
            manager = getattr(handler, "entity_index_manager", None) if handler is not None else None
            if manager is not None:
                manager.mark_dirty()
        except Exception:
            pass   # deliberately silent: the 300 s rebuild is the safety net

    def deviceCreated(self, dev: indigo.Device) -> None:
        super().deviceCreated(dev)
        self._mark_index_dirty()
        self._note_cache_change("device")

    def deviceDeleted(self, dev: indigo.Device) -> None:
        super().deviceDeleted(dev)
        self._mark_index_dirty()
        self._note_cache_change("device")

    def variableCreated(self, var: indigo.Variable) -> None:
        super().variableCreated(var)
        self._mark_index_dirty()
        self._note_cache_change("variable")

    def variableDeleted(self, var: indigo.Variable) -> None:
        super().variableDeleted(var)
        self._mark_index_dirty()
        self._note_cache_change("variable")

    def actionGroupCreated(self, group) -> None:
        super().actionGroupCreated(group)
        self._mark_index_dirty()
        self._note_cache_change("action_group")

    def actionGroupDeleted(self, group) -> None:
        super().actionGroupDeleted(group)
        self._mark_index_dirty()
        self._note_cache_change("action_group")

    def actionGroupUpdated(self, origGroup, newGroup) -> None:
        super().actionGroupUpdated(origGroup, newGroup)
        if index_fields_changed("action_group", origGroup, newGroup):
            self._mark_index_dirty()
        self._note_cache_change("action_group")

    def variableUpdated(self, origVar: indigo.Variable, newVar: indigo.Variable) -> None:
        """
        Called when an Indigo variable changes. Marks the tool cache stale,
        marks the search index stale on a rename or move, and hands the change
        to the outbound webhooks.
        """
        super().variableUpdated(origVar, newVar)
        renamed_or_moved = index_fields_changed("variable", origVar, newVar)
        if renamed_or_moved:
            self._mark_index_dirty()
        if renamed_or_moved or origVar.value != newVar.value:
            # Tell the tool cache the world moved. Without this, list_variables /
            # get_variable_by_id kept serving the pre-change value for a full TTL
            # even though we had the change in hand right here — and until
            # 3.0.2 a rename or a move to another folder was not noted at all.
            # O(1) — a counter bump, not a store walk — because this fires
            # constantly.
            self._note_cache_change("variable")

        # Outbound webhooks (own try/except inside; gated on the enabled flag)
        self._webhook_on_variable_change(origVar, newVar)

    def deviceUpdated(self, origDev: indigo.Device, newDev: indigo.Device) -> None:
        """
        Called when a device state or configuration is updated. Marks the
        tool cache stale and hands the change to the outbound webhooks;
        changes to the plugin's own mcpServer device are only logged.

        Loop-guard: this plugin both subscribeToChanges() AND writes to its own
        mcpServer device states (via deviceStartComm). Without this guard, a
        state write inside the mcpServer branch would fire deviceUpdated again
        and loop. Per-device self-checks aren't sufficient if the plugin ever
        has more than one device — block the whole pluginId at the top.
        """
        super().deviceUpdated(origDev, newDev)
        if newDev.pluginId == self.pluginId:
            # Our own device: config tracking only, never the cache or the
            # webhooks. This is the ONLY place an mcpServer device reaches.
            if newDev.deviceTypeId == "mcpServer":
                self._handle_mcp_server_device_update(origDev, newDev)
            # Safe inside the guard: marking the index writes nothing to Indigo.
            if index_fields_changed("device", origDev, newDev):
                self._mark_index_dirty()
            return

        # A rename, move, enable/disable or type change makes the search index
        # stale. A state change does not, and is most of what arrives here.
        if index_fields_changed("device", origDev, newDev):
            self._mark_index_dirty()

        # Tell the tool cache the world moved — a light switched at the wall, by
        # a Z-Wave association, by a trigger, or by another plugin. Nothing else
        # invalidates on real-world change, so without this home_status /
        # get_device_by_id / list_devices served the pre-change value for up to
        # the full TTL and presented it as current. O(1), because this callback
        # fires on every sensor event on the estate.
        self._note_cache_change("device")

        # Outbound webhooks (all non-plugin devices; own try/except; gated)
        self._webhook_on_device_change(origDev, newDev)

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
            try:
                self.log_level = int(values_dict.get("log_level", 20))
            except (TypeError, ValueError):
                self.log_level = logging.INFO
            self.indigo_log_handler.setLevel(self.log_level)
            self.plugin_file_handler.setLevel(self.log_level)
            logging.getLogger("Plugin").setLevel(self.log_level)

            # Coerce the checkboxes via as_bool: a saved dialog can hand back
            # the string 'false', and bool('false') is True.
            self.allow_destructive_delete = as_bool(
                values_dict.get("allow_destructive_delete"), False)
            self.external_tools_allow_writes = as_bool(
                values_dict.get("external_tools_allow_writes"), True)

            # Phase 2 — apply rate-limit / cache changes live (no restart needed).
            # Coerce ALL three before assigning any: a single try around both the
            # coercions and the live push meant a bad cache_ttl_seconds left the
            # two rate-limit fields already reassigned while the running limiter
            # kept the old values — plugin state and behaviour diverged silently
            # until the next restart.
            try:
                _per_minute = max(1, int(values_dict.get("rate_limit_per_minute", 120)))
                _per_day    = max(1, int(values_dict.get("rate_limit_per_day", 5000)))
                _cache_ttl  = max(0, min(300, int(values_dict.get("cache_ttl_seconds", 60))))
            except (TypeError, ValueError) as _e:
                self.logger.warning(f"\t⚠️  Could not parse Phase 2 settings, keeping "
                                    f"the current values: {_e}")
            else:
                self.rate_limit_per_minute = _per_minute
                self.rate_limit_per_day    = _per_day
                self.cache_ttl_seconds     = _cache_ttl
            try:
                if self.mcp_handler:
                    self.mcp_handler.rate_limiter.per_minute = self.rate_limit_per_minute
                    self.mcp_handler.rate_limiter.per_day    = self.rate_limit_per_day
                    self.mcp_handler.tool_cache.set_ttl(self.cache_ttl_seconds)
                    self.logger.info(
                        f"\t✅ Rate limits updated: {self.rate_limit_per_minute}/min, "
                        f"{self.rate_limit_per_day}/day; cache TTL {self.cache_ttl_seconds}s"
                    )
            except Exception as _e:
                self.logger.warning(f"\t⚠️  Could not apply Phase 2 settings to the "
                                    f"running handler: {_e}")

            # Apply webhook config live (enable/disable + allow-list) — no restart needed
            try:
                self._reconfigure_webhooks()
            except Exception as _we:
                self.logger.warning(f"\t⚠️  Could not apply webhook settings: {_we}")

            # Republish runtime config (same as startup — see runtime_config.py
            # for why this does not go through os.environ).
            runtime_config.configure(
                allow_destructive_delete = self.allow_destructive_delete,
            )

            self.logger.info(
                "✅ Configuration updated successfully. Changes will take effect on next MCP request."
            )

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
            _tool_count = (len(self.mcp_handler._tools)
                           if getattr(self, "mcp_handler", None) is not None
                           and getattr(self.mcp_handler, "_tools", None) is not None
                           else "?")
            extras.append(("Tools:", str(_tool_count)))
            try:
                extras.append(("scopes.json:", self._scopes_path()))
            except Exception:
                pass
            extras.append(("Timestamps in Log:", "ON" if self.timestamp_enabled else "OFF"))
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion, extras=extras)
        else:
            indigo.server.log(f"{self.pluginDisplayName} v{self.pluginVersion}")
            try:
                indigo.server.log(f"scopes.json: {self._scopes_path()}")
            except Exception:
                pass

    def _scopes_path(self) -> str:
        """Where scopes.json lives (Configure and Show Plugin Info name it)."""
        return os.path.join(indigo.server.getInstallFolderPath(),
                            "Preferences/Plugins/com.clives.indigoplugin.claudebridge/scopes.json")

    def menuToggleTimestamps(self):
        self.timestamp_enabled = not self.timestamp_enabled
        self.pluginPrefs["timestampEnabled"] = self.timestamp_enabled
        # Saved now: pluginPrefs reach disk only on a clean shutdown, so a crash
        # or a forced quit used to undo the toggle.
        try:
            self.savePluginPrefs()
        except Exception as exc:
            self.logger.warning(f"\t⚠️  Could not save the timestamp setting: {exc}")
        if self._ts_filter:
            self._ts_filter.enabled = self.timestamp_enabled
        state = "ON" if self.timestamp_enabled else "OFF"
        indigo.server.log(f"[{self.pluginDisplayName}] Timestamps in Log -> {state}")
