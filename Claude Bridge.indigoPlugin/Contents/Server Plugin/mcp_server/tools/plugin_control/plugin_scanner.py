"""
Plugin Scanner Utility

Scans the Indigo plugins directory and extracts plugin metadata.
"""

import glob
import logging
import os
import plistlib
from typing import Dict, List, Optional

try:
    import indigo
except ImportError:
    indigo = None


class PluginScanner:
    """Scanner for Indigo plugin directories"""

    def __init__(self, logger: logging.Logger):
        """
        Initialize the plugin scanner.

        Args:
            logger: Logger instance for logging
        """
        self.logger = logger

    def scan_plugins(
        self, install_path: str, include_disabled: bool = False
    ) -> List[Dict]:
        """
        Scan Indigo plugins directory and return plugin metadata.

        Args:
            install_path: Indigo installation path (from indigo.server.getInstallFolderPath())
            include_disabled: Whether to include disabled plugins

        Returns:
            List of plugin dictionaries with metadata
        """
        plugins = []

        # Scan enabled plugins directory
        enabled_path = os.path.join(install_path, "Plugins")
        if os.path.exists(enabled_path):
            enabled_plugins = self._scan_directory(enabled_path, enabled=True)
            plugins.extend(enabled_plugins)
            self.logger.debug(
                f"Found {len(enabled_plugins)} enabled plugins in {enabled_path}"
            )

        # Scan disabled plugins directory if requested
        if include_disabled:
            disabled_path = os.path.join(install_path, "Plugins (Disabled)")
            if os.path.exists(disabled_path):
                disabled_plugins = self._scan_directory(disabled_path, enabled=False)
                plugins.extend(disabled_plugins)
                self.logger.debug(
                    f"Found {len(disabled_plugins)} disabled plugins in {disabled_path}"
                )

        self.logger.debug(f"Total plugins scanned: {len(plugins)}")
        return plugins

    def _scan_directory(self, directory_path: str, enabled: bool) -> List[Dict]:
        """
        Scan a specific directory for .indigoPlugin bundles.

        Args:
            directory_path: Path to scan for plugins
            enabled: Whether plugins in this directory are enabled

        Returns:
            List of plugin dictionaries
        """
        plugins = []

        # Find all .indigoPlugin bundles
        pattern = os.path.join(directory_path, "*.indigoPlugin")
        plugin_bundles = glob.glob(pattern)

        for bundle_path in plugin_bundles:
            try:
                plugin_info = self._parse_plugin_bundle(bundle_path, enabled)
                if plugin_info:
                    plugins.append(plugin_info)
            except Exception as e:
                self.logger.warning(
                    f"Failed to parse plugin bundle {bundle_path}: {e}"
                )
                continue

        return plugins

    def _parse_plugin_bundle(
        self, bundle_path: str, enabled: bool
    ) -> Optional[Dict]:
        """
        Parse a plugin bundle and extract metadata.

        Args:
            bundle_path: Path to .indigoPlugin bundle
            enabled: Whether plugin is enabled

        Returns:
            Plugin metadata dictionary or None if parsing failed
        """
        # Read Info.plist
        info_plist_path = os.path.join(bundle_path, "Contents", "Info.plist")
        if not os.path.exists(info_plist_path):
            self.logger.debug(
                f"Info.plist not found at {info_plist_path}, skipping bundle"
            )
            return None

        try:
            with open(info_plist_path, "rb") as f:
                plist_data = plistlib.load(f)
        except Exception as e:
            self.logger.warning(f"Failed to read Info.plist at {info_plist_path}: {e}")
            return None

        # Extract metadata
        plugin_id = plist_data.get("CFBundleIdentifier")
        if not plugin_id:
            self.logger.debug(
                f"No CFBundleIdentifier in {info_plist_path}, skipping bundle"
            )
            return None

        plugin_name = plist_data.get("CFBundleDisplayName") or plist_data.get(
            "CFBundleName"
        )
        plugin_version = plist_data.get("CFBundleVersion", "Unknown")

        # Check actual enabled status via Indigo API (if available)
        actual_enabled = enabled
        if indigo:
            try:
                plugin = indigo.server.getPlugin(plugin_id)
                actual_enabled = plugin.isEnabled()
            except Exception as e:
                self.logger.debug(
                    f"Could not check enabled status for {plugin_id}: {e}"
                )

        return {
            "id": plugin_id,
            "name": plugin_name or os.path.basename(bundle_path).replace(
                ".indigoPlugin", ""
            ),
            "version": plugin_version,
            "enabled": actual_enabled,
            "path": bundle_path,
        }

    def parse_info_plist(self, plist_path: str) -> Optional[Dict]:
        """
        Parse an Info.plist file and extract plugin metadata.

        Args:
            plist_path: Path to Info.plist file

        Returns:
            Dictionary with metadata or None if parsing failed
        """
        if not os.path.exists(plist_path):
            return None

        try:
            with open(plist_path, "rb") as f:
                plist_data = plistlib.load(f)

            return {
                "id": plist_data.get("CFBundleIdentifier"),
                "name": plist_data.get("CFBundleDisplayName")
                or plist_data.get("CFBundleName"),
                "version": plist_data.get("CFBundleVersion"),
            }
        except Exception as e:
            self.logger.warning(f"Failed to parse Info.plist at {plist_path}: {e}")
            return None
