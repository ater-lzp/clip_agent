from __future__ import annotations

import operator
from typing import Annotated

from typing_extensions import NotRequired, TypedDict


class GraphState(TypedDict):
    task_id: str
    user_id: str
    thread_id: str
    topic: str
    target_duration_seconds: int
    aspect_ratio: str
    voice_id: str
    provider_mode: str
    status: str
    current_stage: str
    script_version: int
    storyboard_version: int
    preview_version: int
    script: NotRequired[dict]
    script_feedback: NotRequired[str | None]
    parsed_script: NotRequired[dict]
    storyboard: NotRequired[dict]
    storyboard_feedback: NotRequired[str | None]
    parsed_storyboard: NotRequired[dict]
    audio_segments: NotRequired[list[dict]]
    timeline: NotRequired[list[dict]]
    materials: NotRequired[list[dict]]
    subtitle: NotRequired[dict]
    alignment_manifest: NotRequired[dict]
    preview_video: NotRequired[dict]
    bgm_query: NotRequired[str]
    bgm_action: NotRequired[str]
    bgm_volume: NotRequired[float]
    bgm_artifact: NotRequired[dict]
    final_video: NotRequired[dict]
    bgm_added: NotRequired[bool]
    error: NotRequired[dict | None]
    review_history: Annotated[list[dict], operator.add]
