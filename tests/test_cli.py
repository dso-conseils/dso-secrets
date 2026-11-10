import json

from dso_secrets import cli


def _local_env(tmp_path):
    env = tmp_path / "s.env"
    env.write_text("app/main/db#user=u\napp/main/db#password=p\n", encoding="utf-8")
    cfg = tmp_path / "c.yml"
    cfg.write_text(f"mode: local\nlocal:\n  env_file: {env.as_posix()}\n", encoding="utf-8")
    return str(cfg)


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
