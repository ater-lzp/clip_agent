from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from functools import wraps
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from backend.domain.models import (
    AspectRatio,
    AudioSegment,
    BgmAction,
    BgmSelection,
    MaterialAsset,
    MimoVoiceId,
    ReviewAction,
    ScriptArtifact,
    StoryboardArtifact,
    SubtitleArtifact,
    TaskStatus,
    TimelineItem,
    VideoArtifact,
)
from backend.infrastructure.adapters import (
    LlmAdapter,
    MaterialAdapter,
    RendererAdapter,
    TtsAdapter,
)
from backend.infrastructure.storage import ArtifactStore
from backend.workflow.state import GraphState

LOGGER = logging.getLogger(__name__)


class WorkflowValidationError(RuntimeError):
    pass


class ProgressObserver(Protocol):
    def __call__(self, task_id: str, status: TaskStatus) -> None: ...


def _srt_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _split_subtitle(text: str, max_chars: int = 18) -> list[str]:
    parts = re.findall(r"[^，。！？；、：,.!?;:]+[，。！？；、：,.!?;:]*", text.strip())
    lines: list[str] = []
    current = ""
    for part in parts:
        remaining = part.strip()
        while remaining:
            available = max_chars - len(current)
            if len(remaining) <= available:
                current += remaining
                remaining = ""
            elif current:
                lines.append(current)
                current = ""
            else:
                split_at = max_chars
                while split_at < len(remaining) and remaining[split_at] in "，。！？；、：,.!?;:":
                    split_at += 1
                lines.append(remaining[:split_at])
                remaining = remaining[split_at:]
        if current.endswith(tuple("。！？；.!?;")):
            lines.append(current)
            current = ""
    if current.strip():
        lines.append(current.strip())
    return lines or ([text.strip()] if text.strip() else [])


def _spoken_narration_text(text: str) -> str:
    return re.sub(r"^(?:[（(][^）)]{1,40}[）)]\s*)+", "", text.strip()).strip()


def _narration_char_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", _spoken_narration_text(text)))


