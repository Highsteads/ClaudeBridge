#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: Claude Bridge Plugin — exposes Indigo devices, variables and actions
#              to Claude AI via the Model Context Protocol (MCP)
# Author:      CliveS & Claude Sonnet 4.6
# Date:        24-03-2026
# Version:     1.1

try:
    import indigo
except ImportError:
    pass

import json
import logging
import os
import platform
import socket

import anthropic

# Import our modules
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

        # Plugin configuration
        self.anthropic_api_key = plugin_prefs.get("anthropic_api_key", "")
        self.large_model = plugin_prefs.get("large_model", "claude-sonnet-4-6")
        self.small_model = plugin_prefs.get("small_model", "claude-haiku-4-5-20251001")

        # InfluxDB configuration
        self.enable_influxdb = plugin_prefs.get("enable_influxdb", False)
        self.influx_url = plugin_prefs.get("influx_url", "http://localhost")
        self.influx_port = plugin_prefs.get("influx_port", "8086")
        self.influx_login = plugin_prefs.get("influx_login", "")
        self.influx_password = plugin_prefs.get("influx_password", "")
        self.influx_database = plugin_prefs.get("influx_database", "indigo")

        # Security configuration
        self.access_mode = plugin_prefs.get("access_mode", "local_only")

        # Component instances
        self.data_provider = None
        self.mcp_handler = None
        self.auth_manager = AuthManager(logger=self.logger)

        # Device management
        self.mcp_server_device = None

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
        self.logger.info("Starting plugin...")

        # If no key in prefs, fall back to central secrets.py before testing
        if not self.anthropic_api_key:
            try:
                import importlib.util
                _spec = importlib.util.spec_from_file_location(
                    "secrets",
                    "/Library/Application Support/Perceptive Automation/secrets.py"
                )
                _secrets = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_secrets)
                self.anthropic_api_key = getattr(_secrets, "ANTHROPIC_API_KEY", "")
                if self.anthropic_api_key:
                    self.logger.info("\t✅ Anthropic API key loaded from secrets.py")
            except Exception as _e:
                self.logger.warning(f"\t⚠️  Could not load secrets.py: {_e}")

        # Test connections (now that key is loaded)
        if not self.test_connections():
            self.logger.error("\t❌ Required service connections failed - startup aborted")
            return

        # Log CPU architecture information
        self.check_cpu_compatibility()

        # Set Anthropic API key in environment for the modules to use
        os.environ["ANTHROPIC_API_KEY"] = self.anthropic_api_key

        # Set model environment variables
        os.environ["LARGE_MODEL"] = self.large_model
        os.environ["SMALL_MODEL"] = self.small_model

        # Set InfluxDB environment variables if enabled
        if self.enable_influxdb:
            os.environ["INFLUXDB_HOST"] = self.influx_url.replace(
                "http://", ""
            ).replace("https://", "")
            os.environ["INFLUXDB_PORT"] = str(self.influx_port)
            os.environ["INFLUXDB_USERNAME"] = self.influx_login
            os.environ["INFLUXDB_PASSWORD"] = self.influx_password
            os.environ["INFLUXDB_DATABASE"] = self.influx_database
            os.environ["INFLUXDB_ENABLED"] = "true"
        else:
            os.environ["INFLUXDB_ENABLED"] = "false"

        # Set DB_FILE environment variable for vector store
        db_path = os.path.join(
            indigo.server.getInstallFolderPath(),
            "Preferences/Plugins/com.clives.indigoplugin.claudebridge/vector_db",
        )
        os.environ["DB_FILE"] = db_path

        # Initialize data provider
        try:
            self.data_provider = IndigoDataProvider(logger=self.logger)
        except Exception as e:
            self.logger.error(f"\t❌ Data provider initialization failed: {e}")
            return

        # Initialize MCP handler (includes vector store initialization)
        try:
            self.mcp_handler = MCPHandler(
                data_provider=self.data_provider,
                logger=self.logger
            )

            # Log MCP client connection information
            self.logger.info("🌐 MCP Client Connection Information:")
            urls = self._get_mcp_client_urls()
            for url_info in urls:
                self.logger.info(f"   {url_info['label']}: {url_info['url']}")

        except Exception as e:
            self.logger.error(f"\t❌ MCP handler initialization failed: {e}")
            self.mcp_handler = None
            self.logger.error("\t❌ MCP server unavailable - plugin restart required")
            return

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
    # Menu Actions
    ########################################

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

        self.logger.info("\n".join(config_lines))

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
            # Apply values from dialog temporarily — fall back to secrets.py if field is blank
            dialog_key = values_dict.get("anthropic_api_key", "")
            if not dialog_key:
                try:
                    import importlib.util
                    _spec = importlib.util.spec_from_file_location(
                        "secrets",
                        "/Library/Application Support/Perceptive Automation/secrets.py"
                    )
                    _mod = importlib.util.module_from_spec(_spec)
                    _spec.loader.exec_module(_mod)
                    dialog_key = getattr(_mod, "ANTHROPIC_API_KEY", "")
                except Exception:
                    pass
            self.anthropic_api_key = dialog_key
            self.enable_influxdb = values_dict.get("enable_influxdb", False)
            self.influx_url = values_dict.get("influx_url", "http://localhost")
            self.influx_port = values_dict.get("influx_port", "8086")
            self.influx_login = values_dict.get("influx_login", "")
            self.influx_password = values_dict.get("influx_password", "")
            self.influx_database = values_dict.get("influx_database", "indigo")

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

        # Validate Anthropic API key — blank is OK if secrets.py provides it
        api_key = values_dict.get("anthropic_api_key", "")
        if not api_key:
            secrets_path = "/Library/Application Support/Perceptive Automation/secrets.py"
            has_secrets_key = False
            try:
                import importlib.util
                _spec = importlib.util.spec_from_file_location("secrets", secrets_path)
                _mod  = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
                has_secrets_key = bool(getattr(_mod, "ANTHROPIC_API_KEY", ""))
            except Exception:
                pass
            if not has_secrets_key:
                errors_dict["anthropic_api_key"] = "Enter an Anthropic API key (or add ANTHROPIC_API_KEY to secrets.py)"


        # Validate log level
        try:
            log_level = int(values_dict.get("log_level", 20))
            if log_level not in [5, 10, 20, 30, 40, 50]:
                errors_dict["log_level"] = "Invalid log level"
        except (ValueError, TypeError):
            errors_dict["log_level"] = "Log level must be a valid number"

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

            # Update device states to show server is available via IWS
            device.updateStateOnServer(key="serverStatus", value="Running")
            device.updateStateOnServer(key="accessMode", value="IWS")
            device.updateStateOnServer(key="lastActivity", value=str(indigo.server.getTime()))

    def deviceStopComm(self, device: indigo.Device) -> None:
        """
        Called when a device should stop communication.
        """
        if device.deviceTypeId == "mcpServer":
            self.logger.info(f"MCP Server device stopped: {device.name}")
            # Update device state
            device.updateStateOnServer(key="serverStatus", value="Stopped")

            # Clear device reference
            if self.mcp_server_device and self.mcp_server_device.id == device.id:
                self.mcp_server_device = None

    def deviceUpdated(self, origDev: indigo.Device, newDev: indigo.Device) -> None:
        """
        Called when a device configuration is updated.
        """
        if newDev.deviceTypeId == "mcpServer":
            changes = []
            
            # Check property changes (actual configuration)
            for key in newDev.pluginProps:
                old_val = origDev.pluginProps.get(key)
                new_val = newDev.pluginProps.get(key)
                if old_val != new_val:
                    changes.append(f"property '{key}': '{old_val}' → '{new_val}'")
            
            # Check state changes (runtime status)
            for key in newDev.states:
                if key in origDev.states:
                    old_val = origDev.states[key]
                    new_val = newDev.states[key]
                    if old_val != new_val:
                        changes.append(f"state '{key}': '{old_val}' → '{new_val}'")
            
            # Check device name change
            if origDev.name != newDev.name:
                changes.append(f"device name: '{origDev.name}' → '{newDev.name}'")
            
            # Log specific changes at debug level
            if changes:
                self.logger.debug(f"MCP Server device '{newDev.name}' updated: {', '.join(changes)}")

            # Check if access mode changed (keep at INFO level - important configuration change)
            old_access_mode = origDev.pluginProps.get(
                "server_access_mode", "local_only"
            )
            new_access_mode = newDev.pluginProps.get("server_access_mode", "local_only")

            if old_access_mode != new_access_mode:
                self.logger.info(
                    f"Access mode changed from {old_access_mode} to {new_access_mode}"
                )
                # No server restart needed - MCP runs via Indigo Web Server

            # Device name changes are handled automatically by Indigo

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

            # Core configuration — if key field is blank, fall back to secrets.py
            dialog_key = values_dict.get("anthropic_api_key", "")
            if not dialog_key:
                try:
                    import importlib.util
                    _spec = importlib.util.spec_from_file_location(
                        "secrets",
                        "/Library/Application Support/Perceptive Automation/secrets.py"
                    )
                    _mod = importlib.util.module_from_spec(_spec)
                    _spec.loader.exec_module(_mod)
                    dialog_key = getattr(_mod, "ANTHROPIC_API_KEY", "")
                except Exception:
                    pass
            self.anthropic_api_key = dialog_key
            self.large_model = values_dict.get("large_model", "claude-sonnet-4-6")
            self.small_model = values_dict.get("small_model", "claude-haiku-4-5-20251001")

            # Security configuration
            self.access_mode = values_dict.get("access_mode", "local_only")

            # InfluxDB configuration
            self.enable_influxdb = values_dict.get("enable_influxdb", False)
            self.influx_url = values_dict.get("influx_url", "http://localhost")
            self.influx_port = values_dict.get("influx_port", "8086")
            self.influx_login = values_dict.get("influx_login", "")
            self.influx_password = values_dict.get("influx_password", "")
            self.influx_database = values_dict.get("influx_database", "indigo")


            # Set environment variables (same as startup)
            os.environ["ANTHROPIC_API_KEY"] = self.anthropic_api_key
            os.environ["LARGE_MODEL"] = self.large_model
            os.environ["SMALL_MODEL"] = self.small_model

            # Set InfluxDB environment variables
            if self.enable_influxdb:
                os.environ["INFLUXDB_HOST"] = self.influx_url.replace(
                    "http://", ""
                ).replace("https://", "")
                os.environ["INFLUXDB_PORT"] = str(self.influx_port)
                os.environ["INFLUXDB_USERNAME"] = self.influx_login
                os.environ["INFLUXDB_PASSWORD"] = self.influx_password
                os.environ["INFLUXDB_DATABASE"] = self.influx_database
                os.environ["INFLUXDB_ENABLED"] = "true"
            else:
                os.environ["INFLUXDB_ENABLED"] = "false"

            # Set DB_FILE environment variable for vector store (same as startup)
            db_path = os.path.join(
                indigo.server.getInstallFolderPath(),
                "Preferences/Plugins/com.clives.indigoplugin.claudebridge/vector_db",
            )
            os.environ["DB_FILE"] = db_path

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
