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
from ..base_handler import BaseToolHandler
from .plugin_scanner import PluginScanner


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

            # Get plugin from Indigo API
            plugin = indigo.server.getPlugin(plugin_id)

            # Extract plugin information
            plugin_info = {
                "id": plugin_id,
                "enabled": plugin.isEnabled(),
                "displayName": getattr(plugin, "pluginDisplayName", "Unknown"),
            }

            # Try to get version from plugin bundle
            try:
                plugins = self._get_cached_plugins(include_disabled=True)
                for p in plugins:
                    if p["id"] == plugin_id:
                        plugin_info["version"] = p.get("version", "Unknown")
                        plugin_info["path"] = p.get("path", "Unknown")
                        break
            except Exception:
                plugin_info["version"] = "Unknown"
                plugin_info["path"] = "Unknown"

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

            # Get plugin from Indigo API
            plugin = indigo.server.getPlugin(plugin_id)

            # Check if plugin is enabled
            if not plugin.isEnabled():
                return {
                    "success": False,
                    "error": f"Plugin '{plugin_id}' is not enabled",
                    "suggestion": "Enable the plugin in Indigo before restarting",
                }

            # Restart the plugin
            self.logger.info(f"Restarting plugin: {plugin_id}")
            plugin.restart()

            # Invalidate plugin cache
            self._invalidate_cache()

            # Wait a moment for restart to complete
            time.sleep(1)

            return {
                "success": True,
                "message": f"Plugin '{plugin_id}' restarted successfully",
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

            # Get plugin from Indigo API
            plugin = indigo.server.getPlugin(plugin_id)

            # Extract status information
            status = {
                "id": plugin_id,
                "enabled": plugin.isEnabled(),
                "displayName": getattr(plugin, "pluginDisplayName", "Unknown"),
            }

            # Try to get additional info from file system scan
            try:
                plugins = self._get_cached_plugins(include_disabled=True)
                for p in plugins:
                    if p["id"] == plugin_id:
                        status["version"] = p.get("version", "Unknown")
                        status["path"] = p.get("path", "Unknown")
                        status["name"] = p.get("name", status["displayName"])
                        break
            except Exception:
                pass

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
