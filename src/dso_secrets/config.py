"""Chargement de la configuration YAML (sans secret)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

from .errors import ConfigError

ENV_YAML = "DSO_SECRETS_CONFIG_YAML"
ENV_FILE = "DSO_SECRETS_CONFIG"
DEFAULT_FILENAME = "dso-secrets.yml"

FORBIDDEN_KEYS = {"client_secret", "client_id", "password", "secret", "token", "pass", "user"}
DEFAULT_API_URL = "https://eu.api.ovh.com/v2"
DEFAULT_TOKEN_URL = "https://www.ovh.com/auth/oauth2/token"


@dataclass(frozen=True)
class RemoteConfig:
    okms_id: str
    api_url: str = DEFAULT_API_URL
    token_url: str = DEFAULT_TOKEN_URL
    read_user_env: str = "DSO_OKMS_USER"
    read_pass_env: str = "DSO_OKMS_PASS"
    write_secret: Optional[str] = None
    max_versions: int = 3


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
        if not section.get("okms_id"):
            raise ConfigError("remote.okms_id est obligatoire en mode remote.")
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


def _candidates(path: Optional[str]) -> list[Path]:
    if path:
        return [Path(path)]
    env_path = os.environ.get(ENV_FILE)
    found = [Path(env_path)] if env_path else []
    found += [Path.cwd() / DEFAULT_FILENAME, Path.home() / f".{DEFAULT_FILENAME}"]
    return found


def load_config(path: Optional[str] = None) -> Config:
    """Ordre : DSO_SECRETS_CONFIG_YAML (contenu), chemin explicite ou DSO_SECRETS_CONFIG, ./dso-secrets.yml, ~/.dso-secrets.yml."""
    inline = os.environ.get(ENV_YAML)
    if inline and not path:
        return parse_config(yaml.safe_load(inline))
    for candidate in _candidates(path):
        if candidate.is_file():
            return parse_config(yaml.safe_load(candidate.read_text(encoding="utf-8")))
    raise ConfigError(
        f"Aucune configuration trouvee ({ENV_YAML}, {ENV_FILE}, ./{DEFAULT_FILENAME}, ~/.{DEFAULT_FILENAME})."
    )
