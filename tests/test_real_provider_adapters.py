from __future__ import annotations

import base64
import io
import json
import re
import wave
from pathlib import Path

import httpx
import pytest

from backend.config import Settings
from backend.domain.models import (
    AspectRatio,
    AudioSegment,
    MimoVoiceId,
    ScriptSegment,
    StoryboardShot,
)
from backend.infrastructure.adapters import (
    FfmpegRenderer,
    MimoTtsAdapter,
    OpenAICompatibleLlmAdapter,
    PexelsAdapter,
    _concat_wav,
    _write_wave,
)
from backend.infrastructure.storage import ArtifactStore
from backend.workflow.graph import (
    _narration_char_count,
    _split_subtitle,
    _spoken_narration_text,
)


def real_settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_path=tmp_path / "application.sqlite3",
        checkpoint_path=tmp_path / "checkpoints.sqlite3",
        media_root=tmp_path / "media",
        provider_mode="real",
        provider_max_retries=0,
        llm_base_url="https://llm.example/v1",
        llm_api_key="unit-test-value",
        llm_name="unit-test-model",
        tts_base_url="https://tts.example/v1",
        tts_api_key="unit-test-value",
        tts_name="unit-test-tts-model",
        pexels_base_url="https://api.pexels.com",
        pexels_api_key="unit-test-value",
    )


def test_real_llm_adapter_sends_two_structured_requests(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    narration = "海洋维系地球生命，也调节气候、提供氧气，承载无数生物的共同家园，一起守护。"
    script = {
        "title": "海洋生态",
        "platform": "抖音",
        "aspect_ratio": "portrait",
        "total_duration": 10,
        "bgm_suggestion": "calm ocean ambient",
        "scenes": [
            {
                "scene_id": 1,
                "location": "海边 / 外 / 日间",
                "narration": narration,
                "narration_char_count": 32,
                "visual_hint": "海浪与海洋生物的宽景",
                "emotion": "语气沉稳清晰，语速中等",
                "audio_cue": "轻微海浪环境音",
                "speed_tier": "慢速",
                "speed_value": 3.5,
                "estimated_duration": 10,
            }
        ],
    }
    storyboard = {
        "total_duration": 10,
        "total_shots": 1,
        "shots": [
            {
                "shot_id": 1,
                "belongs_to_scene": 1,
                "narration_segment": narration,
                "visual_description": "航拍海浪推进，阳光照亮海面与游动的鱼群",
                "search_query": "ocean waves fish",
                "keywords_en": "ocean, waves, fish",
                "keywords_cn": "海洋, 海浪, 鱼群",
                "shot_type": "wide",
                "mood": "开阔",
                "transition_in": "fade",
                "audio_note": "保留口播与轻微海浪声",
                "estimated_duration": 10,
                "orientation": "portrait",
            }
        ],
    }
    responses = [script, storyboard]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        content = responses[len(requests) - 1]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]},
        )

    adapter = OpenAICompatibleLlmAdapter(real_settings(tmp_path), httpx.MockTransport(handler))
    generated_script = adapter.generate_script(
        "海洋生态", 10, AspectRatio.PORTRAIT, 1, None, "script-request"
    )
    generated_storyboard = adapter.generate_storyboard(
        generated_script,
        AspectRatio.PORTRAIT,
        1,
        "画面更开阔",
        "storyboard-request",
    )

    assert generated_storyboard.shots[0].material_query == "ocean waves fish"
    assert len(requests) == 2
    assert all(
        request.url == httpx.URL("https://llm.example/v1/chat/completions") for request in requests
    )
    first_payload = json.loads(requests[0].content)
    second_payload = json.loads(requests[1].content)
    assert first_payload["response_format"] == {"type": "json_object"}
    assert first_payload["thinking"] == {"type": "disabled"}
    assert "narration_char_count" in first_payload["messages"][0]["content"]
    assert "目标 32 字" in first_payload["messages"][0]["content"]
    assert "31 ~ 33 字" in first_payload["messages"][0]["content"]
    assert "search_query" in second_payload["messages"][0]["content"]
    assert requests[0].headers["idempotency-key"] == "script-request"


