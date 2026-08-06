from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import struct
import subprocess
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol, TypeVar
from urllib.parse import urljoin

import httpx
import imageio_ffmpeg
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.config import Settings
from backend.domain.models import (
    AspectRatio,
    AudioSegment,
    BgmArtifact,
    BgmSelection,
    MaterialAsset,
    MimoVoiceId,
    ScriptArtifact,
    ScriptSegment,
    StoryboardArtifact,
    StoryboardShot,
    SubtitleArtifact,
    TimelineItem,
    VideoArtifact,
)
from backend.infrastructure.bgm_media import BgmCatalog
from backend.infrastructure.security import validate_https_url
from backend.infrastructure.storage import ArtifactStore


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class LlmAdapter(Protocol):
    name: str

    def generate_script(
        self,
        topic: str,
        target_duration_seconds: int,
        aspect_ratio: AspectRatio,
        version: int,
        feedback: str | None,
        idempotency_key: str,
    ) -> ScriptArtifact: ...

    def generate_storyboard(
        self,
        script: ScriptArtifact,
        aspect_ratio: AspectRatio,
        version: int,
        feedback: str | None,
        idempotency_key: str,
    ) -> StoryboardArtifact: ...


class TtsAdapter(Protocol):
    name: str

    def synthesize(
        self,
        segment: ScriptSegment,
        voice_id: MimoVoiceId,
        output_path: Path,
        idempotency_key: str,
    ) -> AudioSegment: ...


class MaterialAdapter(Protocol):
    name: str

    def fetch(
        self,
        shot: StoryboardShot,
        aspect_ratio: AspectRatio,
        target_duration_ms: int,
        output_path: Path,
        idempotency_key: str,
    ) -> MaterialAsset: ...


class RendererAdapter(Protocol):
    name: str

    def render_preview(
        self,
        *,
        audio_segments: list[AudioSegment],
        timeline: list[TimelineItem],
        materials: list[MaterialAsset],
        subtitle: SubtitleArtifact,
        aspect_ratio: AspectRatio,
        output_path: Path,
        store: ArtifactStore,
    ) -> VideoArtifact: ...

    def fetch_bgm(
        self,
        selection: BgmSelection,
        duration_ms: int,
        output_path: Path,
        store: ArtifactStore,
    ) -> BgmArtifact: ...

    def mix_bgm(
        self,
        preview: VideoArtifact,
        bgm: BgmArtifact,
        volume: float,
        output_path: Path,
        store: ArtifactStore,
    ) -> VideoArtifact: ...


TModel = TypeVar("TModel", bound=BaseModel)
MIMO_CALIBRATED_CHARS_PER_SECOND = 3.15
SCRIPT_DURATION_REWRITE_LIMIT = 2


def _header_idempotency_key(value: str) -> str:
    if len(value) <= 200 and re.fullmatch(r"[A-Za-z0-9._:-]+", value):
        return value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _retry(operation: Any, retries: int) -> Any:
    for attempt in range(retries + 1):
        try:
            return operation()
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            if attempt >= retries:
                raise ProviderError("外部服务暂时不可用", retryable=True) from error
            time.sleep(0.15 * (2**attempt))
        except ProviderError as error:
            if not error.retryable or attempt >= retries:
                raise
            time.sleep(0.15 * (2**attempt))
    raise AssertionError("retry loop exhausted")


class FakeLlmAdapter:
    name = "fake-llm"

    def generate_script(
        self,
        topic: str,
        target_duration_seconds: int,
        aspect_ratio: AspectRatio,
        version: int,
        feedback: str | None,
        idempotency_key: str,
    ) -> ScriptArtifact:
        count = max(2, min(6, round(target_duration_seconds / 20)))
        duration = target_duration_seconds / count
        revision_note = f"，已根据反馈“{feedback[:36]}”调整" if feedback else ""
        segments: list[ScriptSegment] = []
        for index in range(1, count + 1):
            narration = f"第{index}部分，我们用清晰的例子理解{topic}{revision_note}。"
            target_chars = round(duration * 4.5)
            while _spoken_char_count(narration) < target_chars:
                narration += f"再说明一个与{topic}有关的关键点。"
            char_count = _spoken_char_count(narration)
            speed_value = round(char_count / duration, 2)
            speed_tier = "慢速" if speed_value < 4 else "中速" if speed_value < 5 else "快速"
            segments.append(
                ScriptSegment(
                    id=f"segment-{index:02d}",
                    order=index,
                    location="通用场景 / 内外景 / 日间",
                    narration=narration,
                    narration_char_count=char_count,
                    visual_intent=f"展示与{topic}相关的第{index}组直观画面",
                    emotion="语气自然清晰，语速中等，重点词适度强调",
                    audio_cue="无环境音，口播清晰",
                    speed_tier=speed_tier,
                    speed_value=speed_value,
                    estimated_duration_seconds=duration,
                )
            )
        return ScriptArtifact(
            version=version,
            title=f"快速理解：{topic[:80]}",
            platform="本地测试",
            aspect_ratio=aspect_ratio,
            total_duration_seconds=round(
                sum(item.estimated_duration_seconds for item in segments), 2
            ),
            hook=f"如果只用一分钟，你会怎样解释{topic}？",
            segments=segments,
            closing=f"这就是{topic}最值得记住的核心。",
            bgm_query="轻快 科技 纯音乐",
        )

    def generate_storyboard(
        self,
        script: ScriptArtifact,
        aspect_ratio: AspectRatio,
        version: int,
        feedback: str | None,
        idempotency_key: str,
    ) -> StoryboardArtifact:
        suffix = f"；按反馈调整：{feedback[:40]}" if feedback else ""
        return StoryboardArtifact(
            version=version,
            shots=[
                StoryboardShot(
                    id=f"shot-{segment.order:02d}",
                    segment_id=segment.id,
                    order=segment.order,
                    narration=segment.narration,
                    visual_description=f"{segment.visual_intent}{suffix}",
                    material_query=f"{topic_word(segment.visual_intent)} concept",
                    keywords_en=[topic_word(segment.visual_intent), "concept", "cinematic"],
                    keywords_cn=["主题", "概念", "电影感"],
                    shot_type="wide" if segment.order == 1 else "medium",
                    mood="清晰自然",
                    transition_in="fade" if segment.order == 1 else "cut",
                    audio_note=segment.audio_cue,
                    orientation=aspect_ratio,
                    estimated_duration_seconds=segment.estimated_duration_seconds,
                )
                for segment in script.segments
            ],
            total_duration_seconds=script.total_duration_seconds,
            total_shots=len(script.segments),
        )


def topic_word(value: str) -> str:
    words = re.findall(r"[A-Za-z]{3,}", value)
    return words[0].lower() if words else "creative"


