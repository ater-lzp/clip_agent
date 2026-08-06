from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import struct
import subprocess
import wave
from pathlib import Path
from statistics import pvariance
from uuid import uuid4

import imageio_ffmpeg

from backend.application.workflow_service import WorkflowService
from backend.config import PROJECT_ROOT, Settings
from backend.db.repository import Repository
from backend.domain.models import (
    AudioSegment,
    MaterialAsset,
    MimoVoiceId,
    ScriptArtifact,
    SubtitleArtifact,
    TaskStatus,
    TimelineItem,
    VideoArtifact,
)
from backend.workflow.graph import _spoken_narration_text


def _timestamp_ms(value: str) -> int:
    hours, minutes, remainder = value.split(":")
    seconds, milliseconds = remainder.split(",")
    return int(hours) * 3_600_000 + int(minutes) * 60_000 + int(seconds) * 1000 + int(milliseconds)


def _parse_srt(path: Path) -> list[tuple[int, int, str]]:
    content = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"\d+\n(\d{2}:\d{2}:\d{2},\d{3}) --> "
        r"(\d{2}:\d{2}:\d{2},\d{3})\n(.+?)(?=\n\n\d+\n|\Z)",
        re.DOTALL,
    )
    return [
        (_timestamp_ms(start), _timestamp_ms(end), text.replace("\n", "").strip())
        for start, end, text in pattern.findall(content.strip())
    ]


def _pcm_rms(samples: bytes) -> float:
    count = len(samples) // 2
    if count == 0:
        return 0.0
    values = struct.unpack(f"<{count}h", samples[: count * 2])
    return math.sqrt(sum(value * value for value in values) / count)


