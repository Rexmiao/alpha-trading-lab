"""Fixed-origin, single-attempt moomoo paper HTTP and an explicit local factory.

No login/register/refresh, CLI, keyring migration, default credential search,
reporter, live route, redirect or request retry. Bearer is injected; API-key PEM
is read only from an explicit private configuration reference. Signing follows
https://open.moomoo.com/zh-cn/api/overview/getting-started exactly.

Upstream paper-only OAuth/API-key restriction has NOT been verified. The local
route guard does not imply that the server credential itself lacks live rights.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json as json_module
import os
from pathlib import Path
import re
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .rest_paper import API_BASE, PREFIX, RestPaperAdapter, SimOnlyRestTransport, _identifier
from .veighna_bridge import BridgeError


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PRIVATE_CONFIG_BYTES = 64 * 1024
SERVER_PAPER_ONLY_SCOPE_VERIFIED = False


class RestTransportError(BridgeError):
    def __init__(self, message, *, code="REST_UNAVAILABLE", http_status=None):
        super().__init__(message)
        self.code, self.http_status = code, http_status


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a bearer token or signature to a redirect destination.
        return None


def _text(value, name, max_length=4096):
    if not isinstance(value, str) or not 1 <= len(value) <= max_length or any(not 33 <= ord(c) <= 126 for c in value):
        raise RestTransportError(f"Invalid {name} configuration.", code="NOT_CONFIGURED")
    return value


def canonical_request(timestamp_ms, method, path, query_string, body_bytes):
    """Exactly five LF-delimited fields; hash the exact transmitted body bytes."""
    body_part = hashlib.sha256(body_bytes).hexdigest() if body_bytes else ""
    return "\n".join((str(timestamp_ms), method, path, query_string, body_part)).encode("utf-8")


class BearerAuth:
    def __init__(self, token_provider):
        if not callable(token_provider):
            raise RestTransportError("Supply an explicitly controlled Bearer provider.", code="NOT_CONFIGURED")
        self._token_provider = token_provider

    def headers(self, method, path, query, body):
        try:
            token = _text(self._token_provider(), "Bearer token")
        except Exception:
            raise RestTransportError("The controlled Bearer token is unavailable.", code="NOT_CONFIGURED") from None
        return {"Authorization": "Bearer " + token}


class ApiKeyAuth:
    def __init__(self, app_key, private_key, *, algorithm, clock=None, nonce_provider=None):
        self._app_key = _text(app_key, "API key identifier", 512)
        if algorithm not in {"Ed25519", "RSA-SHA256"}:
            raise RestTransportError("Only the documented Ed25519 or RSA-SHA256 signatures are supported.", code="NOT_CONFIGURED")
        self._key, self.algorithm = private_key, algorithm
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._nonce = nonce_provider or (lambda: secrets.token_hex(16))

    def headers(self, method, path, query, body):
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
            now = self._clock()
            if not isinstance(now, datetime) or now.tzinfo is None:
                raise ValueError()
            timestamp = str(int(now.timestamp() * 1000))
            nonce = self._nonce()
            if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", nonce):
                raise ValueError()
            message = canonical_request(timestamp, method, path, query, body)
            if self.algorithm == "Ed25519" and isinstance(self._key, ed25519.Ed25519PrivateKey):
                signature = self._key.sign(message)
            elif self.algorithm == "RSA-SHA256" and isinstance(self._key, rsa.RSAPrivateKey) and self._key.key_size >= 2048:
                signature = self._key.sign(message, padding.PKCS1v15(), hashes.SHA256())
            else:
                raise ValueError()
        except ImportError:
            raise RestTransportError("API-key signing requires the isolated cryptography dependency.", code="NOT_CONFIGURED") from None
        except Exception:
            raise RestTransportError("The configured API-key signer is unavailable or invalid.", code="NOT_CONFIGURED") from None
        return {"X-Api-Key": self._app_key, "X-Timestamp": timestamp, "X-Nonce": nonce,
                "Authorization": base64.b64encode(signature).decode("ascii")}


class RestHttpClient:
    """Concrete urllib request-once callable, bound to one string paper account."""

    def __init__(self, auth, *, account_id=None, opener=None):
        if not isinstance(auth, (BearerAuth, ApiKeyAuth)):
            raise RestTransportError("An explicitly configured authentication provider is required.", code="NOT_CONFIGURED")
        self._auth = auth
        self._guard = SimOnlyRestTransport(account_id=account_id)
        self._open = opener or build_opener(ProxyHandler({}), _NoRedirect()).open

    def __call__(self, method, url, *, params=None, json=None, timeout=15.0):
        try:
            parts = urlsplit(url)
            valid = (parts.scheme == "https" and parts.netloc == "webapi.moomoo.com"
                     and parts.username is None and parts.password is None and not parts.query and not parts.fragment)
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise RestTransportError("Only the fixed moomoo REST origin is permitted.", code="INVALID_DESTINATION")
        params, body = self._guard._validated_args(method, parts.path, params, json)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
            raise RestTransportError("Use a bounded REST timeout.")
        query = urlencode(params)
        try:
            payload = json_module.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") if body is not None else b""
        except (TypeError, ValueError):
            raise RestTransportError("Invalid paper request body.") from None
        headers = {"Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": "AlphaLab-REST-Paper/1"}
        headers.update(self._auth.headers(method, parts.path, query, payload))
        if body is not None:
            headers["Content-Type"] = "application/json"
        target = API_BASE + parts.path + ("?" + query if query else "")
        request = Request(target, data=payload if body is not None else None, headers=headers, method=method)
        deadline = time.monotonic() + timeout
        try:
            # No loop. A failed POST is handed back as an unknown outcome.
            with self._open(request, timeout=timeout) as response:
                if hasattr(response, "geturl") and response.geturl() != target:
                    raise RestTransportError("REST redirects are refused.", code="REDIRECT_REFUSED")
                status = getattr(response, "status", 200)
                if status != 200:
                    raise HTTPError(target, status, "", {}, None)
                length = getattr(response, "headers", {}).get("Content-Length")
                if length is not None:
                    try:
                        size = int(length)
                    except (ValueError, TypeError):
                        raise RestTransportError("Invalid REST response length.") from None
                    if not 0 <= size <= MAX_RESPONSE_BYTES:
                        raise RestTransportError("REST response exceeds the size limit.", code="SIZE_LIMIT")
                contents = bytearray()
                read = getattr(response, "read1", response.read)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RestTransportError("REST response timed out; no retry was attempted.", code="TIMEOUT")
                    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                    if sock is not None:
                        sock.settimeout(remaining)
                    chunk = read(min(65536, MAX_RESPONSE_BYTES + 1 - len(contents)))
                    if not isinstance(chunk, bytes):
                        raise RestTransportError("Invalid REST byte response.")
                    if not chunk:
                        break
                    contents.extend(chunk)
                    if len(contents) > MAX_RESPONSE_BYTES:
                        raise RestTransportError("REST response exceeds the size limit.", code="SIZE_LIMIT")
        except RestTransportError:
            raise
        except HTTPError as error:
            status = error.code
            error.close()
            code = "AUTH_REQUIRED" if status in (401, 403, 439) else "REDIRECT_REFUSED" if 300 <= status < 400 else "HTTP_ERROR"
            raise RestTransportError("REST request was not confirmed; no authentication or request retry was attempted.", code=code, http_status=status) from None
        except (TimeoutError, URLError, OSError):
            raise RestTransportError("REST request failed or timed out; its outcome must be reconciled.", code="OUTCOME_UNKNOWN") from None
        try:
            result = json_module.loads(bytes(contents).decode("utf-8"))
        except (ValueError, UnicodeError):
            raise RestTransportError("REST response is not valid JSON.", code="INVALID_RESPONSE") from None
        if not isinstance(result, dict) or type(result.get("ret_code")) is not int or result["ret_code"] != 0:
            raise RestTransportError("REST business response was not successful; reconcile before any further write.", code="BUSINESS_ERROR")
        return result


def _private_bytes(path, *, limit=MAX_PRIVATE_CONFIG_BYTES):
    if not isinstance(path, (str, Path)) or not Path(path).is_absolute():
        raise RestTransportError("Use an explicit absolute private configuration path.", code="NOT_CONFIGURED")
    path = Path(path).resolve()
    if any("dropbox" in part.casefold() for part in path.parts):
        raise RestTransportError("REST credentials must remain outside the synced workspace.", code="NOT_CONFIGURED")
    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError:
        raise RestTransportError("The explicit private REST configuration is unavailable.", code="NOT_CONFIGURED") from None
    if not data or len(data) > limit:
        raise RestTransportError("The private REST configuration has an invalid size.", code="NOT_CONFIGURED")
    return data


def build_rest_paper_adapter(*, backend, config_path=None, account_id=None, quote_provider=None,
                             persist_state=None, state=None, opener=None, token_provider=None,
                             clock=None, key_password_provider=None):
    """Explicit setup only: no credentials or network before backend/quote checks.

    Private JSON schema: schema_version=1, backend=REST_sim_trade, account_id=str,
    authorization_confirmed=true, auth={type:api_key,app_key,algorithm,
    private_key_file:absolute_non_synced_path} or auth={type:bearer} with an
    explicitly injected token_provider. No inline PEM, token or login is used.
    This factory only discovers the selected paper account; it never submits.
    """
    unavailable = RestPaperAdapter()
    if backend != "REST_sim_trade":
        unavailable.reason = "REST paper setup requires an explicit REST_sim_trade backend selection."
        return unavailable
    if not callable(quote_provider):
        unavailable.reason = "A configured fresh-quote provider is required; completed bar closes are not quotes."
        return unavailable
    config_path = config_path or os.environ.get("ALPHA_REST_PAPER_CONFIG")
    if not config_path:
        unavailable.reason = "An explicit private REST paper configuration is required."
        return unavailable
    try:
        config = json_module.loads(_private_bytes(config_path).decode("utf-8"))
        if (not isinstance(config, dict) or type(config.get("schema_version")) is not int
                or config["schema_version"] != 1 or config.get("backend") != "REST_sim_trade"
                or config.get("authorization_confirmed") is not True):
            raise RestTransportError("The private paper configuration has not been explicitly approved.", code="NOT_CONFIGURED")
        selected = _identifier(config.get("account_id"), "account_id")
        if account_id is not None and account_id != selected:
            raise BridgeError("The explicit REST paper account differs from its private configuration.")
        auth_config = config.get("auth")
        if not isinstance(auth_config, dict):
            raise RestTransportError("REST authentication is not configured.", code="NOT_CONFIGURED")
        if auth_config.get("type") == "bearer":
            auth = BearerAuth(token_provider)
        elif auth_config.get("type") == "api_key":
            try:
                from cryptography.hazmat.primitives.serialization import load_pem_private_key
            except ImportError:
                raise RestTransportError("API-key signing requires the isolated cryptography dependency.", code="NOT_CONFIGURED") from None
            password = key_password_provider() if callable(key_password_provider) else None
            if password is not None and not isinstance(password, bytes):
                raise RestTransportError("Provide a controlled key-password callback returning bytes.", code="NOT_CONFIGURED")
            try:
                key = load_pem_private_key(_private_bytes(auth_config.get("private_key_file")), password=password)
            except RestTransportError:
                raise
            except Exception:
                raise RestTransportError("The explicitly selected private key could not be loaded.", code="NOT_CONFIGURED") from None
            auth = ApiKeyAuth(auth_config.get("app_key"), key, algorithm=auth_config.get("algorithm"), clock=clock)
        else:
            raise RestTransportError("Select a documented REST authentication method.", code="NOT_CONFIGURED")
        http = RestHttpClient(auth, account_id=selected, opener=opener)
        transport = SimOnlyRestTransport(http, account_id=selected, auth_confirmed=True)
        matches = [row for row in transport.accounts() if row.get("account_id") == selected]
        if len(matches) != 1:
            raise RestTransportError("The selected REST paper account was not returned uniquely.", code="NOT_CONFIGURED")
        adapter = RestPaperAdapter(transport, account_id=selected, account_metadata=matches[0], auth_confirmed=True,
            persist_state=persist_state, state=state, max_order_notional=config.get("max_order_notional", 1000))
        adapter.quote_provider = quote_provider
        adapter.auth_policy = {"operator_reviewed": True, "upstream_paper_only_scope_verified": False,
                               "local_routes": "US sim-trade only"}
        return adapter
    except RestTransportError as error:
        unavailable.reason = str(error)
        return unavailable
    except BridgeError:
        unavailable.reason = "The explicit REST paper account or authenticated discovery could not be verified."
        return unavailable
    except (ValueError, TypeError, UnicodeError):
        raise BridgeError("The explicit private REST paper configuration or account metadata is invalid.") from None
