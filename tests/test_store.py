import json

import pytest

from dso_secrets import SecretStore, open_store
from dso_secrets.config import load_config, parse_config
from dso_secrets.errors import ConfigError, NotFoundError, ReadOnlyError
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


def test_local_is_read_only(tmp_path):
    file = tmp_path / "s.env"
    file.write_text("a/b#k=v\n", encoding="utf-8")
    store = SecretStore(LocalStore(str(file)))
    assert store.get("a/b", "k") == "v"
    assert store.read_only
    with pytest.raises(ReadOnlyError):
        store.delete("a/b")


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
        parse_config({"mode": "local", "local": {}})


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
    (tmp_path / ".dso-secrets" / "config.yml").write_text("mode: local\nlocal:\n  env_file: x\n", encoding="utf-8")
    assert load_config().mode == "local"
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


def test_open_store_local(tmp_path):
    file = tmp_path / "s.env"
    file.write_text("a#k=v\n", encoding="utf-8")
    cfg = parse_config({"mode": "local", "local": {"env_file": str(file)}})
    assert open_store(cfg).get("a", "k") == "v"
