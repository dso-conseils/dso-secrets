"""Acces distant a OVHcloud OKMS (Secret Manager) via compte de service OAuth2."""
from __future__ import annotations

import os
import time
import urllib.parse
from typing import Dict, List, Optional

import requests

from .config import RemoteConfig
from .errors import ApiError, AuthError, ConfigError, NotFoundError

TOKEN_MARGIN_SECONDS = 60
TIMEOUT = 30


class _TokenSource:
    def __init__(self, token_url: str, client_id: str, client_secret: str, session: requests.Session):
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session
        self._token = ""
        self._expires_at = 0.0

    def get(self) -> str:
        if self._token and time.time() < self._expires_at - TOKEN_MARGIN_SECONDS:
            return self._token
        response = self._session.post(
            self._token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": "all",
            },
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            raise AuthError(f"Obtention du jeton refusee (HTTP {response.status_code}).")
        payload = response.json()
        self._token = payload["access_token"]
        self._expires_at = time.time() + int(payload.get("expires_in", 3600))
        return self._token


class RemoteStore:
    def __init__(self, config: RemoteConfig, session: Optional[requests.Session] = None):
        self._config = config
        self._session = session or requests.Session()
        self._read: Optional[_TokenSource] = None
        self._write: Optional[_TokenSource] = None

    @property
    def read_only(self) -> bool:
        return False

    def _read_source(self) -> _TokenSource:
        if self._read is None:
            user = os.environ.get(self._config.read_user_env)
            password = os.environ.get(self._config.read_pass_env)
            if not user or not password:
                raise ConfigError(
                    f"Variables {self._config.read_user_env} / {self._config.read_pass_env} absentes."
                )
            self._read = _TokenSource(self._config.token_url, user, password, self._session)
        return self._read

    def _write_source(self) -> _TokenSource:
        if self._write is None:
            if not self._config.write_secret:
                raise ConfigError("remote.write_secret n'est pas defini : ecriture impossible.")
            creds = self.get(self._config.write_secret)
            if "client_id" not in creds or "client_secret" not in creds:
                raise ConfigError(
                    f"Le secret '{self._config.write_secret}' doit contenir client_id et client_secret."
                )
            self._write = _TokenSource(
                self._config.token_url, creds["client_id"], creds["client_secret"], self._session
            )
        return self._write

    def _url(self, suffix: str = "") -> str:
        okms = urllib.parse.quote(self._config.okms_id, safe="")
        return f"{self._config.api_url.rstrip('/')}/okms/resource/{okms}/secret{suffix}"

    def _secret_url(self, path: str, suffix: str = "") -> str:
        return self._url("/" + urllib.parse.quote(path, safe="") + suffix)

    def _request(self, source: _TokenSource, method: str, url: str, **kwargs) -> requests.Response:
        headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {source.get()}"}
        response = self._session.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
        if response.status_code == 404:
            raise NotFoundError(f"Introuvable : {url.rsplit('/secret', 1)[-1] or '/'}")
        if response.status_code >= 400:
            try:
                message = response.json().get("message", "")
            except ValueError:
                message = response.text[:200]
            raise ApiError(response.status_code, message)
        return response

    def list(self, prefix: str = "") -> List[str]:
        paths: List[str] = []
        cursor: Optional[str] = None
        while True:
            headers = {"X-Pagination-Size": "100"}
            if cursor:
                headers["X-Pagination-Cursor"] = cursor
            response = self._request(self._read_source(), "GET", self._url(), headers=headers)
            items = response.json()
            paths.extend(item["path"] for item in items)
            cursor = response.headers.get("X-Pagination-Cursor-Next")
            if not cursor:
                break
        return sorted(p for p in paths if p.startswith(prefix))

    def get(self, path: str) -> Dict[str, str]:
        response = self._request(
            self._read_source(), "GET", self._secret_url(path), params={"includeData": "true"}
        )
        return response.json()["version"]["data"]

    def exists(self, path: str) -> bool:
        try:
            self._request(self._read_source(), "GET", self._secret_url(path))
            return True
        except NotFoundError:
            return False

    def create(self, path: str, data: Dict[str, str]) -> None:
        body = {
            "path": path,
            "version": {"data": data},
            "metadata": {"maxVersions": self._config.max_versions},
        }
        self._request(self._write_source(), "POST", self._url(), json=body)

    def update(self, path: str, data: Dict[str, str]) -> None:
        self._request(self._write_source(), "POST", self._secret_url(path, "/version"), json={"data": data})

    def delete(self, path: str) -> None:
        self._request(self._write_source(), "DELETE", self._secret_url(path))
