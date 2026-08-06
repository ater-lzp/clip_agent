from __future__ import annotations

import argparse
import json
import subprocess
import wave
from pathlib import Path
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
from backend.infrastructure.security import hash_password
from backend.tools.validate_real_workflow import _ffmpeg_probe, _parse_srt, _pcm_rms
from backend.workflow.graph import _spoken_narration_text


def _assert_status(repository: Repository, task_id: str, expected: TaskStatus) -> dict:
    task = repository.get_task_internal(task_id)
    if task["status"] != expected.value:
        raise RuntimeError(
            f"expected {expected.value}, received {task['status']}: "
            f"{task.get('error_code') or 'no error code'}"
        )
    return task


def _sample_backgrounds(video_path: Path, timeline: list[TimelineItem]) -> list[str]:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    colors: list[str] = []
    for item in timeline:
        position = (item.start_ms + item.end_ms) / 2000
        pixel = subprocess.run(
            [
                ffmpeg,
                "-ss",
                f"{position:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                "format=rgb24,crop=1:1:0:0",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=60,
        ).stdout[:3]
        if len(pixel) != 3:
            raise RuntimeError("unable to sample a rendered shot")
        colors.append(pixel.hex())
    return colors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and inspect a deterministic local Clip Agent video."
    )
    parser.add_argument("--duration", type=int, default=60, choices=range(10, 181))
    parser.add_argument("--aspect-ratio", choices=["16:9", "9:16"], default="9:16")
    parser.add_argument("--voice", default="白桦", choices=[voice.value for voice in MimoVoiceId])
    parser.add_argument("--bgm", choices=["add", "no_add"], default="add")
    arguments = parser.parse_args()

    run_id = str(uuid4())
    validation_root = PROJECT_ROOT / "data" / "fake-validation" / run_id
    settings = Settings(
        environment="validation",
        database_path=validation_root / "application.sqlite3",
        checkpoint_path=validation_root / "checkpoints.sqlite3",
        media_root=validation_root / "media",
        provider_mode="fake",
        bgm_library_dir=PROJECT_ROOT / "backend" / "bgms",
    )
    settings.ensure_directories()
    repository = Repository(settings.database_path)
    repository.initialize()
    user = repository.create_user(
        f"fake-validation-{run_id}@example.invalid", hash_password(str(uuid4()))
    )
    task, _ = repository.create_task(
        user_id=user["id"],
        topic="60 秒认识海洋生态系统如何维持地球生命",
        target_duration_seconds=arguments.duration,
        aspect_ratio=arguments.aspect_ratio,
        voice_id=arguments.voice,
        provider_mode="fake",
        idempotency_key=f"fake-validation:{run_id}",
        default_bgm_volume=0.18,
    )
    service = WorkflowService(settings, repository)
    try:
        service.run_now(task["id"])
        script_review = _assert_status(repository, task["id"], TaskStatus.AWAITING_SCRIPT_REVIEW)
        repository.claim_review(
            user_id=user["id"],
            task_id=task["id"],
            kind="script",
            version=script_review["script_version"],
            action="approve",
        )
        service.run_now(task["id"])
        storyboard_review = _assert_status(
            repository, task["id"], TaskStatus.AWAITING_STORYBOARD_REVIEW
        )
        repository.claim_review(
            user_id=user["id"],
            task_id=task["id"],
            kind="storyboard",
            version=storyboard_review["storyboard_version"],
            action="approve",
        )
        service.run_now(task["id"])
        bgm_review = _assert_status(repository, task["id"], TaskStatus.AWAITING_BGM_DECISION)
        review_arguments: dict[str, object] = {
            "user_id": user["id"],
            "task_id": task["id"],
            "kind": "bgm",
            "version": bgm_review["preview_version"],
            "action": arguments.bgm,
        }
        if arguments.bgm == "add":
            tracks = service.bgm_catalog.list_tracks()
            if not tracks:
                raise RuntimeError("the project BGM library is empty")
            review_arguments.update(
                {
                    "volume": 0.18,
                    "bgm_selection": service.resolve_bgm_selection(
                        user["id"], task["id"], bgm_review["preview_version"], tracks[0].id
                    ),
                }
            )
        repository.claim_review(**review_arguments)
        service.run_now(task["id"])
        complete = _assert_status(repository, task["id"], TaskStatus.COMPLETED)

        state = service.graph.get_state({"configurable": {"thread_id": task["thread_id"]}}).values
        script = ScriptArtifact.model_validate(state["script"])
        audio = [AudioSegment.model_validate(item) for item in state["audio_segments"]]
        timeline = [TimelineItem.model_validate(item) for item in state["timeline"]]
        materials = [MaterialAsset.model_validate(item) for item in state["materials"]]
        subtitle = SubtitleArtifact.model_validate(state["subtitle"])
        preview = VideoArtifact.model_validate(state["preview_video"])
        final = VideoArtifact.model_validate(state["final_video"])

        target_ms = arguments.duration * 1000
        audio_total_ms = sum(item.duration_ms for item in audio)
        if not timeline or timeline[0].start_ms != 0 or timeline[-1].end_ms != audio_total_ms:
            raise RuntimeError("timeline boundaries differ from synthesized TTS")
        if any(
            previous.end_ms != current.start_ms
            for previous, current in zip(timeline, timeline[1:], strict=False)
        ):
            raise RuntimeError("timeline contains a gap or overlap")
        material_map = {item.shot_id: item for item in materials}
        if set(material_map) != {item.shot_id for item in timeline}:
            raise RuntimeError("material coverage differs from timeline shots")
        for item in timeline:
            if material_map[item.shot_id].target_duration_ms != item.end_ms - item.start_ms:
                raise RuntimeError("material duration differs from its timeline shot")

        for segment in audio:
            audio_path = settings.media_root / segment.relative_path
            with wave.open(str(audio_path), "rb") as source:
                measured_ms = round(source.getnframes() * 1000 / source.getframerate())
                samples = source.readframes(source.getnframes())
            if measured_ms != segment.duration_ms or _pcm_rms(samples) < 20:
                raise RuntimeError("a TTS WAV is silent or its duration metadata is inaccurate")

        subtitle_path = settings.media_root / subtitle.relative_path
        cues = _parse_srt(subtitle_path)
        if not cues or cues[0][0] != 0 or cues[-1][1] != audio_total_ms:
            raise RuntimeError("SRT boundaries differ from the audio timeline")
        if any(
            previous[1] != current[0] for previous, current in zip(cues, cues[1:], strict=False)
        ):
            raise RuntimeError("SRT contains a gap or overlap")
        expected_caption = "".join(
            _spoken_narration_text(segment.narration) for segment in script.segments
        )
        if "".join(text for _, _, text in cues) != expected_caption:
            raise RuntimeError("SRT text does not exactly cover the generated narration")

        preview_path = settings.media_root / preview.relative_path
        final_path = settings.media_root / final.relative_path
        preview_probe = _ffmpeg_probe(preview_path, audio_total_ms / 1000)
        final_probe = _ffmpeg_probe(final_path, audio_total_ms / 1000)
        expected_dimensions = [720, 1280] if arguments.aspect_ratio == "9:16" else [1280, 720]
        if preview_probe["dimensions"] != expected_dimensions:
            raise RuntimeError("rendered video dimensions differ from the selected aspect ratio")
        for probe in (preview_probe, final_probe):
            if abs(int(probe["duration_ms"]) - audio_total_ms) > 150:
                raise RuntimeError("rendered media duration differs from the audio timeline")
        sampled_backgrounds = _sample_backgrounds(preview_path, timeline)
        if len(timeline) > 1 and len(set(sampled_backgrounds)) < 2:
            raise RuntimeError("rendered video does not switch visuals with timeline shots")
        if arguments.bgm == "add":
            if not final.has_bgm or final.checksum == preview.checksum:
                raise RuntimeError("the final video does not contain the selected BGM mix")
        elif final.has_bgm or final.checksum != preview.checksum:
            raise RuntimeError("the no-BGM branch did not preserve the preview")
        if complete["final_duration_ms"] != audio_total_ms:
            raise RuntimeError("database duration differs from the validated timeline")

        print(
            json.dumps(
                {
                    "status": "passed",
                    "run_id": run_id,
                    "task_id": task["id"],
                    "video_path": str(final_path),
                    "preview_path": str(preview_path),
                    "subtitle_path": str(subtitle_path),
                    "target_duration_ms": target_ms,
                    "audio_duration_ms": audio_total_ms,
                    "subtitle_duration_ms": subtitle.duration_ms,
                    "timeline_duration_ms": timeline[-1].end_ms,
                    "shots": len(timeline),
                    "subtitle_cues": len(cues),
                    "sampled_backgrounds": sampled_backgrounds,
                    "preview": preview_probe,
                    "final": final_probe,
                    "bgm_added": final.has_bgm,
                },
                ensure_ascii=False,
            )
        )
    finally:
        service.close()


if __name__ == "__main__":
    main()
