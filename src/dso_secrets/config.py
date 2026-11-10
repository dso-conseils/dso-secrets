"""Chargement de la configuration YAML (sans secret)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

from .errors import ConfigError

ENV_YAML = "DSO_SECRETS_CONFIG_YAML"
CONFIG_DIR = ".dso-secrets"
CONFIG_FILE = "config.yml"

FORBIDDEN_KEYS = {"client_secret", "client_id", "password", "secret", "token", "pass", "user"}


@dataclass(frozen=True)
class RemoteConfig:
    okms_id: str
    api_url: str
    token_url: str
    read_user_env: str
    read_pass_env: str
    write_secret: Optional[str] = None
    max_versions: Optional[int] = None


@dataclass(frozen=True)
class LocalConfig:
    env_file: str


@dataclass(frozen=True)
class Config:
    mode: str
    remote: Optional[RemoteConfig] = None
    local: Optional[LocalConfig] = None


def _reject_secrets(node: Any, trail: str = "") -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ConfigError(
                    f"La cle '{trail}{key}' ressemble a un secret : le YAML ne doit contenir que des noms de variables d'environnement."
                )
            _reject_secrets(value, f"{trail}{key}.")


def parse_config(data: Mapping[str, Any]) -> Config:
    if not isinstance(data, Mapping):
        raise ConfigError("Le YAML doit etre un objet (mode: remote|local).")
    _reject_secrets(data)
    mode = data.get("mode")
    if mode == "remote":
        section = data.get("remote") or {}
        required = ("okms_id", "api_url", "token_url", "read_user_env", "read_pass_env")
        missing = [key for key in required if not section.get(key)]
        if missing:
            raise ConfigError(f"Parametres remote obligatoires manquants : {missing}")
        known = {f for f in RemoteConfig.__dataclass_fields__}
        unknown = set(section) - known
        if unknown:
            raise ConfigError(f"Parametres remote inconnus : {sorted(unknown)}")
        return Config(mode="remote", remote=RemoteConfig(**section))
    if mode == "local":
        section = data.get("local") or {}
        if not section.get("env_file"):
            raise ConfigError("local.env_file est obligatoire en mode local.")
        unknown = set(section) - {"env_file"}
        if unknown:
            raise ConfigError(f"Parametres local inconnus : {sorted(unknown)}")
        return Config(mode="local", local=LocalConfig(env_file=str(section["env_file"])))
    raise ConfigError("mode doit valoir 'remote' ou 'local'.")


def config_path() -> Path:
    """Emplacement unique du YAML : ~/.dso-secrets/config.yml (Windows, Linux, container)."""
    return Path.home() / CONFIG_DIR / CONFIG_FILE


def load_config(path: Optional[str] = None) -> Config:
    """Ordre : chemin explicite (--config), DSO_SECRETS_CONFIG_YAML (contenu), ~/.dso-secrets/config.yml."""
    if path:
        target = Path(path)
    else:
        inline = os.environ.get(ENV_YAML)
        if inline:
            return parse_config(yaml.safe_load(inline))
        target = config_path()
    if not target.is_file():
        raise ConfigError(
            f"Configuration introuvable : {target}. Creer le fichier avec `dso-secrets init` "
            f"ou fournir son contenu dans {ENV_YAML}."
        )
    return parse_config(yaml.safe_load(target.read_text(encoding="utf-8")))


def write_config(data: Mapping[str, Any], target: Optional[Path] = None, force: bool = False) -> Path:
    parse_config(data)
    target = target or config_path()
    if target.exists() and not force:
        raise ConfigError(f"{target} existe deja : utiliser --force pour le remplacer.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True), encoding="utf-8")
    return target
