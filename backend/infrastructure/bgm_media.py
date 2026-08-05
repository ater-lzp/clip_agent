from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg

from backend.infrastructure.storage import ArtifactStore

SUPPORTED_BGM_EXTENSIONS = {".mp3", ".wav", ".m4a"}
MAX_BGM_UPLOAD_BYTES = 25 * 1024 * 1024
_DURATION_PATTERN = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


class InvalidBgmError(ValueError):
    pass


@dataclass(frozen=True)
class BgmTrackRecord:
    id: str
    name: str
    source: str
    duration_ms: int
    path: Path


def _is_link_or_reparse(path: Path) -> bool:
    metadata = path.lstat()
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _library_id(filename: str) -> str:
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:24]
    return f"library:{digest}"


def _display_name(path: Path) -> str:
    normalized = re.sub(r"[_-]+", " ", path.stem).strip()
    return normalized[:100] or "背景音乐"


def _probe_duration_ms(path: Path) -> int:
    completed = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
        shell=False,
    )
    details = completed.stderr.decode("utf-8", errors="replace")
    match = _DURATION_PATTERN.search(details)
    if not match or "Audio:" not in details:
        raise InvalidBgmError("audio metadata is invalid")
    hours, minutes, seconds = match.groups()
    duration_ms = round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)
    if duration_ms <= 0 or duration_ms > 30 * 60 * 1000:
        raise InvalidBgmError("audio duration is out of range")
    return duration_ms


class BgmCatalog:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def list_tracks(self) -> list[BgmTrackRecord]:
        if not self.root.is_dir() or _is_link_or_reparse(self.root):
            return []
        tracks: list[BgmTrackRecord] = []
        for path in sorted(self.root.iterdir(), key=lambda item: item.name.casefold()):
            if (
                not path.is_file()
                or _is_link_or_reparse(path)
                or path.suffix.lower() not in SUPPORTED_BGM_EXTENSIONS
                or path.resolve().parent != self.root
            ):
                continue
            try:
                duration_ms = _probe_duration_ms(path)
            except (InvalidBgmError, OSError, subprocess.SubprocessError):
                continue
            tracks.append(
                BgmTrackRecord(
                    id=_library_id(path.name),
                    name=_display_name(path),
                    source="library",
                    duration_ms=duration_ms,
                    path=path.resolve(),
                )
            )
        return tracks

    def resolve(self, track_id: str) -> BgmTrackRecord:
        track = next((item for item in self.list_tracks() if item.id == track_id), None)
        if track is None:
            raise InvalidBgmError("library track does not exist")
        return track


def normalize_uploaded_bgm(
    store: ArtifactStore,
    user_id: str,
    task_id: str,
    preview_version: int,
    original_filename: str,
    content: bytes,
) -> tuple[str, str, int, str]:
    suffix = Path(original_filename or "").suffix.lower()
    if suffix not in SUPPORTED_BGM_EXTENSIONS:
        raise InvalidBgmError("unsupported audio extension")
    if not content or len(content) > MAX_BGM_UPLOAD_BYTES:
        raise InvalidBgmError("invalid audio size")
    source = store.artifact_path(user_id, task_id, "bgm", f"upload-v{preview_version}{suffix}")
    pending = store.artifact_path(
        user_id, task_id, "bgm", f"uploaded-v{preview_version}.pending.wav"
    )
    source.write_bytes(content)
    try:
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-hide_banner",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "2",
                "-ar",
                "44100",
                "-c:a",
                "pcm_s16le",
                str(pending),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=120,
            check=True,
            shell=False,
        )
        with wave.open(str(pending), "rb") as audio:
            duration_ms = round(audio.getnframes() / audio.getframerate() * 1000)
        if duration_ms <= 0 or duration_ms > 30 * 60 * 1000:
            raise InvalidBgmError("audio duration is out of range")
        checksum = store.checksum(pending)
        destination = store.artifact_path(
            user_id,
            task_id,
            "bgm",
            f"uploaded-v{preview_version}-{checksum[:16]}.wav",
        )
        os.replace(pending, destination)
        display_name = _display_name(Path(original_filename))
        return (
            store.relative_path(destination),
            display_name,
            duration_ms,
            checksum,
        )
    except (OSError, subprocess.SubprocessError, wave.Error) as error:
        raise InvalidBgmError("audio cannot be decoded") from error
    finally:
        source.unlink(missing_ok=True)
        pending.unlink(missing_ok=True)
