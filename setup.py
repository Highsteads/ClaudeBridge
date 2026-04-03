#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# Filename:    setup.py
# Description: ClaudeBridge automated installer — sets up the plugin, proxy script,
#              and Claude Code MCP configuration in one command.
# Author:      CliveS & Claude Sonnet 4.6
# Date:        03-04-2026
# Version:     1.0
#
# Usage:
#   python3 setup.py
#
# What this script does:
#   1. Copies Claude Bridge.indigoPlugin to the Indigo Plugins directory
#   2. Copies indigo_mcp_proxy.py to Indigo's Python Scripts directory
#   3. Reads the Bearer token from Indigo's secrets.json and patches the proxy
#   4. Creates/updates ~/.mcp.json with the indigo-mcp server entry
#   5. Creates/updates ~/.claude/settings.json with enabledMcpjsonServers
#   6. Prints a clear summary of remaining manual steps
#
# After running:
#   - Open Indigo → Plugins → Manage Plugins → Enable Claude Bridge
#   - Restart Claude Code

import json
import os
import re
import shutil
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

REPO_ROOT          = Path(__file__).parent.resolve()
PLUGIN_BUNDLE_NAME = "Claude Bridge.indigoPlugin"
PROXY_SCRIPT_NAME  = "indigo_mcp_proxy.py"
# Proxy lives inside the bundle — single source of truth, no separate repo-root copy needed
PROXY_IN_BUNDLE    = REPO_ROOT / PLUGIN_BUNDLE_NAME / "Contents" / "Server Plugin" / PROXY_SCRIPT_NAME

INDIGO_BASE        = Path("/Library/Application Support/Perceptive Automation")
INDIGO_APP         = INDIGO_BASE / "Indigo 2025.1"
PLUGINS_DIR        = INDIGO_APP / "Plugins"
SECRETS_JSON       = INDIGO_APP / "Preferences/secrets.json"

MCP_JSON_PATH      = Path.home() / ".mcp.json"
SETTINGS_JSON_PATH = Path.home() / ".claude/settings.json"

MCP_SERVER_NAME    = "indigo-mcp"

# Standard Indigo scripts directory — created during install if it doesn't exist
SCRIPTS_DIR    = INDIGO_BASE / "Scripts"
MCP_PROXY_DEST = SCRIPTS_DIR / PROXY_SCRIPT_NAME
MCP_SERVER_ENTRY = {
    "command": "python3",
    "args": [str(MCP_PROXY_DEST)]
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def ok(msg):  print(f"  ✅  {msg}")
def info(msg): print(f"  ℹ️   {msg}")
def warn(msg): print(f"  ⚠️   {msg}")
def err(msg):  print(f"  ❌  {msg}")


def read_json(path):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ──────────────────────────────────────────────────────────────────────────────
# Step 1: Copy plugin bundle
# ──────────────────────────────────────────────────────────────────────────────

def install_plugin_bundle():
    src  = REPO_ROOT / PLUGIN_BUNDLE_NAME
    dest = PLUGINS_DIR / PLUGIN_BUNDLE_NAME

    if not src.exists():
        err(f"Plugin bundle not found in repo: {src}")
        sys.exit(1)

    if not PLUGINS_DIR.exists():
        err(f"Indigo Plugins directory not found: {PLUGINS_DIR}")
        err("Is Indigo 2025.1 installed?")
        sys.exit(1)

    if dest.exists():
        info(f"Plugin already present — updating: {PLUGIN_BUNDLE_NAME}")
        shutil.rmtree(dest)

    shutil.copytree(src, dest)
    ok(f"Plugin bundle copied to: {dest}")


# ──────────────────────────────────────────────────────────────────────────────
# Step 2: Copy proxy script
# ──────────────────────────────────────────────────────────────────────────────

def install_proxy_script():
    # Proxy lives inside the bundle — same copy the plugin uses for auto-setup
    src = PROXY_IN_BUNDLE

    if not src.exists():
        err(f"Proxy script not found in bundle: {src}")
        sys.exit(1)

    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, MCP_PROXY_DEST)
    ok(f"Proxy script copied to: {MCP_PROXY_DEST}")


