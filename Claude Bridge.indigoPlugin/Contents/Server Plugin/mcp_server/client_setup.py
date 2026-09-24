#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    client_setup.py
# Description: Claude Code auto-setup run at plugin start - deploys the MCP proxy
#              with the bearer token patched in, and registers it in ~/.mcp.json
#              and ~/.claude/settings.json
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.1
#
# Moved out of plugin.py in the 3.0 spring clean so it can be tested against
# temporary folders. Every path comes in as an argument; nothing here imports
# indigo, so a test never touches the real home folder or Indigo install.
#
# 1.1 (24-09-2026): the proxy is written owner-only from the first byte (a
#   0600 temp file renamed into place), where it used to be copied at the
#   bundle's mode, patched, and only then chmodded - a window in which the
#   live token sat in a readable file. The token goes in as a Python string
#   literal (json.dumps), so no character in it can break the source. Every
#   read and write names UTF-8.

import json
import os
import re
from pathlib import Path
from typing import List, Optional

SERVER_KEY = "indigo-mcp"
PROXY_NAME = "indigo_mcp_proxy.py"

# The line the token is written into. A rename of that line in the proxy would
# otherwise turn the patch into a silent no-op (see patch_bearer_token). The
# value is a whole double-quoted Python string literal, escapes included, so a
# proxy that was already patched can be patched again.
_TOKEN_LINE = re.compile(r'^(BEARER_TOKEN\s*=\s*)"(?:[^"\\\n]|\\.)*"', re.MULTILINE)


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
        data = json.loads(secrets_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"\tIWS secrets.json read failed: {exc}")
        return ""
    if isinstance(data, list) and data and isinstance(data[0], str) and data[0].strip():
        return data[0].strip()
    return ""


def _patch_source(text: str, token: str, logger) -> Optional[str]:
    """The proxy source with the token in it, or None if the line is missing."""
    # json.dumps makes a valid Python string literal of any token: quotes,
    # backslashes and non-ASCII are escaped, so the deployed proxy reads back
    # exactly the token. A callable replacement, so nothing in the token is
    # read as a regex backreference. subn, not sub, so a missing line is
    # noticed instead of deploying the placeholder.
    new_text, count = _TOKEN_LINE.subn(lambda m: m.group(1) + json.dumps(token), text)
    if not count:
        logger.error(
            "[Config] BEARER_TOKEN line not found in the bundled MCP "
            "proxy — the token was NOT patched in and Claude Code will "
            "fail to authenticate. The proxy's token line has been "
            "renamed or removed."
        )
        return None
    return new_text


def write_private(path: Path, text: str) -> None:
    """Write text to path owner-only (0600) from the first byte: a temp file
    created 0600 beside it, then renamed over it. There is never a moment when
    the content sits in a file anyone else can read."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.unlink()        # an old temp file would keep its old mode through O_TRUNC
    except FileNotFoundError:
        pass
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(str(tmp), str(path))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def patch_bearer_token(proxy_path: Path, token: str, logger) -> bool:
    """Write the token into a deployed proxy in place. True only when it went in."""
    try:
        new_text = _patch_source(Path(proxy_path).read_text(encoding="utf-8"), token, logger)
        if new_text is None:
            return False
        write_private(Path(proxy_path), new_text)
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
    source = bundle_proxy.read_text(encoding="utf-8")

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
        new_source = _patch_source(source, token, logger)
        if new_source is not None:
            source, patched = new_source, True

    # The deployed proxy may hold the live token, so it is written owner-only
    # from the first byte (it used to be copied at the bundle's mode and
    # chmodded afterwards).
    write_private(dest_proxy, source)
    return patched


def update_mcp_json(home, proxy_path: Path, logger) -> bool:
    """Point the indigo-mcp entry in ~/.mcp.json at the deployed proxy. True
    when the file changed; other servers in it are left alone."""
    mcp_json_path = Path(home) / ".mcp.json"
    entry = {"command": "python3", "args": [str(proxy_path)]}
    try:
        data = (json.loads(mcp_json_path.read_text(encoding="utf-8"))
                if mcp_json_path.exists() else {})
        if data.get("mcpServers", {}).get(SERVER_KEY) == entry:
            return False
        data.setdefault("mcpServers", {})[SERVER_KEY] = entry
        mcp_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning(f"\t⚠️  Could not update ~/.mcp.json: {exc}")
        return False


def update_claude_settings(home, logger) -> bool:
    """Add indigo-mcp to enabledMcpjsonServers in ~/.claude/settings.json.
    True when the file changed; every other setting is left as it was."""
    settings_path = Path(home) / ".claude" / "settings.json"
    try:
        data = (json.loads(settings_path.read_text(encoding="utf-8"))
                if settings_path.exists() else {})
        enabled = data.get("enabledMcpjsonServers", [])
        if SERVER_KEY in enabled:
            return False
        enabled.append(SERVER_KEY)
        data["enabledMcpjsonServers"] = enabled
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
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