class DifyScriptScene(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scene_id: int = Field(ge=1, le=100)
    location: str = Field(min_length=1, max_length=300)
    narration: str = Field(min_length=1, max_length=2000)
    narration_char_count: int = Field(ge=1, le=2000)
    visual_hint: str = Field(min_length=1, max_length=1000)
    emotion: str | dict[str, Any]
    audio_cue: str = Field(min_length=1, max_length=500)
    speed_tier: str | None = None
    speed_value: float | None = Field(default=None, gt=0, le=20)
    estimated_duration: float = Field(gt=0, le=180)


class DifyScriptOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=200)
    platform: str = Field(min_length=1, max_length=80)
    aspect_ratio: str = Field(min_length=1, max_length=30)
    total_duration: float = Field(gt=0, le=180)
    bgm_suggestion: str = Field(min_length=1, max_length=200)
    scenes: list[DifyScriptScene] = Field(min_length=1, max_length=50)


class DifyStoryboardShot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shot_id: int = Field(ge=1, le=200)
    belongs_to_scene: int = Field(ge=1, le=100)
    search_query: str = Field(min_length=1, max_length=200)
    keywords_en: str | list[str]
    keywords_cn: str | list[str]
    visual_description: str = Field(min_length=1, max_length=1000)
    shot_type: str
    mood: str = Field(min_length=1, max_length=80)
    transition_in: str
    audio_note: str = Field(min_length=1, max_length=500)
    narration_segment: str = Field(min_length=1, max_length=2000)
    estimated_duration: float = Field(gt=0, le=180)
    orientation: str = Field(min_length=1, max_length=30)


class DifyStoryboardOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_duration: float = Field(gt=0, le=180)
    total_shots: int = Field(ge=1, le=200)
    shots: list[DifyStoryboardShot] = Field(min_length=1, max_length=100)


SCRIPT_PROMPT_TEMPLATE = """# Role
专业的短视频口播编剧与分镜设计师

# Profile
- description: 擅长根据用户主题，结合精准的时长控制与语速计算模型，撰写高信息密度、情绪饱满的短视频口播剧本，并输出标准化JSON格式。

# Workflow
1. 接收用户输入的主题、时长、风格等参数。
2. 根据“MiMo 实测口播基准（3.15字/秒）”计算全片总字数预算。
3. 规划场景数量与各场景情绪、语速档位，撰写口播文案。
4. 在口播文案中嵌入语音风格标签，并在emotion字段中提供细致的语气描述。
5. 逐段计算 `narration_char_count` 和 `estimated_duration`，校验总字数与总时长。
6. 严格按JSON格式输出，不包含任何多余字符。

# Input Parameters
- 视频主题：__TOPIC__
- 目标总时长：约 __DURATION__ 秒
- 全片 narration 有效字符预算：目标 __TARGET_CHARS__ 字，必须控制在 __MIN_CHARS__ ~ __MAX_CHARS__ 字
- 建议场景数：__MIN_SCENES__ ~ __MAX_SCENES__ 个；不得用少量短场景提前结束
- 视频风格：__STYLE__
- 视频画幅：__ORIENTATION__ （对应比例：__ASPECT_WORD__）
- 修改反馈：__FEEDBACK__

# Core Calculation Rules
## 1. 字数预算与校准（最高优先级）
- 全片口播基准语速：3.15个实际朗读字符/秒（已包含 MiMo 情绪、停顿和分段开销的实测校准）。
- 目标总字数 = `__DURATION__ × 3.15`。
- 输出前必须逐段重新计数，确保所有 scene 的 `narration_char_count` 之和处于 `__MIN_CHARS__` ~ `__MAX_CHARS__` 之间，目标值为 `__TARGET_CHARS__`。
- 字数不足时补充有信息量的口语化内容；超出时精简。不得为了压缩字数而滥用快速档。

## 2. 语速标准与时长计算
根据场景情绪与信息密度，从以下三档中选择合适语速：

| 语速档位 | 范围（字/秒） | 适用场景 |
|---------|-------------|---------|
| 慢速 | 3.0 ~ 4.0 | 情感渲染、低落/疲惫情绪、正式演讲、需深度思考的内容 |
| 中速 | 4.0 ~ 5.0 | 日常对话、叙事推进、绝大多数自然表达场景（默认） |
| 快速 | 5.0 ~ 8.0 | 信息密集输出、新闻播报风格、紧张/兴奋情绪、高效传递要点 |

- **单场景时长计算**：`estimated_duration = narration_char_count ÷ speed_value`（保留2位小数）。
- **总时长计算**：`total_duration = Σ 所有场景的 estimated_duration`。
- 若总时长与目标时长偏差过大，通过调整 `narration` 字数或切换 `speed_tier` 来修正。

# Writing Rules
1. 单个 scene 只表达一个核心信息点，覆盖约 4~8 秒口播，避免过度拆分。
2. `narration` 必须口语化，适合朗读，避免书面语和长从句。
3. 旁白中的视觉意象必须在 `visual_hint` 中有对应画面，旁白信息顺序 = 画面呈现顺序。

# Voice Control Rules
## narration 字段（文本内嵌风格标签）
在文本开头添加 `(风格)` 标签指定发音风格，支持多种风格置于同一括号内（分隔符不限，支持半角/全角括号）。
- 基础情绪：开心/悲伤/愤怒/恐惧/惊讶/兴奋/委屈/平静/冷漠
- 复合情绪：怅然/欣慰/无奈/愧疚/释然/嫉妒/厌倦/忐忑/动情
- 整体语调：温柔/高冷/活泼/严肃/慵懒/俏皮/深沉/干练/凌厉
- 音色定位：磁性/醇厚/清亮/空灵/稚嫩/苍老/甜美/沙哑/醇雅
- 人设腔调：夹子音/御姐音/正太音/大叔音/台湾腔
- 方言：东北话/四川话/河南话/粤语
- 角色扮演：孙悟空/林黛玉
- 唱歌：唱歌
- **示例**：`(慵懒)再让我睡五分钟……就五分钟，真的，最后一次。`

## emotion 字段（自然语言描述）
用一句话完整描述语气、语速、音量和情绪指令。
- **示例**：`用明亮活泼的青少年嗓音，带着恶作剧得逞后的得意与戏谑，语速偏快且咬字轻巧，在强调赌注时语气微微上扬。`

# Output Format
严格输出以下合法 JSON 对象，不要输出解释、Markdown 代码块标记或任何前后缀文字：
{
  "title": "视频标题",
  "platform": "抖音",
  "aspect_ratio": "__ASPECT_WORD__",
  "total_duration": __DURATION__,
  "bgm_suggestion": "配乐风格建议",
  "scenes": [
    {
      "scene_id": 1,
      "location": "地点 / 内外 / 时间",
      "narration": "包含风格标签的口播文案",
      "narration_char_count": 25,
      "visual_hint": "15~30字具体画面描述",
      "emotion": "完整的语气、语速、音量和情绪指令",
      "audio_cue": "[BGM渐入] [环境音：风声]",
      "speed_tier": "中速",
      "speed_value": 4.5,
      "estimated_duration": 5.56
    }
  ]
}

# Constraints
- `narration_char_count` 统计规则：仅计算实际会朗读的中文、英文和数字字符，绝对不含标点、空白及 narration 开头的 `(风格)` / `（风格）` 控制标签。
- `scene_id` 从 1 连续递增。
- 输出前最后检查：Σ `narration_char_count` 必须处于 `__MIN_CHARS__` ~ `__MAX_CHARS__`。
- 仅输出合法 JSON 对象，绝对禁止输出任何非 JSON 格式的文字。
"""


