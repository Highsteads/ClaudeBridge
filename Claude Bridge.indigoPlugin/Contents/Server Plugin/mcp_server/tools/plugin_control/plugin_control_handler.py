"""
Plugin Control Handler

Provides MCP tools for managing Indigo plugins.
"""

import logging
import time
from typing import Any, Dict, List, Optional

try:
    import indigo
except ImportError:
    indigo = None

from ...adapters.data_provider import DataProvider
from ...common import plugin_actions
from ..base_handler import BaseToolHandler
from .plugin_scanner import PluginScanner

# Restarting ClaudeBridge from within its own MCP session tears down the very
# connection serving the request (IWS goes dark for several minutes). Refuse it.
_OWN_PLUGIN_ID = "com.clives.indigoplugin.claudebridge"


class PluginControlHandler(BaseToolHandler):
    """Handler for plugin control operations"""

    # Cache duration: 60 minutes
    CACHE_DURATION = 3600

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the plugin control handler.

        Args:
            data_provider: Data provider instance
            logger: Logger instance
        """
        super().__init__(tool_name="plugin_control", logger=logger)
        self.data_provider = data_provider
        self.scanner = PluginScanner(logger or self.logger)
        self._plugin_cache = {}  # {cache_key: (timestamp, data)}

    def list_plugins(self, include_disabled: bool = False) -> Dict[str, Any]:
        """
        List all Indigo plugins.

        Args:
            include_disabled: Whether to include disabled plugins (default: False)

        Returns:
            Dictionary with success status and list of plugins
        """
        try:
            # Check cache
            plugins = self._get_cached_plugins(include_disabled)

            return {
                "success": True,
                "plugins": plugins,
                "count": len(plugins),
                "include_disabled": include_disabled,
            }

        except Exception as e:
            error_msg = f"Failed to list plugins: {e}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg, "plugins": []}

    def get_plugin_by_id(self, plugin_id: str) -> Dict[str, Any]:
        """
        Get specific plugin information by ID.

        Args:
            plugin_id: Plugin bundle identifier (e.g., "com.clives.indigoplugin.mcpserver")

        Returns:
            Dictionary with plugin information
        """
        try:
            if not indigo:
                return {
                    "success": False,
                    "error": "Indigo module not available",
                }

            # Get plugin from Indigo API. NB getPlugin() returns a PluginInfo object
            # even for an id that doesn't exist (its isEnabled() just returns False),
            # so it never raises — we must confirm the plugin is real ourselves,
            # otherwise a bogus id returns success:true / enabled:false.
            plugin = indigo.server.getPlugin(plugin_id)

            match = None
            try:
                for p in self._get_cached_plugins(include_disabled=True):
                    if p["id"] == plugin_id:
                        match = p
                        break
            except Exception:
                match = None

            if match is None:
                return {
                    "success": False,
                    "error": f"Plugin '{plugin_id}' not found",
                    "suggestion": "Use list_plugins to see available plugins",
                }

            plugin_info = {
                "id": plugin_id,
                "enabled": plugin.isEnabled(),
                "displayName": getattr(plugin, "pluginDisplayName", match.get("name", "Unknown")),
                "version": match.get("version", "Unknown"),
                "path": match.get("path", "Unknown"),
            }
            return {"success": True, "plugin": plugin_info}

        except AttributeError as e:
            # Plugin not found or invalid plugin object
            error_msg = f"Plugin '{plugin_id}' not found: {e}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "suggestion": "Use list_plugins to see available plugins",
            }
        except Exception as e:
            error_msg = f"Failed to get plugin '{plugin_id}': {e}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}

    def restart_plugin(self, plugin_id: str) -> Dict[str, Any]:
        """
        Restart an Indigo plugin.

        Args:
            plugin_id: Plugin bundle identifier

        Returns:
            Dictionary with restart status
        """
        try:
            if not indigo:
                return {
                    "success": False,
                    "error": "Indigo module not available",
                }

            # Refuse to restart ourselves — it kills the in-flight MCP session
            # mid-response and blacks out IWS for minutes.
            if plugin_id == _OWN_PLUGIN_ID:
                return {
                    "success": False,
                    "error": ("Refusing to restart ClaudeBridge from within its own MCP "
                              "session — restart it from the Indigo Plugins menu instead."),
                }

            # Get plugin from Indigo API
            plugin = indigo.server.getPlugin(plugin_id)

            # Check if plugin is enabled
            if not plugin.isEnabled():
                return {
                    "success": False,
                    "error": f"Plugin '{plugin_id}' is not enabled",
                    "suggestion": "Enable the plugin in Indigo before restarting",
                }

            # Restart the plugin (fire-and-forget — plugin.restart() defaults to
            # waitUntilDone=True, which would BLOCK this IWS request thread for the
            # whole stop+start cycle, contradicting the intent. Pass False.)
            self.logger.info(f"Restarting plugin: {plugin_id}")
            plugin.restart(waitUntilDone=False)

            # Invalidate plugin cache
            self._invalidate_cache()

            return {
                "success": True,
                "message": f"Plugin '{plugin_id}' restart requested",
                "plugin_id": plugin_id,
            }

        except AttributeError as e:
            error_msg = f"Plugin '{plugin_id}' not found: {e}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "suggestion": "Use list_plugins to see available plugins",
            }
        except Exception as e:
            error_msg = f"Failed to restart plugin '{plugin_id}': {e}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}

    def execute_device_action(
        self,
        action_type_id: str,
        device_id: Optional[Any] = None,
        props: Optional[Dict[str, Any]] = None,
        plugin_id: Optional[str] = None,
        wait_until_done: bool = True,
    ) -> Dict[str, Any]:
        """Invoke a plugin's own Actions.xml action, with the guards Indigo lacks.

        The bare `executeAction` call has three silent-failure modes, and this
        method exists to convert each into an error the caller can act on:
        an unknown action id, a device action called with no device, and an
        owning plugin that is not running (a stopped plugin swallows every
        action and the caller sees no exception at all).
        """
        self.log_incoming_request(
            "execute_device_action",
            {"action_type_id": action_type_id, "device_id": device_id,
             "plugin_id": plugin_id, "prop_keys": sorted(props or {})},
        )
        try:
            if not indigo:
                return {"success": False, "error": "Indigo module not available"}

            action_type_id = (action_type_id or "").strip()
            if not action_type_id:
                return {"success": False, "error": "action_type_id is required"}

            # ── Resolve the device (id or name), if one was given ───────────
            device = None
            dev_id: Optional[int] = None
            if device_id is not None:
                device, err = self._resolve_device(device_id)
                if err:
                    return {"success": False, "error": err}
                dev_id = device.id

            # ── Resolve the owning plugin ──────────────────────────────────
            if not plugin_id:
                if device is None:
                    return {
                        "success": False,
                        "error": ("Pass device_id (the action's device) or plugin_id "
                                  "(for a plugin-level action) so the owning plugin "
                                  "can be identified."),
                    }
                plugin_id = device.pluginId
                if not plugin_id:
                    return {
                        "success": False,
                        "error": (f"Device {dev_id} ('{device.name}') is not owned by a "
                                  f"plugin, so it has no plugin actions. Use the "
                                  f"built-in device tools instead."),
                    }

            plugin = indigo.server.getPlugin(plugin_id)

            # getPlugin() with a WRONG id does not raise — it returns an object
            # whose isInstalled/isEnabled/isRunning are all False, which reads
            # exactly like a real outage. An empty pluginFolderPath is the only
            # thing that tells the two apart.
            if not plugin.pluginFolderPath:
                return {
                    "success": False,
                    "error": (f"No plugin is installed with id '{plugin_id}'. Check the "
                              f"id — a typo here looks identical to a stopped plugin."),
                    "suggestion": "Use list_plugins to see installed plugin ids",
                }

            if not plugin.isRunning():
                return {
                    "success": False,
                    "error": (f"Plugin '{plugin_id}' is installed but not running "
                              f"(enabled={plugin.isEnabled()}). Indigo would swallow the "
                              f"action and report nothing."),
                    "plugin": {"id": plugin_id, "installed": True,
                               "enabled": plugin.isEnabled(), "running": False},
                    "suggestion": "Enable or restart the plugin, then retry",
                }

            # ── Check the call against the plugin's own Actions.xml ─────────
            declared = plugin_actions.read_plugin_actions(plugin.pluginFolderPath)
            validated = declared["available"]
            warnings: List[str] = []
            action_meta = None

            if validated:
                verdict = plugin_actions.check_call(
                    declared["actions"], action_type_id, dev_id, props
                )
                if not verdict["ok"]:
                    return {
                        "success": False,
                        "error": verdict["error"],
                        "plugin_id": plugin_id,
                        "available_actions": plugin_actions.summarise_actions(
                            declared["actions"]
                        ),
                    }
                warnings = verdict["warnings"]
                action_meta = verdict["action"]
            else:
                warnings.append(
                    f"Could not check this call against the plugin's Actions.xml "
                    f"({declared['reason']}) — dispatching unguarded, so a wrong "
                    f"action id or a missing device would fail silently."
                )

            # ── Dispatch ───────────────────────────────────────────────────
            # Audit trail in the Indigo event log: an action fired by an AI
            # caller must be as visible afterwards as one fired from the UI.
            target = f" on '{device.name}' ({dev_id})" if device is not None else ""
            prop_desc = ", ".join(f"{k}={v!r}" for k, v in sorted((props or {}).items()))
            indigo.server.log(
                f"execute_device_action: '{action_type_id}'{target} via {plugin_id}"
                + (f" [{prop_desc}]" if prop_desc else " [no props]")
            )

            kwargs: Dict[str, Any] = {"waitUntilDone": bool(wait_until_done)}
            if dev_id is not None:
                kwargs["deviceId"] = dev_id
            if props:
                kwargs["props"] = props

            returned = plugin.executeAction(action_type_id, **kwargs)

            result: Dict[str, Any] = {
                "success": True,
                "plugin_id": plugin_id,
                "action_type_id": action_type_id,
                "device_id": dev_id,
                "device_name": device.name if device is not None else None,
                "props_sent": dict(props or {}),
                "wait_until_done": bool(wait_until_done),
                "validated_against_actions_xml": validated,
                # Most actions return nothing. A None here means "the plugin's
                # callback returned nothing", NOT "nothing happened" — read the
                # device's own state to confirm an effect.
                "plugin_returned": self._plain(returned),
                "note": ("Dispatched. A plugin action reports success by changing "
                         "state, not by returning a value — re-read the device if "
                         "you need proof the effect landed."),
            }
            if action_meta:
                result["action"] = {
                    "name": action_meta.get("name", ""),
                    "needs_device": action_meta.get("device_action", False),
                    "declared_props": action_meta.get("fields", []),
                }
            if warnings:
                result["warnings"] = warnings

            self.log_tool_outcome(
                "execute_device_action", True,
                f"{plugin_id}:{action_type_id}{target}",
            )
            return result

        except Exception as e:
            error_msg = f"Failed to execute '{action_type_id}' on '{plugin_id}': {e}"
            self.logger.error(error_msg, exc_info=True)
            self.log_tool_outcome("execute_device_action", False, error_msg)
            return {"success": False, "error": error_msg}

    def _resolve_device(self, device_id: Any):
        """Accept a numeric id or an exact device name. Returns (device, error)."""
        # bool subclasses int, so a stray JSON true would otherwise be device 1.
        if isinstance(device_id, bool):
            return None, f"Expected a device id or name, got {device_id!r}"
        if isinstance(device_id, int) or (
            isinstance(device_id, str) and device_id.strip().isdigit()
        ):
            did = int(str(device_id).strip())
            if did not in indigo.devices:
                return None, f"No device with id {did}"
            return indigo.devices[did], ""
        name = str(device_id).strip()
        for dev in indigo.devices:
            if dev.name == name:
                return dev, ""
        for dev in indigo.devices:
            if dev.name.lower() == name.lower():
                return dev, ""
        return None, f"No device found matching '{name}'"

    @staticmethod
    def _plain(value):
        """Make a plugin's return value JSON-safe (it may be an indigo.Dict)."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        try:
            if hasattr(value, "items"):
                return {str(k): PluginControlHandler._plain(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [PluginControlHandler._plain(v) for v in value]
        except Exception:                                          # noqa: BLE001
            pass
        return str(value)

    def get_plugin_status(self, plugin_id: str) -> Dict[str, Any]:
        """
        Get detailed plugin status.

        Args:
            plugin_id: Plugin bundle identifier

        Returns:
            Dictionary with plugin status information
        """
        try:
            if not indigo:
                return {
                    "success": False,
                    "error": "Indigo module not available",
                }

            # Confirm the plugin EXISTS before reporting on it. getPlugin() hands
            # back a live-looking PluginInfo for any string, so a typo'd or
            # uninstalled bundle id used to return success with enabled=False and
            # displayName "Unknown" — indistinguishable from a plugin that really
            # is installed and disabled. Same check get_plugin_by_id gained in
            # v2.10.1; this sibling was missed.
            installed = None
            try:
                for p in self._get_cached_plugins(include_disabled=True):
                    if p["id"] == plugin_id:
                        installed = p
                        break
            except Exception:
                installed = None

            if installed is None:
                return {
                    "success": False,
                    "error": f"Plugin '{plugin_id}' not found",
                    "suggestion": "Use list_plugins to see the installed bundle ids.",
                }

            # Get plugin from Indigo API
            plugin = indigo.server.getPlugin(plugin_id)

            # Extract status information
            status = {
                "id": plugin_id,
                "enabled": plugin.isEnabled(),
                "displayName": getattr(plugin, "pluginDisplayName", "Unknown"),
                "version": installed.get("version", "Unknown"),
                "path": installed.get("path", "Unknown"),
            }
            status["name"] = installed.get("name", status["displayName"])

            return {"success": True, "status": status}

        except AttributeError as e:
            error_msg = f"Plugin '{plugin_id}' not found: {e}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "suggestion": "Use list_plugins to see available plugins",
            }
        except Exception as e:
            error_msg = f"Failed to get status for plugin '{plugin_id}': {e}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}

    # Private methods for caching

    def _get_cached_plugins(self, include_disabled: bool) -> List[Dict]:
        """
        Get plugins from cache or scan file system.

        Args:
            include_disabled: Whether to include disabled plugins

        Returns:
            List of plugin dictionaries
        """
        cache_key = f"plugins_{include_disabled}"

        # Check cache
        if cache_key in self._plugin_cache:
            timestamp, data = self._plugin_cache[cache_key]
            age = time.time() - timestamp

            if age < self.CACHE_DURATION:
                self.logger.debug(f"Using cached plugin list (age: {age:.1f}s)")
                return data
            else:
                self.logger.debug("Plugin cache expired, rescanning file system")

        # Cache miss or expired - scan file system
        data = self._scan_plugins(include_disabled)

        # Store in cache
        self._plugin_cache[cache_key] = (time.time(), data)

        return data

    def _scan_plugins(self, include_disabled: bool) -> List[Dict]:
        """
        Scan file system for plugins.

        Args:
            include_disabled: Whether to include disabled plugins

        Returns:
            List of plugin dictionaries
        """
        if not indigo:
            raise RuntimeError("Indigo module not available")

        install_path = indigo.server.getInstallFolderPath()
        return self.scanner.scan_plugins(install_path, include_disabled)

    def _invalidate_cache(self):
        """Invalidate all plugin caches."""
        if self._plugin_cache:
            self.logger.debug("Plugin cache invalidated due to restart operation")
            self._plugin_cache.clear()