def test_script_duration_is_guidance_not_a_failure_limit(tmp_path: Path) -> None:
    narration = "海洋连接生命循环" * 7
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"unexpected":true}'}}]},
            )
        content = {
            "title": "海洋生命",
            "platform": "抖音",
            "aspect_ratio": "portrait",
            "total_duration": 14,
            "bgm_suggestion": "calm ocean ambient",
            "scenes": [
                {
                    "scene_id": 1,
                    "location": "海边 / 外 / 日间",
                    "narration": narration,
                    "narration_char_count": 56,
                    "visual_hint": "海浪与海洋生物",
                    "emotion": "自然清晰，中速讲述",
                    "audio_cue": "海浪环境音",
                    "speed_tier": "中速",
                    "speed_value": 4,
                    "estimated_duration": 14,
                }
            ],
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content)}}]},
        )

    settings = real_settings(tmp_path).model_copy(update={"provider_max_retries": 1})
    adapter = OpenAICompatibleLlmAdapter(settings, httpx.MockTransport(handler))
    script = adapter.generate_script(
        "海洋生命", 10, AspectRatio.PORTRAIT, 1, None, "duration-guidance"
    )

    assert script.total_duration_seconds == 17.78
    assert calls == 4


def test_narration_count_excludes_mimo_voice_control_tags() -> None:
    assert _narration_char_count("（深沉、坚定）海洋连接着所有生命。") == 9
    assert _narration_char_count("(温柔)(欣慰)一起守护蔚蓝。") == 6
    assert _spoken_narration_text("(温柔)(欣慰)一起守护蔚蓝。") == "一起守护蔚蓝。"


def test_subtitle_split_keeps_punctuation_with_spoken_text() -> None:
    lines = _split_subtitle("它提供食物，养活数十亿人。", max_chars=8)
    assert "".join(lines) == "它提供食物，养活数十亿人。"
    assert all(not line.startswith(tuple("，。！？；、：,.!?;:")) for line in lines)
    assert _split_subtitle("一二三四五六七八。", max_chars=8) == ["一二三四五六七八。"]


def _wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\0\0" * 3_200)
    return output.getvalue()


def test_wav_concat_accepts_segments_with_different_frame_counts(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    combined = tmp_path / "combined.wav"
    _write_wave(first, 0.2, 220, 0.1)
    _write_wave(second, 0.35, 240, 0.1)

    _concat_wav([first, second], combined)

    with wave.open(str(combined), "rb") as audio:
        assert audio.getnframes() == round(0.55 * audio.getframerate())


def test_ffmpeg_renderer_retimes_audio_to_exact_duration(tmp_path: Path) -> None:
    settings = real_settings(tmp_path)
    store = ArtifactStore(settings.media_root)
    renderer = FfmpegRenderer(settings)
    source = store.artifact_path(
        "48da6f89-4533-43fb-8a78-950cec8213cd",
        "307ba0f2-5fb1-48b2-a81d-ad50ec4083b4",
        "audio",
        "source.wav",
    )
    output = source.with_name("aligned.wav")
    _write_wave(source, 1.8, 220, 0.1)
    segment = AudioSegment(
        segment_id="scene-01",
        relative_path=store.relative_path(source),
        duration_ms=1800,
        sample_rate=16_000,
        provider="test",
        voice_id=MimoVoiceId.BAI_HUA,
        checksum=store.checksum(source),
    )

    aligned = renderer.retime_audio(segment, 1000, output, store)

    assert aligned.duration_ms == 1000
    assert aligned.relative_path == store.relative_path(output)
    assert aligned.checksum == store.checksum(output)
    assert source.exists()


def test_mimo_tts_request_uses_selected_voice_and_decodes_audio(tmp_path: Path) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"audio": {"data": base64.b64encode(_wav_bytes()).decode("ascii")}}}
                ]
            },
        )

    settings = real_settings(tmp_path)
    store = ArtifactStore(settings.media_root)
    adapter = MimoTtsAdapter(settings, store, httpx.MockTransport(handler))
    output_path = store.artifact_path(
        "48da6f89-4533-43fb-8a78-950cec8213cd",
        "307ba0f2-5fb1-48b2-a81d-ad50ec4083b4",
        "audio",
        "segment.wav",
    )
    segment = ScriptSegment(
        id="segment-01",
        order=1,
        location="演播室 / 内 / 日间",
        narration="真实的配音请求。",
        narration_char_count=7,
        visual_intent="演播室麦克风",
        emotion="语气自然，语速中等",
        audio_cue="无环境音",
        speed_tier="快速",
        speed_value=7,
        estimated_duration_seconds=1,
    )
    audio = adapter.synthesize(segment, MimoVoiceId.BAI_HUA, output_path, "tts-request:白桦")

    assert output_path.exists()
    assert audio.voice_id == MimoVoiceId.BAI_HUA
    assert audio.duration_ms == 200
    assert len(captured) == 1
    payload = json.loads(captured[0].content)
    assert captured[0].url == httpx.URL("https://tts.example/v1/chat/completions")
    assert captured[0].headers["api-key"] == "unit-test-value"
    assert re.fullmatch(r"[0-9a-f]{64}", captured[0].headers["idempotency-key"])
    assert "authorization" not in captured[0].headers
    assert payload["audio"] == {"format": "mp3", "voice": "白桦"}
    assert payload["messages"] == [
        {"role": "user", "content": segment.emotion},
        {"role": "assistant", "content": segment.narration},
    ]


