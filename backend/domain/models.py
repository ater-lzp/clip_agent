from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AspectRatio(str, Enum):
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    GENERATING_SCRIPT = "generating_script"
    AWAITING_SCRIPT_REVIEW = "awaiting_script_review"
    GENERATING_STORYBOARD = "generating_storyboard"
    AWAITING_STORYBOARD_REVIEW = "awaiting_storyboard_review"
    SYNTHESIZING_AUDIO = "synthesizing_audio"
    BUILDING_TIMELINE = "building_timeline"
    FETCHING_ASSETS = "fetching_assets"
    ALIGNING_TIMELINE = "aligning_timeline"
    RENDERING_PREVIEW = "rendering_preview"
    AWAITING_BGM_DECISION = "awaiting_bgm_decision"
    PROCESSING_BGM = "processing_bgm"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class BgmAction(str, Enum):
    NO_ADD = "no_add"
    ADD = "add"


class MimoVoiceId(str, Enum):
    DEFAULT = "mimo_default"
    BING_TANG = "冰糖"
    MO_LI = "茉莉"
    SU_DA = "苏打"
    BAI_HUA = "白桦"
    MIA = "Mia"
    CHLOE = "Chloe"
    MILO = "Milo"
    DEAN = "Dean"


MIMO_VOICE_OPTIONS: tuple[dict[str, str], ...] = (
    {
        "id": MimoVoiceId.DEFAULT.value,
        "name": "MiMo-默认",
        "language": "因部署集群而异",
        "gender": "因部署集群而异",
    },
    {"id": MimoVoiceId.BING_TANG.value, "name": "冰糖", "language": "中文", "gender": "女性"},
    {"id": MimoVoiceId.MO_LI.value, "name": "茉莉", "language": "中文", "gender": "女性"},
    {"id": MimoVoiceId.SU_DA.value, "name": "苏打", "language": "中文", "gender": "男性"},
    {"id": MimoVoiceId.BAI_HUA.value, "name": "白桦", "language": "中文", "gender": "男性"},
    {"id": MimoVoiceId.MIA.value, "name": "Mia", "language": "英文", "gender": "女性"},
    {"id": MimoVoiceId.CHLOE.value, "name": "Chloe", "language": "英文", "gender": "女性"},
    {"id": MimoVoiceId.MILO.value, "name": "Milo", "language": "英文", "gender": "男性"},
    {"id": MimoVoiceId.DEAN.value, "name": "Dean", "language": "英文", "gender": "男性"},
)


class ScriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    order: int = Field(ge=1)
    location: str = Field(min_length=1, max_length=300)
    narration: str = Field(min_length=1, max_length=2000)
    narration_char_count: int = Field(ge=1, le=2000)
    visual_intent: str = Field(min_length=1, max_length=1000)
    emotion: str = Field(min_length=1, max_length=1000)
    audio_cue: str = Field(min_length=1, max_length=500)
    speed_tier: Literal["慢速", "中速", "快速"] | None = None
    speed_value: float | None = Field(default=None, ge=3.0, le=8.0)
    estimated_duration_seconds: float = Field(gt=0, le=180)


class ScriptArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    platform: str = Field(min_length=1, max_length=80)
    aspect_ratio: AspectRatio
    total_duration_seconds: float = Field(gt=0, le=180)
    hook: str = Field(min_length=1, max_length=1000)
    segments: list[ScriptSegment] = Field(min_length=1, max_length=50)
    closing: str = Field(min_length=1, max_length=1000)
    bgm_query: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_segments(self) -> ScriptArtifact:
        ids = [item.id for item in self.segments]
        orders = [item.order for item in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("script segment ids must be unique")
        if sorted(orders) != list(range(1, len(orders) + 1)):
            raise ValueError("script segment orders must be continuous")
        segment_total = round(sum(item.estimated_duration_seconds for item in self.segments), 2)
        if abs(segment_total - self.total_duration_seconds) > 0.05:
            raise ValueError("script total duration must equal segment durations")
        return self


class StoryboardShot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    segment_id: str = Field(min_length=1, max_length=80)
    order: int = Field(ge=1)
    narration: str = Field(min_length=1, max_length=2000)
    visual_description: str = Field(min_length=1, max_length=1000)
    material_query: str = Field(min_length=1, max_length=200)
    keywords_en: list[str] = Field(min_length=1, max_length=8)
    keywords_cn: list[str] = Field(min_length=1, max_length=8)
    shot_type: str = Field(pattern=r"^(wide|medium|close-up)$")
    mood: str = Field(min_length=1, max_length=80)
    transition_in: str = Field(pattern=r"^(cut|dissolve|fade|wipe)$")
    audio_note: str = Field(min_length=1, max_length=500)
    orientation: AspectRatio
    estimated_duration_seconds: float = Field(gt=0, le=180)


class StoryboardArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    total_duration_seconds: float = Field(gt=0, le=180)
    total_shots: int = Field(ge=1, le=100)
    shots: list[StoryboardShot] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_shots(self) -> StoryboardArtifact:
        ids = [item.id for item in self.shots]
        orders = [item.order for item in self.shots]
        if len(ids) != len(set(ids)):
            raise ValueError("storyboard shot ids must be unique")
        if sorted(orders) != list(range(1, len(orders) + 1)):
            raise ValueError("storyboard shot orders must be continuous")
        if self.total_shots != len(self.shots):
            raise ValueError("storyboard total_shots must equal shot count")
        shot_total = round(sum(item.estimated_duration_seconds for item in self.shots), 2)
        if abs(shot_total - self.total_duration_seconds) > 0.05:
            raise ValueError("storyboard total duration must equal shot durations")
        return self


class AudioSegment(BaseModel):
    segment_id: str
    relative_path: str
    duration_ms: int = Field(gt=0)
    sample_rate: int = Field(gt=0)
    provider: str
    voice_id: MimoVoiceId
    checksum: str


class TimelineItem(BaseModel):
    shot_id: str
    segment_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    narration: str

    @model_validator(mode="after")
    def validate_interval(self) -> TimelineItem:
        if self.end_ms <= self.start_ms:
            raise ValueError("timeline end must be after start")
        return self


class MaterialAsset(BaseModel):
    shot_id: str
    provider: str
    provider_id: str
    source_url: str | None = None
    relative_path: str | None = None
    author: str
    license_name: str
    query: str
    matched_query: str
    original_duration_ms: int = Field(ge=0)
    target_duration_ms: int = Field(gt=0)
    trim_start_ms: int = Field(ge=0)
    trim_end_ms: int = Field(ge=0)
    loop_needed: bool
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    score: float


class SubtitleArtifact(BaseModel):
    relative_path: str
    cue_count: int = Field(ge=1)
    duration_ms: int = Field(gt=0)
    checksum: str


class VideoArtifact(BaseModel):
    relative_path: str
    duration_ms: int = Field(gt=0)
    checksum: str
    has_bgm: bool


class BgmArtifact(BaseModel):
    relative_path: str
    duration_ms: int = Field(gt=0)
    checksum: str
    source: str


class BgmSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(min_length=8, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    source: Literal["library", "upload"]
    uploaded_relative_path: str | None = None

    @model_validator(mode="after")
    def validate_source_path(self) -> BgmSelection:
        if self.source == "upload" and not self.uploaded_relative_path:
            raise ValueError("uploaded BGM path is required")
        if self.source == "library" and self.uploaded_relative_path is not None:
            raise ValueError("library BGM must not include a task path")
        return self


class SafeWorkflowError(BaseModel):
    code: str
    message: str
    retryable: bool
    failed_stage: str


class UserPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE
    default_duration_seconds: int = Field(default=60, ge=10, le=180)
    default_bgm_volume: float = Field(default=0.2, ge=0, le=1)
    preferred_voice: MimoVoiceId = MimoVoiceId.DEFAULT

    @field_validator("default_bgm_volume")
    @classmethod
    def round_volume(cls, value: float) -> float:
        return round(value, 3)


PROGRESS: dict[TaskStatus, tuple[int, str]] = {
    TaskStatus.QUEUED: (0, "等待开始"),
    TaskStatus.GENERATING_SCRIPT: (0, "生成剧本"),
    TaskStatus.AWAITING_SCRIPT_REVIEW: (1, "审核剧本"),
    TaskStatus.GENERATING_STORYBOARD: (2, "生成分镜"),
    TaskStatus.AWAITING_STORYBOARD_REVIEW: (3, "审核分镜"),
    TaskStatus.SYNTHESIZING_AUDIO: (4, "合成配音"),
    TaskStatus.BUILDING_TIMELINE: (5, "建立时间轴"),
    TaskStatus.FETCHING_ASSETS: (6, "获取素材与字幕"),
    TaskStatus.ALIGNING_TIMELINE: (8, "校验音画对齐"),
    TaskStatus.RENDERING_PREVIEW: (9, "渲染预览"),
    TaskStatus.AWAITING_BGM_DECISION: (10, "选择背景音乐"),
    TaskStatus.PROCESSING_BGM: (11, "处理背景音乐"),
    TaskStatus.COMPLETED: (12, "已完成"),
    TaskStatus.FAILED: (0, "处理失败"),
}


WAITING_STATUSES = {
    TaskStatus.AWAITING_SCRIPT_REVIEW,
    TaskStatus.AWAITING_STORYBOARD_REVIEW,
    TaskStatus.AWAITING_BGM_DECISION,
}
TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED}
