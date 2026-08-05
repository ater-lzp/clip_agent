from __future__ import annotations

import hashlib
import math
import secrets
import subprocess
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from backend.api.dependencies import (
    AuthContext,
    get_repository,
    require_admin,
    require_admin_csrf,
    require_auth,
    require_csrf,
)
from backend.api.errors import ApiError
from backend.api.schemas import (
    AccountResponse,
    AccountSummaryResponse,
    AdCreateMetadata,
    AdEventRequest,
    AdminAdPageResponse,
    AdminAdResponse,
    AdminAdUpdateRequest,
    AdminAuditLogPageResponse,
    AdminCdkPageResponse,
    AdminDashboardResponse,
    AdminPasswordResetRequest,
    AdminTaskPageResponse,
    AdminUserDetailResponse,
    AdminUserPageResponse,
    AdminUserResponse,
    AdminUserUpdateRequest,
    AdSelectionResponse,
    BgmDecisionRequest,
    BgmTrackPageResponse,
    BgmTrackResponse,
    BulkDeleteRequest,
    BulkDeleteResponse,
    CapabilitiesResponse,
    CdkBatchRequest,
    CommentRequest,
    CreatedCdkBatchResponse,
    CreatePostRequest,
    CreateTaskRequest,
    CredentialsRequest,
    DuplicateTaskRequest,
    LedgerPageResponse,
    MembershipPurchaseRequest,
    MembershipPurchaseResponse,
    PasswordChangeRequest,
    PaymentPasswordRequest,
    ProfileUpdateRequest,
    PublicUserResponse,
    RedeemCdkRequest,
    ReviewRequest,
    SettingsRequest,
    SettingsResponse,
    SharePostRequest,
    TaskDetailResponse,
    TaskPageResponse,
    TaskStatsResponse,
    UserResponse,
)
from backend.application.workflow_service import WorkflowService
from backend.config import Settings
from backend.db.repository import (
    AccountDisabledError,
    CdkNotFoundError,
    CdkUsedError,
    CommunityConflictError,
    CommunityNotFoundError,
    DuplicateEmailError,
    DuplicateNicknameError,
    IdempotencyConflictError,
    InsufficientBalanceError,
    QuotaExceededError,
    Repository,
    StateConflictError,
    TaskNotFoundError,
    UserNotFoundError,
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
from backend.infrastructure.ad_media import (
    MAX_AD_UPLOAD_BYTES,
    InvalidAdImageError,
    delete_ad_media,
    resolve_ad_image,
    save_ad_image,
)
from backend.infrastructure.bgm_media import (
    MAX_BGM_UPLOAD_BYTES,
    InvalidBgmError,
    normalize_uploaded_bgm,
)
from backend.infrastructure.profile_media import (
    MAX_AVATAR_BYTES,
    InvalidAvatarError,
    save_avatar,
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

MEMBERSHIP_PLANS = {
    "vip": {
        "tier": "vip",
        "name": "VIP",
        "price_cents": 2990,
        "duration_days": 30,
        "generation_credits": 30,
    },
    "svip": {
        "tier": "svip",
        "name": "SVIP",
        "price_cents": 7990,
        "duration_days": 30,
        "generation_credits": 100,
    },
}
CDK_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _cdk_hash(code: str) -> str:
    return hashlib.sha256(f"clip-cdk:{code}".encode()).hexdigest()


def _new_cdk() -> str:
    groups = ["".join(secrets.choice(CDK_ALPHABET) for _ in range(4)) for _ in range(4)]
    return f"CLIP-{'-'.join(groups)}"


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


def _user_response(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "nickname": user.get("nickname"),
        "avatar_url": f"/api/v1/users/{user['id']}/avatar"
        if user.get("avatar_relative_path")
        else None,
        "role": user.get("role", "user"),
        "created_at": user["created_at"],
    }


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _author_response(source: dict, prefix: str = "author_") -> dict:
    user_id = source["user_id"]
    return {
        "id": user_id,
        "name": source.get(f"{prefix}nickname") or "创作者",
        "avatar_url": f"/api/v1/users/{user_id}/avatar" if source.get(f"{prefix}avatar") else None,
    }


def _post_response(post: dict, viewer_id: str) -> dict:
    return {
        "id": post["id"],
        "task_id": post["task_id"],
        "title": post["title"],
        "description": post["description"],
        "author": _author_response(post),
        "aspect_ratio": post["aspect_ratio"],
        "duration_seconds": round((post.get("final_duration_ms") or 0) / 1000, 3),
        "prompt_public": bool(post["prompt_public"]),
        "generation_prompt": post["generation_prompt"]
        if post["prompt_public"] or post["user_id"] == viewer_id
        else None,
        "tags": post["tags"],
        "created_at": post["created_at"],
        "comment_count": post["comment_count"],
        "share_count": post["share_count"],
        "favorite_count": post["favorite_count"],
        "like_count": post["like_count"],
        "favorited": bool(post["favorited"]),
        "liked": bool(post["liked"]),
        "owned_by_me": post["user_id"] == viewer_id,
        "video_url": f"/api/v1/community/posts/{post['id']}/video",
        "cover_url": f"/api/v1/community/posts/{post['id']}/cover",
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
        "cover_url": f"/api/v1/tasks/{task['id']}/cover"
        if task.get("preview_relative_path")
        else None,
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
        uploaded_track = None
        if task.get("uploaded_bgm_relative_path"):
            uploaded_track = {
                "id": WorkflowService.uploaded_track_id(task["id"], task["preview_version"]),
                "name": task.get("uploaded_bgm_name") or "已上传音乐",
                "source": "upload",
                "duration_seconds": round(task["uploaded_bgm_duration_ms"] / 1000, 3),
                "preview_url": f"/api/v1/tasks/{task['id']}/bgm-upload/audio",
            }
        return {
            "kind": "bgm",
            "version": task["preview_version"],
            "allowed_actions": [BgmAction.NO_ADD.value, BgmAction.ADD.value],
            "suggested_query": task.get("bgm_suggested_query") or "轻快 纯音乐",
            "default_volume": task["bgm_default_volume"],
            "uploaded_track": uploaded_track,
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
    return _user_response(user)


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
    return _user_response(user)


@router.get("/auth/me", response_model=UserResponse)
def current_user(context: AuthContext = Depends(require_auth)) -> dict:
    return {
        "id": context.user_id,
        "email": context.email,
        "nickname": context.nickname,
        "avatar_url": f"/api/v1/users/{context.user_id}/avatar"
        if context.avatar_relative_path
        else None,
        "role": context.role,
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


@router.put("/profile", response_model=UserResponse)
def update_profile(
    body: ProfileUpdateRequest,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    try:
        return _user_response(repository.update_profile(context.user_id, body.nickname))
    except DuplicateNicknameError as error:
        raise ApiError(409, "NICKNAME_EXISTS", "该昵称已被使用") from error


@router.post("/profile/avatar", response_model=UserResponse)
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    if file.content_type not in {"image/jpeg", "image/png"}:
        raise ApiError(422, "INVALID_IMAGE", "头像只支持 JPG 或 PNG")
    content = await file.read(MAX_AVATAR_BYTES + 1)
    await file.close()
    if len(content) > MAX_AVATAR_BYTES:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "头像不能超过 2MB")
    try:
        relative_path = save_avatar(workflow_service(request).store, context.user_id, content)
    except InvalidAvatarError as error:
        raise ApiError(422, "INVALID_IMAGE", "头像文件内容无效") from error
    user = repository.update_avatar(context.user_id, relative_path)
    return _user_response(user)


@router.get("/users/{user_id}/avatar")
def user_avatar(
    user_id: UUID,
    request: Request,
    repository: Repository = Depends(get_repository),
    _: AuthContext = Depends(require_auth),
) -> FileResponse:
    user = repository.get_user_by_id(str(user_id))
    if not user or not user.get("avatar_relative_path"):
        raise ApiError(404, "MEDIA_NOT_FOUND", "用户头像不存在")
    try:
        path = workflow_service(request).store.resolve_profile_path(
            str(user_id), user["avatar_relative_path"]
        )
    except (FileNotFoundError, ValueError) as error:
        raise ApiError(404, "MEDIA_NOT_FOUND", "用户头像不存在") from error
    return FileResponse(path, media_type="image/jpeg")


@router.post("/profile/password", status_code=204)
def change_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> Response:
    credentials = repository.get_user_credentials(context.user_id)
    if not credentials or not verify_password(body.current_password, credentials["password_hash"]):
        raise ApiError(400, "CURRENT_PASSWORD_INVALID", "当前密码不正确")
    repository.change_password(context.user_id, hash_password(body.new_password))
    repository.record_audit(
        context.user_id, "password_changed", _client_ip(request), "user", context.user_id
    )
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


@router.get("/account", response_model=AccountResponse)
def get_account(
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> dict:
    return {
        "account": repository.get_account(context.user_id),
        "plans": list(MEMBERSHIP_PLANS.values()),
    }


@router.post("/account/payment-password", status_code=204)
def set_payment_password(
    body: PaymentPasswordRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> Response:
    credentials = repository.get_user_credentials(context.user_id)
    if not credentials or not verify_password(body.account_password, credentials["password_hash"]):
        raise ApiError(400, "CURRENT_PASSWORD_INVALID", "登录密码不正确")
    repository.set_payment_password_hash(
        context.user_id, hash_password(f"payment:{body.payment_password}")
    )
    repository.record_audit(
        context.user_id, "payment_password_set", _client_ip(request), "user", context.user_id
    )
    return Response(status_code=204)


@router.post("/account/redeem-cdk", response_model=AccountSummaryResponse)
def redeem_cdk(
    body: RedeemCdkRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    try:
        account = repository.redeem_cdk(context.user_id, _cdk_hash(body.code))
    except CdkNotFoundError as error:
        raise ApiError(404, "CDK_NOT_FOUND", "CDK 不存在或格式无效") from error
    except CdkUsedError as error:
        raise ApiError(409, "CDK_USED", "该 CDK 已被使用") from error
    repository.record_audit(
        context.user_id, "cdk_redeemed", _client_ip(request), "user", context.user_id
    )
    return account


@router.post("/account/memberships", status_code=201, response_model=MembershipPurchaseResponse)
def purchase_membership(
    body: MembershipPurchaseRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
) -> dict:
    payment_hash = repository.get_payment_password_hash(context.user_id)
    if not payment_hash:
        raise ApiError(409, "PAYMENT_PASSWORD_REQUIRED", "请先设置支付密码")
    if not verify_password(f"payment:{body.payment_password}", payment_hash):
        raise ApiError(400, "PAYMENT_PASSWORD_INVALID", "支付密码错误")
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            raise ApiError(422, "VALIDATION_ERROR", "Idempotency-Key 不能为空")
    plan = MEMBERSHIP_PLANS[body.tier]
    try:
        order, _ = repository.purchase_membership(
            user_id=context.user_id,
            tier=body.tier,
            price_cents=plan["price_cents"],
            generation_credits=plan["generation_credits"],
            duration_days=plan["duration_days"],
            idempotency_key=idempotency_key,
        )
    except InsufficientBalanceError as error:
        raise ApiError(409, "INSUFFICIENT_BALANCE", "账户余额不足") from error
    except IdempotencyConflictError as error:
        raise ApiError(409, "IDEMPOTENCY_CONFLICT", "该幂等键已用于其他购买") from error
    repository.record_audit(
        context.user_id,
        "membership_purchased",
        _client_ip(request),
        "membership_order",
        order["id"],
    )
    return {
        "order": {
            "id": order["id"],
            "tier": order["tier"],
            "price_cents": order["price_cents"],
            "generation_credits": order["generation_credits"],
            "status": order["status"],
            "created_at": order["created_at"],
        },
        "account": repository.get_account(context.user_id),
    }


@router.get("/account/ledger", response_model=LedgerPageResponse)
def get_account_ledger(
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    items, total = repository.list_ledger(context.user_id, page, page_size)
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": math.ceil(total / page_size) if total else 0,
    }


def _admin_user_response(user: dict) -> dict:
    quota = int(user["generation_quota"])
    used = int(user["generations_used"])
    return {
        **user,
        "is_active": bool(user["is_active"]),
        "balance_cents": int(user["balance_cents"]),
        "generation_quota": quota,
        "generations_used": used,
        "generations_remaining": max(0, quota - used),
    }


def _ad_response(ad: dict, *, admin: bool) -> dict:
    image_prefix = "/api/v1/admin/ads" if admin else "/api/v1/ads"
    response = {
        "id": ad["id"],
        "title": ad["title"],
        "link_url": ad["link_url"],
        "placement": ad["placement"],
        "image_url": f"{image_prefix}/{ad['id']}/image",
        "image_media_type": ad["image_media_type"],
    }
    if admin:
        response.update(
            {
                "is_active": bool(ad["is_active"]),
                "impressions": int(ad["impressions"]),
                "clicks": int(ad["clicks"]),
                "created_at": ad["created_at"],
                "updated_at": ad["updated_at"],
            }
        )
    return response


@router.get("/admin/dashboard", response_model=AdminDashboardResponse)
def admin_dashboard(
    repository: Repository = Depends(get_repository),
    _: AuthContext = Depends(require_admin),
) -> dict:
    return repository.admin_dashboard()


@router.get("/admin/users", response_model=AdminUserPageResponse)
def admin_users(
    repository: Repository = Depends(get_repository),
    _: AuthContext = Depends(require_admin),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=200),
    active: bool | None = Query(default=None),
    role: Literal["user", "admin"] | None = Query(default=None),
    membership: Literal["free", "vip", "svip"] | None = Query(default=None),
) -> dict:
    query = q.strip() if q else None
    items, total = repository.list_admin_users(page, page_size, query, active, role, membership)
    return {
        "items": [_admin_user_response(item) for item in items],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/admin/users/{user_id}", response_model=AdminUserDetailResponse)
def admin_user_detail(
    user_id: UUID,
    repository: Repository = Depends(get_repository),
    _: AuthContext = Depends(require_admin),
) -> dict:
    try:
        return _admin_user_response(repository.get_admin_user(str(user_id)))
    except UserNotFoundError as error:
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在") from error


@router.patch("/admin/users/{user_id}", response_model=AdminUserResponse)
def admin_update_user(
    user_id: UUID,
    body: AdminUserUpdateRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_admin_csrf),
) -> dict:
    if str(user_id) == context.user_id and (body.is_active is False or body.role == "user"):
        raise ApiError(409, "STATE_CONFLICT", "不能停用或降级当前管理员")
    try:
        user = repository.update_admin_user(
            str(user_id),
            is_active=body.is_active,
            role=body.role,
            generation_quota=body.generation_quota,
        )
    except UserNotFoundError as error:
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在") from error
    except StateConflictError as error:
        raise ApiError(409, "STATE_CONFLICT", "总额度不能低于已使用次数") from error
    repository.record_audit(
        context.user_id, "admin_user_updated", _client_ip(request), "user", str(user_id)
    )
    return _admin_user_response(user)


@router.post("/admin/users/{user_id}/password", status_code=204)
def admin_reset_user_password(
    user_id: UUID,
    body: AdminPasswordResetRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_admin_csrf),
) -> Response:
    if not repository.get_user_by_id(str(user_id)):
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在")
    repository.change_password(str(user_id), hash_password(body.new_password))
    repository.record_audit(
        context.user_id,
        "admin_user_password_reset",
        _client_ip(request),
        "user",
        str(user_id),
    )
    return Response(status_code=204)


@router.post("/admin/cdks", status_code=201, response_model=CreatedCdkBatchResponse)
def admin_create_cdks(
    body: CdkBatchRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_admin_csrf),
) -> dict:
    codes = [_new_cdk() for _ in range(body.count)]
    stored = repository.create_cdks(
        context.user_id,
        [(_cdk_hash(code), f"****-{code[-4:]}", body.amount_cents) for code in codes],
    )
    repository.record_audit(
        context.user_id, "cdk_batch_created", _client_ip(request), "cdk_batch", stored[0]["id"]
    )
    return {"items": [{**item, "code": code} for item, code in zip(stored, codes, strict=True)]}


@router.get("/admin/cdks", response_model=AdminCdkPageResponse)
def admin_list_cdks(
    repository: Repository = Depends(get_repository),
    _: AuthContext = Depends(require_admin),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Literal["unused", "used"] | None = Query(default=None),
) -> dict:
    items, total = repository.list_cdks(page, page_size, status)
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/admin/tasks", response_model=AdminTaskPageResponse)
def admin_list_tasks(
    repository: Repository = Depends(get_repository),
    _: AuthContext = Depends(require_admin),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=200),
    status: TaskStatus | None = Query(default=None),
    provider_mode: Literal["real", "fake"] | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
) -> dict:
    items, total = repository.list_admin_tasks(
        page,
        page_size,
        q.strip() if q else None,
        status.value if status else None,
        provider_mode,
        str(user_id) if user_id else None,
    )
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/admin/audit-logs", response_model=AdminAuditLogPageResponse)
def admin_list_audit_logs(
    repository: Repository = Depends(get_repository),
    _: AuthContext = Depends(require_admin),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=200),
    action: str | None = Query(default=None, min_length=1, max_length=100),
) -> dict:
    items, total = repository.list_admin_audit_logs(
        page, page_size, q.strip() if q else None, action.strip() if action else None
    )
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@router.post("/admin/ads", status_code=201, response_model=AdminAdResponse)
async def admin_create_ad(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(...),
    link_url: str = Form(...),
    placement: str = Form(default="auto"),
    is_active: bool = Form(default=True),
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_admin_csrf),
) -> dict:
    try:
        metadata = AdCreateMetadata(
            title=title, link_url=link_url, placement=placement, is_active=is_active
        )
    except ValidationError as error:
        link_error = any(issue["loc"] == ("link_url",) for issue in error.errors())
        code = "INVALID_LINK_URL" if link_error else "VALIDATION_ERROR"
        message = "广告跳转链接无效" if link_error else "广告字段无效"
        raise ApiError(422, code, message) from error
    content = await file.read(MAX_AD_UPLOAD_BYTES + 1)
    await file.close()
    if len(content) > MAX_AD_UPLOAD_BYTES:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "广告图片不能超过 5MB")
    ad_id = str(uuid4())
    store = workflow_service(request).store
    try:
        relative_path, media_type = save_ad_image(store, ad_id, content)
    except InvalidAdImageError as error:
        raise ApiError(422, "INVALID_AD_IMAGE", "广告图片内容无效") from error
    try:
        ad = repository.create_ad(
            ad_id,
            metadata.title,
            metadata.link_url,
            metadata.placement,
            relative_path,
            media_type,
            metadata.is_active,
            context.user_id,
        )
    except Exception:
        delete_ad_media(store, ad_id)
        raise
    repository.record_audit(context.user_id, "ad_created", _client_ip(request), "ad", ad_id)
    return _ad_response(ad, admin=True)


@router.get("/admin/ads", response_model=AdminAdPageResponse)
def admin_list_ads(
    repository: Repository = Depends(get_repository),
    _: AuthContext = Depends(require_admin),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
    active: bool | None = Query(default=None),
    placement: Literal["auto", "history", "community", "new_task", "task_detail"] | None = Query(
        default=None
    ),
) -> dict:
    items, total = repository.list_admin_ads(page, page_size, active, placement)
    return {
        "items": [_ad_response(item, admin=True) for item in items],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/admin/ads/{ad_id}/image")
def admin_ad_image(
    ad_id: UUID,
    request: Request,
    repository: Repository = Depends(get_repository),
    _: AuthContext = Depends(require_admin),
) -> FileResponse:
    ad = repository.get_ad(str(ad_id))
    if ad is None:
        raise ApiError(404, "AD_NOT_FOUND", "广告不存在")
    try:
        path = resolve_ad_image(
            workflow_service(request).store, str(ad_id), ad["image_relative_path"]
        )
    except (FileNotFoundError, ValueError) as error:
        raise ApiError(404, "AD_NOT_FOUND", "广告不存在") from error
    return FileResponse(
        path, media_type=ad["image_media_type"], headers={"Cache-Control": "private, no-store"}
    )


@router.patch("/admin/ads/{ad_id}", response_model=AdminAdResponse)
def admin_update_ad(
    ad_id: UUID,
    body: AdminAdUpdateRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_admin_csrf),
) -> dict:
    ad = repository.update_ad(
        str(ad_id),
        title=body.title,
        link_url=body.link_url,
        placement=body.placement,
        is_active=body.is_active,
    )
    if ad is None:
        raise ApiError(404, "AD_NOT_FOUND", "广告不存在")
    repository.record_audit(context.user_id, "ad_updated", _client_ip(request), "ad", str(ad_id))
    return _ad_response(ad, admin=True)


@router.delete("/admin/ads/{ad_id}", status_code=204)
def admin_delete_ad(
    ad_id: UUID,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_admin_csrf),
) -> Response:
    ad = repository.get_ad(str(ad_id))
    if ad is None:
        raise ApiError(404, "AD_NOT_FOUND", "广告不存在")
    delete_ad_media(workflow_service(request).store, str(ad_id))
    repository.delete_ad(str(ad_id))
    repository.record_audit(context.user_id, "ad_deleted", _client_ip(request), "ad", str(ad_id))
    return Response(status_code=204)


