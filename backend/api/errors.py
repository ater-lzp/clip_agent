from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        fields: list[dict[str, str]] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.fields = fields


def api_error_response(request: Request, error: ApiError) -> JSONResponse:
    body: dict[str, Any] = {
        "code": error.code,
        "message": error.message,
        "request_id": request.state.request_id,
        "retryable": error.retryable,
    }
    if error.fields:
        body["fields"] = error.fields
    return JSONResponse(status_code=error.status_code, content={"error": body})


def validation_error_response(request: Request, error: RequestValidationError) -> JSONResponse:
    fields = []
    for issue in error.errors():
        location = [str(part) for part in issue["loc"] if part not in {"body", "query", "path"}]
        fields.append({"field": ".".join(location) or "request", "message": issue["msg"]})
    return api_error_response(
        request,
        ApiError(422, "VALIDATION_ERROR", "请求字段无效", fields=fields),
    )
