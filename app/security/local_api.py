"""Local API authentication and browser-origin hardening.

RedSight services bind to loopback by default, but loopback alone is not an
authorization boundary: a browser page or another local process can still
reach those ports.  A random per-user token protects HTTP and WebSocket routes
and is shared by the desktop, API, and action gateway through a private file.
"""

from __future__ import annotations

import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Iterable

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

TOKEN_ENV = "REDSIGHT_LOCAL_API_TOKEN"
DEFAULT_HEADER = "X-RedSight-Token"


def _private_state_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return root / "RedSight" / "private"


def token_path() -> Path:
    override = str(os.environ.get("REDSIGHT_LOCAL_API_TOKEN_FILE") or "").strip()
    return Path(override).expanduser() if override else _private_state_dir() / "api-token"


def get_or_create_api_token() -> str:
    """Return the configured token, creating a mode-0600 user token if needed."""
    configured = str(os.environ.get(TOKEN_ENV) or "").strip()
    if configured:
        return configured

    path = token_path()
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            os.environ[TOKEN_ENV] = existing
            return existing
    except (FileNotFoundError, OSError):
        pass

    value = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value + "\n")
    except FileExistsError:
        # The API and action gateway may start together.  The process that won
        # O_EXCL can still be flushing its token when the other process sees
        # the file, so wait briefly instead of accepting an empty credential.
        value = ""
        for _ in range(20):
            try:
                value = path.read_text(encoding="utf-8").strip()
            except OSError:
                value = ""
            if value:
                break
            time.sleep(0.05)
        if not value:
            raise RuntimeError("The local API token file exists but is empty")
    if os.name != "nt":
        try:
            path.chmod(0o600)
        except OSError:
            pass
    os.environ[TOKEN_ENV] = value
    return value


def auth_headers() -> dict[str, str]:
    """Headers for trusted local clients."""
    header = str(os.environ.get("RED_SIGHT_SECURITY__API_TOKEN_HEADER") or DEFAULT_HEADER).strip()
    return {header: get_or_create_api_token()}


class LocalApiSecurityMiddleware:
    """Authenticate HTTP/WebSocket traffic and reject oversized bodies."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        token: str,
        header_name: str = DEFAULT_HEADER,
        public_paths: Iterable[str] = (),
        max_request_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.app = app
        self.token = token.encode("utf-8")
        self.header_name = header_name.lower().encode("latin-1")
        self.public_paths = frozenset(public_paths)
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")
        if scope_type not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "").upper()
        public_request = scope_type == "http" and (
            path in self.public_paths or method == "OPTIONS"
        )

        supplied = b""
        for key, value in scope.get("headers", ()):
            if key.lower() == self.header_name:
                supplied = value
                break
        if scope_type == "websocket" and not supplied:
            query = bytes(scope.get("query_string") or b"").decode("latin-1")
            for pair in query.split("&"):
                key, _, value = pair.partition("=")
                if key == "token":
                    from urllib.parse import unquote_plus

                    supplied = unquote_plus(value).encode("utf-8")
                    break

        if not public_request and (
            not supplied or not hmac.compare_digest(supplied, self.token)
        ):
            if scope_type == "websocket":
                await send({"type": "websocket.close", "code": 4401, "reason": "Authentication required"})
            else:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"cache-control", b"no-store"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": b'{"detail":"Authentication required"}'})
            return

        replay_receive = receive
        if scope_type == "http":
            content_length = next(
                (value for key, value in scope.get("headers", ()) if key.lower() == b"content-length"),
                b"0",
            )
            try:
                too_large = int(content_length) > self.max_request_bytes
            except ValueError:
                too_large = True
            if too_large:
                await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"detail":"Request body too large"}'})
                return

            messages: list[dict] = []
            received_bytes = 0
            while True:
                message = await receive()
                messages.append(message)
                if message.get("type") != "http.request":
                    break
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_request_bytes:
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 413,
                            "headers": [(b"content-type", b"application/json")],
                        }
                    )
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b'{"detail":"Request body too large"}',
                        }
                    )
                    return
                if not message.get("more_body", False):
                    break

            async def replay() -> dict:
                if messages:
                    return messages.pop(0)
                return {"type": "http.request", "body": b"", "more_body": False}

            replay_receive = replay

        async def secure_send(message: dict) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", ()))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"cache-control", b"no-store"),
                        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, replay_receive, secure_send)


def configure_local_api_security(
    app: FastAPI,
    *,
    public_paths: Iterable[str],
    auth_enabled: bool = True,
    header_name: str = DEFAULT_HEADER,
    max_request_bytes: int = 2 * 1024 * 1024,
    allowed_origins: Iterable[str] = (),
) -> None:
    """Apply one consistent security policy to a RedSight FastAPI service."""
    if auth_enabled:
        app.add_middleware(
            LocalApiSecurityMiddleware,
            token=get_or_create_api_token(),
            header_name=header_name,
            public_paths=tuple(public_paths),
            max_request_bytes=max_request_bytes,
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_origin_regex=r"^https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d{1,5})?$",
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[header_name, "Content-Type", "Accept"],
        max_age=600,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"],
    )
