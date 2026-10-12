"""Auth plugins for multistac: turn a provider profile into request headers.

Secrets are read lazily from an INI file (path from $STAC_CREDENTIALS, default
/home/pmontesa/code/credentials.ini) and are never logged, printed or saved.
Tokens live in memory only.
"""

from __future__ import annotations

import configparser
import os
import threading
import time
from typing import Any, Dict, Optional

import requests

DEFAULT_CREDENTIALS = "/home/pmontesa/code/credentials.ini"


class AuthError(RuntimeError):
    pass


def credentials_path() -> str:
    return os.environ.get("STAC_CREDENTIALS", DEFAULT_CREDENTIALS)


def has_credentials(section: str) -> bool:
    """True if the section exists in the credentials file (values not read)."""
    config = configparser.ConfigParser()
    config.read(credentials_path())
    return config.has_section(section)


def _read_section(section: str) -> Dict[str, str]:
    config = configparser.ConfigParser()
    if not config.read(credentials_path()):
        raise AuthError(f"Credentials file not found: {credentials_path()}")
    if not config.has_section(section):
        raise AuthError(f"Section [{section}] missing from {credentials_path()}")
    return dict(config.items(section))


def _short(response: requests.Response) -> str:
    return f"HTTP {response.status_code}: {response.text[:300]}"


class NoAuth:
    def __init__(self, profile: Dict[str, Any]):
        self.profile = profile

    def headers(self) -> Dict[str, str]:
        return {}

    def invalidate(self) -> None:
        pass

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class OAuth2ClientCredentials(NoAuth):
    """Generic OAuth2 client-credentials flow with refresh before expiry."""

    refresh_margin_s = 300

    def __init__(self, profile: Dict[str, Any]):
        super().__init__(profile)
        self.cfg = profile["auth"]
        self._token: Optional[str] = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def _token_payload(self, creds: Dict[str, str]) -> Dict[str, str]:
        payload = {
            "grant_type": "client_credentials",
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
        }
        for key in ("audience", "scope"):
            if self.cfg.get(key):
                payload[key] = self.cfg[key]
        return payload

    def _fetch_token(self) -> None:
        token_url = self.cfg.get("token_url")
        if not token_url or token_url == "TBD":
            raise AuthError(f"No token_url configured for {self.profile['name']}")
        creds = _read_section(self.cfg["credentials_section"])
        response = requests.post(
            token_url, json=self._token_payload(creds), timeout=60
        )
        if response.status_code != 200:
            raise AuthError(f"Token request failed ({_short(response)})")
        data = response.json()
        self._token = data["access_token"]
        self._expires_at = time.time() + float(data.get("expires_in", 3600))

    def token(self) -> str:
        with self._lock:
            if self._token is None or time.time() >= self._expires_at - self.refresh_margin_s:
                self._fetch_token()
            return self._token

    def invalidate(self) -> None:
        with self._lock:
            self._token = None

    def headers(self) -> Dict[str, str]:
        name = self.cfg.get("token_header", "Authorization")
        return {name: f"Bearer {self.token()}"}


class SatellogicAuth(OAuth2ClientCredentials):
    """Satellogic: OAuth2 token in an `authorizationToken` header + contract ID.

    Optional INI key `contract_id` pins a contract; otherwise the first contract
    returned by the API is used.
    """

    def __init__(self, profile: Dict[str, Any]):
        super().__init__(profile)
        self._contract_id: Optional[str] = None

    def contract_id(self) -> str:
        if self._contract_id is None:
            pinned = _read_section(self.cfg["credentials_section"]).get("contract_id")
            if pinned:
                self._contract_id = pinned
            else:
                response = requests.get(
                    self.cfg["contracts_url"],
                    headers=OAuth2ClientCredentials.headers(self),
                    timeout=60,
                )
                if response.status_code != 200:
                    raise AuthError(f"Contract lookup failed ({_short(response)})")
                contracts = response.json()
                if not contracts:
                    raise AuthError("No Satellogic contracts found for this account")
                self._contract_id = contracts[0]["contract_id"]
        return self._contract_id

    def headers(self) -> Dict[str, str]:
        headers = super().headers()
        headers["X-Satellogic-Contract-Id"] = self.contract_id()
        return headers


class BearerEnv(NoAuth):
    """Bearer token taken from an environment variable (e.g. EARTHDATA_TOKEN)."""

    def headers(self) -> Dict[str, str]:
        var = self.profile["auth"]["env_var"]
        token = os.environ.get(var)
        if not token:
            raise AuthError(f"Environment variable {var} is not set")
        return {"Authorization": f"Bearer {token}"}


class ApiKeyHeader(NoAuth):
    """Static API key from the INI file, sent in a named header."""

    def headers(self) -> Dict[str, str]:
        cfg = self.profile["auth"]
        key = _read_section(cfg["credentials_section"])[cfg.get("key_name", "api_key")]
        prefix = cfg.get("prefix", "")
        return {cfg.get("header", "Authorization"): f"{prefix}{key}"}


AUTH_TYPES = {
    "none": NoAuth,
    "oauth2_client_credentials": OAuth2ClientCredentials,
    "satellogic": SatellogicAuth,
    "bearer_env": BearerEnv,
    "api_key_header": ApiKeyHeader,
}


def make_auth(profile: Dict[str, Any]) -> NoAuth:
    auth_type = profile.get("auth", {}).get("type", "none")
    if auth_type not in AUTH_TYPES:
        raise AuthError(f"Unknown auth type '{auth_type}' for {profile['name']}")
    return AUTH_TYPES[auth_type](profile)
