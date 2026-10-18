"""One error envelope for every non-2xx response. Raw exceptions, stack traces, DSNs and input
values never reach the client; details go to the structured log, keyed by request_id."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.exceptions import ResponseError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.logging import BodyTooLarge, request_id_var
from app.db.postgres import PostgresUnavailable
from app.graph.client import GraphUnavailable
from app.graph.repository import TenantConflict
from app.graph.schema import SchemaViolation

log = logging.getLogger("app.errors")


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[dict] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: list[dict] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code


class NotFound(ApiError):
    status, code = 404, "not_found"


class Conflict(ApiError):
    status, code = 409, "conflict"


class InvalidInput(ApiError):
    status, code = 422, "invalid_input"


class Unauthenticated(ApiError):
    status, code = 401, "unauthenticated"


class Forbidden(ApiError):
    status, code = 403, "forbidden"


def error_json(status: int, code: str, message: str, details: list[dict] | None = None,
               headers: dict | None = None) -> JSONResponse:
    body = {"code": code, "message": message, "request_id": request_id_var.get()}
    if details:
        body["details"] = details
    return JSONResponse(status_code=status, content={"error": body}, headers=headers)


ERROR_RESPONSES = {
    s: {"model": ErrorResponse} for s in (401, 403, 404, 409, 413, 422, 500, 503)
}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return error_json(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # Echo location and reason only; never the submitted value.
        details = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
                   for e in exc.errors()]
        return error_json(422, "validation_error", "request failed validation", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        return error_json(exc.status_code, code, message, headers=getattr(exc, "headers", None))

    @app.exception_handler(BodyTooLarge)
    async def _too_large(_: Request, exc: BodyTooLarge):
        return error_json(413, "payload_too_large", "request body too large")

    @app.exception_handler(SchemaViolation)
    async def _schema(_: Request, exc: SchemaViolation):
        status, code = (409, "tenant_conflict") if isinstance(exc, TenantConflict) else (422, "schema_violation")
        return error_json(status, code, str(exc))

    @app.exception_handler(GraphUnavailable)
    async def _graph_down(_: Request, exc: GraphUnavailable):
        log.warning("graph unavailable", extra={"error_type": type(exc.__cause__ or exc).__name__})
        return error_json(503, "dependency_unavailable", "graph database unavailable", headers={"Retry-After": "5"})

    @app.exception_handler(PostgresUnavailable)
    async def _pg_down(_: Request, exc: PostgresUnavailable):
        log.warning("postgres unavailable")
        return error_json(503, "dependency_unavailable", "checkpoint database unavailable",
                          headers={"Retry-After": "5"})

    @app.exception_handler(ResponseError)
    async def _graph_error(_: Request, exc: ResponseError):
        if "timed out" in str(exc).lower():
            log.warning("graph query timed out")
            return error_json(503, "dependency_timeout", "graph query timed out", headers={"Retry-After": "5"})
        log.error("graph query failed", extra={"error_type": type(exc).__name__, "error": str(exc)[:300]})
        return error_json(500, "internal_error", "internal error")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error", extra={"error_type": type(exc).__name__})
        return error_json(500, "internal_error", "internal error")
