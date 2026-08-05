from __future__ import annotations

import io
import os
import shutil
import stat
import tempfile
from pathlib import Path
from uuid import UUID

from PIL import Image, UnidentifiedImageError

from backend.infrastructure.storage import ArtifactStore, UnsafePathError

MAX_AD_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_AD_PIXELS = 20_000_000
MAX_AD_DIMENSION = 4096
MAX_GIF_FRAMES = 300

_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "GIF": ("gif", "image/gif"),
}


class InvalidAdImageError(ValueError):
    pass


def save_ad_image(store: ArtifactStore, ad_id: str, content: bytes) -> tuple[str, str]:
    if not content or len(content) > MAX_AD_UPLOAD_BYTES:
        raise InvalidAdImageError("ad image size is invalid")
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in _FORMATS:
                raise InvalidAdImageError("ad image format is invalid")
            width, height = image.size
            frames = int(getattr(image, "n_frames", 1))
            if (
                width < 1
                or height < 1
                or width > MAX_AD_DIMENSION
                or height > MAX_AD_DIMENSION
                or width * height * frames > MAX_AD_PIXELS
                or frames > MAX_GIF_FRAMES
            ):
                raise InvalidAdImageError("ad image dimensions are invalid")
            for frame_index in range(frames):
                image.seek(frame_index)
                image.load()
            extension, media_type = _FORMATS[image.format]
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as error:
        if isinstance(error, InvalidAdImageError):
            raise
        raise InvalidAdImageError("ad image content is invalid") from error

    destination = ad_image_path(store, ad_id, f"creative.{extension}", create=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".creative.", suffix=".pending", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return store.relative_path(destination), media_type


def ad_image_path(store: ArtifactStore, ad_id: str, filename: str, *, create: bool) -> Path:
    safe_id = str(UUID(ad_id))
    if safe_id != ad_id.lower() or filename not in {"creative.jpg", "creative.png", "creative.gif"}:
        raise UnsafePathError("ad media path is unsafe")
    ads_root = store.media_root / "ads"
    ad_directory = ads_root / safe_id
    for candidate in (ads_root, ad_directory):
        if (candidate.exists() or candidate.is_symlink()) and _is_link_or_reparse(candidate):
            raise UnsafePathError("ad media directory contains a link or reparse point")
    if create:
        ad_directory.mkdir(parents=True, exist_ok=True)
    resolved_directory = ad_directory.resolve()
    if os.path.commonpath([str(store.media_root), str(resolved_directory)]) != str(
        store.media_root
    ):
        raise UnsafePathError("ad media directory escapes media root")
    return resolved_directory / filename


def resolve_ad_image(store: ArtifactStore, ad_id: str, relative_path: str) -> Path:
    suffix = Path(relative_path).suffix.lower()
    filename = f"creative{suffix}"
    expected = ad_image_path(store, ad_id, filename, create=False).resolve()
    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise UnsafePathError("registered ad path is unsafe")
    candidate = (store.media_root / Path(relative_path)).resolve(strict=True)
    if candidate != expected or not candidate.is_file() or _is_link_or_reparse(candidate):
        raise UnsafePathError("ad image is not registered")
    return candidate


def delete_ad_media(store: ArtifactStore, ad_id: str) -> None:
    directory = ad_image_path(store, ad_id, "creative.jpg", create=False).parent
    if not directory.exists():
        return
    for root, directories, files in os.walk(directory, topdown=True, followlinks=False):
        for name in [*directories, *files]:
            if _is_link_or_reparse(Path(root) / name):
                raise UnsafePathError("ad media directory contains a link or reparse point")
    shutil.rmtree(directory)


def _is_link_or_reparse(path: Path) -> bool:
    metadata = path.lstat()
    is_reparse = bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )
    return path.is_symlink() or is_reparse
