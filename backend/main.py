from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from backend.api.errors import ApiError, api_error_response, validation_error_response
from backend.api.routes import router
from backend.application.workflow_service import WorkflowService
from backend.config import Settings, get_settings
from backend.db.repository import Repository
from backend.infrastructure.security import configure_logging

LOGGER = logging.getLogger(__name__)
MAX_JSON_REQUEST_BYTES = 1_048_576


def _request_id(value: str | None) -> str:
    if value:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return str(uuid4())


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    active_settings.ensure_directories()
    repository = Repository(active_settings.database_path)
    repository.initialize()
    service = WorkflowService(active_settings, repository)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.resume_incomplete()
        yield
        service.close()

    application = FastAPI(title="Clip Agent API", version="0.1.0", lifespan=lifespan)
    application.state.settings = active_settings
    application.state.repository = repository
    application.state.workflow_service = service
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=active_settings.allowed_hosts)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "Idempotency-Key"],
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = _request_id(request.headers.get("X-Request-ID"))
        content_length = request.headers.get("content-length")
        try:
            request_size = int(content_length) if content_length else 0
        except ValueError:
            request_size = MAX_JSON_REQUEST_BYTES + 1
        if request_size > MAX_JSON_REQUEST_BYTES:
            response = api_error_response(
                request, ApiError(413, "PAYLOAD_TOO_LARGE", "请求正文超过大小限制")
            )
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        return api_error_response(request, error)

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return validation_error_response(request, error)

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        LOGGER.exception(
            "unhandled request failure request_id=%s error_type=%s",
            request.state.request_id,
            type(error).__name__,
        )
        return api_error_response(
            request,
            ApiError(500, "INTERNAL_ERROR", "服务暂时无法完成请求", retryable=True),
        )

    @application.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(router)
    return application


configure_logging()
app = create_app()