class WorkflowNodes:
    def __init__(
        self,
        *,
        llm: LlmAdapter,
        tts: TtsAdapter,
        materials: MaterialAdapter,
        renderer: RendererAdapter,
        store: ArtifactStore,
        progress: ProgressObserver,
    ) -> None:
        self.llm = llm
        self.tts = tts
        self.materials = materials
        self.renderer = renderer
        self.store = store
        self.progress = progress

    def _status(self, state: GraphState, status: TaskStatus) -> None:
        self.progress(state["task_id"], status)

    def _manifest(self, state: GraphState, filename: str) -> Path:
        return self.store.artifact_path(state["user_id"], state["task_id"], "manifests", filename)

    def generate_script(self, state: GraphState) -> dict[str, Any]:
        self._status(state, TaskStatus.GENERATING_SCRIPT)
        version = int(state.get("script_version", 0)) + 1
        manifest = self._manifest(state, f"script-v{version}.json")
        saved = self.store.load_json(manifest)
        script: ScriptArtifact | None = None
        if saved:
            with suppress(ValidationError):
                script = ScriptArtifact.model_validate(saved)
        if script is None:
            script = self.llm.generate_script(
                state["topic"],
                state["target_duration_seconds"],
                AspectRatio(state["aspect_ratio"]),
                version,
                state.get("script_feedback"),
                f"{state['task_id']}:generate-script:v{version}",
            )
            self.store.save_json_atomic(manifest, script.model_dump(mode="json"))
        return {
            "script": script.model_dump(mode="json"),
            "script_version": version,
            "status": TaskStatus.AWAITING_SCRIPT_REVIEW.value,
            "current_stage": TaskStatus.AWAITING_SCRIPT_REVIEW.value,
            "error": None,
        }

    def review_script(self, state: GraphState) -> dict[str, Any]:
        script = ScriptArtifact.model_validate(state["script"])
        decision = interrupt(
            {
                "kind": "script",
                "version": script.version,
                "allowed_actions": [ReviewAction.APPROVE.value, ReviewAction.REJECT.value],
                "script": script.model_dump(mode="json"),
            }
        )
        if not isinstance(decision, dict) or decision.get("kind") != "script":
            raise WorkflowValidationError("invalid script review resume payload")
        if decision.get("version") != script.version:
            raise WorkflowValidationError("script review version mismatch")
        action = ReviewAction(decision.get("action"))
        feedback = decision.get("feedback")
        if action == ReviewAction.REJECT and (
            not isinstance(feedback, str) or not feedback.strip()
        ):
            raise WorkflowValidationError("script rejection feedback is required")
        return {
            "script_feedback": feedback.strip() if action == ReviewAction.REJECT else None,
            "review_history": [decision],
            "status": (
                TaskStatus.GENERATING_SCRIPT.value
                if action == ReviewAction.REJECT
                else TaskStatus.GENERATING_STORYBOARD.value
            ),
            "current_stage": (
                TaskStatus.GENERATING_SCRIPT.value
                if action == ReviewAction.REJECT
                else TaskStatus.GENERATING_STORYBOARD.value
            ),
        }

    @staticmethod
    def route_script_review(state: GraphState) -> str:
        return "reject" if state.get("script_feedback") else "approve"

    def parse_script(self, state: GraphState) -> dict[str, Any]:
        script = ScriptArtifact.model_validate(state["script"])
        if script.aspect_ratio != AspectRatio(state["aspect_ratio"]):
            raise WorkflowValidationError("script aspect ratio does not match task")
        for segment in script.segments:
            actual_chars = _narration_char_count(segment.narration)
            if actual_chars != segment.narration_char_count:
                raise WorkflowValidationError("script narration character count is incorrect")
            if segment.speed_value is None or segment.speed_tier is None:
                raise WorkflowValidationError("script segment is missing speed metadata")
            expected_range = {
                "慢速": (3.0, 4.0),
                "中速": (4.0, 5.0),
                "快速": (5.0, 8.0),
            }[segment.speed_tier]
            if not expected_range[0] <= segment.speed_value <= expected_range[1]:
                raise WorkflowValidationError("script speed tier and value are inconsistent")
            calculated_duration = actual_chars / segment.speed_value
            if abs(calculated_duration - segment.estimated_duration_seconds) > 0.15:
                raise WorkflowValidationError("script duration formula is inconsistent")
        estimated_ms = round(
            sum(segment.estimated_duration_seconds for segment in script.segments) * 1000
        )
        if estimated_ms <= 0:
            raise WorkflowValidationError("script has no positive duration")
        return {
            "parsed_script": {
                "segment_ids": [segment.id for segment in script.segments],
                "estimated_duration_ms": estimated_ms,
            },
            "bgm_query": script.bgm_query,
            "status": TaskStatus.GENERATING_STORYBOARD.value,
            "current_stage": TaskStatus.GENERATING_STORYBOARD.value,
        }

    def generate_storyboard(self, state: GraphState) -> dict[str, Any]:
        self._status(state, TaskStatus.GENERATING_STORYBOARD)
        version = int(state.get("storyboard_version", 0)) + 1
        manifest = self._manifest(state, f"storyboard-v{version}.json")
        saved = self.store.load_json(manifest)
        storyboard: StoryboardArtifact | None = None
        if saved:
            with suppress(ValidationError):
                storyboard = StoryboardArtifact.model_validate(saved)
        if storyboard is None:
            storyboard = self.llm.generate_storyboard(
                ScriptArtifact.model_validate(state["script"]),
                AspectRatio(state["aspect_ratio"]),
                version,
                state.get("storyboard_feedback"),
                f"{state['task_id']}:generate-storyboard:v{version}",
            )
            self.store.save_json_atomic(manifest, storyboard.model_dump(mode="json"))
        return {
            "storyboard": storyboard.model_dump(mode="json"),
            "storyboard_version": version,
            "status": TaskStatus.AWAITING_STORYBOARD_REVIEW.value,
            "current_stage": TaskStatus.AWAITING_STORYBOARD_REVIEW.value,
        }

    def review_storyboard(self, state: GraphState) -> dict[str, Any]:
        storyboard = StoryboardArtifact.model_validate(state["storyboard"])
        decision = interrupt(
            {
                "kind": "storyboard",
                "version": storyboard.version,
                "allowed_actions": [ReviewAction.APPROVE.value, ReviewAction.REJECT.value],
                "storyboard": storyboard.model_dump(mode="json"),
            }
        )
        if not isinstance(decision, dict) or decision.get("kind") != "storyboard":
            raise WorkflowValidationError("invalid storyboard review resume payload")
        if decision.get("version") != storyboard.version:
            raise WorkflowValidationError("storyboard review version mismatch")
        action = ReviewAction(decision.get("action"))
        feedback = decision.get("feedback")
        if action == ReviewAction.REJECT and (
            not isinstance(feedback, str) or not feedback.strip()
        ):
            raise WorkflowValidationError("storyboard rejection feedback is required")
        return {
            "storyboard_feedback": feedback.strip() if action == ReviewAction.REJECT else None,
            "review_history": [decision],
            "status": (
                TaskStatus.GENERATING_STORYBOARD.value
                if action == ReviewAction.REJECT
                else TaskStatus.SYNTHESIZING_AUDIO.value
            ),
            "current_stage": (
                TaskStatus.GENERATING_STORYBOARD.value
                if action == ReviewAction.REJECT
                else TaskStatus.SYNTHESIZING_AUDIO.value
            ),
        }

    @staticmethod
    def route_storyboard_review(state: GraphState) -> str:
        return "reject" if state.get("storyboard_feedback") else "approve"

    def parse_storyboard(self, state: GraphState) -> dict[str, Any]:
        storyboard = StoryboardArtifact.model_validate(state["storyboard"])
        script = ScriptArtifact.model_validate(state["script"])
        segment_ids = {segment.id for segment in script.segments}
        missing = [
            shot.segment_id for shot in storyboard.shots if shot.segment_id not in segment_ids
        ]
        if missing:
            raise WorkflowValidationError("storyboard references unknown script segments")
        if storyboard.total_shots != len(storyboard.shots):
            raise WorkflowValidationError("storyboard shot count is inconsistent")
        if abs(storyboard.total_duration_seconds - script.total_duration_seconds) > 0.05:
            raise WorkflowValidationError("storyboard duration does not match script")
        for segment in script.segments:
            segment_shots = [shot for shot in storyboard.shots if shot.segment_id == segment.id]
            if not 1 <= len(segment_shots) <= 3:
                raise WorkflowValidationError("script segment must have one to three shots")
            if any(
                shot.orientation != AspectRatio(state["aspect_ratio"]) for shot in segment_shots
            ):
                raise WorkflowValidationError("storyboard shot aspect ratio does not match task")
            shot_duration = sum(shot.estimated_duration_seconds for shot in segment_shots)
            if abs(shot_duration - segment.estimated_duration_seconds) > 0.05:
                raise WorkflowValidationError("storyboard segment duration is inconsistent")
        return {
            "parsed_storyboard": {
                "shot_ids": [shot.id for shot in storyboard.shots],
                "segment_ids": sorted(segment_ids),
            },
            "status": TaskStatus.SYNTHESIZING_AUDIO.value,
            "current_stage": TaskStatus.SYNTHESIZING_AUDIO.value,
        }

    def synthesize_tts(self, state: GraphState) -> dict[str, Any]:
        self._status(state, TaskStatus.SYNTHESIZING_AUDIO)
        script = ScriptArtifact.model_validate(state["script"])

        def synthesize_one(segment: Any) -> AudioSegment:
            manifest = self._manifest(state, f"tts-v{script.version}-{segment.id}.json")
            audio_path = self.store.artifact_path(
                state["user_id"],
                state["task_id"],
                "audio",
                f"{segment.id}-v{script.version}.wav",
            )
            saved = self.store.load_json(manifest)
            if saved and audio_path.exists():
                try:
                    audio = AudioSegment.model_validate(saved)
                except ValidationError:
                    saved = None
                else:
                    if self.store.checksum(audio_path) != audio.checksum:
                        saved = None
            if not saved:
                audio = self.tts.synthesize(
                    segment,
                    MimoVoiceId(state["voice_id"]),
                    audio_path,
                    f"{state['task_id']}:tts:v{script.version}:{segment.id}:{state['voice_id']}",
                )
                self.store.save_json_atomic(manifest, audio.model_dump(mode="json"))
            return audio

        with ThreadPoolExecutor(max_workers=min(5, len(script.segments))) as executor:
            audio_segments = list(executor.map(synthesize_one, script.segments))
        if any(item.duration_ms <= 0 for item in audio_segments):
            raise WorkflowValidationError("synthesized audio duration is invalid")
        self._status(state, TaskStatus.BUILDING_TIMELINE)
        return {
            "audio_segments": [item.model_dump(mode="json") for item in audio_segments],
            "status": TaskStatus.BUILDING_TIMELINE.value,
            "current_stage": TaskStatus.BUILDING_TIMELINE.value,
        }

    def build_timeline(self, state: GraphState) -> dict[str, Any]:
        self._status(state, TaskStatus.BUILDING_TIMELINE)
        storyboard = StoryboardArtifact.model_validate(state["storyboard"])
        audio_segments = [AudioSegment.model_validate(item) for item in state["audio_segments"]]
        shots_by_segment: dict[str, list[Any]] = {}
        for shot in storyboard.shots:
            shots_by_segment.setdefault(shot.segment_id, []).append(shot)
        timeline: list[TimelineItem] = []
        cursor = 0
        for audio in audio_segments:
            shots = shots_by_segment.get(audio.segment_id, [])
            if not shots:
                raise WorkflowValidationError("audio segment has no storyboard shot")
            total_weight = sum(shot.estimated_duration_seconds for shot in shots)
            segment_end = cursor + audio.duration_ms
            for index, shot in enumerate(shots):
                if index == len(shots) - 1:
                    end = segment_end
                else:
                    share = round(
                        audio.duration_ms * shot.estimated_duration_seconds / total_weight
                    )
                    end = min(segment_end, cursor + max(1, share))
                timeline.append(
                    TimelineItem(
                        shot_id=shot.id,
                        segment_id=shot.segment_id,
                        start_ms=cursor,
                        end_ms=end,
                        narration=shot.narration,
                    )
                )
                cursor = end
        if cursor != sum(item.duration_ms for item in audio_segments):
            raise WorkflowValidationError("timeline duration does not match synthesized audio")
        self._status(state, TaskStatus.FETCHING_ASSETS)
        return {
            "timeline": [item.model_dump(mode="json") for item in timeline],
            "status": TaskStatus.FETCHING_ASSETS.value,
            "current_stage": TaskStatus.FETCHING_ASSETS.value,
        }

    def fetch_materials(self, state: GraphState) -> dict[str, Any]:
        self._status(state, TaskStatus.FETCHING_ASSETS)
        storyboard = StoryboardArtifact.model_validate(state["storyboard"])
        timeline_by_shot = {
            item.shot_id: item
            for item in (TimelineItem.model_validate(raw) for raw in state["timeline"])
        }

        def fetch_one(shot: Any) -> MaterialAsset:
            timeline_item = timeline_by_shot.get(shot.id)
            if timeline_item is None:
                raise WorkflowValidationError("storyboard shot has no timeline interval")
            target_duration_ms = timeline_item.end_ms - timeline_item.start_ms
            manifest = self._manifest(state, f"material-v{storyboard.version}-{shot.id}.json")
            saved = self.store.load_json(manifest)
            if saved:
                try:
                    asset = MaterialAsset.model_validate(saved)
                except ValidationError:
                    saved = None
                else:
                    if (
                        asset.relative_path
                        and not (self.store.media_root / asset.relative_path).exists()
                    ):
                        saved = None
                    if asset.target_duration_ms != target_duration_ms:
                        saved = None
            if not saved:
                output_path = self.store.artifact_path(
                    state["user_id"],
                    state["task_id"],
                    "materials",
                    f"{shot.id}.mp4",
                )
                asset = self.materials.fetch(
                    shot,
                    AspectRatio(state["aspect_ratio"]),
                    target_duration_ms,
                    output_path,
                    f"{state['task_id']}:material:v{storyboard.version}:{shot.id}",
                )
                self.store.save_json_atomic(manifest, asset.model_dump(mode="json"))
            return asset

        with ThreadPoolExecutor(max_workers=min(5, len(storyboard.shots))) as executor:
            assets = list(executor.map(fetch_one, storyboard.shots))
        return {"materials": [asset.model_dump(mode="json") for asset in assets]}

    def generate_srt(self, state: GraphState) -> dict[str, Any]:
        self._status(state, TaskStatus.FETCHING_ASSETS)
        timeline = [TimelineItem.model_validate(item) for item in state["timeline"]]
        script = ScriptArtifact.model_validate(state["script"])
        manifest = self._manifest(state, f"subtitle-v{script.version}.json")
        subtitle_path = self.store.artifact_path(
            state["user_id"], state["task_id"], "subtitles", "captions.srt"
        )
        saved = self.store.load_json(manifest)
        if saved and subtitle_path.exists():
            try:
                subtitle = SubtitleArtifact.model_validate(saved)
            except ValidationError:
                saved = None
            else:
                if self.store.checksum(subtitle_path) != subtitle.checksum:
                    saved = None
        if not saved:
            cues: list[tuple[int, int, str]] = []
            for segment in script.segments:
                segment_items = [item for item in timeline if item.segment_id == segment.id]
                if not segment_items:
                    raise WorkflowValidationError("script segment has no timeline interval")
                segment_start = segment_items[0].start_ms
                segment_end = segment_items[-1].end_ms
                lines = _split_subtitle(_spoken_narration_text(segment.narration))
                total_chars = sum(max(1, len(line)) for line in lines)
                cursor = segment_start
                consumed_chars = 0
                for index, line in enumerate(lines):
                    consumed_chars += max(1, len(line))
                    if index == len(lines) - 1:
                        end_ms = segment_end
                    else:
                        end_ms = segment_start + round(
                            (segment_end - segment_start) * consumed_chars / total_chars
                        )
                        end_ms = min(segment_end, max(cursor + 1, end_ms))
                    if end_ms <= cursor:
                        raise WorkflowValidationError("subtitle cue duration is not positive")
                    cues.append((cursor, end_ms, line))
                    cursor = end_ms
            blocks = [
                f"{index}\n{_srt_timestamp(start_ms)} --> {_srt_timestamp(end_ms)}\n{text}\n"
                for index, (start_ms, end_ms, text) in enumerate(cues, start=1)
            ]
            subtitle_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".captions-", suffix=".srt", dir=subtitle_path.parent
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as temporary:
                    temporary.write("\n".join(blocks))
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_name, subtitle_path)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
            subtitle = SubtitleArtifact(
                relative_path=self.store.relative_path(subtitle_path),
                cue_count=len(cues),
                duration_ms=timeline[-1].end_ms,
                checksum=self.store.checksum(subtitle_path),
            )
            self.store.save_json_atomic(manifest, subtitle.model_dump(mode="json"))
        return {"subtitle": subtitle.model_dump(mode="json")}

    def align(self, state: GraphState) -> dict[str, Any]:
        self._status(state, TaskStatus.ALIGNING_TIMELINE)
        timeline = [TimelineItem.model_validate(item) for item in state["timeline"]]
        materials = [MaterialAsset.model_validate(item) for item in state["materials"]]
        subtitle = SubtitleArtifact.model_validate(state["subtitle"])
        if not timeline or timeline[0].start_ms != 0:
            raise WorkflowValidationError("timeline must start at zero")
        for previous, current in pairwise(timeline):
            if previous.end_ms != current.start_ms:
                raise WorkflowValidationError("timeline contains a gap or overlap")
        if {item.shot_id for item in timeline} != {item.shot_id for item in materials}:
            raise WorkflowValidationError("materials do not cover every shot")
        script = ScriptArtifact.model_validate(state["script"])
        if subtitle.cue_count < len(script.segments):
            raise WorkflowValidationError("subtitle cues do not cover every script segment")
        audio_total = sum(
            AudioSegment.model_validate(item).duration_ms for item in state["audio_segments"]
        )
        if timeline[-1].end_ms != audio_total:
            raise WorkflowValidationError("final timeline is not aligned with audio")
        if subtitle.duration_ms != audio_total:
            raise WorkflowValidationError("subtitle duration is not aligned with audio")
        for item in timeline:
            material = next(asset for asset in materials if asset.shot_id == item.shot_id)
            if material.target_duration_ms != item.end_ms - item.start_ms:
                raise WorkflowValidationError("material trim duration is not aligned with audio")
        return {
            "alignment_manifest": {
                "duration_ms": audio_total,
                "shot_count": len(timeline),
                "subtitle_cues": subtitle.cue_count,
                "aspect_ratio": state["aspect_ratio"],
            },
            "status": TaskStatus.RENDERING_PREVIEW.value,
            "current_stage": TaskStatus.RENDERING_PREVIEW.value,
        }

    def render_preview(self, state: GraphState) -> dict[str, Any]:
        self._status(state, TaskStatus.RENDERING_PREVIEW)
        version = int(state.get("preview_version", 0)) + 1
        manifest = self._manifest(state, f"preview-v{version}.json")
        output_path = self.store.artifact_path(
            state["user_id"], state["task_id"], "video", f"preview-v{version}.mp4"
        )
        saved = self.store.load_json(manifest)
        if saved and output_path.exists():
            preview = VideoArtifact.model_validate(saved)
            if self.store.checksum(output_path) != preview.checksum:
                saved = None
        if not saved:
            preview = self.renderer.render_preview(
                audio_segments=[
                    AudioSegment.model_validate(item) for item in state["audio_segments"]
                ],
                timeline=[TimelineItem.model_validate(item) for item in state["timeline"]],
                materials=[MaterialAsset.model_validate(item) for item in state["materials"]],
                subtitle=SubtitleArtifact.model_validate(state["subtitle"]),
                aspect_ratio=AspectRatio(state["aspect_ratio"]),
                output_path=output_path,
                store=self.store,
            )
            self.store.save_json_atomic(manifest, preview.model_dump(mode="json"))
        return {
            "preview_video": preview.model_dump(mode="json"),
            "preview_version": version,
            "status": TaskStatus.AWAITING_BGM_DECISION.value,
            "current_stage": TaskStatus.AWAITING_BGM_DECISION.value,
        }

    def review_bgm(self, state: GraphState) -> dict[str, Any]:
        decision = interrupt(
            {
                "kind": "bgm",
                "version": state["preview_version"],
                "allowed_actions": [BgmAction.NO_ADD.value, BgmAction.ADD.value],
                "suggested_query": state["bgm_query"],
            }
        )
        if not isinstance(decision, dict) or decision.get("kind") != "bgm":
            raise WorkflowValidationError("invalid BGM resume payload")
        if decision.get("version") != state["preview_version"]:
            raise WorkflowValidationError("BGM review version mismatch")
        action = BgmAction(decision.get("action"))
        volume = decision.get("volume")
        if action == BgmAction.ADD and not isinstance(volume, (int, float)):
            raise WorkflowValidationError("BGM volume is required")
        if action == BgmAction.ADD and not 0 <= float(volume) <= 1:
            raise WorkflowValidationError("BGM volume is out of range")
        selection = None
        if action == BgmAction.ADD:
            try:
                selection = BgmSelection.model_validate(decision.get("selection"))
            except ValidationError as error:
                raise WorkflowValidationError("BGM selection is invalid") from error
        return {
            "bgm_action": action.value,
            "bgm_volume": float(volume) if action == BgmAction.ADD else 0.0,
            **(
                {"bgm_selection": selection.model_dump(mode="json")}
                if selection is not None
                else {}
            ),
            "review_history": [decision],
            "status": (
                TaskStatus.PROCESSING_BGM.value
                if action == BgmAction.ADD
                else TaskStatus.COMPLETED.value
            ),
            "current_stage": (
                TaskStatus.PROCESSING_BGM.value
                if action == BgmAction.ADD
                else TaskStatus.COMPLETED.value
            ),
        }

    @staticmethod
    def route_bgm(state: GraphState) -> str:
        return state["bgm_action"]

    def complete_without_bgm(self, state: GraphState) -> dict[str, Any]:
        preview = VideoArtifact.model_validate(state["preview_video"])
        return {
            "final_video": preview.model_dump(mode="json"),
            "bgm_added": False,
            "status": TaskStatus.COMPLETED.value,
            "current_stage": TaskStatus.COMPLETED.value,
        }

    def fetch_bgm(self, state: GraphState) -> dict[str, Any]:
        self._status(state, TaskStatus.PROCESSING_BGM)
        preview = VideoArtifact.model_validate(state["preview_video"])
        manifest = self._manifest(state, f"bgm-v{state['preview_version']}.json")
        output_path = self.store.artifact_path(
            state["user_id"], state["task_id"], "bgm", "selected.wav"
        )
        saved = self.store.load_json(manifest)
        if saved and output_path.exists():
            bgm = saved
        else:
            artifact = self.renderer.fetch_bgm(
                BgmSelection.model_validate(state["bgm_selection"]),
                preview.duration_ms,
                output_path,
                self.store,
            )
            bgm = artifact.model_dump(mode="json")
            self.store.save_json_atomic(manifest, bgm)
        return {"bgm_artifact": bgm}

    def mix_bgm(self, state: GraphState) -> dict[str, Any]:
        preview = VideoArtifact.model_validate(state["preview_video"])
        manifest = self._manifest(state, f"final-v{state['preview_version']}.json")
        output_path = self.store.artifact_path(
            state["user_id"], state["task_id"], "video", "final.mp4"
        )
        saved = self.store.load_json(manifest)
        if saved and output_path.exists():
            final = VideoArtifact.model_validate(saved)
            if self.store.checksum(output_path) != final.checksum:
                saved = None
        if not saved:
            from backend.domain.models import BgmArtifact

            final = self.renderer.mix_bgm(
                preview,
                BgmArtifact.model_validate(state["bgm_artifact"]),
                state["bgm_volume"],
                output_path,
                self.store,
            )
            self.store.save_json_atomic(manifest, final.model_dump(mode="json"))
        return {
            "final_video": final.model_dump(mode="json"),
            "bgm_added": True,
            "status": TaskStatus.COMPLETED.value,
            "current_stage": TaskStatus.COMPLETED.value,
        }


