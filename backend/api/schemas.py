from __future__ import annotations

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.domain.models import (
    AspectRatio,
    BgmAction,
    MimoVoiceId,
    ReviewAction,
    ScriptArtifact,
    StoryboardArtifact,
    TaskStatus,
    UserPreferences,
)
from backend.infrastructure.security import normalize_email


class CredentialsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        try:
            return normalize_email(value)
        except ValueError as error:
            raise ValueError("请输入有效邮箱") from error


class UserResponse(BaseModel):
    id: str
    email: str
    nickname: str | None
    avatar_url: str | None
    role: Literal["user", "admin"]
    created_at: str


NICKNAME_PATTERN = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9]{2,12}$")


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, value: str) -> str:
        normalized = value.strip()
        if not NICKNAME_PATTERN.fullmatch(normalized):
            raise ValueError("昵称必须为 2–12 个中文、字母或数字")
        return normalized


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_new_password(self) -> PasswordChangeRequest:
        if self.new_password != self.confirm_password:
            raise ValueError("两次输入的新密码不一致")
        if not (
            re.search(r"[a-z]", self.new_password)
            and re.search(r"[A-Z]", self.new_password)
            and re.search(r"[0-9]", self.new_password)
        ):
            raise ValueError("新密码必须包含大写字母、小写字母和数字")
        return self


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=3, max_length=1000)
    target_duration_seconds: int = Field(ge=10, le=180)
    aspect_ratio: AspectRatio
    voice_id: MimoVoiceId | None = None

    @field_validator("topic")
    @classmethod
    def strip_topic(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("主题至少需要 3 个字符")
        return normalized


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    action: ReviewAction
    feedback: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_feedback(self) -> ReviewRequest:
        if self.action == ReviewAction.REJECT:
            if self.feedback is None or not self.feedback.strip():
                raise ValueError("退回时必须填写反馈")
            self.feedback = self.feedback.strip()
        elif self.feedback is not None:
            raise ValueError("批准时不得提交反馈")
        return self


class BgmDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    action: BgmAction
    volume: float | None = Field(default=None, ge=0, le=1)
    track_id: str | None = Field(default=None, min_length=8, max_length=100)

    @model_validator(mode="after")
    def validate_volume(self) -> BgmDecisionRequest:
        if self.action == BgmAction.ADD and self.volume is None:
            raise ValueError("添加 BGM 时必须提供音量")
        if self.action == BgmAction.ADD and self.track_id is None:
            raise ValueError("添加 BGM 时必须选择音乐")
        if self.action == BgmAction.NO_ADD and (
            self.volume is not None or self.track_id is not None
        ):
            raise ValueError("不添加 BGM 时不得提供音量或音乐")
        if self.volume is not None:
            self.volume = round(self.volume, 3)
        return self


class BgmTrackResponse(BaseModel):
    id: str
    name: str
    source: Literal["library", "upload"]
    duration_seconds: float
    preview_url: str


class BgmTrackPageResponse(BaseModel):
    items: list[BgmTrackResponse]


class BulkDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["all", "selected"]
    task_ids: list[UUID] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_selection(self) -> BulkDeleteRequest:
        unique_ids = list(dict.fromkeys(self.task_ids))
        if len(unique_ids) != len(self.task_ids):
            raise ValueError("任务 ID 不得重复")
        if self.mode == "all" and self.task_ids:
            raise ValueError("全选删除时不得提交任务 ID")
        if self.mode == "selected" and not self.task_ids:
            raise ValueError("请选择至少一个任务")
        return self


class BulkDeleteResponse(BaseModel):
    deleted_count: int = Field(ge=0)


class TaskProgressResponse(BaseModel):
    current_step: str
    completed_steps: int
    total_steps: Literal[12] = 12


class SafeTaskErrorResponse(BaseModel):
    code: str
    message: str
    retryable: bool
    failed_stage: str


class TaskSummaryResponse(BaseModel):
    id: str
    topic: str
    target_duration_seconds: int
    aspect_ratio: AspectRatio
    voice_id: MimoVoiceId
    provider_mode: Literal["real", "fake"]
    status: TaskStatus
    progress: TaskProgressResponse
    created_at: str
    updated_at: str
    preview_ready: bool
    export_ready: bool
    cover_url: str | None
    error: SafeTaskErrorResponse | None


class ScriptPendingReview(BaseModel):
    kind: Literal["script"]
    version: int
    allowed_actions: list[ReviewAction]
    script: ScriptArtifact


class StoryboardPendingReview(BaseModel):
    kind: Literal["storyboard"]
    version: int
    allowed_actions: list[ReviewAction]
    storyboard: StoryboardArtifact


class BgmPendingReview(BaseModel):
    kind: Literal["bgm"]
    version: int
    allowed_actions: list[BgmAction]
    suggested_query: str
    default_volume: float
    uploaded_track: BgmTrackResponse | None


PendingReview = Annotated[
    ScriptPendingReview | StoryboardPendingReview | BgmPendingReview,
    Field(discriminator="kind"),
]


class TaskDetailResponse(TaskSummaryResponse):
    thread_id: str
    script: ScriptArtifact | None
    storyboard: StoryboardArtifact | None
    pending_review: PendingReview | None
    preview_url: str | None
    export_url: str | None
    final_duration_seconds: float | None
    bgm_added: bool | None


class TaskPageResponse(BaseModel):
    items: list[TaskSummaryResponse]
    page: int
    page_size: int
    total: int
    pages: int


class ErrorField(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    fields: list[ErrorField] | None = None
    retryable: bool = False


class ErrorResponse(BaseModel):
    error: ErrorBody


SettingsRequest = UserPreferences
SettingsResponse = UserPreferences


class VoiceOptionResponse(BaseModel):
    id: MimoVoiceId
    name: str
    language: Literal["中文", "英文", "因部署集群而异"]
    gender: Literal["女性", "男性", "因部署集群而异"]


class CapabilitiesResponse(BaseModel):
    provider_mode: Literal["real", "fake"]
    external_requests_enabled: bool
    voices: list[VoiceOptionResponse]


class CreatePostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    title: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=500)
    prompt_public: bool = False
    tags: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("title", "description")
    @classmethod
    def strip_post_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        tags = []
        for value in values:
            tag = value.strip().lstrip("#")
            if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]{1,20}", tag):
                raise ValueError("标签必须为 1–20 个中文、字母或数字")
            if tag not in tags:
                tags.append(tag)
        return tags


class CommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=200)
    parent_id: str | None = None

    @field_validator("content")
    @classmethod
    def strip_comment(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("评论不能为空")
        return normalized


class SharePostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_id: str


class TaskStatsResponse(BaseModel):
    total: int
    completed: int
    failed: int
    in_progress: int
    awaiting_review: int
    total_duration_seconds: float


class PublicUserResponse(BaseModel):
    id: str
    nickname: str | None
    avatar_url: str | None
    created_at: str
    follower_count: int
    following_count: int
    post_count: int
    is_following: bool
    is_self: bool


class DuplicateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaymentPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_password: str = Field(min_length=1, max_length=128)
    payment_password: str = Field(pattern=r"^\d{6}$")
    confirm_password: str = Field(pattern=r"^\d{6}$")

    @model_validator(mode="after")
    def validate_confirmation(self) -> PaymentPasswordRequest:
        if self.payment_password != self.confirm_password:
            raise ValueError("两次输入的支付密码不一致")
        return self


class RedeemCdkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=24, max_length=24)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"CLIP-[A-Z2-9]{4}(?:-[A-Z2-9]{4}){3}", normalized):
            raise ValueError("CDK 格式无效")
        return normalized


class MembershipPurchaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tier: Literal["vip", "svip"]
    payment_password: str = Field(pattern=r"^\d{6}$")


class AccountSummaryResponse(BaseModel):
    membership_tier: Literal["free", "vip", "svip"]
    membership_expires_at: str | None
    balance_cents: int
    generation_quota: int
    generations_used: int
    generations_remaining: int
    has_payment_password: bool


class MembershipPlanResponse(BaseModel):
    tier: Literal["vip", "svip"]
    name: str
    price_cents: int
    duration_days: int
    generation_credits: int


class AccountResponse(BaseModel):
    account: AccountSummaryResponse
    plans: list[MembershipPlanResponse]


class MembershipOrderResponse(BaseModel):
    id: str
    tier: Literal["vip", "svip"]
    price_cents: int
    generation_credits: int
    status: Literal["paid"]
    created_at: str


class MembershipPurchaseResponse(BaseModel):
    order: MembershipOrderResponse
    account: AccountSummaryResponse


class LedgerEntryResponse(BaseModel):
    id: str
    kind: Literal["cdk_recharge", "membership_payment"]
    amount_cents: int
    balance_after_cents: int
    reference_type: str
    created_at: str


class LedgerPageResponse(BaseModel):
    items: list[LedgerEntryResponse]
    page: int
    page_size: int
    total: int
    pages: int


class AdminUserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: bool | None = None
    role: Literal["user", "admin"] | None = None
    generation_quota: int | None = Field(default=None, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def require_change(self) -> AdminUserUpdateRequest:
        if self.is_active is None and self.role is None and self.generation_quota is None:
            raise ValueError("至少提交一个修改字段")
        return self


class AdminPasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_new_password(self) -> AdminPasswordResetRequest:
        if self.new_password != self.confirm_password:
            raise ValueError("两次输入的新密码不一致")
        if not (
            re.search(r"[a-z]", self.new_password)
            and re.search(r"[A-Z]", self.new_password)
            and re.search(r"[0-9]", self.new_password)
        ):
            raise ValueError("新密码必须包含大写字母、小写字母和数字")
        return self


class CdkBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_cents: int = Field(ge=1, le=1_000_000)
    count: int = Field(ge=1, le=100)


class AdminDashboardResponse(BaseModel):
    user_total: int
    active_users: int
    vip_users: int
    svip_users: int
    task_total: int
    completed_tasks: int
    failed_tasks: int
    in_progress_tasks: int
    awaiting_tasks: int
    today_users: int
    membership_revenue_cents: int
    cdk_total: int
    cdk_used: int


class AdminUserResponse(BaseModel):
    id: str
    email: str
    nickname: str | None
    role: Literal["user", "admin"]
    is_active: bool
    membership_tier: Literal["free", "vip", "svip"]
    membership_expires_at: str | None
    balance_cents: int
    generation_quota: int
    generations_used: int
    generations_remaining: int
    created_at: str
    task_count: int | None = None


class AdminUserPageResponse(BaseModel):
    items: list[AdminUserResponse]
    page: int
    page_size: int
    total: int
    pages: int


class AdminUserDetailResponse(AdminUserResponse):
    task_count: int
    completed_task_count: int
    failed_task_count: int
    recent_ledger: list[LedgerEntryResponse]


class AdminTaskResponse(BaseModel):
    id: str
    user_id: str
    user_email: str
    user_nickname: str | None
    topic: str
    status: TaskStatus
    current_stage: str
    provider_mode: Literal["real", "fake"]
    target_duration_seconds: int
    final_duration_seconds: float | None
    aspect_ratio: AspectRatio
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str


class AdminTaskPageResponse(BaseModel):
    items: list[AdminTaskResponse]
    page: int
    page_size: int
    total: int
    pages: int


class AdminAuditLogResponse(BaseModel):
    id: str
    actor_id: str | None
    actor_email: str | None
    actor_nickname: str | None
    action: str
    target_type: str | None
    target_id: str | None
    ip_address: str
    created_at: str


class AdminAuditLogPageResponse(BaseModel):
    items: list[AdminAuditLogResponse]
    page: int
    page_size: int
    total: int
    pages: int


class CreatedCdkResponse(BaseModel):
    id: str
    code: str
    amount_cents: int
    created_at: str


class CreatedCdkBatchResponse(BaseModel):
    items: list[CreatedCdkResponse]


class AdminCdkResponse(BaseModel):
    id: str
    code_hint: str
    amount_cents: int
    status: Literal["unused", "used"]
    created_at: str
    used_at: str | None
    used_by: str | None
    used_by_email: str | None
    used_by_nickname: str | None


class AdminCdkPageResponse(BaseModel):
    items: list[AdminCdkResponse]
    page: int
    page_size: int
    total: int
    pages: int


AdPlacement = Literal["auto", "history", "community", "new_task", "task_detail"]


def _validated_ad_link(value: str) -> str:
    normalized = value.strip()
    if len(normalized) > 2048 or any(ord(character) < 32 for character in normalized):
        raise ValueError("广告链接无效")
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as error:
        raise ValueError("广告链接无效") from error
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        and not 1 <= port <= 65535
    ):
        raise ValueError("广告链接必须是安全的 HTTP 或 HTTPS 地址")
    return normalized


class AdCreateMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=80)
    link_url: str = Field(min_length=1, max_length=2048)
    placement: AdPlacement = "auto"
    is_active: bool = True

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("广告标题不能为空")
        return normalized

    @field_validator("link_url")
    @classmethod
    def validate_link(cls, value: str) -> str:
        return _validated_ad_link(value)


class AdminAdUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=80)
    link_url: str | None = Field(default=None, min_length=1, max_length=2048)
    placement: AdPlacement | None = None
    is_active: bool | None = None

    @field_validator("title")
    @classmethod
    def strip_optional_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("广告标题不能为空")
        return normalized

    @field_validator("link_url")
    @classmethod
    def validate_optional_link(cls, value: str | None) -> str | None:
        return None if value is None else _validated_ad_link(value)

    @model_validator(mode="after")
    def require_change(self) -> AdminAdUpdateRequest:
        if all(
            value is None for value in (self.title, self.link_url, self.placement, self.is_active)
        ):
            raise ValueError("至少提交一个修改字段")
        return self


class AdEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["impression", "click"]


class AdCreativeResponse(BaseModel):
    id: str
    title: str
    link_url: str
    placement: AdPlacement
    image_url: str
    image_media_type: Literal["image/jpeg", "image/png", "image/gif"]


class AdSelectionResponse(BaseModel):
    item: AdCreativeResponse | None


class AdminAdResponse(AdCreativeResponse):
    is_active: bool
    impressions: int
    clicks: int
    created_at: str
    updated_at: str


class AdminAdPageResponse(BaseModel):
    items: list[AdminAdResponse]
    page: int
    page_size: int
    total: int
    pages: int
