"""Request guards for the loopback API.

Host allowlisting stops a browser DNS rebind: after the name points at
127.0.0.1 the browser still sends the attacker's host, and this process
refuses it. Body limits stop upload and message work from starting on an
unsized payload.
"""

import json

from . import config

_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}


def host_is_loopback(value) -> bool:
    """True when a Host header is a loopback name, with or without a port."""
    if not isinstance(value, str) or not value:
        return False
    if any(ch in value for ch in " \t\r\n\\/@#?"):
        return False
    if value == "::1":
        return True
    host = value
    if host.startswith("["):
        end = host.find("]")
        if end < 0:
            return False
        name = host[1:end]
        rest = host[end + 1:]
        if rest == "":
            return name == "::1"
        if not (rest.startswith(":") and rest[1:].isdigit()):
            return False
        return name == "::1"
    if host.count(":") == 1:
        name, port = host.split(":", 1)
        if not port.isdigit():
            return False
        host = name
    elif host.count(":") > 1:
        return False
    return host in _LOOPBACK_NAMES


def max_body_bytes(path: str) -> int:
    if path == "/api/upload":
        return config.MAX_REQUEST_BYTES
    return config.MAX_MESSAGE_BODY_BYTES


def _header(scope, name: bytes):
    for key, value in scope.get("headers") or []:
        if key == name:
            return value
    return None


async def _send_json(send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class LoopbackHostMiddleware:
    """Reject requests whose Host header is not a loopback name."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw = _header(scope, b"host")
        try:
            host = raw.decode("latin-1") if raw else ""
        except UnicodeError:
            host = ""
        if not host_is_loopback(host):
            await _send_json(send, 400, "Host is not allowed")
            return
        await self.app(scope, receive, send)


class BodyLimitMiddleware:
    """Stop reading a request body once it passes the route's byte cap."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = max_body_bytes(scope.get("path") or "")
        raw_length = _header(scope, b"content-length")
        if raw_length:
            try:
                if int(raw_length) > limit:
                    await _send_json(send, 413, "Request body exceeds the size limit")
                    return
            except ValueError:
                await _send_json(send, 400, "Invalid content length")
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body") or b""
                received += len(body)
                if received > limit:
                    raise _BodyTooLarge()
            return message

        started = False

        async def guarded_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            if not started:
                await _send_json(send, 413, "Request body exceeds the size limit")


class _BodyTooLarge(Exception):
    pass
