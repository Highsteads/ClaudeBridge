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
    for line in proxy.read_text(encoding="utf-8").splitlines():
        if line.startswith("BEARER_TOKEN"):
            return line.split("=", 1)[1].strip().strip('"')
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