STORYBOARD_PROMPT_TEMPLATE = """# Role
专业视频分镜师

# Profile
- description: 擅长将剧本拆解为可执行的素材搜索与剪辑方案，严格把控时长计算与声画同步，输出标准化JSON格式。

# Input Parameters
- 视频剧本：__SCRIPT__
- 视频画幅：__ASPECT_WORD__
- 修改反馈：__FEEDBACK__

# Workflow
1. 分析输入剧本的每个场景，根据旁白语义将场景拆解为1~3个镜头。
2. 为每个镜头生成精确的素材检索词、视觉描述与剪辑标注。
3. 严格执行时长分配与校验，确保各分镜时长之和精确匹配场景及全片总时长。
4. 仅输出合法的JSON对象。

# Core Rules (必须严格遵守)

## 1. 时长铁律
- 同一 `belongs_to_scene` 下所有 shot 的 `estimated_duration` 之和，必须等于该剧本场景的 `estimated_duration`（允许 ±0.5 秒误差）。
- 所有 shot 的 `estimated_duration` 之和，必须等于剧本 `total_duration`（允许 ±1 秒误差）。

## 2. 声画同步
- shot 排列顺序必须与 narration 的语义顺序完全一致。
- 旁白先提到的意象，对应 shot 必须排在前面。
- 若一句话包含两个意象，必须拆成两个 shot 并按出现顺序排列。

## 3. 镜头数量与节奏
- 每个剧本场景拆为 1~3 个 shot。
- 单 shot 建议 3~8 秒；快切蒙太奇可缩短到 1.5~3 秒。
- 不要为了凑数量而强行拆分，每个 shot 只表达一个核心画面或动作。

# Field Rules
- `shot_id`：从 1 全局连续递增。
- `belongs_to_scene`：必须引用剧本中存在的 scene_id。
- `search_query`：必须是 2~4 个具体英文名词或形容词，适合 Pexels API 检索，禁止使用抽象词。
- `keywords_en`：使用 3~4 个英文实词。
- `keywords_cn`：给出对应的中文实词。
- `visual_description`：用中文详细描述主体、动作、环境、镜头运动和光线。
- `shot_type`：只能是 `wide` / `medium` / `close-up`。
- `transition_in`：只能是 `cut` / `dissolve` / `fade` / `wipe`，且第一镜固定使用 `fade`。
- `narration_segment`：该镜头期间正在说的具体文字；若为纯画面则写“（无）”。
- `orientation`：必须为 `__ASPECT_WORD__`。

# Output Format
严格输出以下合法 JSON 对象，不要输出解释、Markdown 代码块标记或任何前后缀文字：
{
  "total_duration": 30,
  "total_shots": 8,
  "shots": [
    {
      "shot_id": 1,
      "belongs_to_scene": 1,
      "search_query": "mountain cloud sea",
      "keywords_en": "mountain clouds peak sunrise",
      "keywords_cn": "山峰 云海 日出",
      "visual_description": "航拍视角，群峰在云海中若隐若现，晨光穿透云层，镜头缓慢横移",
      "shot_type": "wide",
      "mood": "大气磅礴",
      "transition_in": "fade",
      "audio_note": "BGM渐入；环境音：高空风声",
      "narration_segment": "与该镜头对应的具体旁白文字",
      "estimated_duration": 4,
      "orientation": "__ASPECT_WORD__"
    }
  ]
}

# Constraints
- 优先选择 Pexels 等素材库容易检索到的真实画面。
- 输出前必须检查各场景和全部镜头的时长之和是否符合时长铁律。
- 仅输出合法 JSON 对象，绝对禁止输出任何非 JSON 格式的文字。
"""


def _json_content(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, list):
        text = "".join(
            str(item.get("text", "")) for item in value if isinstance(item, dict)
        ).strip()
    else:
        raise ProviderError("模型返回的内容类型无效", retryable=True)
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ProviderError("模型没有返回 JSON 对象", retryable=True)
    return re.sub(r",\s*([}\]])", r"\1", match.group(0))


