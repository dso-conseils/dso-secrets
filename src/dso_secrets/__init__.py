"""dso-secrets : CRUD de secrets OVHcloud OKMS (distant) ou lecture d'un fichier local (hors ligne)."""
from __future__ import annotations

from typing import Dict, List, Optional, Union

from .config import Config, load_config
from .errors import (
    ApiError,
    AuthError,
    ConfigError,
    DsoSecretsError,
    NotFoundError,
    ReadOnlyError,
)
from .local import LocalStore, write_env_file
from .remote import RemoteStore

__all__ = [
    "SecretStore",
    "open_store",
    "ApiError",
    "AuthError",
    "ConfigError",
    "DsoSecretsError",
    "NotFoundError",
    "ReadOnlyError",
]
__version__ = "0.1.0"


class SecretStore:
    """Facade CRUD identique en mode remote et local."""

    def __init__(self, backend: Union[RemoteStore, LocalStore]):
        self._backend = backend

    @property
    def read_only(self) -> bool:
        return self._backend.read_only

    def list(self, prefix: str = "") -> List[str]:
        return self._backend.list(prefix)

    def get(self, path: str, key: Optional[str] = None):
        data = self._backend.get(path)
        if key is None:
            return data
        if key not in data:
            raise NotFoundError(f"Cle '{key}' absente du secret '{path}'.")
        return data[key]

    def exists(self, path: str) -> bool:
        return self._backend.exists(path)

    def create(self, path: str, data: Dict[str, str]) -> None:
        if self._backend.exists(path):
            raise DsoSecretsError(f"Le secret '{path}' existe deja : utiliser update ou upsert.")
        self._backend.create(path, data)

    def update(self, path: str, data: Dict[str, str]) -> None:
        if not self._backend.exists(path):
            raise NotFoundError(f"Introuvable : {path}")
        self._backend.update(path, data)

    def upsert(self, path: str, data: Dict[str, str]) -> str:
        if self._backend.exists(path):
            self._backend.update(path, data)
            return "updated"
        self._backend.create(path, data)
        return "created"

    def delete(self, path: str) -> None:
        self._backend.delete(path)

    def export_local(self, env_file: str, prefix: str = "") -> int:
        """Ecrit une copie hors ligne des secrets (mode remote)."""
        secrets = {path: self._backend.get(path) for path in self._backend.list(prefix)}
        write_env_file(env_file, secrets)
        return len(secrets)


def open_store(config: Optional[Config] = None, config_path: Optional[str] = None) -> SecretStore:
    config = config or load_config(config_path)
    if config.mode == "remote":
        return SecretStore(RemoteStore(config.remote))
    return SecretStore(LocalStore(config.local.env_file))
