from __future__ import annotations

import math
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import FileResponse

from backend.api.dependencies import AuthContext, get_repository, require_auth, require_csrf
from backend.api.errors import ApiError
from backend.api.schemas import (
    BgmDecisionRequest,
    CapabilitiesResponse,
    CreateTaskRequest,
    CredentialsRequest,
    ReviewRequest,
    SettingsRequest,
    SettingsResponse,
    TaskDetailResponse,
    TaskPageResponse,
    UserResponse,
)
from backend.application.workflow_service import WorkflowService
from backend.config import Settings
from backend.db.repository import (
    DuplicateEmailError,
    IdempotencyConflictError,
    Repository,
    StateConflictError,
    TaskNotFoundError,
    VersionConflictError,
)
from backend.domain.models import (
    MIMO_VOICE_OPTIONS,
    PROGRESS,
    BgmAction,
    MimoVoiceId,
    ReviewAction,
    TaskStatus,
    UserPreferences,
)
from backend.infrastructure.security import (
    DUMMY_PASSWORD_HASH,
    expires_at,
    hash_password,
    new_token,
    token_hash,
    verify_password,
)

router = APIRouter(prefix="/api/v1")


def workflow_service(request: Request) -> WorkflowService:
    return request.app.state.workflow_service


def app_settings(request: Request) -> Settings:
    return request.app.state.settings


