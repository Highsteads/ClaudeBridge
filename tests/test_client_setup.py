#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_client_setup.py
# Description: Claude Code auto-setup (mcp_server/client_setup.py), run against
#              temporary folders: the proxy is deployed owner-only with the
#              token patched in literally, and ~/.mcp.json and
#              ~/.claude/settings.json gain one entry without losing anything.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Replaces test_install_chmods_the_deployed_proxy, which read install.py's
# source text. install.py is gone: double-clicking the bundle installs it and
# the plugin does this setup itself at start.

import ast
import json
import logging
import os
import shutil
import stat
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conftest import SERVER_PLUGIN, load_plugin_module
from mcp_server import client_setup


class _Recorder(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append((record.levelname, record.getMessage()))

    def text(self, level=None):
        return "\n".join(m for lv, m in self.records if level in (None, lv))


@pytest.fixture()
def env(tmp_path):
    root    = tmp_path / "Perceptive Automation"
    install = root / "Indigo 2025.2"
    (install / "Preferences").mkdir(parents=True)
    bundle  = tmp_path / "Server Plugin"
    bundle.mkdir()
    shutil.copy2(os.path.join(SERVER_PLUGIN, "indigo_mcp_proxy.py"), bundle)
    home = tmp_path / "home"
    home.mkdir()
    log = logging.getLogger(f"test-client-setup-{tmp_path.name}")
    log.setLevel(logging.DEBUG)
    rec = _Recorder()
    log.addHandler(rec)
    return SimpleNamespace(root=root, install=install, bundle=bundle, home=home,
                           log=log, rec=rec, proxy=root / "Scripts" / "indigo_mcp_proxy.py")


def _run(env, fallback=""):
    return client_setup.setup_claude_code_integration(
        env.log, bundle_dir=str(env.bundle), install_folder=str(env.install),
        home=str(env.home), fallback_token=fallback)


def _token_in(proxy):
    """The token the deployed proxy will actually USE: its BEARER_TOKEN line
    read as the Python literal it is, not as raw text."""
    for line in proxy.read_text(encoding="utf-8").splitlines():
        if line.startswith("BEARER_TOKEN"):
            return ast.literal_eval(line.split("=", 1)[1].strip())
    raise AssertionError("no BEARER_TOKEN line")


def _write_secrets(env, data):
    (env.install / "Preferences" / "secrets.json").write_text(json.dumps(data))


def test_full_setup_from_a_clean_home(env):
    _write_secrets(env, ["iws-token-123"])
    changed = _run(env)
    assert changed == ["proxy script", "~/.mcp.json", "~/.claude/settings.json"]
    # The proxy lands in the Scripts folder beside the versioned folder.
    assert _token_in(env.proxy) == "iws-token-123"
    mcp = json.loads((env.home / ".mcp.json").read_text())
    assert mcp["mcpServers"]["indigo-mcp"] == {"command": "python3", "args": [str(env.proxy)]}
    settings = json.loads((env.home / ".claude" / "settings.json").read_text())
    assert settings["enabledMcpjsonServers"] == ["indigo-mcp"]


def test_the_deployed_proxy_is_owner_only(env):
    """It carries the live bearer token, so it must not be group/world readable."""
    _write_secrets(env, ["iws-token-123"])
    _run(env)
    assert stat.S_IMODE(os.stat(env.proxy).st_mode) == 0o600


def test_the_fallback_token_is_used_when_secrets_json_is_unusable(env):
    for bad in ([], [""], ["   "], [42], {"a": 1}):
        _write_secrets(env, bad)
        _run(env, fallback="from-indigosecrets")
        assert _token_in(env.proxy) == "from-indigosecrets", bad


def test_a_token_is_inserted_literally(env):
    token = r'ab\1\g<0>c\\d'
    _write_secrets(env, [token])
    _run(env)
    assert _token_in(env.proxy) == token


def test_no_token_is_an_error_and_not_reported_as_configured(env):
    changed = _run(env)
    assert "proxy script" not in changed
    assert "No bearer token" in env.rec.text("ERROR")
    assert stat.S_IMODE(os.stat(env.proxy).st_mode) == 0o600


def test_a_missing_token_line_is_an_error_not_a_silent_no_op(env):
    (env.bundle / "indigo_mcp_proxy.py").write_text("TOKEN_RENAMED = ''\n", encoding="utf-8")
    _write_secrets(env, ["iws-token-123"])
    changed = _run(env)
    assert "proxy script" not in changed
    assert "BEARER_TOKEN line not found" in env.rec.text("ERROR")


def test_existing_dotfiles_keep_everything_else(env):
    (env.home / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    (env.home / ".claude").mkdir()
    (env.home / ".claude" / "settings.json").write_text(
        json.dumps({"theme": "dark", "enabledMcpjsonServers": ["other"]}))
    _write_secrets(env, ["t"])
    _run(env)
    mcp = json.loads((env.home / ".mcp.json").read_text())
    assert set(mcp["mcpServers"]) == {"other", "indigo-mcp"}
    settings = json.loads((env.home / ".claude" / "settings.json").read_text())
    assert settings["theme"] == "dark"
    assert settings["enabledMcpjsonServers"] == ["other", "indigo-mcp"]


def test_a_second_run_changes_no_dotfile(env):
    _write_secrets(env, ["t"])
    _run(env)
    before = ((env.home / ".mcp.json").stat().st_mtime_ns,
              (env.home / ".claude" / "settings.json").stat().st_mtime_ns)
    changed = _run(env)
    assert changed == ["proxy script"]      # the proxy is always re-copied from the bundle
    after = ((env.home / ".mcp.json").stat().st_mtime_ns,
             (env.home / ".claude" / "settings.json").stat().st_mtime_ns)
    assert before == after


def test_no_proxy_in_the_bundle_still_writes_the_dotfiles(env):
    (env.bundle / "indigo_mcp_proxy.py").unlink()
    changed = _run(env)
    assert changed == ["~/.mcp.json", "~/.claude/settings.json"]
    assert "not found in bundle" in env.rec.text("WARNING")
    assert not env.proxy.exists()


# ── the plugin calls it, unless the user turned it off ───────────────────────

@pytest.mark.parametrize("stored,expected_calls", [(None, 1), (True, 1), ("false", 0), (False, 0)])
def test_startup_honours_the_auto_configure_checkbox(monkeypatch, tmp_path, stored, expected_calls):
    mod = load_plugin_module()
    p = object.__new__(mod.Plugin)
    p.pluginId = "com.clives.indigoplugin.claudebridge"
    p.pluginVersion = "test"
    p.allow_destructive_delete = False
    p.rate_limit_per_minute, p.rate_limit_per_day, p.cache_ttl_seconds = 120, 5000, 60
    p.logger = logging.getLogger("test-client-setup-startup")
    p.pluginPrefs = {} if stored is None else {"auto_configure_claude_code": stored}
    p._init_webhooks = MagicMock()
    ind = sys.modules["indigo"]
    install = str(tmp_path / "Indigo 2025.2")
    monkeypatch.setattr(ind, "server", SimpleNamespace(getInstallFolderPath=lambda: install,
                                                       getReflectorURL=lambda: None))
    monkeypatch.setattr(mod, "IndigoDataProvider", MagicMock())
    monkeypatch.setattr(mod, "MCPHandler", MagicMock())
    setup = MagicMock(return_value=[])
    monkeypatch.setattr(mod.client_setup, "setup_claude_code_integration", setup)
    monkeypatch.chdir(SERVER_PLUGIN)
    p.startup()
    assert setup.call_count == expected_calls
    if expected_calls:
        kwargs = setup.call_args.kwargs
        assert kwargs["bundle_dir"] == os.getcwd()
        assert kwargs["install_folder"] == install
        assert kwargs["home"] == os.path.expanduser("~")


# ── 1.1: a literal token, and owner-only from the first byte ─────────────────

@pytest.mark.parametrize("token", ['has"quote', "back\\slash\\", "new\nline", "pound-£-and-é", "'single'"])
def test_any_token_round_trips_as_a_python_literal(env, token):
    _write_secrets(env, [token])
    assert "proxy script" in _run(env)
    assert _token_in(env.proxy) == token
    compile(env.proxy.read_text(encoding="utf-8"), "proxy", "exec")   # still valid Python


def test_the_proxy_is_never_written_at_a_wider_mode(env, monkeypatch):
    """Every file the setup creates in Scripts/ is 0600 when it is created,
    not chmodded afterwards — the bundle copy is 0644 or wider."""
    os.chmod(env.bundle / "indigo_mcp_proxy.py", 0o755)
    _write_secrets(env, ["iws-token-123"])
    created = []
    real_open = os.open

    def _spy(path, flags, mode=0o777, *a, **k):
        if flags & os.O_CREAT and "Scripts" in str(path):
            created.append((str(path), mode))
        return real_open(path, flags, mode, *a, **k)

    monkeypatch.setattr(client_setup.os, "open", _spy)
    _run(env)
    assert created and all(mode == 0o600 for _, mode in created), created
    assert stat.S_IMODE(os.stat(env.proxy).st_mode) == 0o600
    assert not [p for p in os.listdir(env.proxy.parent) if p.endswith(".tmp")]


def test_an_existing_readable_proxy_ends_owner_only(env):
    env.proxy.parent.mkdir(parents=True)
    env.proxy.write_text("old", encoding="utf-8")
    os.chmod(env.proxy, 0o644)
    _write_secrets(env, ["t"])
    _run(env)
    assert stat.S_IMODE(os.stat(env.proxy).st_mode) == 0o600
    assert _token_in(env.proxy) == "t"


def test_dotfiles_are_read_and_written_as_utf8(env):
    (env.home / ".claude").mkdir()
    (env.home / ".claude" / "settings.json").write_text(
        json.dumps({"note": "café £5"}, ensure_ascii=False), encoding="utf-8")
    _write_secrets(env, ["t"])
    _run(env)
    settings = json.loads((env.home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["note"] == "café £5"


# ── 1.2: the web server's real address goes into the proxy too ──────────────

def _deployed(env, url):
    """Deploy with this web server URL and import the proxy that results."""
    import importlib.util
    _write_secrets(env, ["a-token-for-the-address-tests"])
    assert client_setup.setup_claude_code_integration(
        env.log, bundle_dir=str(env.bundle), install_folder=str(env.install),
        home=str(env.home), web_server_url=url)
    spec = importlib.util.spec_from_file_location(f"cb_deployed_{abs(hash(url))}", env.proxy)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.BEARER_TOKEN == "a-token-for-the-address-tests"
    return module


@pytest.mark.parametrize("url", [None, "", "not a url", "ftp://files.example/"])
def test_no_usable_url_keeps_the_old_default(env, url):
    proxy = _deployed(env, url)
    assert (proxy.INDIGO_SCHEME, proxy.INDIGO_HOST, proxy.INDIGO_PORT) == ("http", "localhost", 8176)


def test_another_hosts_address_is_written_in_full(env):
    # 203.0.113.0/24 is a documentation range: never one of this machine's.
    proxy = _deployed(env, "https://203.0.113.5:8443")
    assert (proxy.INDIGO_SCHEME, proxy.INDIGO_HOST, proxy.INDIGO_PORT) == ("https", "203.0.113.5", 8443)


@pytest.mark.parametrize("url,port", [("http://127.0.0.1:9000", 9000),
                                      ("https://localhost", 443),
                                      ("http://[::1]:8176/", 8176)])
def test_a_loopback_address_stays_localhost(env, url, port):
    proxy = _deployed(env, url)
    assert proxy.INDIGO_HOST == "localhost" and proxy.INDIGO_PORT == port


def test_this_macs_own_name_becomes_localhost(env, monkeypatch):
    monkeypatch.setattr(client_setup.socket, "gethostname", lambda: "Indigo-Mac")
    proxy = _deployed(env, "https://indigo-mac.local:8176")
    assert (proxy.INDIGO_SCHEME, proxy.INDIGO_HOST, proxy.INDIGO_PORT) == ("https", "localhost", 8176)


def test_an_address_on_this_machine_becomes_localhost():
    """An address a socket can bind to is on one of this machine's interfaces."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("203.0.113.1", 9))      # UDP: picks a route, sends nothing
            own = probe.getsockname()[0]
    except OSError:
        pytest.skip("no network interface to test with")
    if own.startswith("127."):
        pytest.skip("only a loopback interface here")
    assert client_setup.is_this_machine(own)
    assert client_setup.web_server_target(f"http://{own}:8176") == ("http", "localhost", 8176)
    assert not client_setup.is_this_machine("203.0.113.5")


def test_the_proxy_uses_tls_for_an_https_web_server(env):
    import http.client
    import ssl
    proxy = _deployed(env, "https://203.0.113.5:8443")
    proxy._connection = None
    conn = proxy._get_connection()
    assert isinstance(conn, http.client.HTTPSConnection)
    assert (conn.host, conn.port) == ("203.0.113.5", 8443)
    assert conn._context.verify_mode == ssl.CERT_REQUIRED       # another host: verified

    proxy = _deployed(env, "https://127.0.0.1:8176")
    proxy._connection = None
    conn = proxy._get_connection()
    assert isinstance(conn, http.client.HTTPSConnection) and conn.host == "localhost"
    # Loopback: the certificate names the Mac, never "localhost", and the
    # connection never leaves the machine.
    assert conn._context.verify_mode == ssl.CERT_NONE


def test_startup_passes_the_web_server_url(monkeypatch, tmp_path):
    mod = load_plugin_module()
    p = object.__new__(mod.Plugin)
    p.logger = logging.getLogger("test-client-setup-url")
    p.pluginPrefs = {}
    ind = sys.modules["indigo"]
    monkeypatch.setattr(ind, "server", SimpleNamespace(
        getInstallFolderPath=lambda: str(tmp_path / "Indigo 2025.2"),
        getWebServerURL=lambda: "https://203.0.113.5:8443"))
    setup = MagicMock(return_value=[])
    monkeypatch.setattr(mod.client_setup, "setup_claude_code_integration", setup)
    p._configure_claude_code()
    assert setup.call_args.kwargs["web_server_url"] == "https://203.0.113.5:8443"

    def _raises():
        raise RuntimeError("web server not configured")
    monkeypatch.setattr(ind, "server", SimpleNamespace(
        getInstallFolderPath=lambda: str(tmp_path / "Indigo 2025.2"), getWebServerURL=_raises))
    p._configure_claude_code()
    assert setup.call_args.kwargs["web_server_url"] == ""
