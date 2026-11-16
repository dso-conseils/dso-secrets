import json
import os
import subprocess
import sys

import pytest

from dso_secrets import SecretStore, open_store
from dso_secrets.config import load_config, parse_config
from dso_secrets.errors import ConfigError, DsoSecretsError, NotFoundError
from dso_secrets.local import LocalStore, format_env, parse_env
from dso_secrets.remote import RemoteConfig, RemoteStore


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    """Simule le jeton OAuth2 et un OKMS en memoire."""

    def __init__(self):
        self.secrets = {}
        self.calls = []
        self.tokens = 0

    def post(self, url, data=None, timeout=None):
        self.tokens += 1
        return FakeResponse(200, {"access_token": f"t-{data['client_id']}", "expires_in": 3600})

    def request(self, method, url, headers=None, timeout=None, json=None, params=None):
        self.calls.append((method, url, headers["Authorization"]))
        base = "/okms/resource/ID/secret"
        tail = url.split(base, 1)[1]
        if method == "GET" and tail == "":
            return FakeResponse(200, [{"path": p} for p in self.secrets])
        path = tail.lstrip("/").replace("%2F", "/")
        if method == "POST" and tail == "":
            self.secrets[json["path"]] = json["version"]["data"]
            return FakeResponse(201, {})
        if method == "POST" and path.endswith("/version"):
            self.secrets[path[: -len("/version")]] = json["data"]
            return FakeResponse(201, {})
        if path not in self.secrets:
            return FakeResponse(404, {"message": "nope"})
        if method == "DELETE":
            del self.secrets[path]
            return FakeResponse(204, {})
        return FakeResponse(200, {"version": {"data": self.secrets[path]}})


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setenv("DSO_OKMS_USER", "reader")
    monkeypatch.setenv("DSO_OKMS_PASS", "x")
    session = FakeSession()
    session.secrets["dso/accounts/okms-write"] = {"client_id": "writer", "client_secret": "y"}
    cfg = RemoteConfig(
        okms_id="ID",
        api_url="https://api.test/v2",
        token_url="https://token.test",
        read_user_env="DSO_OKMS_USER",
        read_pass_env="DSO_OKMS_PASS",
        write_secret="dso/accounts/okms-write",
    )
    return SecretStore(RemoteStore(cfg, session)), session


def test_remote_crud_uses_write_account(remote):
    store, session = remote
    store.create("app/main/db", {"user": "u", "password": "p"})
    assert store.get("app/main/db", "user") == "u"
    store.update("app/main/db", {"user": "u2"})
    assert store.get("app/main/db") == {"user": "u2"}
    assert store.upsert("app/main/new", {"a": "1"}) == "created"
    assert store.list("app/") == ["app/main/db", "app/main/new"]
    store.delete("app/main/new")
    assert not store.exists("app/main/new")
    writes = {auth for m, _, auth in session.calls if m in ("POST", "DELETE")}
    assert writes == {"Bearer t-writer"}
    reads = {auth for m, _, auth in session.calls if m == "GET"}
    assert "Bearer t-reader" in reads


def test_remote_create_existing_and_update_missing(remote):
    store, _ = remote
    with pytest.raises(Exception):
        store.create("dso/accounts/okms-write", {"a": "b"})
    with pytest.raises(NotFoundError):
        store.update("absent", {"a": "b"})


def test_remote_missing_credentials(monkeypatch):
    monkeypatch.delenv("DSO_OKMS_USER", raising=False)
    store = SecretStore(
        RemoteStore(
            RemoteConfig("ID", "https://api.test/v2", "https://token.test", "DSO_OKMS_USER", "DSO_OKMS_PASS"),
            FakeSession(),
        )
    )
    with pytest.raises(ConfigError):
        store.list()


def test_env_roundtrip_with_newlines():
    secrets = {"a/b": {"k": "line1\nline2", "z": "v=1"}}
    assert parse_env(format_env(secrets)) == secrets