def _completion_endpoint(base_url: str, suffix: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith(suffix.strip("/")):
        return normalized
    return urljoin(normalized + "/", suffix)


def _spoken_char_count(text: str) -> int:
    spoken_text = re.sub(r"^(?:[（(][^）)]{1,40}[）)]\s*)+", "", text.strip())
    return len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", spoken_text))


def _emotion_text(value: str | dict[str, Any]) -> str:
    if isinstance(value, str):
        normalized = value.strip()
    else:
        normalized = "，".join(f"{key}：{item}" for key, item in value.items() if str(item).strip())
    if not normalized:
        raise ProviderError("剧本场景缺少有效情绪指令", retryable=True)
    return normalized


def _string_list(value: str | list[str]) -> list[str]:
    items = re.split(r"[,，\s]+", value.strip()) if isinstance(value, str) else value
    normalized = [str(item).strip() for item in items if str(item).strip()]
    if not normalized:
        raise ProviderError("分镜关键词为空", retryable=True)
    return normalized[:8]


def _script_prompt(
    topic: str,
    target_duration_seconds: int,
    aspect_ratio: AspectRatio,
    feedback: str | None,
) -> str:
    target_chars = max(1, round(target_duration_seconds * MIMO_CALIBRATED_CHARS_PER_SECOND))
    minimum_chars = max(1, round(target_chars * 0.97))
    maximum_chars = max(minimum_chars, round(target_chars * 1.03))
    minimum_scenes = max(1, math.ceil(target_duration_seconds / 8))
    maximum_scenes = min(50, max(minimum_scenes, math.ceil(target_duration_seconds / 4)))
    aspect_word = "portrait" if aspect_ratio == AspectRatio.PORTRAIT else "landscape"
    orientation = (
        "portrait（竖屏 9:16）"
        if aspect_ratio == AspectRatio.PORTRAIT
        else "landscape（横屏 16:9）"
    )
    feedback_section = (
        f"\n# 上一版本审核反馈\n请在保持全部结构约束的前提下修改：{feedback}" if feedback else ""
    )
    return (
        SCRIPT_PROMPT_TEMPLATE.replace("__TOPIC__", topic)
        .replace("__DURATION__", str(target_duration_seconds))
        .replace("__TARGET_CHARS__", str(target_chars))
        .replace("__MIN_CHARS__", str(minimum_chars))
        .replace("__MAX_CHARS__", str(maximum_chars))
        .replace("__MIN_SCENES__", str(minimum_scenes))
        .replace("__MAX_SCENES__", str(maximum_scenes))
        .replace("__STYLE__", "专业、自然、有节奏感，适合短视频口播")
        .replace("__ORIENTATION__", orientation)
        .replace("__ASPECT_WORD__", aspect_word)
        .replace("__FEEDBACK__", feedback_section)
    )


def _storyboard_prompt(
    script: ScriptArtifact,
    aspect_ratio: AspectRatio,
    feedback: str | None,
) -> str:
    aspect_word = "portrait" if aspect_ratio == AspectRatio.PORTRAIT else "landscape"
    provider_script = {
        "title": script.title,
        "platform": script.platform,
        "aspect_ratio": aspect_word,
        "total_duration": script.total_duration_seconds,
        "bgm_suggestion": script.bgm_query,
        "scenes": [
            {
                "scene_id": segment.order,
                "location": segment.location,
                "narration": segment.narration,
                "narration_char_count": segment.narration_char_count,
                "visual_hint": segment.visual_intent,
                "emotion": segment.emotion,
                "audio_cue": segment.audio_cue,
                "speed_tier": segment.speed_tier,
                "speed_value": segment.speed_value,
                "estimated_duration": segment.estimated_duration_seconds,
            }
            for segment in script.segments
        ],
    }
    feedback_section = (
        f"\n# 上一版本审核反馈\n请在保持全部结构约束的前提下修改：{feedback}" if feedback else ""
    )
    return (
        STORYBOARD_PROMPT_TEMPLATE.replace(
            "__SCRIPT__", json.dumps(provider_script, ensure_ascii=False)
        )
        .replace("__ASPECT_WORD__", aspect_word)
        .replace("__FEEDBACK__", feedback_section)
    )


class OpenAICompatibleLlmAdapter:
    name = "openai-compatible-llm"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.endpoint = _completion_endpoint(settings.llm_base_url, "chat/completions")
        self.api_key = settings.llm_api_key
        self.model = settings.llm_name
        self.timeout = settings.llm_timeout_seconds
        self.retries = settings.provider_max_retries
        self.transport = transport

    def _structured(
        self,
        system_prompt: str,
        prompt: str,
        model_type: type[TModel],
        idempotency_key: str,
    ) -> TModel:
        def request() -> TModel:
            timeout = httpx.Timeout(self.timeout, connect=10.0, write=10.0, pool=10.0)
            with httpx.Client(timeout=timeout, transport=self.transport) as client:
                response = client.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Idempotency-Key": _header_idempotency_key(idempotency_key),
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": system_prompt,
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "thinking": {"type": "disabled"},
                        "response_format": {"type": "json_object"},
                        "temperature": 0.5,
                    },
                )
                if response.status_code in {408, 429} or response.status_code >= 500:
                    raise httpx.NetworkError("temporary provider response")
                if response.status_code >= 400:
                    raise ProviderError("模型请求被供应商拒绝", retryable=False)
                if len(response.content) > 2 * 1024 * 1024:
                    raise ProviderError("模型响应超过大小限制", retryable=False)
                try:
                    content = response.json()["choices"][0]["message"]["content"]
                    return model_type.model_validate_json(_json_content(content))
                except ValidationError as error:
                    first = error.errors(include_url=False, include_context=False)[0]
                    location = ".".join(str(item) for item in first.get("loc", ()))
                    detail = f"（字段：{location}）" if location else ""
                    raise ProviderError(
                        f"模型返回的结构不符合约定{detail}", retryable=True
                    ) from error
                except (KeyError, TypeError, json.JSONDecodeError) as error:
                    raise ProviderError("模型返回的结构不符合约定", retryable=True) from error

        return _retry(request, self.retries)

    def generate_script(
        self,
        topic: str,
        target_duration_seconds: int,
        aspect_ratio: AspectRatio,
        version: int,
        feedback: str | None,
        idempotency_key: str,
    ) -> ScriptArtifact:
        provider_output = self._structured(
            _script_prompt(topic, target_duration_seconds, aspect_ratio, feedback),
            "严格执行系统提示，只返回 JSON。",
            DifyScriptOutput,
            idempotency_key,
        )
        target_chars = max(1, round(target_duration_seconds * MIMO_CALIBRATED_CHARS_PER_SECOND))
        for rewrite_index in range(SCRIPT_DURATION_REWRITE_LIMIT):
            actual_total_chars = sum(
                _spoken_char_count(scene.narration) for scene in provider_output.scenes
            )
            if round(target_chars * 0.97) <= actual_total_chars <= round(target_chars * 1.03):
                break
            minimum_scenes = max(1, math.ceil(target_duration_seconds / 8))
            maximum_scenes = min(50, max(minimum_scenes, math.ceil(target_duration_seconds / 4)))
            per_scene_target = max(1, round(target_chars / max(minimum_scenes, 1)))
            duration_feedback = (
                f"上一版第 {rewrite_index + 1} 次字数校验失败：实际为 {actual_total_chars} 个"
                f"会被朗读的有效字符，与 {target_duration_seconds} 秒所需的 {target_chars} 字不符。"
                f"必须完整重写，确保所有 narration 的实际有效字符总数为 "
                f"{round(target_chars * 0.97)}~{round(target_chars * 1.03)} 字；"
                f"使用 {minimum_scenes}~{maximum_scenes} 个场景，每个场景平均约 "
                f"{per_scene_target} 字。不要复用上一版的文案，不要只修改计数字段或 "
                "total_duration 数字；逐段实际计数后再输出。"
            )
            combined_feedback = (
                f"{feedback.strip()}；{duration_feedback}" if feedback else duration_feedback
            )
            provider_output = self._structured(
                _script_prompt(
                    topic,
                    target_duration_seconds,
                    aspect_ratio,
                    combined_feedback,
                ),
                "上一版口播字数不足或过多。严格按总字数预算重写，只返回 JSON。",
                DifyScriptOutput,
                f"{idempotency_key}:duration-rewrite:{rewrite_index + 1}",
            )
        ordered_scenes = sorted(provider_output.scenes, key=lambda item: item.scene_id)
        if [item.scene_id for item in ordered_scenes] != list(range(1, len(ordered_scenes) + 1)):
            raise ProviderError("剧本 scene_id 不连续", retryable=True)
        segments: list[ScriptSegment] = []
        for scene in ordered_scenes:
            actual_chars = _spoken_char_count(scene.narration)
            calibrated_duration = round(actual_chars / MIMO_CALIBRATED_CHARS_PER_SECOND, 2)
            speed_value = round(actual_chars / calibrated_duration, 2)
            speed_tier = "慢速" if speed_value < 4 else "中速" if speed_value < 5 else "快速"
            segments.append(
                ScriptSegment(
                    id=f"scene-{scene.scene_id:02d}",
                    order=scene.scene_id,
                    location=scene.location,
                    narration=scene.narration,
                    narration_char_count=actual_chars,
                    visual_intent=scene.visual_hint,
                    emotion=_emotion_text(scene.emotion),
                    audio_cue=scene.audio_cue,
                    speed_tier=speed_tier,
                    speed_value=speed_value,
                    estimated_duration_seconds=calibrated_duration,
                )
            )
        return ScriptArtifact(
            version=version,
            title=provider_output.title,
            platform=provider_output.platform,
            aspect_ratio=aspect_ratio,
            total_duration_seconds=round(
                sum(segment.estimated_duration_seconds for segment in segments), 2
            ),
            hook=segments[0].narration,
            segments=segments,
            closing=segments[-1].narration,
            bgm_query=provider_output.bgm_suggestion,
        )

    def generate_storyboard(
        self,
        script: ScriptArtifact,
        aspect_ratio: AspectRatio,
        version: int,
        feedback: str | None,
        idempotency_key: str,
    ) -> StoryboardArtifact:
        provider_output = self._structured(
            _storyboard_prompt(script, aspect_ratio, feedback),
            "严格执行系统提示，只返回 JSON。",
            DifyStoryboardOutput,
            idempotency_key,
        )
        ordered_shots = sorted(provider_output.shots, key=lambda item: item.shot_id)
        if [item.shot_id for item in ordered_shots] != list(range(1, len(ordered_shots) + 1)):
            raise ProviderError("分镜 shot_id 不连续", retryable=True)
        segments_by_order = {segment.order: segment for segment in script.segments}
        unknown_scenes = {
            shot.belongs_to_scene
            for shot in ordered_shots
            if shot.belongs_to_scene not in segments_by_order
        }
        if unknown_scenes:
            raise ProviderError("分镜引用了不存在的剧本场景", retryable=True)
        shots: list[StoryboardShot] = []
        expected_orientation = "portrait" if aspect_ratio == AspectRatio.PORTRAIT else "landscape"
        for scene_order, segment in segments_by_order.items():
            scene_shots = [item for item in ordered_shots if item.belongs_to_scene == scene_order]
            if not scene_shots:
                raise ProviderError("剧本场景缺少分镜", retryable=True)
            if len(scene_shots) > 3:
                raise ProviderError("单个剧本场景超过 3 个镜头", retryable=True)
            raw_total = sum(item.estimated_duration for item in scene_shots)
            if raw_total <= 0:
                raise ProviderError("分镜场景时长无效", retryable=True)
            scene_cursor = 0.0
            for scene_index, provider_shot in enumerate(scene_shots):
                orientation_aliases = {
                    "portrait": {"portrait", "9:16", "vertical"},
                    "landscape": {"landscape", "16:9", "horizontal"},
                }
                if (
                    provider_shot.orientation.lower().strip()
                    not in orientation_aliases[expected_orientation]
                ):
                    raise ProviderError("分镜画幅与任务不一致", retryable=True)
                shot_type = {
                    "wide shot": "wide",
                    "medium shot": "medium",
                    "closeup": "close-up",
                    "close up": "close-up",
                }.get(provider_shot.shot_type.lower().strip(), provider_shot.shot_type.lower())
                transition = provider_shot.transition_in.lower()
                if shot_type not in {"wide", "medium", "close-up"}:
                    raise ProviderError("分镜景别不合法", retryable=True)
                if transition not in {"cut", "dissolve", "fade", "wipe"}:
                    raise ProviderError("分镜转场不合法", retryable=True)
                query_words = re.findall(r"[A-Za-z]+", provider_shot.search_query)
                if len(query_words) < 2:
                    query_words = _string_list(provider_shot.keywords_en)
                    query_words = [word for word in query_words if re.fullmatch(r"[A-Za-z]+", word)]
                if len(query_words) < 2:
                    raise ProviderError("Pexels 查询词必须包含 2~4 个英文词", retryable=True)
                material_query = " ".join(query_words[:4]).lower()
                if scene_index == len(scene_shots) - 1:
                    duration = round(segment.estimated_duration_seconds - scene_cursor, 2)
                else:
                    duration = round(
                        segment.estimated_duration_seconds
                        * provider_shot.estimated_duration
                        / raw_total,
                        2,
                    )
                    scene_cursor += duration
                narration = provider_shot.narration_segment.strip()
                if narration in {"（无）", "(无)", "无"}:
                    narration = segment.narration
                shots.append(
                    StoryboardShot(
                        id=f"shot-{provider_shot.shot_id:02d}",
                        segment_id=segment.id,
                        order=provider_shot.shot_id,
                        narration=narration,
                        visual_description=provider_shot.visual_description,
                        material_query=material_query,
                        keywords_en=_string_list(provider_shot.keywords_en),
                        keywords_cn=_string_list(provider_shot.keywords_cn),
                        shot_type=shot_type,
                        mood=provider_shot.mood,
                        transition_in=transition,
                        audio_note=provider_shot.audio_note,
                        orientation=aspect_ratio,
                        estimated_duration_seconds=max(0.01, duration),
                    )
                )
        shots.sort(key=lambda item: item.order)
        total_duration = round(sum(item.estimated_duration_seconds for item in shots), 2)
        if abs(total_duration - script.total_duration_seconds) > 0.05:
            raise ProviderError("分镜总时长与剧本不一致", retryable=False)
        return StoryboardArtifact(
            version=version,
            total_duration_seconds=total_duration,
            total_shots=len(shots),
            shots=shots,
        )


