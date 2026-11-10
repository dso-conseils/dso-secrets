import json

from dso_secrets import cli


def _local_env(tmp_path):
    env = tmp_path / "s.env"
    env.write_text("app/main/db#user=u\napp/main/db#password=p\n", encoding="utf-8")
    cfg = tmp_path / "c.yml"
    cfg.write_text(f"mode: local\nlocal:\n  env_file: {env.as_posix()}\n", encoding="utf-8")
    return str(cfg)


def test_cli_init_remote_writes_answers(tmp_path, monkeypatch, capsys):
    answers = iter(["abc", "", "", "U", "P", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    target = tmp_path / "cfg" / "config.yml"
    assert cli.main(["init", "--output", str(target)]) == 0
    from dso_secrets.config import load_config

    config = load_config(str(target))
    assert config.remote.okms_id == "abc" and config.remote.read_user_env == "U"
    assert config.remote.api_url == "https://api.eu.ovhcloud.com/v2"
    assert config.remote.token_url == "https://www.ovh.com/auth/oauth2/token"
    assert config.remote.write_secret is None and config.remote.max_versions == 3
    assert cli.main(["init", "--output", str(target)]) == 1
    assert "--force" in capsys.readouterr().err


def test_cli_get_and_list(tmp_path, capsys):
    cfg = _local_env(tmp_path)
    assert cli.main(["--config", cfg, "get", "app/main/db", "--key", "user"]) == 0
    assert capsys.readouterr().out.strip() == "u"
    assert cli.main(["--config", cfg, "get", "app/main/db"]) == 0
    assert json.loads(capsys.readouterr().out) == {"user": "u", "password": "p"}
    assert cli.main(["--config", cfg, "list", "app/"]) == 0
    assert capsys.readouterr().out.strip() == "app/main/db"


def test_cli_github_env(tmp_path, monkeypatch, capsys):
    cfg = _local_env(tmp_path)
    target = tmp_path / "github_env"
    monkeypatch.setenv("GITHUB_ENV", str(target))
    assert cli.main(["--config", cfg, "get", "app/main/db", "--key", "password", "--github-env", "DB_PASSWORD"]) == 0
    assert "::add-mask::p" in capsys.readouterr().out
    assert "DB_PASSWORD<<" in target.read_text(encoding="utf-8")


def test_cli_write_refused_in_local_and_delete_needs_yes(tmp_path, capsys):
    cfg = _local_env(tmp_path)
    assert cli.main(["--config", cfg, "delete", "app/main/db"]) == 1
    assert "--yes" in capsys.readouterr().err
    assert cli.main(["--config", cfg, "delete", "app/main/db", "--yes"]) == 1
    assert "lecture seule" in capsys.readouterr().err