def test_isolated_crud_persists_and_preserves_other_secrets(tmp_path):
    file = tmp_path / "s.env"
    file.write_text("# existing note\na/b#k=v\nother#password=existing\n", encoding="utf-8")
    store = SecretStore(LocalStore(str(file)))
    second = SecretStore(LocalStore(str(file)))
    assert not store.read_only
    store.create("new", {"special": " slash\\n \n = ", "empty": ""})
    assert second.get("new") == {"special": " slash\\n \n = ", "empty": ""}
    assert second.get("other") == {"password": "existing"}
    assert "# existing note" in file.read_text(encoding="utf-8")
    store.update("new", {})
    assert second.get("new") == {}
    assert store.upsert("new", {"x": "y"}) == "updated"
    assert second.upsert("newer", {"x": "z"}) == "created"
    store.delete("new")
    assert not second.exists("new")
    assert second.list() == ["a/b", "newer", "other"]
    with pytest.raises(DsoSecretsError):
        store.create("other", {"password": "overwrite"})
    with pytest.raises(NotFoundError):
        store.update("missing", {})
    with pytest.raises(NotFoundError):
        store.delete("missing")
    assert second.get("other") == {"password": "existing"}


def test_isolated_concurrent_processes_do_not_lose_secrets(tmp_path):
    file = tmp_path / "s.env"
    file.write_text("existing#key=kept\n", encoding="utf-8")
    code = (
        "import sys; from dso_secrets.local import LocalStore; "
        "LocalStore(sys.argv[1]).create(sys.argv[2], {'key': 'value'})"
    )
    processes = [
        subprocess.Popen([sys.executable, "-c", code, str(file), f"secret-{i}"])
        for i in range(4)
    ]
    assert [process.wait(timeout=30) for process in processes] == [0] * len(processes)
    store = LocalStore(str(file))
    assert store.list() == ["existing", "secret-0", "secret-1", "secret-2", "secret-3"]
    assert store.get("existing") == {"key": "kept"}


def test_failed_isolated_write_keeps_previous_file(tmp_path, monkeypatch):
    file = tmp_path / "s.env"
    original = "existing#key=kept\n"
    file.write_text(original, encoding="utf-8")
    store = LocalStore(str(file))
    def fail_replace(source, target):
        raise OSError("replacement failed")
    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failed"):
        store.create("new", {"key": "value"})
    assert file.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".dso-secrets-*")) == []


def test_export_then_local(remote, tmp_path):
    store, _ = remote
    store.create("app/main/db", {"k": "v"})
    out = tmp_path / "out.env"
    assert store.export_local(str(out), "app/") == 1
    assert SecretStore(LocalStore(str(out))).get("app/main/db", "k") == "v"


def test_config_rejects_secret_keys():
    with pytest.raises(ConfigError):
        parse_config({"mode": "remote", "remote": {"okms_id": "x", "client_secret": "s"}})


def test_config_requires_mode_values():
    with pytest.raises(ConfigError):
        parse_config({"mode": "auto"})
    with pytest.raises(ConfigError):
        parse_config({"mode": "isolated", "isolated": {}})
    with pytest.raises(ConfigError):
        parse_config({"mode": "local", "local": {"env_file": "x"}})


REMOTE_YAML = (
    "mode: remote\nremote:\n  okms_id: abc\n  api_url: https://a\n  token_url: https://t\n"
    "  read_user_env: U\n  read_pass_env: P\n"
)


def test_config_remote_requires_all_mandatory_parameters():
    with pytest.raises(ConfigError, match="manquants"):
        parse_config({"mode": "remote", "remote": {"okms_id": "x"}})


def test_config_inline_yaml_has_priority_over_home_file(monkeypatch, tmp_path):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    (tmp_path / ".dso-secrets").mkdir()
    (tmp_path / ".dso-secrets" / "config.yml").write_text("mode: isolated\nisolated:\n  env_file: x\n", encoding="utf-8")
    assert load_config().mode == "isolated"
    monkeypatch.setenv("DSO_SECRETS_CONFIG_YAML", REMOTE_YAML)
    assert load_config().mode == "remote"


def test_config_missing_points_to_init(monkeypatch, tmp_path):
    monkeypatch.delenv("DSO_SECRETS_CONFIG_YAML", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    with pytest.raises(ConfigError, match="dso-secrets init"):
        load_config()


def test_config_explicit_path(tmp_path):
    other = tmp_path / "other.yml"
    other.write_text(REMOTE_YAML, encoding="utf-8")
    assert load_config(str(other)).mode == "remote"


def test_open_store_isolated(tmp_path):
    file = tmp_path / "s.env"
    file.write_text("a#k=v\n", encoding="utf-8")
    cfg = parse_config({"mode": "isolated", "isolated": {"env_file": str(file)}})
    assert open_store(cfg).get("a", "k") == "v"
