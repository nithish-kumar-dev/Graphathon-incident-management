"""Structured JSON logs, request ids, and a request body size limit.

Every log line is one JSON object. Request and response bodies are never logged.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
user_var: ContextVar[str] = ContextVar("user", default="-")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_EXTRA_FIELDS = ("method", "path", "status", "duration_ms", "error_type", "error", "outcome", "incident_id",
                 "alert_id", "investigation_id")

access_log = logging.getLogger("app.access")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
            "user": user_var.get(),
        }
        for key in _EXTRA_FIELDS:
            if hasattr(record, key):
                out[key] = getattr(record, key)
        if record.exc_info:
            out["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            out["exc"] = self.formatException(record.exc_info)[-2000:]
        return json.dumps(out, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class RequestContextMiddleware:
    """Pure ASGI: assigns a request id, enforces the body size limit, writes one access log line."""

    def __init__(self, app, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode(errors="replace") for k, v in scope.get("headers", [])}
        incoming = headers.get("x-request-id", "")
        rid = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        rid_token = request_id_var.set(rid)
        user_token = user_var.set(headers.get("x-demo-user", "-")[:64])
        start = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", rid.encode())]
            await send(message)

        try:
            declared = headers.get("content-length")
            if declared is not None:
                if declared.isdigit() and int(declared) > self.max_body_bytes:
                    return await self._reject_too_large(send_wrapper)
                await self.app(scope, self._limited_receive(receive), send_wrapper)
            else:
                # No Content-Length (chunked): buffer up to the limit here, because a body parser
                # would turn an exception raised mid-stream into a generic 400.
                buffered = await self._buffer(receive)
                if buffered is None:
                    return await self._reject_too_large(send_wrapper)
                await self.app(scope, buffered, send_wrapper)
        finally:
            access_log.info("request", extra={
                "method": scope.get("method"), "path": scope.get("path"), "status": status_holder["status"],
                "duration_ms": round((time.perf_counter() - start) * 1000, 2)})
            request_id_var.reset(rid_token)
            user_var.reset(user_token)

    def _limited_receive(self, receive):
        """Guards against a Content-Length that understates the real body."""
        seen = {"bytes": 0}

        async def wrapped():
            message = await receive()
            if message["type"] == "http.request":
                seen["bytes"] += len(message.get("body", b""))
                if seen["bytes"] > self.max_body_bytes:
                    raise BodyTooLarge()
            return message

        return wrapped

    async def _buffer(self, receive):
        messages, total = [], 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            total += len(message.get("body", b""))
            if total > self.max_body_bytes:
                return None
            if not message.get("more_body", False):
                break

        async def replay():
            return messages.pop(0) if messages else await receive()

        return replay

    async def _reject_too_large(self, send):
        body = json.dumps({"error": {"code": "payload_too_large", "request_id": request_id_var.get(),
                                     "message": f"request body exceeds {self.max_body_bytes} bytes"}}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class BodyTooLarge(Exception):
    """Raised mid-stream when a body without Content-Length exceeds the limit."""
