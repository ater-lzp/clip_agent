from __future__ import annotations

from pathlib import Path

import pytest

from backend.domain.models import AspectRatio, ScriptArtifact, ScriptSegment
from backend.infrastructure.adapters import FakeLlmAdapter, FakePexelsAdapter, FakeTtsAdapter
from backend.infrastructure.storage import ArtifactStore
from backend.workflow.graph import WorkflowNodes, WorkflowValidationError
from tests.fakes import FastRenderer


class CountingTts:
    name = "counting-tts"

    def __init__(self, store: ArtifactStore) -> None:
        self.delegate = FakeTtsAdapter(store)
        self.calls = 0

    def synthesize(self, segment, voice_id, output_path, idempotency_key):
        self.calls += 1
        return self.delegate.synthesize(segment, voice_id, output_path, idempotency_key)


def make_nodes(tmp_path: Path) -> tuple[WorkflowNodes, ArtifactStore, CountingTts]:
    store = ArtifactStore(tmp_path / "media")
    tts = CountingTts(store)
    nodes = WorkflowNodes(
        llm=FakeLlmAdapter(),
        tts=tts,
        materials=FakePexelsAdapter(),
        renderer=FastRenderer(),
        store=store,
        progress=lambda task_id, status: None,
    )
    return nodes, store, tts


def test_tts_retry_reuses_stable_artifact(tmp_path: Path) -> None:
    nodes, _, tts = make_nodes(tmp_path)
    script = ScriptArtifact(
        version=1,
        title="幂等测试",
        platform="抖音",
        aspect_ratio=AspectRatio.LANDSCAPE,
        total_duration_seconds=1,
        hook="开场",
        closing="结尾",
        bgm_query="轻快",
        segments=[
            ScriptSegment(
                id="segment-01",
                order=1,
                location="演播室 / 内 / 日间",
                narration="一段口播",
                narration_char_count=4,
                visual_intent="一段画面",
                emotion="自然清晰",
                audio_cue="无环境音",
                speed_tier="中速",
                speed_value=4,
                estimated_duration_seconds=1,
            )
        ],
    )
    state = {
        "task_id": "f023432d-910c-442c-a55b-df78bc3ecf15",
        "user_id": "1e2b77d0-6420-4d62-9837-b44a9b7b48f3",
        "voice_id": "mimo_default",
        "script": script.model_dump(mode="json"),
    }
    first = nodes.synthesize_tts(state)
    second = nodes.synthesize_tts(state)
    assert tts.calls == 1
    assert first["audio_segments"] == second["audio_segments"]


def test_final_alignment_rejects_missing_material_branch(tmp_path: Path) -> None:
    nodes, _, _ = make_nodes(tmp_path)
    state = {
        "task_id": "f023432d-910c-442c-a55b-df78bc3ecf15",
        "timeline": [
            {
                "shot_id": "shot-01",
                "segment_id": "segment-01",
                "start_ms": 0,
                "end_ms": 1000,
                "narration": "一段口播",
            }
        ],
        "materials": [],
        "subtitle": {
            "relative_path": "safe/captions.srt",
            "cue_count": 1,
            "duration_ms": 1000,
            "checksum": "x",
        },
        "audio_segments": [
            {
                "segment_id": "segment-01",
                "relative_path": "safe/audio.wav",
                "duration_ms": 1000,
                "sample_rate": 16000,
                "provider": "fake",
                "voice_id": "mimo_default",
                "checksum": "x",
            }
        ],
        "aspect_ratio": "16:9",
    }
    with pytest.raises(WorkflowValidationError, match="materials"):
        nodes.align(state)
