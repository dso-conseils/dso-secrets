"""Mode local hors ligne : lecture seule d'un fichier .env.

Format : une ligne `chemin#cle=valeur` (retours a la ligne ecrits \\n). Les lignes vides et `#` en debut de ligne sont ignorees.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Dict, List

from .errors import ConfigError, NotFoundError, ReadOnlyError


def _unescape(value: str) -> str:
    return value.replace("\\n", "\n")


def _escape(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\n", "\\n")


def parse_env(text: str) -> Dict[str, Dict[str, str]]:
    secrets: Dict[str, Dict[str, str]] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        left, sep, value = line.partition("=")
        path, hash_sep, key = left.partition("#")
        if not sep or not hash_sep or not path or not key:
            raise ConfigError(f"Ligne {number} invalide : attendu chemin#cle=valeur.")
        secrets.setdefault(path, {})[key] = _unescape(value)
    return secrets


def format_env(secrets: Dict[str, Dict[str, str]]) -> str:
    lines: List[str] = ["# Copie hors ligne des secrets OKMS - ne pas versionner"]
    for path in sorted(secrets):
        for key in sorted(secrets[path]):
            lines.append(f"{path}#{key}={_escape(secrets[path][key])}")
    return "\n".join(lines) + "\n"


def write_env_file(path: str, secrets: Dict[str, Dict[str, str]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(format_env(secrets), encoding="utf-8")
    if os.name == "nt":
        user = os.environ.get("USERNAME", "")
        if user:
            os.system(f'icacls "{target}" /inheritance:r /grant:r "{user}:(R,W)" >nul')
    else:
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)


class LocalStore:
    def __init__(self, env_file: str):
        file = Path(env_file)
        if not file.is_file():
            raise ConfigError(f"Fichier local introuvable : {env_file}")
        self._secrets = parse_env(file.read_text(encoding="utf-8"))

    @property
    def read_only(self) -> bool:
        return True

    def list(self, prefix: str = "") -> List[str]:
        return sorted(p for p in self._secrets if p.startswith(prefix))

    def get(self, path: str) -> Dict[str, str]:
        if path not in self._secrets:
            raise NotFoundError(f"Introuvable : {path}")
        return dict(self._secrets[path])

    def exists(self, path: str) -> bool:
        return path in self._secrets

    def _refuse(self) -> None:
        raise ReadOnlyError("Mode local : lecture seule, ecriture refusee.")

    def create(self, path: str, data: Dict[str, str]) -> None:
        self._refuse()

    def update(self, path: str, data: Dict[str, str]) -> None:
        self._refuse()

    def delete(self, path: str) -> None:
        self._refuse()
