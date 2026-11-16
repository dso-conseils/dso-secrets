"""Stockage isolé dans un fichier de secrets .env."""
from __future__ import annotations

import getpass
import json
import os
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List
from urllib.parse import quote, unquote

from .errors import ConfigError, DsoSecretsError, NotFoundError


_FORMAT = "# dso-secrets-format: 2"


def parse_env(text: str) -> Dict[str, Dict[str, str]]:
    lines = text.splitlines()
    modern = _FORMAT in lines
    secrets: Dict[str, Dict[str, str]] = {}
    for number, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        left, sep, value = line.partition("=")
        path, hash_sep, key = left.partition("#")
        if not sep or not hash_sep or not path or not key:
            raise ConfigError(f"Ligne {number} invalide : attendu chemin#cle=valeur.")
        if modern:
            if key != "@secret":
                raise ConfigError(f"Ligne {number} invalide dans le format isolé.")
            path = unquote(path)
            try:
                data = json.loads(value)
            except json.JSONDecodeError as error:
                raise ConfigError(f"JSON invalide ligne {number}.") from error
            if not isinstance(data, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in data.items()
            ):
                raise ConfigError(f"Secret invalide ligne {number} : valeurs texte attendues.")
            if path in secrets:
                raise ConfigError(f"Chemin de secret répété ligne {number}.")
            secrets[path] = data
        else:
            secrets.setdefault(path.strip(), {})[key.strip()] = value.strip().replace("\\n", "\n")
    return secrets


def format_env(secrets: Dict[str, Dict[str, str]]) -> str:
    lines = [_FORMAT, "# Secrets isolés - ne pas versionner"]
    for path in sorted(secrets):
        value = json.dumps(secrets[path], ensure_ascii=True, separators=(",", ":"))
        lines.append(f"{quote(path, safe='/')}#@secret={value}")
    return "\n".join(lines) + "\n"


def _protect_file(path: Path) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{getpass.getuser()}:(F)"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise ConfigError("Impossible de protéger le fichier de secrets avec une ACL privée.") from error
    else:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def write_env_file(path: str, secrets: Dict[str, Dict[str, str]], comments: List[str] | None = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".dso-secrets-", dir=str(target.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            _protect_file(temporary)
            content = format_env(secrets)
            if comments:
                content = content.replace(_FORMAT + "\n", _FORMAT + "\n" + "\n".join(comments) + "\n", 1)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def _file_lock(path: Path):
    lock_path = path.with_name(path.name + ".lock")
    if not path.parent.is_dir():
        raise ConfigError(f"Répertoire du fichier isolé introuvable : {path.parent}")
    with open(lock_path, "a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0, os.SEEK_END)
            if not lock.tell():
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class LocalStore:
    def __init__(self, env_file: str):
        self._file = Path(env_file)
        self._read()

    def _read(self) -> Dict[str, Dict[str, str]]:
        with _file_lock(self._file):
            if not self._file.is_file():
                raise ConfigError(f"Fichier isolé introuvable : {self._file}")
            return parse_env(self._file.read_text(encoding="utf-8"))

    @property
    def read_only(self) -> bool:
        return False

    def list(self, prefix: str = "") -> List[str]:
        return sorted(p for p in self._read() if p.startswith(prefix))

    def get(self, path: str) -> Dict[str, str]:
        secrets = self._read()
        if path not in secrets:
            raise NotFoundError(f"Introuvable : {path}")
        return dict(secrets[path])

    def exists(self, path: str) -> bool:
        return path in self._read()

    def _write(self, path: str, data: Dict[str, str], operation: str) -> str:
        if not path or not isinstance(path, str):
            raise ConfigError("Le chemin du secret doit être un texte non vide.")
        if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
            raise ConfigError("Le secret doit contenir uniquement des clés et valeurs texte.")
        with _file_lock(self._file):
            text = self._file.read_text(encoding="utf-8")
            secrets = parse_env(text)
            comments = [
                line for line in text.splitlines()
                if line.lstrip().startswith("#")
                and line != _FORMAT
                and line != "# Secrets isolés - ne pas versionner"
            ]
            exists = path in secrets
            if operation == "create" and exists:
                raise DsoSecretsError(f"Le secret '{path}' existe deja : utiliser update ou upsert.")
            if operation in ("update", "delete") and not exists:
                raise NotFoundError(f"Introuvable : {path}")
            if operation == "delete":
                del secrets[path]
            else:
                secrets[path] = dict(data)
            write_env_file(str(self._file), secrets, comments)
            return "updated" if exists else "created"

    def create(self, path: str, data: Dict[str, str]) -> None:
        self._write(path, data, "create")

    def update(self, path: str, data: Dict[str, str]) -> None:
        self._write(path, data, "update")

    def upsert(self, path: str, data: Dict[str, str]) -> str:
        return self._write(path, data, "upsert")

    def delete(self, path: str) -> None:
        self._write(path, {}, "delete")