def _ffmpeg_probe(video_path: Path, duration_seconds: float) -> dict[str, object]:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    inspection = subprocess.run(
        [ffmpeg, "-i", str(video_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    ).stderr.decode("utf-8", errors="replace")
    dimension_match = re.search(r"Video:.*?\b(\d{2,5})x(\d{2,5})\b", inspection)
    if dimension_match is None:
        raise RuntimeError("rendered video stream has no dimensions")
    dimensions = (int(dimension_match.group(1)), int(dimension_match.group(2)))
    if "Audio:" not in inspection or "Subtitle:" not in inspection:
        raise RuntimeError("rendered video is missing its audio or subtitle stream")

    frame_variances: list[float] = []
    for position in (0.25, 0.5, 0.75):
        frame = subprocess.run(
            [
                ffmpeg,
                "-ss",
                f"{duration_seconds * position:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                "scale=180:320",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "gray",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=60,
        ).stdout
        frame_variances.append(pvariance(frame) if frame else 0.0)
    if max(frame_variances, default=0) < 5:
        raise RuntimeError("rendered video frames appear blank")

    rendered_pcm = subprocess.run(
        [
            ffmpeg,
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "s16le",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=120,
    ).stdout
    rendered_rms = _pcm_rms(rendered_pcm)
    if rendered_rms < 20:
        raise RuntimeError("rendered narration track appears silent")
    _, probed_duration = imageio_ffmpeg.count_frames_and_secs(str(video_path))
    return {
        "dimensions": list(dimensions),
        "duration_ms": round(probed_duration * 1000),
        "frame_variance": round(max(frame_variances), 2),
        "audio_rms": round(rendered_rms, 2),
        "has_subtitle_stream": True,
    }


def _assert_status(repository: Repository, task_id: str, expected: TaskStatus) -> dict:
    task = repository.get_task_internal(task_id)
    if task["status"] == TaskStatus.FAILED.value:
        raise RuntimeError(
            json.dumps(
                {
                    "status": task["status"],
                    "code": task.get("error_code"),
                    "failed_stage": task.get("failed_stage"),
                    "retryable": task.get("error_retryable"),
                },
                ensure_ascii=True,
            )
        )
    if task["status"] != expected.value:
        raise RuntimeError(f"expected {expected.value}, received {task['status']}")
    return task


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-run-id")
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--voice", default="白桦", choices=[voice.value for voice in MimoVoiceId])
    arguments = parser.parse_args()
    base = Settings.from_environment()
    if base.provider_mode != "real":
        raise RuntimeError("CLIP_PROVIDER_MODE must be real for this validation")
    run_id = arguments.resume_run_id or str(uuid4())
    validation_root = PROJECT_ROOT / "data" / "real-validation" / run_id
    settings = base.model_copy(
        update={
            "database_path": validation_root / "application.sqlite3",
            "checkpoint_path": validation_root / "checkpoints.sqlite3",
            "media_root": validation_root / "media",
        }
    )
    settings.ensure_directories()
    repository = Repository(settings.database_path)
    repository.initialize()
    if arguments.resume_run_id:
        with sqlite3.connect(settings.database_path) as connection:
            row = connection.execute(
                "SELECT id, user_id FROM video_tasks ORDER BY created_at LIMIT 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("validation run has no task to resume")
        task = repository.get_task_internal(str(row[0]))
        user = {"id": str(row[1])}
    else:
        user = repository.create_user(f"real-validation-{run_id}@example.test", "not-a-login")
        task, _ = repository.create_task(
            user_id=user["id"],
            topic="解释为什么海洋对地球生命至关重要",
            target_duration_seconds=arguments.duration,
            aspect_ratio="9:16",
            voice_id=arguments.voice,
            provider_mode="real",
            idempotency_key=f"real-validation-{run_id}",
            default_bgm_volume=0.18,
        )
    service = WorkflowService(settings, repository)
    try:
        if arguments.resume_run_id:
            service.run_now(task["id"])
        else:
            service.run_now(task["id"])
            first = _assert_status(repository, task["id"], TaskStatus.AWAITING_SCRIPT_REVIEW)
            repository.claim_review(
                user_id=user["id"],
                task_id=task["id"],
                kind="script",
                version=first["script_version"],
                action="approve",
            )
            service.run_now(task["id"])
            second = _assert_status(repository, task["id"], TaskStatus.AWAITING_STORYBOARD_REVIEW)
            repository.claim_review(
                user_id=user["id"],
                task_id=task["id"],
                kind="storyboard",
                version=second["storyboard_version"],
                action="approve",
            )
            service.run_now(task["id"])
        third = _assert_status(repository, task["id"], TaskStatus.AWAITING_BGM_DECISION)
        repository.claim_review(
            user_id=user["id"],
            task_id=task["id"],
            kind="bgm",
            version=third["preview_version"],
            action="no_add",
        )
        service.run_now(task["id"])
        complete = _assert_status(repository, task["id"], TaskStatus.COMPLETED)

        config = {"configurable": {"thread_id": task["thread_id"]}}
        state = service.graph.get_state(config).values
        script = ScriptArtifact.model_validate(state["script"])
        audio = [AudioSegment.model_validate(item) for item in state["audio_segments"]]
        timeline = [TimelineItem.model_validate(item) for item in state["timeline"]]
        materials = [MaterialAsset.model_validate(item) for item in state["materials"]]
        subtitle = SubtitleArtifact.model_validate(state["subtitle"])
        video = VideoArtifact.model_validate(state["final_video"])

        audio_total_ms = sum(item.duration_ms for item in audio)
        target_duration_ms = int(task["target_duration_seconds"]) * 1000
        if timeline[0].start_ms != 0 or timeline[-1].end_ms != audio_total_ms:
            raise RuntimeError("timeline is not bounded by the real narration duration")
        for previous, current in zip(timeline, timeline[1:], strict=False):
            if previous.end_ms != current.start_ms:
                raise RuntimeError("timeline contains a gap or overlap")
        material_map = {item.shot_id: item for item in materials}
        for item in timeline:
            material = material_map[item.shot_id]
            if material.target_duration_ms != item.end_ms - item.start_ms:
                raise RuntimeError("material target duration differs from timeline")
            if not material.relative_path:
                raise RuntimeError("real Pexels asset has no local file")
            material_path = settings.media_root / material.relative_path
            if not material_path.is_file() or material_path.stat().st_size == 0:
                raise RuntimeError("real Pexels asset was not downloaded")

        for segment in audio:
            audio_path = settings.media_root / segment.relative_path
            with wave.open(str(audio_path), "rb") as source:
                measured_ms = round(source.getnframes() * 1000 / source.getframerate())
                samples = source.readframes(source.getnframes())
            if abs(measured_ms - segment.duration_ms) > 1:
                raise RuntimeError("TTS manifest duration differs from WAV duration")
            if _pcm_rms(samples) < 20:
                raise RuntimeError("a MiMo TTS segment appears silent")

        subtitle_path = settings.media_root / subtitle.relative_path
        cues = _parse_srt(subtitle_path)
        if not cues or cues[0][0] != 0 or cues[-1][1] != audio_total_ms:
            raise RuntimeError("SRT boundaries differ from the real narration timeline")
        for previous, current in zip(cues, cues[1:], strict=False):
            if previous[1] != current[0]:
                raise RuntimeError("SRT contains a gap or overlap")
        actual_caption = "".join(item[2] for item in cues)
        expected_caption = "".join(
            _spoken_narration_text(segment.narration) for segment in script.segments
        )
        if actual_caption != expected_caption:
            raise RuntimeError("SRT text does not exactly cover the generated narration")

        video_path = settings.media_root / video.relative_path
        media_probe = _ffmpeg_probe(video_path, audio_total_ms / 1000)
        if media_probe["dimensions"] != [720, 1280]:
            raise RuntimeError("rendered video has the wrong 9:16 dimensions")
        if abs(int(media_probe["duration_ms"]) - audio_total_ms) > 150:
            raise RuntimeError("rendered video duration differs from narration timeline")
        if complete["final_duration_ms"] != audio_total_ms:
            raise RuntimeError("database final duration differs from narration timeline")

        print(
            json.dumps(
                {
                    "status": "passed",
                    "run_id": run_id,
                    "task_id": task["id"],
                    "video_path": str(video_path),
                    "subtitle_path": str(subtitle_path),
                    "script_scenes": len(script.segments),
                    "storyboard_shots": len(timeline),
                    "pexels_assets": len(materials),
                    "script_characters": sum(
                        segment.narration_char_count for segment in script.segments
                    ),
                    "target_duration_ms": target_duration_ms,
                    "audio_duration_ms": audio_total_ms,
                    "subtitle_duration_ms": subtitle.duration_ms,
                    "video": media_probe,
                },
                ensure_ascii=True,
            )
        )
    finally:
        service.close()


if __name__ == "__main__":
    main()
