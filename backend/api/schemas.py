from __future__ import annotations

from typing import Annotated, Literal

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
    password: str = Field(min_length=10, max_length=128)

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
    created_at: str


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

    @model_validator(mode="after")
    def validate_volume(self) -> BgmDecisionRequest:
        if self.action == BgmAction.ADD and self.volume is None:
            raise ValueError("添加 BGM 时必须提供音量")
        if self.action == BgmAction.NO_ADD and self.volume is not None:
            raise ValueError("不添加 BGM 时不得提供音量")
        if self.volume is not None:
            self.volume = round(self.volume, 3)
        return self


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