def test_pexels_adapter_stops_after_first_successful_layer_and_calculates_trim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    search_requests: list[httpx.Request] = []
    download_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.pexels.com":
            search_requests.append(request)
            return httpx.Response(
                200,
                json={
                    "videos": [
                        {
                            "id": 123,
                            "width": 1080,
                            "height": 1920,
                            "duration": 20,
                            "url": "https://www.pexels.com/video/123/",
                            "user": {"name": "Fixture Author"},
                            "video_files": [
                                {
                                    "quality": "hd",
                                    "width": 1080,
                                    "height": 1920,
                                    "link": "https://videos.pexels.com/video-files/123.mp4",
                                }
                            ],
                        }
                    ]
                },
            )
        download_requests.append(request)
        return httpx.Response(200, content=b"video-fixture", headers={"content-type": "video/mp4"})

    monkeypatch.setattr(
        "backend.infrastructure.adapters.validate_https_url",
        lambda url, allowed_hosts: url,
    )
    settings = real_settings(tmp_path)
    store = ArtifactStore(settings.media_root)
    adapter = PexelsAdapter(settings, store, httpx.MockTransport(handler))
    output_path = store.artifact_path(
        "48da6f89-4533-43fb-8a78-950cec8213cd",
        "307ba0f2-5fb1-48b2-a81d-ad50ec4083b4",
        "materials",
        "shot.mp4",
    )
    shot = StoryboardShot(
        id="shot-01",
        segment_id="segment-01",
        order=1,
        narration="看见海浪与鱼群。",
        visual_description="航拍海洋，海浪下方出现游动鱼群",
        material_query="ocean waves fish",
        keywords_en=["ocean", "waves", "fish"],
        keywords_cn=["海洋", "海浪", "鱼群"],
        shot_type="wide",
        mood="开阔",
        transition_in="fade",
        audio_note="海浪环境音",
        orientation=AspectRatio.PORTRAIT,
        estimated_duration_seconds=5,
    )
    material = adapter.fetch(shot, AspectRatio.PORTRAIT, 5_000, output_path, "pexels-request")

    assert len(search_requests) == 1
    assert all(request.headers["authorization"] == "unit-test-value" for request in search_requests)
    assert search_requests[0].url.params["query"] == "ocean waves fish"
    assert len(download_requests) == 1
    assert output_path.read_bytes() == b"video-fixture"
    assert material.matched_query == "ocean waves fish"
    assert material.original_duration_ms == 20_000
    assert material.target_duration_ms == 5_000
    assert material.trim_start_ms == 5_250
    assert material.trim_end_ms == 10_250
    assert material.loop_needed is False