@router.get("/ads", response_model=AdSelectionResponse)
def select_ad(
    slot: Literal["history", "community", "new_task", "task_detail"],
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> dict:
    account = repository.get_account(context.user_id)
    if account["membership_tier"] != "free":
        return {"item": None}
    ad = repository.select_active_ad(slot)
    return {"item": _ad_response(ad, admin=False) if ad else None}


@router.get("/ads/{ad_id}/image")
def ad_image(
    ad_id: UUID,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> FileResponse:
    account = repository.get_account(context.user_id)
    ad = repository.get_ad(str(ad_id))
    if account["membership_tier"] != "free" or ad is None or not ad["is_active"]:
        raise ApiError(404, "AD_NOT_FOUND", "广告不存在")
    try:
        path = resolve_ad_image(
            workflow_service(request).store, str(ad_id), ad["image_relative_path"]
        )
    except (FileNotFoundError, ValueError) as error:
        raise ApiError(404, "AD_NOT_FOUND", "广告不存在") from error
    return FileResponse(
        path, media_type=ad["image_media_type"], headers={"Cache-Control": "private, no-store"}
    )


@router.post("/ads/{ad_id}/events", status_code=204)
def record_ad_event(
    ad_id: UUID,
    body: AdEventRequest,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> Response:
    account = repository.get_account(context.user_id)
    if account["membership_tier"] != "free" or not repository.record_ad_event(
        str(ad_id), body.event
    ):
        raise ApiError(404, "AD_NOT_FOUND", "广告不存在")
    return Response(status_code=204)


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


@router.post("/community/posts", status_code=201)
def publish_post(
    body: CreatePostRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    try:
        task_id = str(UUID(body.task_id))
        post = repository.create_post(
            context.user_id,
            task_id,
            body.title,
            body.description,
            body.prompt_public,
            body.tags,
        )
    except ValueError as error:
        raise ApiError(422, "VALIDATION_ERROR", "关联任务 ID 无效") from error
    except StateConflictError as error:
        raise ApiError(409, "STATE_CONFLICT", "只能发布自己已完成的视频") from error
    repository.record_audit(
        context.user_id, "community_post_published", _client_ip(request), "post", post["id"]
    )
    return _post_response(post, context.user_id)


@router.get("/community/posts")
def list_community_posts(
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=40),
    scope: str = Query(default="all", pattern="^(all|mine|favorites|shared|following)$"),
    tag: str | None = Query(default=None, max_length=20),
    owner_id: UUID | None = Query(default=None),
) -> dict:
    if scope == "shared":
        posts, total = repository.list_received_posts(context.user_id, page, page_size)
    else:
        posts, total = repository.list_posts(
            context.user_id,
            page,
            page_size,
            owner_id=str(owner_id) if owner_id else (context.user_id if scope == "mine" else None),
            favorite_only=scope == "favorites",
            following_only=scope == "following",
            tag=tag,
        )
    return {
        "items": [_post_response(post, context.user_id) for post in posts],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/community/posts/{post_id}")
def get_community_post(
    post_id: UUID,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> dict:
    try:
        return _post_response(repository.get_post(context.user_id, str(post_id)), context.user_id)
    except CommunityNotFoundError as error:
        raise ApiError(404, "POST_NOT_FOUND", "作品不存在") from error


@router.delete("/community/posts/{post_id}", status_code=204)
def delete_community_post(
    post_id: UUID,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> Response:
    try:
        repository.soft_delete_post(context.user_id, str(post_id))
    except CommunityNotFoundError as error:
        raise ApiError(404, "POST_NOT_FOUND", "作品不存在") from error
    repository.record_audit(
        context.user_id, "community_post_deleted", _client_ip(request), "post", str(post_id)
    )
    return Response(status_code=204)


@router.get("/community/posts/{post_id}/comments")
def list_post_comments(
    post_id: UUID,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
    sort: str = Query(default="latest", pattern="^(latest|hot)$"),
) -> dict:
    try:
        post = repository.get_post(context.user_id, str(post_id))
    except CommunityNotFoundError as error:
        raise ApiError(404, "POST_NOT_FOUND", "作品不存在") from error
    comments = repository.list_comments(context.user_id, str(post_id), sort)
    items = []
    for comment in comments:
        items.append(
            {
                "id": comment["id"],
                "parent_id": comment["parent_id"],
                "content": comment["content"],
                "author": _author_response(comment),
                "created_at": comment["created_at"],
                "like_count": comment["like_count"],
                "liked": comment["liked"],
                "can_delete": context.user_id in {comment["user_id"], post["user_id"]},
            }
        )
    return {"items": items}


@router.post("/community/posts/{post_id}/comments", status_code=201)
def add_post_comment(
    post_id: UUID,
    body: CommentRequest,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    try:
        parent_id = str(UUID(body.parent_id)) if body.parent_id else None
        return repository.add_comment(context.user_id, str(post_id), body.content, parent_id)
    except ValueError as error:
        raise ApiError(422, "VALIDATION_ERROR", "回复目标无效") from error
    except CommunityNotFoundError as error:
        raise ApiError(404, "POST_NOT_FOUND", "作品不存在") from error
    except CommunityConflictError as error:
        raise ApiError(409, "STATE_CONFLICT", "只支持回复一级评论") from error


@router.put("/community/comments/{comment_id}/like")
def toggle_comment_like(
    comment_id: UUID,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    try:
        return {"liked": repository.toggle_comment_like(context.user_id, str(comment_id))}
    except CommunityNotFoundError as error:
        raise ApiError(404, "COMMENT_NOT_FOUND", "评论不存在") from error


@router.delete("/community/comments/{comment_id}", status_code=204)
def delete_post_comment(
    comment_id: UUID,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> Response:
    try:
        repository.delete_comment(context.user_id, str(comment_id))
    except CommunityNotFoundError as error:
        raise ApiError(404, "COMMENT_NOT_FOUND", "评论不存在或无权删除") from error
    return Response(status_code=204)


@router.put("/community/posts/{post_id}/favorite")
def toggle_post_favorite(
    post_id: UUID,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    try:
        return {"favorited": repository.toggle_favorite(context.user_id, str(post_id))}
    except CommunityNotFoundError as error:
        raise ApiError(404, "POST_NOT_FOUND", "作品不存在") from error


@router.put("/community/posts/{post_id}/like")
def toggle_post_like(
    post_id: UUID,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    try:
        return {"liked": repository.toggle_post_like(context.user_id, str(post_id))}
    except CommunityNotFoundError as error:
        raise ApiError(404, "POST_NOT_FOUND", "作品不存在") from error


@router.get("/users/{user_id}", response_model=PublicUserResponse)
def get_public_user(
    user_id: UUID,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> dict:
    try:
        profile = repository.get_public_profile(context.user_id, str(user_id))
    except CommunityNotFoundError as error:
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在") from error
    return {
        "id": profile["id"],
        "nickname": profile["nickname"],
        "avatar_url": f"/api/v1/users/{profile['id']}/avatar"
        if profile.get("avatar_relative_path")
        else None,
        "created_at": profile["created_at"],
        "follower_count": profile["follower_count"],
        "following_count": profile["following_count"],
        "post_count": profile["post_count"],
        "is_following": profile["is_following"],
        "is_self": profile["is_self"],
    }


@router.put("/users/{user_id}/follow")
def follow_user(
    user_id: UUID,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    try:
        return {"following": repository.follow_user(context.user_id, str(user_id))}
    except CommunityNotFoundError as error:
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在") from error
    except CommunityConflictError as error:
        raise ApiError(409, "STATE_CONFLICT", "不能关注自己") from error


@router.get("/community/users/search")
def search_community_users(
    q: str = Query(min_length=1, max_length=50),
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> dict:
    return {
        "items": [
            {
                "id": user["id"],
                "name": user.get("nickname") or user["email"],
                "avatar_url": f"/api/v1/users/{user['id']}/avatar"
                if user.get("avatar_relative_path")
                else None,
            }
            for user in repository.search_users(q.strip(), context.user_id)
        ]
    }


@router.post("/community/posts/{post_id}/shares", status_code=201)
def share_community_post(
    post_id: UUID,
    body: SharePostRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    try:
        recipient_id = str(UUID(body.recipient_id))
        repository.share_post(context.user_id, str(post_id), recipient_id)
    except ValueError as error:
        raise ApiError(422, "VALIDATION_ERROR", "目标用户无效") from error
    except CommunityNotFoundError as error:
        raise ApiError(404, "POST_NOT_FOUND", "作品或目标用户不存在") from error
    except CommunityConflictError as error:
        raise ApiError(409, "SHARE_EXISTS", "不能重复转发给该用户") from error
    repository.record_audit(
        context.user_id, "community_post_shared", _client_ip(request), "post", str(post_id)
    )
    return {"shared": True}


def _community_media(
    post_id: UUID, request: Request, repository: Repository, context: AuthContext
) -> tuple[dict, Path]:
    try:
        post = repository.get_post(context.user_id, str(post_id))
        path = workflow_service(request).store.resolve_registered_path(
            post["user_id"], post["task_id"], post["final_relative_path"]
        )
        return post, path
    except CommunityNotFoundError as error:
        raise ApiError(404, "POST_NOT_FOUND", "作品不存在") from error
    except (FileNotFoundError, ValueError) as error:
        raise ApiError(404, "MEDIA_NOT_FOUND", "作品视频不存在") from error


@router.get("/community/posts/{post_id}/video")
def community_video(
    post_id: UUID,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> FileResponse:
    _, path = _community_media(post_id, request, repository, context)
    return FileResponse(path, media_type="video/mp4")


@router.get("/community/posts/{post_id}/cover")
def community_cover(
    post_id: UUID,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> FileResponse:
    post, _ = _community_media(post_id, request, repository, context)
    try:
        relative = workflow_service(request).ensure_cover(
            post["user_id"], post["task_id"], post["final_relative_path"]
        )
        path = workflow_service(request).store.resolve_registered_path(
            post["user_id"], post["task_id"], relative
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError, ValueError) as error:
        raise ApiError(404, "MEDIA_NOT_FOUND", "作品封面不存在") from error
    return FileResponse(path, media_type="image/jpeg")


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
    except QuotaExceededError as error:
        raise ApiError(409, "QUOTA_EXHAUSTED", "生成次数已用完，请充值并开通会员") from error
    except AccountDisabledError as error:
        raise ApiError(403, "ACCOUNT_DISABLED", "账户已停用") from error
    if created:
        workflow_service(request).submit(task["id"])
    return _task_detail(task)


def _library_track_response(track) -> dict:
    return {
        "id": track.id,
        "name": track.name,
        "source": "library",
        "duration_seconds": round(track.duration_ms / 1000, 3),
        "preview_url": f"/api/v1/bgms/{track.id}/audio",
    }


@router.get("/bgms", response_model=BgmTrackPageResponse)
def list_bgms(
    request: Request,
    _: AuthContext = Depends(require_auth),
) -> dict:
    return {
        "items": [
            _library_track_response(track)
            for track in workflow_service(request).bgm_catalog.list_tracks()
        ]
    }


@router.get("/bgms/{track_id}/audio")
def library_bgm_audio(
    track_id: str,
    request: Request,
    _: AuthContext = Depends(require_auth),
) -> FileResponse:
    try:
        track = workflow_service(request).bgm_catalog.resolve(track_id)
    except InvalidBgmError as error:
        raise ApiError(404, "BGM_NOT_FOUND", "背景音乐不存在") from error
    media_type = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
    }.get(track.path.suffix.lower(), "application/octet-stream")
    return FileResponse(track.path, media_type=media_type)


@router.get("/tasks/stats", response_model=TaskStatsResponse)
def get_task_stats(
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> dict:
    return repository.get_task_stats(context.user_id)


@router.get("/tasks", response_model=TaskPageResponse)
def list_tasks(
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
    status: TaskStatus | None = Query(default=None),
    status_group: Literal["in_progress"] | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
) -> dict:
    if status is not None and status_group is not None:
        raise ApiError(422, "VALIDATION_ERROR", "status 与 status_group 不能同时使用")
    query = q.strip() if q is not None else None
    if q is not None and not query:
        raise ApiError(422, "VALIDATION_ERROR", "搜索关键词不能为空")
    items, total = repository.list_tasks(
        context.user_id,
        page,
        page_size,
        status.value if status else None,
        status_group=status_group,
        query=query,
    )
    return {
        "items": [_task_summary(item) for item in items],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@router.post("/tasks/bulk-delete", response_model=BulkDeleteResponse)
def bulk_delete_tasks(
    body: BulkDeleteRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict[str, int]:
    task_ids = None if body.mode == "all" else [str(task_id) for task_id in body.task_ids]
    try:
        tasks = repository.tasks_for_bulk_delete(context.user_id, task_ids)
        deletable = {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.AWAITING_SCRIPT_REVIEW.value,
            TaskStatus.AWAITING_STORYBOARD_REVIEW.value,
            TaskStatus.AWAITING_BGM_DECISION.value,
        }
        if any(task["status"] not in deletable for task in tasks):
            raise StateConflictError
        service = workflow_service(request)
        for task in tasks:
            service.store.validate_task_directory(context.user_id, task["id"])
        deleted_count = repository.delete_task_rows(context.user_id, [task["id"] for task in tasks])
        for task in tasks:
            service.delete_checkpoints(task["thread_id"])
            service.store.delete_task_directory(context.user_id, task["id"])
    except TaskNotFoundError as error:
        raise _not_found() from error
    except StateConflictError as error:
        raise ApiError(
            409, "STATE_CONFLICT", "所选记录中包含执行中的任务，未删除任何记录"
        ) from error
    return {"deleted_count": deleted_count}


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


@router.post(
    "/tasks/{task_id}/bgm-upload",
    status_code=201,
    response_model=BgmTrackResponse,
)
async def upload_task_bgm(
    task_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
) -> dict:
    try:
        task = repository.get_task(context.user_id, str(task_id))
    except TaskNotFoundError as error:
        raise _not_found() from error
    if task["status"] != TaskStatus.AWAITING_BGM_DECISION.value:
        raise ApiError(409, "STATE_CONFLICT", "任务当前不接受背景音乐上传")
    content = await file.read(MAX_BGM_UPLOAD_BYTES + 1)
    await file.close()
    if len(content) > MAX_BGM_UPLOAD_BYTES:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "背景音乐不能超过 25MB")
    try:
        relative_path, name, duration_ms, checksum = normalize_uploaded_bgm(
            workflow_service(request).store,
            context.user_id,
            str(task_id),
            int(task["preview_version"]),
            file.filename or "",
            content,
        )
        registered = repository.register_uploaded_bgm(
            user_id=context.user_id,
            task_id=str(task_id),
            preview_version=int(task["preview_version"]),
            relative_path=relative_path,
            name=name,
            duration_ms=duration_ms,
            checksum=checksum,
        )
    except InvalidBgmError as error:
        raise ApiError(
            422, "INVALID_BGM_FILE", "上传文件不是有效的 MP3、WAV 或 M4A 音频"
        ) from error
    except StateConflictError as error:
        raise ApiError(409, "STATE_CONFLICT", "任务当前不接受背景音乐上传") from error
    except VersionConflictError as error:
        raise ApiError(409, "VERSION_CONFLICT", "预览版本已变化，请刷新任务") from error
    return _pending_review(registered)["uploaded_track"]


@router.get("/tasks/{task_id}/bgm-upload/audio")
def uploaded_bgm_audio(
    task_id: UUID,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> FileResponse:
    try:
        task = repository.get_task(context.user_id, str(task_id))
        relative_path = task.get("uploaded_bgm_relative_path")
        if not relative_path:
            raise FileNotFoundError
        path = workflow_service(request).store.resolve_registered_path(
            context.user_id, str(task_id), relative_path
        )
    except TaskNotFoundError as error:
        raise _not_found() from error
    except (FileNotFoundError, ValueError) as error:
        raise ApiError(404, "BGM_NOT_FOUND", "该任务没有已上传的背景音乐") from error
    return FileResponse(path, media_type="audio/wav")


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
    bgm_selection: dict | None = None,
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
            bgm_selection=bgm_selection,
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
    selection = None
    if body.action == BgmAction.ADD:
        try:
            selection = workflow_service(request).resolve_bgm_selection(
                context.user_id, str(task_id), body.version, body.track_id or ""
            )
        except TaskNotFoundError as error:
            raise _not_found() from error
        except (InvalidBgmError, FileNotFoundError, ValueError) as error:
            raise ApiError(422, "BGM_NOT_FOUND", "所选背景音乐不存在或已失效") from error
    return _claim_review(
        request=request,
        repository=repository,
        context=context,
        task_id=task_id,
        kind="bgm",
        version=body.version,
        action=body.action.value,
        volume=body.volume,
        bgm_selection=selection,
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


@router.post("/tasks/{task_id}/duplicate", status_code=202, response_model=TaskDetailResponse)
def duplicate_task(
    task_id: UUID,
    body: DuplicateTaskRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_csrf),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
) -> dict:
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            raise ApiError(422, "VALIDATION_ERROR", "Idempotency-Key 不能为空")
    try:
        source = repository.get_task(context.user_id, str(task_id))
    except TaskNotFoundError as error:
        raise _not_found() from error
    if source["status"] != TaskStatus.COMPLETED.value:
        raise ApiError(409, "STATE_CONFLICT", "只能再次创作已完成的任务")
    preferences = repository.get_settings(context.user_id)
    settings = app_settings(request)
    try:
        task, created = repository.duplicate_task(
            user_id=context.user_id,
            source_task_id=str(task_id),
            provider_mode=settings.provider_mode,
            default_bgm_volume=preferences["default_bgm_volume"],
            idempotency_key=idempotency_key,
        )
    except IdempotencyConflictError as error:
        raise ApiError(409, "IDEMPOTENCY_CONFLICT", "该幂等键已用于不同请求") from error
    except StateConflictError as error:
        raise ApiError(409, "STATE_CONFLICT", "只能再次创作已完成的任务") from error
    except QuotaExceededError as error:
        raise ApiError(409, "QUOTA_EXHAUSTED", "生成次数已用完，请充值并开通会员") from error
    except AccountDisabledError as error:
        raise ApiError(403, "ACCOUNT_DISABLED", "账户已停用") from error
    if created:
        workflow_service(request).submit(task["id"])
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
    if kind == "preview":
        relative_path = (
            task.get("final_relative_path")
            if task["status"] == TaskStatus.COMPLETED.value
            and task.get("bgm_added")
            and task.get("final_relative_path")
            else task.get("preview_relative_path")
        )
    else:
        relative_path = task.get("final_relative_path")
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


@router.get("/tasks/{task_id}/cover")
def task_cover(
    task_id: UUID,
    request: Request,
    repository: Repository = Depends(get_repository),
    context: AuthContext = Depends(require_auth),
) -> FileResponse:
    task, _ = _authorized_media(repository, workflow_service(request), context, task_id, "preview")
    try:
        cover_relative_path = workflow_service(request).ensure_cover(
            context.user_id, str(task_id), task["preview_relative_path"]
        )
        cover_path = workflow_service(request).store.resolve_registered_path(
            context.user_id, str(task_id), cover_relative_path
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError, ValueError) as error:
        raise ApiError(404, "MEDIA_NOT_FOUND", "视频封面暂时不可用") from error
    return FileResponse(cover_path, media_type="image/jpeg")


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
