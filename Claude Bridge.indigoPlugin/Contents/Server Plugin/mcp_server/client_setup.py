#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    client_setup.py
# Description: Claude Code auto-setup run at plugin start - deploys the MCP proxy
#              with the bearer token patched in, and registers it in ~/.mcp.json
#              and ~/.claude/settings.json
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.2
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
#
# 1.2 (25-09-2026): the web server's scheme, host and port are patched into
#   the proxy too, from indigo.server.getWebServerURL() (passed in, as this
#   module does not import indigo). The proxy used to assume http on
#   localhost:8176, so an HTTPS-only or moved web server was unreachable. The
#   host stays "localhost" when the URL names this Mac; with no usable URL the
#   old defaults stand.

import ipaddress
import json
import os
import re
import socket
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

SERVER_KEY = "indigo-mcp"
PROXY_NAME = "indigo_mcp_proxy.py"

# The line the token is written into. A rename of that line in the proxy would
# otherwise turn the patch into a silent no-op (see patch_bearer_token). The
# value is a whole double-quoted Python string literal, escapes included, so a
# proxy that was already patched can be patched again.
_TOKEN_LINE = re.compile(r'^(BEARER_TOKEN\s*=\s*)"(?:[^"\\\n]|\\.)*"', re.MULTILINE)

# The web server the proxy talks to: the proxy's defaults, and the lines they
# are written into.
DEFAULT_TARGET = ("http", "localhost", 8176)
_TARGET_LINES = {
    "INDIGO_SCHEME": re.compile(r'^(INDIGO_SCHEME\s*=\s*)"[^"\n]*"', re.MULTILINE),
    "INDIGO_HOST":   re.compile(r'^(INDIGO_HOST\s*=\s*)"[^"\n]*"', re.MULTILINE),
    "INDIGO_PORT":   re.compile(r'^(INDIGO_PORT\s*=\s*)\d+', re.MULTILINE),
}


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_this_machine(host: str) -> bool:
    """True if host names this Mac: a loopback name, the Mac's own host name
    (with or without .local), or an address that is on one of its interfaces —
    which is exactly an address a socket can bind to. Best effort: a lookup
    that fails answers False, and the URL's own host is then used."""
    host = (host or "").strip("[]").rstrip(".").lower()
    if not host:
        return False
    if _is_loopback(host):
        return True
    try:
        own = socket.gethostname().lower()
        own_base = own[:-len(".local")] if own.endswith(".local") else own
        if own and host in (own, own_base, f"{own_base}.local"):
            return True
        for family, _type, _proto, _name, sockaddr in socket.getaddrinfo(host, None):
            address = sockaddr[0]
            if _is_loopback(address):
                return True
            with socket.socket(family, socket.SOCK_DGRAM) as probe:
                try:
                    probe.bind((address, 0))
                    return True
                except OSError:
                    continue
    except (OSError, UnicodeError, ValueError):
        return False
    return False


def web_server_target(url: Optional[str]) -> Tuple[str, str, int]:
    """(scheme, host, port) for the proxy from Indigo's web server URL, or
    DEFAULT_TARGET when there is no usable URL."""
    try:
        parts = urlsplit(str(url or "").strip())
        scheme = (parts.scheme or "").lower()
        host = parts.hostname
        port = parts.port
    except ValueError:
        return DEFAULT_TARGET
    if scheme not in ("http", "https") or not host:
        return DEFAULT_TARGET
    if port is None:
        port = 443 if scheme == "https" else 80
    if is_this_machine(host):
        host = "localhost"
    return scheme, host, int(port)


def _patch_target(text: str, target: Tuple[str, str, int], logger) -> str:
    """The proxy source pointed at target. A missing line is warned about and
    left at its default: the proxy still runs, just not with the new value."""
    scheme, host, port = target
    values = {"INDIGO_SCHEME": json.dumps(scheme), "INDIGO_HOST": json.dumps(host),
              "INDIGO_PORT": str(int(port))}
    for name, pattern in _TARGET_LINES.items():
        text, count = pattern.subn(lambda m, v=values[name]: m.group(1) + v, text)
        if not count:
            logger.warning(f"\t⚠️  {name} line not found in the bundled MCP proxy — "
                           f"it keeps its built-in default")
    return text


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


def deploy_proxy(bundle_dir, install_folder, fallback_token: str, logger,
                 web_server_url: Optional[str] = None) -> Optional[bool]:
    """Copy the bundled proxy into Indigo's Scripts folder and patch the token
    and the web server's address.

    Returns True when the proxy was deployed with a token, False when it was
    copied but carries no token, None when the bundle has no proxy to copy.
    The token comes from Indigo's secrets.json first, then from
    CLAUDEBRIDGE_BEARER_TOKEN in IndigoSecrets.py (``fallback_token``). The
    address comes from ``web_server_url`` (indigo.server.getWebServerURL()),
    falling back to http://localhost:8176."""
    bundle_proxy = Path(bundle_dir) / PROXY_NAME
    if not bundle_proxy.exists():
        logger.warning(f"\t{PROXY_NAME} not found in bundle — skipping proxy setup")
        return None
    scripts_dir = scripts_dir_for(install_folder)
    dest_proxy  = scripts_dir / PROXY_NAME
    scripts_dir.mkdir(parents=True, exist_ok=True)
    source = bundle_proxy.read_text(encoding="utf-8")
    target = web_server_target(web_server_url)
    source = _patch_target(source, target, logger)
    if target != DEFAULT_TARGET:
        logger.debug(f"\tMCP proxy points at {target[0]}://{target[1]}:{target[2]}")

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
                                  fallback_token: str = "",
                                  web_server_url: Optional[str] = None) -> List[str]:
    """Everything Claude Code needs to connect, with no Terminal steps: the
    proxy in Indigo's Scripts folder with the token and the web server's
    address in it, and the two dotfile entries. Returns the list of things it
    changed."""
    changed = []
    # Only claim the proxy was configured when the token actually went in -
    # reporting success on the no-token and patch-failed paths is how a broken
    # deployment looks healthy.
    if deploy_proxy(bundle_dir, install_folder, fallback_token, logger,
                    web_server_url=web_server_url):
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