# ──────────────────────────────────────────────────────────────────────────────
# Step 3: Read Bearer token and patch proxy
# ──────────────────────────────────────────────────────────────────────────────

def patch_proxy_bearer_token():
    # secrets.json is a JSON array; the Bearer token is at index [0]
    if not SECRETS_JSON.exists():
        warn(f"secrets.json not found at: {SECRETS_JSON}")
        warn("Bearer token NOT patched — edit BEARER_TOKEN in proxy script manually")
        return None

    with open(SECRETS_JSON) as f:
        secrets = json.load(f)

    if not isinstance(secrets, list) or not secrets:
        warn("secrets.json has unexpected format — Bearer token NOT patched")
        return None

    token = secrets[0]
    if not token:
        warn("Bearer token is empty in secrets.json — NOT patched")
        return None

    # Patch BEARER_TOKEN = "..." in the installed proxy script
    proxy_text = MCP_PROXY_DEST.read_text()
    new_text = re.sub(
        r'^(BEARER_TOKEN\s*=\s*")[^"]*(")',
        rf'\g<1>{token}\g<2>',
        proxy_text,
        flags=re.MULTILINE
    )

    if new_text == proxy_text:
        warn("Could not find BEARER_TOKEN line in proxy script — not patched")
        return None

    MCP_PROXY_DEST.write_text(new_text)
    ok(f"Bearer token patched in proxy script")
    return token


# ──────────────────────────────────────────────────────────────────────────────
# Step 4: Update ~/.mcp.json
# ──────────────────────────────────────────────────────────────────────────────

def update_mcp_json():
    data = read_json(MCP_JSON_PATH) or {}

    if "mcpServers" not in data:
        data["mcpServers"] = {}

    if data["mcpServers"].get(MCP_SERVER_NAME) == MCP_SERVER_ENTRY:
        ok(f"~/.mcp.json already has correct {MCP_SERVER_NAME} entry")
        return

    data["mcpServers"][MCP_SERVER_NAME] = MCP_SERVER_ENTRY
    write_json(MCP_JSON_PATH, data)
    ok(f"~/.mcp.json updated with {MCP_SERVER_NAME} entry")


# ──────────────────────────────────────────────────────────────────────────────
# Step 5: Update ~/.claude/settings.json
# ──────────────────────────────────────────────────────────────────────────────

def update_claude_settings():
    data = read_json(SETTINGS_JSON_PATH) or {}

    enabled = data.get("enabledMcpjsonServers", [])
    if MCP_SERVER_NAME in enabled:
        ok(f"~/.claude/settings.json already enables {MCP_SERVER_NAME}")
        return

    enabled.append(MCP_SERVER_NAME)
    data["enabledMcpjsonServers"] = enabled
    write_json(SETTINGS_JSON_PATH, data)
    ok(f"~/.claude/settings.json: added {MCP_SERVER_NAME} to enabledMcpjsonServers")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 60)
    print("  ClaudeBridge Setup")
    print("=" * 60)
    print()

    print("Step 1: Installing plugin bundle...")
    install_plugin_bundle()

    print("\nStep 2: Installing proxy script...")
    install_proxy_script()

    print("\nStep 3: Patching Bearer token...")
    patch_proxy_bearer_token()

    print("\nStep 4: Updating ~/.mcp.json...")
    update_mcp_json()

    print("\nStep 5: Updating ~/.claude/settings.json...")
    update_claude_settings()

    print()
    print("=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    print()
    print("Remaining manual steps:")
    print()
    print("  1. Open Indigo → Plugins → Manage Plugins")
    print("     → Enable 'Claude Bridge'")
    print("     (The plugin will auto-create its device on first enable)")
    print()
    print("  2. If prompted for an Anthropic API key:")
    print("     → Add ANTHROPIC_API_KEY to secrets.py, or")
    print("     → Enter it in Plugins → Claude Bridge → Configure")
    print()
    print("  3. Restart Claude Code")
    print("     → You should see 23 indigo-mcp tools available")
    print()


if __name__ == "__main__":
    main()