def _write_wave(path: Path, duration_seconds: float, frequency: float, amplitude: float) -> None:
    sample_rate = 16_000
    frame_count = max(1, round(duration_seconds * sample_rate))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        block = bytearray()
        for frame in range(frame_count):
            envelope = min(1.0, frame / 800, (frame_count - frame) / 800)
            value = int(
                32767
                * amplitude
                * envelope
                * math.sin(2 * math.pi * frequency * frame / sample_rate)
            )
            block.extend(struct.pack("<h", value))
            if len(block) >= 64 * 1024:
                output.writeframesraw(block)
                block.clear()
        if block:
            output.writeframesraw(block)


def _wave_duration_ms(path: Path) -> tuple[int, int]:
    with wave.open(str(path), "rb") as source:
        sample_rate = source.getframerate()
        duration_ms = round(source.getnframes() * 1000 / sample_rate)
    return duration_ms, sample_rate


class FakeTtsAdapter:
    name = "fake-tts"

    def __init__(self, store: ArtifactStore) -> None:
        self.store = store

    def synthesize(
        self,
        segment: ScriptSegment,
        voice_id: MimoVoiceId,
        output_path: Path,
        idempotency_key: str,
    ) -> AudioSegment:
        duration = max(
            0.8, _spoken_char_count(segment.narration) / MIMO_CALIBRATED_CHARS_PER_SECOND
        )
        _write_wave(output_path, duration, 180 + segment.order * 22, 0.035)
        duration_ms, sample_rate = _wave_duration_ms(output_path)
        return AudioSegment(
            segment_id=segment.id,
            relative_path=self.store.relative_path(output_path),
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            provider=self.name,
            voice_id=voice_id,
            checksum=self.store.checksum(output_path),
        )