def build_workflow(nodes: WorkflowNodes, checkpointer: Any) -> Any:
    workflow = StateGraph(GraphState)

    def timed(name: str, operation: Any) -> Any:
        @wraps(operation)
        def invoke(state: GraphState) -> dict[str, Any]:
            started = time.perf_counter()
            try:
                return operation(state)
            finally:
                LOGGER.info(
                    "workflow node timing task_id=%s node=%s elapsed_ms=%d",
                    state.get("task_id", "unknown"),
                    name,
                    round((time.perf_counter() - started) * 1000),
                )

        return invoke

    node_handlers = {
        "generate_script": nodes.generate_script,
        "review_script": nodes.review_script,
        "parse_script": nodes.parse_script,
        "generate_storyboard": nodes.generate_storyboard,
        "review_storyboard": nodes.review_storyboard,
        "parse_storyboard": nodes.parse_storyboard,
        "synthesize_tts": nodes.synthesize_tts,
        "build_timeline": nodes.build_timeline,
        "fetch_materials": nodes.fetch_materials,
        "generate_srt": nodes.generate_srt,
        "align": nodes.align,
        "render_preview": nodes.render_preview,
        "review_bgm": nodes.review_bgm,
        "complete_without_bgm": nodes.complete_without_bgm,
        "fetch_bgm": nodes.fetch_bgm,
        "mix_bgm": nodes.mix_bgm,
    }
    for node_name, handler in node_handlers.items():
        workflow.add_node(node_name, timed(node_name, handler))

    workflow.add_edge(START, "generate_script")
    workflow.add_edge("generate_script", "review_script")
    workflow.add_conditional_edges(
        "review_script",
        nodes.route_script_review,
        {"reject": "generate_script", "approve": "parse_script"},
    )
    workflow.add_edge("parse_script", "generate_storyboard")
    workflow.add_edge("generate_storyboard", "review_storyboard")
    workflow.add_conditional_edges(
        "review_storyboard",
        nodes.route_storyboard_review,
        {"reject": "generate_storyboard", "approve": "parse_storyboard"},
    )
    workflow.add_edge("parse_storyboard", "synthesize_tts")
    workflow.add_edge("synthesize_tts", "build_timeline")
    workflow.add_edge("build_timeline", "fetch_materials")
    workflow.add_edge("build_timeline", "generate_srt")
    workflow.add_edge(["fetch_materials", "generate_srt"], "align")
    workflow.add_edge("align", "render_preview")
    workflow.add_edge("render_preview", "review_bgm")
    workflow.add_conditional_edges(
        "review_bgm",
        nodes.route_bgm,
        {BgmAction.NO_ADD.value: "complete_without_bgm", BgmAction.ADD.value: "fetch_bgm"},
    )
    workflow.add_edge("complete_without_bgm", END)
    workflow.add_edge("fetch_bgm", "mix_bgm")
    workflow.add_edge("mix_bgm", END)
    return workflow.compile(checkpointer=checkpointer)