def _set_session_cookies(
    response: Response,
    repository: Repository,
    settings: Settings,
    user_id: str,
) -> None:
    session_token = new_token()
    csrf_token = new_token()
    repository.create_session(
        token_hash(session_token),
        token_hash(csrf_token),
        user_id,
        expires_at(settings.session_ttl_hours),
    )
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(
        "clip_session",
        session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        "clip_csrf",
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _task_error(task: dict) -> dict | None:
    if not task.get("error_code"):
        return None
    return {
        "code": task["error_code"],
        "message": task["error_message"],
        "retryable": bool(task["error_retryable"]),
        "failed_stage": task["failed_stage"] or "unknown",
    }


def _task_summary(task: dict) -> dict:
    status = TaskStatus(task["status"])
    completed_steps, label = PROGRESS[status]
    return {
        "id": task["id"],
        "topic": task["topic"],
        "target_duration_seconds": task["target_duration_seconds"],
        "aspect_ratio": task["aspect_ratio"],
        "voice_id": task["voice_id"],
        "provider_mode": task["provider_mode"],
        "status": task["status"],
        "progress": {
            "current_step": label,
            "completed_steps": completed_steps,
            "total_steps": 12,
        },
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
        "preview_ready": bool(task.get("preview_relative_path")),
        "export_ready": status == TaskStatus.COMPLETED and bool(task.get("final_relative_path")),
        "error": _task_error(task),
    }


def _pending_review(task: dict) -> dict | None:
    status = TaskStatus(task["status"])
    if status == TaskStatus.AWAITING_SCRIPT_REVIEW and task.get("script"):
        return {
            "kind": "script",
            "version": task["script_version"],
            "allowed_actions": [ReviewAction.APPROVE.value, ReviewAction.REJECT.value],
            "script": task["script"],
        }
    if status == TaskStatus.AWAITING_STORYBOARD_REVIEW and task.get("storyboard"):
        return {
            "kind": "storyboard",
            "version": task["storyboard_version"],
            "allowed_actions": [ReviewAction.APPROVE.value, ReviewAction.REJECT.value],
            "storyboard": task["storyboard"],
        }
    if status == TaskStatus.AWAITING_BGM_DECISION:
        return {
            "kind": "bgm",
            "version": task["preview_version"],
            "allowed_actions": [BgmAction.NO_ADD.value, BgmAction.ADD.value],
            "suggested_query": task.get("bgm_suggested_query") or "轻快 纯音乐",
            "default_volume": task["bgm_default_volume"],
        }
    return None


def _task_detail(task: dict) -> dict:
    duration_ms = task.get("final_duration_ms")
    return {
        **_task_summary(task),
        "thread_id": task["thread_id"],
        "script": task.get("script"),
        "storyboard": task.get("storyboard"),
        "pending_review": _pending_review(task),
        "preview_url": f"/api/v1/tasks/{task['id']}/preview"
        if task.get("preview_relative_path")
        else None,
        "export_url": f"/api/v1/tasks/{task['id']}/export"
        if TaskStatus(task["status"]) == TaskStatus.COMPLETED and task.get("final_relative_path")
        else None,
        "final_duration_seconds": round(duration_ms / 1000, 3) if duration_ms else None,
        "bgm_added": task.get("bgm_added"),
    }


def _not_found() -> ApiError:
    return ApiError(404, "TASK_NOT_FOUND", "任务不存在")


@router.post("/auth/register", status_code=201, response_model=UserResponse)
def register(
    body: CredentialsRequest,
    response: Response,
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(app_settings),
) -> dict:
    try:
        user = repository.create_user(body.email, hash_password(body.password))
    except DuplicateEmailError as error:
        raise ApiError(409, "EMAIL_EXISTS", "该邮箱已注册") from error
    _set_session_cookies(response, repository, settings, user["id"])
    return user


@router.post("/auth/login", response_model=UserResponse)
def login(
    body: CredentialsRequest,
    response: Response,
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(app_settings),
) -> dict:
    user = repository.get_user_by_email(body.email)
    encoded_hash = user["password_hash"] if user else DUMMY_PASSWORD_HASH
    password_valid = verify_password(body.password, encoded_hash)
    if not user or not password_valid:
        raise ApiError(401, "INVALID_CREDENTIALS", "邮箱或密码错误")
    _set_session_cookies(response, repository, settings, user["id"])
    return {"id": user["id"], "email": user["email"], "created_at": user["created_at"]}


@router.get("/auth/me", response_model=UserResponse)
def current_user(context: AuthContext = Depends(require_auth)) -> dict:
    return {
        "id": context.user_id,
        "email": context.email,
        "created_at": context.user_created_at,
    }


@router.delete("/auth/session", status_code=204)
def logout(
    response: Response,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> Response:
    repository.delete_session(context.session_hash)
    response.delete_cookie("clip_session", path="/")
    response.delete_cookie("clip_csrf", path="/")
    response.status_code = 204
    return response


@router.get("/settings", response_model=SettingsResponse)
def get_user_settings(
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> dict:
    return repository.get_settings(context.user_id)


@router.put("/settings", response_model=SettingsResponse)
def put_user_settings(
    body: SettingsRequest,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    return repository.update_settings(context.user_id, UserPreferences.model_validate(body))


@router.get("/capabilities", response_model=CapabilitiesResponse)
def get_capabilities(
    settings: Settings = Depends(app_settings),
    _: AuthContext = Depends(require_auth),
) -> dict:
    return {
        "provider_mode": settings.provider_mode,
        "external_requests_enabled": settings.provider_mode == "real",
        "voices": list(MIMO_VOICE_OPTIONS),
    }


@router.post("/tasks", status_code=201, response_model=TaskDetailResponse)
def create_task(
    body: CreateTaskRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
) -> dict:
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            raise ApiError(422, "VALIDATION_ERROR", "Idempotency-Key 不能为空")
    preferences = repository.get_settings(context.user_id)
    settings = app_settings(request)
    voice_id = body.voice_id or MimoVoiceId(preferences["preferred_voice"])
    try:
        task, created = repository.create_task(
            user_id=context.user_id,
            topic=body.topic,
            target_duration_seconds=body.target_duration_seconds,
            aspect_ratio=body.aspect_ratio.value,
            voice_id=voice_id.value,
            provider_mode=settings.provider_mode,
            idempotency_key=idempotency_key,
            default_bgm_volume=preferences["default_bgm_volume"],
        )
    except IdempotencyConflictError as error:
        raise ApiError(409, "IDEMPOTENCY_CONFLICT", "该幂等键已用于不同请求") from error
    if created:
        workflow_service(request).submit(task["id"])
    return _task_detail(task)


@router.get("/tasks", response_model=TaskPageResponse)
def list_tasks(
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
    status: TaskStatus | None = Query(default=None),
) -> dict:
    items, total = repository.list_tasks(
        context.user_id, page, page_size, status.value if status else None
    )
    return {
        "items": [_task_summary(item) for item in items],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
def get_task(
    task_id: UUID,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> dict:
    try:
        return _task_detail(repository.get_task(context.user_id, str(task_id)))
    except TaskNotFoundError as error:
        raise _not_found() from error


def _claim_review(
    *,
    request: Request,
    repository: Repository,
    context: AuthContext,
    task_id: UUID,
    kind: str,
    version: int,
    action: str,
    feedback: str | None = None,
    volume: float | None = None,
) -> dict:
    try:
        task = repository.claim_review(
            user_id=context.user_id,
            task_id=str(task_id),
            kind=kind,
            version=version,
            action=action,
            feedback=feedback,
            volume=volume,
        )
    except TaskNotFoundError as error:
        raise _not_found() from error
    except VersionConflictError as error:
        raise ApiError(409, "VERSION_CONFLICT", "审核版本已过期，请刷新任务") from error
    except StateConflictError as error:
        raise ApiError(409, "STATE_CONFLICT", "任务当前状态不接受此操作") from error
    workflow_service(request).submit(str(task_id))
    return _task_detail(task)


@router.post("/tasks/{task_id}/reviews/script", status_code=202, response_model=TaskDetailResponse)
def review_script(
    task_id: UUID,
    body: ReviewRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    return _claim_review(
        request=request,
        repository=repository,
        context=context,
        task_id=task_id,
        kind="script",
        version=body.version,
        action=body.action.value,
        feedback=body.feedback,
    )


@router.post(
    "/tasks/{task_id}/reviews/storyboard",
    status_code=202,
    response_model=TaskDetailResponse,
)
def review_storyboard(
    task_id: UUID,
    body: ReviewRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    return _claim_review(
        request=request,
        repository=repository,
        context=context,
        task_id=task_id,
        kind="storyboard",
        version=body.version,
        action=body.action.value,
        feedback=body.feedback,
    )


@router.post("/tasks/{task_id}/bgm-decision", status_code=202, response_model=TaskDetailResponse)
def decide_bgm(
    task_id: UUID,
    body: BgmDecisionRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    return _claim_review(
        request=request,
        repository=repository,
        context=context,
        task_id=task_id,
        kind="bgm",
        version=body.version,
        action=body.action.value,
        volume=body.volume,
    )


@router.post("/tasks/{task_id}/retry", status_code=202, response_model=TaskDetailResponse)
def retry_task(
    task_id: UUID,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    try:
        task = repository.claim_retry(context.user_id, str(task_id))
    except TaskNotFoundError as error:
        raise _not_found() from error
    except StateConflictError as error:
        raise ApiError(409, "STATE_CONFLICT", "该任务当前不可重试") from error
    workflow_service(request).submit(str(task_id))
    return _task_detail(task)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: UUID,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> Response:
    try:
        task = repository.get_task(context.user_id, str(task_id))
        deletable = {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.AWAITING_SCRIPT_REVIEW.value,
            TaskStatus.AWAITING_STORYBOARD_REVIEW.value,
            TaskStatus.AWAITING_BGM_DECISION.value,
        }
        if task["status"] not in deletable:
            raise StateConflictError
        service = workflow_service(request)
        service.store.validate_task_directory(context.user_id, str(task_id))
        repository.delete_task_row(context.user_id, str(task_id))
        service.delete_checkpoints(task["thread_id"])
        service.store.delete_task_directory(context.user_id, str(task_id))
    except TaskNotFoundError as error:
        raise _not_found() from error
    except StateConflictError as error:
        raise ApiError(409, "STATE_CONFLICT", "执行中的任务不能删除") from error
    return Response(status_code=204)


def _authorized_media(
    repository: Repository,
    service: WorkflowService,
    context: AuthContext,
    task_id: UUID,
    kind: str,
) -> tuple[dict, Path]:
    try:
        task = repository.get_task(context.user_id, str(task_id))
    except TaskNotFoundError as error:
        raise _not_found() from error
    relative_path = (
        task.get("preview_relative_path") if kind == "preview" else task.get("final_relative_path")
    )
    if kind == "export" and task["status"] != TaskStatus.COMPLETED.value:
        raise ApiError(409, "STATE_CONFLICT", "最终视频尚未就绪")
    if not relative_path:
        raise ApiError(409, "STATE_CONFLICT", "视频尚未就绪")
    try:
        media_path = service.store.resolve_registered_path(
            context.user_id, str(task_id), relative_path
        )
    except (FileNotFoundError, ValueError) as error:
        raise ApiError(404, "MEDIA_NOT_FOUND", "媒体文件不存在") from error
    return task, media_path


@router.get("/tasks/{task_id}/preview")
def preview_video(
    task_id: UUID,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> FileResponse:
    _, media_path = _authorized_media(
        repository, workflow_service(request), context, task_id, "preview"
    )
    return FileResponse(media_path, media_type="video/mp4")


@router.get("/tasks/{task_id}/export")
def export_video(
    task_id: UUID,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> FileResponse:
    _, media_path = _authorized_media(
        repository, workflow_service(request), context, task_id, "export"
    )
    return FileResponse(
        media_path,
        media_type="video/mp4",
        filename=f"clip-{task_id}.mp4",
        content_disposition_type="attachment",
    )