class MimoTtsAdapter:
    name = "mimo-tts"

    def __init__(
        self,
        settings: Settings,
        store: ArtifactStore,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint = _completion_endpoint(settings.tts_base_url, "chat/completions")
        self.api_key = settings.tts_api_key
        self.model = settings.tts_name
        self.timeout = settings.tts_timeout_seconds
        self.retries = settings.provider_max_retries
        self.store = store
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        self.transport = transport

    def synthesize(
        self,
        segment: ScriptSegment,
        voice_id: MimoVoiceId,
        output_path: Path,
        idempotency_key: str,
    ) -> AudioSegment:
        source_path = output_path.with_suffix(".provider.mp3")

        def request() -> bytes:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.post(
                    self.endpoint,
                    headers={
                        "api-key": self.api_key,
                        "Idempotency-Key": _header_idempotency_key(idempotency_key),
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "user", "content": segment.emotion},
                            {"role": "assistant", "content": segment.narration},
                        ],
                        "audio": {"format": "mp3", "voice": voice_id.value},
                    },
                )
                if response.status_code in {408, 429} or response.status_code >= 500:
                    raise httpx.NetworkError("temporary provider response")
                if response.status_code >= 400:
                    raise ProviderError("配音请求被供应商拒绝", retryable=False)
                if len(response.content) > 20 * 1024 * 1024:
                    raise ProviderError("配音响应超过大小限制", retryable=False)
                try:
                    encoded = response.json()["choices"][0]["message"]["audio"]["data"]
                    if not isinstance(encoded, str) or len(encoded) > 28 * 1024 * 1024:
                        raise ValueError("invalid audio payload")
                    audio_bytes = base64.b64decode(encoded, validate=True)
                except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
                    raise ProviderError("MiMo 配音响应结构无效", retryable=False) from error
                if not audio_bytes or len(audio_bytes) > 20 * 1024 * 1024:
                    raise ProviderError("MiMo 配音音频大小无效", retryable=False)
                return audio_bytes

        audio_bytes = _retry(request, self.retries)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(audio_bytes)
        command = [
            self.ffmpeg,
            "-y",
            "-i",
            str(source_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
        _run_ffmpeg(command, timeout=120)
        source_path.unlink(missing_ok=True)
        duration_ms, sample_rate = _wave_duration_ms(output_path)
        return AudioSegment(
            segment_id=segment.id,
            relative_path=self.store.relative_path(output_path),
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            provider=self.name,
            voice_id=voice_id,
            checksum=self.store.checksum(output_path),
        )


class FakePexelsAdapter:
    name = "fake-pexels"

    def fetch(
        self,
        shot: StoryboardShot,
        aspect_ratio: AspectRatio,
        target_duration_ms: int,
        output_path: Path,
        idempotency_key: str,
    ) -> MaterialAsset:
        return MaterialAsset(
            shot_id=shot.id,
            provider=self.name,
            provider_id=f"fake-{shot.id}",
            author="Clip Agent deterministic fixture",
            license_name="Generated test asset",
            query=shot.material_query,
            matched_query=shot.material_query,
            original_duration_ms=target_duration_ms,
            target_duration_ms=target_duration_ms,
            trim_start_ms=0,
            trim_end_ms=target_duration_ms,
            loop_needed=False,
            width=1280 if aspect_ratio == AspectRatio.LANDSCAPE else 720,
            height=720 if aspect_ratio == AspectRatio.LANDSCAPE else 1280,
            score=100.0,
        )


def _build_pexels_queries(shot: StoryboardShot) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()

    def add(query: str) -> None:
        normalized = " ".join(query.lower().strip().split())
        if normalized and normalized not in seen:
            queries.append(normalized)
            seen.add(normalized)

    add(shot.material_query)
    words = [word.strip(" ,") for word in shot.keywords_en if word.strip(" ,")]
    if len(words) >= 3:
        add(" ".join(words[:3]))
    if len(words) >= 2:
        add(" ".join(words[:2]))

    description_map = {
        "地铁": "subway",
        "车厢": "train interior",
        "街道": "city street",
        "咖啡": "coffee shop",
        "办公": "office",
        "雨": "rain",
        "夜": "night city",
        "海": "ocean",
        "山": "mountain",
        "森林": "forest",
        "天空": "sky",
        "人群": "crowd people",
        "桥": "bridge",
        "厨房": "kitchen",
        "日出": "sunrise",
        "日落": "sunset",
        "雪": "snow",
    }
    for chinese, english in description_map.items():
        if chinese in shot.visual_description:
            add(english)
    if words:
        add(words[0])
        shot_prefix = {"wide": "wide shot", "close-up": "close up"}.get(shot.shot_type, "")
        if shot_prefix:
            add(f"{shot_prefix} {words[0]}")
    add("cinematic background")
    add("nature landscape")
    return queries


def _score_pexels_video(video: dict[str, Any], target_duration_ms: int, orientation: str) -> float:
    target_seconds = max(0.1, target_duration_ms / 1000)
    duration = float(video.get("duration") or 10)
    ratio = duration / target_seconds
    if 0.8 <= ratio <= 1.5:
        score = 25.0
    elif 0.5 <= ratio < 0.8:
        score = 15.0
    elif 1.5 < ratio <= 3.0:
        score = 18.0
    elif ratio > 3.0:
        score = 8.0
    else:
        score = 5.0

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    orientation_matches = (orientation == "portrait" and height > width) or (
        orientation == "landscape" and width > height
    )
    score += 20 if orientation_matches else 3

    files = video.get("video_files") or []
    best_width = max((int(item.get("width") or 0) for item in files), default=0)
    has_hd = any(item.get("quality") == "hd" for item in files)
    if has_hd and best_width >= 1920:
        score += 10
    elif has_hd and best_width >= 1080:
        score += 8
    elif has_hd:
        score += 5
    else:
        score += 2
    score += float(video.get("_rank") or 0)
    return round(score, 1)


def _pick_pexels_file(files: list[dict[str, Any]], orientation: str) -> dict[str, Any] | None:
    def file_score(item: dict[str, Any]) -> float:
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        target_width, target_height = (720, 1280) if orientation == "portrait" else (1280, 720)
        score = 100 if item.get("quality") == "hd" else 0
        orientation_matches = (orientation == "portrait" and height > width) or (
            orientation == "landscape" and width > height
        )
        if orientation_matches:
            score += 50
        if width >= target_width and height >= target_height:
            excess = (width - target_width) + (height - target_height)
            score += 200 - min(excess / 100, 80)
        else:
            scale = min(width / target_width, height / target_height)
            score += max(0, scale) * 100
        return score

    candidates = [item for item in files if item.get("link")]
    return max(candidates, key=file_score) if candidates else None


def _calculate_trim(original_duration_ms: int, target_duration_ms: int) -> tuple[int, int, bool]:
    if original_duration_ms <= 0:
        original_duration_ms = target_duration_ms
    if original_duration_ms < target_duration_ms:
        return 0, original_duration_ms, True
    if original_duration_ms > round(target_duration_ms * 1.8):
        trim_start = round((original_duration_ms - target_duration_ms) * 0.35)
        return trim_start, trim_start + target_duration_ms, False
    return 0, target_duration_ms, False


class PexelsAdapter:
    name = "pexels"

    def __init__(
        self,
        settings: Settings,
        store: ArtifactStore,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = settings.pexels_base_url.rstrip("/") + "/"
        self.api_key = settings.pexels_api_key
        self.timeout = settings.pexels_timeout_seconds
        self.retries = settings.provider_max_retries
        self.max_bytes = settings.max_download_bytes
        self.max_queries = settings.pexels_max_queries
        self.per_page = settings.pexels_per_page
        self.store = store
        self.allowed_api_hosts = {"api.pexels.com"}
        self.allowed_media_hosts = {"videos.pexels.com", "player.vimeo.com"}
        self.transport = transport

    def fetch(
        self,
        shot: StoryboardShot,
        aspect_ratio: AspectRatio,
        target_duration_ms: int,
        output_path: Path,
        idempotency_key: str,
    ) -> MaterialAsset:
        endpoint = _completion_endpoint(self.base_url, "videos/search")
        validate_https_url(endpoint, self.allowed_api_hosts)
        orientation = "landscape" if aspect_ratio == AspectRatio.LANDSCAPE else "portrait"

        queries = _build_pexels_queries(shot)[: self.max_queries]
        all_videos: list[dict[str, Any]] = []
        seen: set[str] = set()
        last_retryable_error: ProviderError | None = None
        base_ranks = [50, 38, 28, 20, 14, 10]
        with httpx.Client(timeout=self.timeout, transport=self.transport) as search_client:

            def search(query: str) -> dict[str, Any]:
                response = search_client.get(
                    endpoint,
                    headers={
                        "Authorization": self.api_key,
                        "Idempotency-Key": _header_idempotency_key(idempotency_key),
                    },
                    params={
                        "query": query,
                        "orientation": orientation,
                        "per_page": self.per_page,
                        "page": 1,
                        "size": "medium",
                    },
                )
                if response.status_code in {408, 429} or response.status_code >= 500:
                    raise httpx.NetworkError("temporary Pexels response")
                if response.status_code >= 400:
                    raise ProviderError("Pexels 请求被拒绝", retryable=False)
                if len(response.content) > 2 * 1024 * 1024:
                    raise ProviderError("Pexels 搜索响应超过大小限制", retryable=False)
                return response.json()

            for query_level, query in enumerate(queries):
                try:
                    payload = _retry(lambda query=query: search(query), self.retries)
                except ProviderError as error:
                    if not error.retryable:
                        raise
                    last_retryable_error = error
                    continue
                found_in_layer = 0
                for rank, video in enumerate(payload.get("videos", [])):
                    provider_id = str(video.get("id", ""))
                    if not provider_id or provider_id in seen:
                        continue
                    if _pick_pexels_file(video.get("video_files", []), orientation) is None:
                        continue
                    candidate = dict(video)
                    candidate["_rank"] = max(0, base_ranks[query_level] - rank * 2)
                    candidate["_query_level"] = query_level
                    candidate["_matched_query"] = query
                    candidate["_score"] = _score_pexels_video(
                        candidate, target_duration_ms, orientation
                    )
                    all_videos.append(candidate)
                    seen.add(provider_id)
                    found_in_layer += 1
                # Later query layers are fallbacks, not mandatory extra calls. Once a
                # layer has usable candidates, preserve relevance and stop searching.
                if found_in_layer:
                    break
        if not all_videos:
            if last_retryable_error:
                raise last_retryable_error
            raise ProviderError("Pexels 未找到匹配素材", retryable=False)
        selected = max(all_videos, key=lambda item: float(item["_score"]))
        selected_file = _pick_pexels_file(selected.get("video_files", []), orientation)
        if not selected_file:
            raise ProviderError("Pexels 素材没有可下载文件", retryable=False)
        source_url = str(selected_file.get("link", ""))
        self._download(source_url, output_path)
        user = selected.get("user") or {}
        original_duration_ms = round(float(selected.get("duration") or 0) * 1000)
        if original_duration_ms <= 0:
            original_duration_ms = target_duration_ms
        trim_start_ms, trim_end_ms, loop_needed = _calculate_trim(
            original_duration_ms, target_duration_ms
        )
        return MaterialAsset(
            shot_id=shot.id,
            provider=self.name,
            provider_id=str(selected.get("id", "unknown")),
            source_url=source_url,
            relative_path=self.store.relative_path(output_path),
            author=str(user.get("name", "Pexels contributor")),
            license_name="Pexels License",
            query=shot.material_query,
            matched_query=str(selected["_matched_query"]),
            original_duration_ms=original_duration_ms,
            target_duration_ms=target_duration_ms,
            trim_start_ms=trim_start_ms,
            trim_end_ms=trim_end_ms,
            loop_needed=loop_needed,
            width=int(selected_file.get("width") or selected.get("width") or 0),
            height=int(selected_file.get("height") or selected.get("height") or 0),
            score=float(selected["_score"]),
        )

    def _download(self, initial_url: str, output_path: Path) -> None:
        current_url = validate_https_url(initial_url, self.allowed_media_hosts)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(
            timeout=self.timeout, follow_redirects=False, transport=self.transport
        ) as client:
            for _ in range(4):
                with client.stream("GET", current_url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ProviderError("素材重定向缺少目标", retryable=False)
                        current_url = validate_https_url(
                            urljoin(current_url, location), self.allowed_media_hosts
                        )
                        continue
                    if response.status_code >= 500:
                        raise ProviderError("素材下载暂时失败", retryable=True)
                    if response.status_code >= 400:
                        raise ProviderError("素材下载失败", retryable=False)
                    content_type = response.headers.get("content-type", "").lower()
                    if not (content_type.startswith("video/") or "octet-stream" in content_type):
                        raise ProviderError("素材响应类型不是视频", retryable=False)
                    size = 0
                    with output_path.open("wb") as destination:
                        for chunk in response.iter_bytes(64 * 1024):
                            size += len(chunk)
                            if size > self.max_bytes:
                                destination.close()
                                output_path.unlink(missing_ok=True)
                                raise ProviderError("素材超过下载大小限制", retryable=False)
                            destination.write(chunk)
                    return
        raise ProviderError("素材重定向次数过多", retryable=False)


def _run_ffmpeg(command: list[str], timeout: int = 300) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
            shell=False,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ProviderError("本地媒体处理失败", retryable=True) from error


def _subtitle_filter(path: Path, aspect_ratio: AspectRatio) -> str:
    escaped_path = path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
    font_size = 22 if aspect_ratio == AspectRatio.PORTRAIT else 20
    margin = 56 if aspect_ratio == AspectRatio.PORTRAIT else 36
    style = (
        f"FontName=Microsoft YaHei,FontSize={font_size},"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        f"BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV={margin}"
    )
    return f"subtitles=filename='{escaped_path}':charenc=UTF-8:force_style='{style}'"


def _concat_wav(paths: list[Path], output_path: Path) -> None:
    if not paths:
        raise ProviderError("没有可合并的配音片段", retryable=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(paths[0]), "rb") as first:
        parameters = first.getparams()
        audio_format = (
            first.getnchannels(),
            first.getsampwidth(),
            first.getframerate(),
            first.getcomptype(),
            first.getcompname(),
        )
    with wave.open(str(output_path), "wb") as destination:
        destination.setparams(parameters)
        for path in paths:
            with wave.open(str(path), "rb") as source:
                source_format = (
                    source.getnchannels(),
                    source.getsampwidth(),
                    source.getframerate(),
                    source.getcomptype(),
                    source.getcompname(),
                )
                if source_format != audio_format:
                    raise ProviderError("配音片段采样参数不一致", retryable=False)
                destination.writeframes(source.readframes(source.getnframes()))


class FfmpegRenderer:
    name = "ffmpeg"

    def __init__(self, settings: Settings) -> None:
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        self.bgm_library_dir = settings.bgm_library_dir
        self.bgm_catalog = BgmCatalog(settings.bgm_library_dir)
        self.media_root = settings.media_root

    def render_preview(
        self,
        *,
        audio_segments: list[AudioSegment],
        timeline: list[TimelineItem],
        materials: list[MaterialAsset],
        subtitle: SubtitleArtifact,
        aspect_ratio: AspectRatio,
        output_path: Path,
        store: ArtifactStore,
    ) -> VideoArtifact:
        width, height = (1280, 720) if aspect_ratio == AspectRatio.LANDSCAPE else (720, 1280)
        work_dir = output_path.parent / "render-work"
        work_dir.mkdir(parents=True, exist_ok=True)
        narration_path = work_dir / "narration.wav"
        _concat_wav(
            [store.media_root / segment.relative_path for segment in audio_segments], narration_path
        )
        materials_by_shot = {item.shot_id: item for item in materials}
        palette = ["162033", "183b4e", "2b3252", "263f3a", "48324a", "3f3525"]

        def render_clip(indexed_item: tuple[int, TimelineItem]) -> Path:
            index, item = indexed_item
            clip_path = work_dir / f"clip-{index + 1:03d}.mp4"
            duration = max(0.04, (item.end_ms - item.start_ms) / 1000)
            frame_count = max(1, math.ceil(duration * 24))
            frame_duration = frame_count / 24
            material = materials_by_shot.get(item.shot_id)
            source_path = (
                store.media_root / material.relative_path
                if material and material.relative_path
                else None
            )
            if source_path and source_path.exists():
                command = [
                    self.ffmpeg,
                    "-y",
                ]
                if material and material.loop_needed:
                    command.extend(["-stream_loop", "-1"])
                if material and material.trim_start_ms:
                    command.extend(["-ss", f"{material.trim_start_ms / 1000:.3f}"])
                command.extend(
                    [
                        "-i",
                        str(source_path),
                        "-vf",
                        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                        f"crop={width}:{height},fps=24,format=yuv420p",
                        "-an",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "23",
                        "-threads",
                        "1",
                        "-frames:v",
                        str(frame_count),
                        str(clip_path),
                    ]
                )
            else:
                command = [
                    self.ffmpeg,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=0x{palette[index % len(palette)]}:s={width}x{height}:r=24:d={frame_duration:.6f}",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-threads",
                    "1",
                    "-frames:v",
                    str(frame_count),
                    "-pix_fmt",
                    "yuv420p",
                    str(clip_path),
                ]
            _run_ffmpeg(command)
            return clip_path

        with ThreadPoolExecutor(max_workers=min(4, len(timeline))) as executor:
            clip_paths = list(executor.map(render_clip, enumerate(timeline)))

        concat_manifest = work_dir / "clips.txt"
        manifest_lines = [
            f"file '{path.as_posix().replace(chr(39), chr(39) * 2)}'" for path in clip_paths
        ]
        concat_manifest.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
        visual_path = work_dir / "visual.mp4"
        _run_ffmpeg(
            [
                self.ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_manifest),
                "-c",
                "copy",
                str(visual_path),
            ]
        )
        subtitle_path = store.media_root / subtitle.relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _run_ffmpeg(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(visual_path),
                "-i",
                str(narration_path),
                "-i",
                str(subtitle_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-map",
                "2:0",
                "-vf",
                _subtitle_filter(subtitle_path, aspect_ratio),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "21",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-c:s",
                "mov_text",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        duration_ms = timeline[-1].end_ms
        return VideoArtifact(
            relative_path=store.relative_path(output_path),
            duration_ms=duration_ms,
            checksum=store.checksum(output_path),
            has_bgm=False,
        )

    def fetch_bgm(
        self,
        selection: BgmSelection,
        duration_ms: int,
        output_path: Path,
        store: ArtifactStore,
    ) -> BgmArtifact:
        if selection.source == "library":
            track = self.bgm_catalog.resolve(selection.track_id)
            selected = track.path
        else:
            selected = store.resolve_registered_path(
                output_path.parents[1].parent.name,
                output_path.parents[1].name,
                selection.uploaded_relative_path or "",
            )
        _run_ffmpeg(
            [
                self.ffmpeg,
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(selected),
                "-t",
                f"{duration_ms / 1000:.3f}",
                "-ac",
                "2",
                "-ar",
                "44100",
                str(output_path),
            ]
        )
        checksum = _checksum(output_path)
        relative = output_path.resolve().relative_to(self.media_root.resolve()).as_posix()
        return BgmArtifact(
            relative_path=relative,
            duration_ms=duration_ms,
            checksum=checksum,
            source=f"{selection.source}:{selection.name}",
        )

    def mix_bgm(
        self,
        preview: VideoArtifact,
        bgm: BgmArtifact,
        volume: float,
        output_path: Path,
        store: ArtifactStore,
    ) -> VideoArtifact:
        preview_path = store.media_root / preview.relative_path
        bgm_path = store.media_root / bgm.relative_path
        fade_out_start = max(0, preview.duration_ms / 1000 - 1.2)
        _run_ffmpeg(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(preview_path),
                "-i",
                str(bgm_path),
                "-filter_complex",
                f"[1:a]volume={volume:.3f},afade=t=in:st=0:d=0.8,"
                f"afade=t=out:st={fade_out_start:.3f}:d=1.2[bgm];"
                "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0,alimiter=limit=0.95[mixed]",
                "-map",
                "0:v:0",
                "-map",
                "[mixed]",
                "-map",
                "0:s?",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-c:s",
                "copy",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        return VideoArtifact(
            relative_path=store.relative_path(output_path),
            duration_ms=preview.duration_ms,
            checksum=store.checksum(output_path),
            has_bgm=True,
        )


def _checksum(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_adapters(
    settings: Settings, store: ArtifactStore
) -> tuple[LlmAdapter, TtsAdapter, MaterialAdapter, RendererAdapter]:
    renderer = FfmpegRenderer(settings)
    if settings.provider_mode == "real":
        return (
            OpenAICompatibleLlmAdapter(settings),
            MimoTtsAdapter(settings, store),
            PexelsAdapter(settings, store),
            renderer,
        )
    return FakeLlmAdapter(), FakeTtsAdapter(store), FakePexelsAdapter(), renderer
