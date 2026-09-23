#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    client_setup.py
# Description: Claude Code auto-setup run at plugin start - deploys the MCP proxy
#              with the bearer token patched in, and registers it in ~/.mcp.json
#              and ~/.claude/settings.json
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved out of plugin.py in the 3.0 spring clean so it can be tested against
# temporary folders. Every path comes in as an argument; nothing here imports
# indigo, so a test never touches the real home folder or Indigo install.

import json
import os
import re
import shutil
from pathlib import Path
from typing import List, Optional

SERVER_KEY = "indigo-mcp"
PROXY_NAME = "indigo_mcp_proxy.py"

# The line the token is written into. A rename of that line in the proxy would
# otherwise turn the patch into a silent no-op (see patch_bearer_token).
_TOKEN_LINE = re.compile(r'^(BEARER_TOKEN\s*=\s*")[^"]*(")', re.MULTILINE)


def scripts_dir_for(install_folder) -> Path:
    """Indigo's shared Scripts folder. getInstallFolderPath() returns the
    VERSIONED folder and the two script folders sit at its parent. A literal
    path once created a bogus Scripts folder on a non-default install root,
    deployed the proxy (carrying the live token) into it, pointed ~/.mcp.json
    at that dead path and logged success."""
    return Path(os.path.dirname(str(install_folder))) / "Scripts"


def read_iws_token(install_folder, logger) -> str:
    """The first IWS API key from Indigo's Preferences/secrets.json, or "".

    The shape is checked before element 0 is trusted: a non-list, or an empty,
    blank or non-string entry, falls through to the IndigoSecrets.py fallback
    rather than patching junk into the proxy."""
    secrets_path = Path(install_folder) / "Preferences" / "secrets.json"
    if not secrets_path.exists():
        return ""
    try:
        data = json.loads(secrets_path.read_text())
    except Exception as exc:
        logger.warning(f"\tIWS secrets.json read failed: {exc}")
        return ""
    if isinstance(data, list) and data and isinstance(data[0], str) and data[0].strip():
        return data[0].strip()
    return ""


def patch_bearer_token(proxy_path: Path, token: str, logger) -> bool:
    """Write the token into the deployed proxy. True only when it went in."""
    try:
        text = proxy_path.read_text(encoding="utf-8")
        # Callable replacement so a token holding backslashes, '\g<...>' or
        # quotes goes in LITERALLY - a plain replacement string would read
        # backreferences and silently corrupt it. subn, not sub, so a missing
        # line is noticed instead of deploying the placeholder.
        new_text, count = _TOKEN_LINE.subn(lambda m: m.group(1) + token + m.group(2), text)
        if not count:
            logger.error(
                "[Config] BEARER_TOKEN line not found in the bundled MCP "
                "proxy — the token was NOT patched in and Claude Code will "
                "fail to authenticate. The proxy's token line has been "
                "renamed or removed."
            )
            return False
        proxy_path.write_text(new_text, encoding="utf-8")
        return True
    except Exception as exc:
        logger.error(f"[Config] Bearer token patch failed: {exc}")
        return False


def deploy_proxy(bundle_dir, install_folder, fallback_token: str, logger) -> Optional[bool]:
    """Copy the bundled proxy into Indigo's Scripts folder and patch the token.

    Returns True when the proxy was deployed with a token, False when it was
    copied but carries no token, None when the bundle has no proxy to copy.
    The token comes from Indigo's secrets.json first, then from
    CLAUDEBRIDGE_BEARER_TOKEN in IndigoSecrets.py (``fallback_token``)."""
    bundle_proxy = Path(bundle_dir) / PROXY_NAME
    if not bundle_proxy.exists():
        logger.warning(f"\t{PROXY_NAME} not found in bundle — skipping proxy setup")
        return None
    scripts_dir = scripts_dir_for(install_folder)
    dest_proxy  = scripts_dir / PROXY_NAME
    scripts_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle_proxy, dest_proxy)

    token = read_iws_token(install_folder, logger) or (fallback_token or "")
    patched = False
    if not token:
        logger.error(
            "[Config] No bearer token available to patch into the MCP proxy. "
            "Indigo IWS Preferences/secrets.json is empty AND "
            "CLAUDEBRIDGE_BEARER_TOKEN is not set in IndigoSecrets.py. "
            "Claude Code will not be able to authenticate. "
            "Generate an IWS bearer token in Indigo (Server -> Web Server -> "
            "Manage Authentication) or add CLAUDEBRIDGE_BEARER_TOKEN to "
            "/Library/Application Support/Perceptive Automation/IndigoSecrets.py."
        )
    else:
        patched = patch_bearer_token(dest_proxy, token, logger)

    # The deployed proxy may hold the live token, so it must not be group or
    # world readable (it used to inherit the umask's 0o640).
    try:
        os.chmod(dest_proxy, 0o600)
    except Exception as exc:
        logger.warning(f"\tCould not chmod deployed proxy to 0o600: {exc}")
    return patched


def update_mcp_json(home, proxy_path: Path, logger) -> bool:
    """Point the indigo-mcp entry in ~/.mcp.json at the deployed proxy. True
    when the file changed; other servers in it are left alone."""
    mcp_json_path = Path(home) / ".mcp.json"
    entry = {"command": "python3", "args": [str(proxy_path)]}
    try:
        data = json.loads(mcp_json_path.read_text()) if mcp_json_path.exists() else {}
        if data.get("mcpServers", {}).get(SERVER_KEY) == entry:
            return False
        data.setdefault("mcpServers", {})[SERVER_KEY] = entry
        mcp_json_path.write_text(json.dumps(data, indent=2) + "\n")
        return True
    except Exception as exc:
        logger.warning(f"\t⚠️  Could not update ~/.mcp.json: {exc}")
        return False


def update_claude_settings(home, logger) -> bool:
    """Add indigo-mcp to enabledMcpjsonServers in ~/.claude/settings.json.
    True when the file changed; every other setting is left as it was."""
    settings_path = Path(home) / ".claude" / "settings.json"
    try:
        data = json.loads(settings_path.read_text()) if settings_path.exists() else {}
        enabled = data.get("enabledMcpjsonServers", [])
        if SERVER_KEY in enabled:
            return False
        enabled.append(SERVER_KEY)
        data["enabledMcpjsonServers"] = enabled
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(data, indent=2) + "\n")
        return True
    except Exception as exc:
        logger.warning(f"\t⚠️  Could not update ~/.claude/settings.json: {exc}")
        return False


def setup_claude_code_integration(logger, *, bundle_dir, install_folder, home,
                                  fallback_token: str = "") -> List[str]:
    """Everything Claude Code needs to connect, with no Terminal steps: the
    proxy in Indigo's Scripts folder with the token in it, and the two
    dotfile entries. Returns the list of things it changed."""
    changed = []
    # Only claim the proxy was configured when the token actually went in -
    # reporting success on the no-token and patch-failed paths is how a broken
    # deployment looks healthy.
    if deploy_proxy(bundle_dir, install_folder, fallback_token, logger):
        changed.append("proxy script")
    proxy_path = scripts_dir_for(install_folder) / PROXY_NAME
    if update_mcp_json(home, proxy_path, logger):
        changed.append("~/.mcp.json")
    if update_claude_settings(home, logger):
        changed.append("~/.claude/settings.json")

    if changed:
        logger.info(f"\t✅ Claude Code integration configured: {', '.join(changed)}")
        logger.info("\t   Restart Claude Code to activate the indigo-mcp tools")
    else:
        logger.info("\t✅ Claude Code integration already up to date")
    return changed
