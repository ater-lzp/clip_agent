from __future__ import annotations

import io
import os

from PIL import Image, ImageOps, UnidentifiedImageError

from backend.infrastructure.storage import ArtifactStore

MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_AVATAR_PIXELS = 20_000_000


class InvalidAvatarError(ValueError):
    pass


def save_avatar(store: ArtifactStore, user_id: str, content: bytes) -> str:
    if not content or len(content) > MAX_AVATAR_BYTES:
        raise InvalidAvatarError("avatar size is invalid")
    Image.MAX_IMAGE_PIXELS = MAX_AVATAR_PIXELS
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.format not in {"JPEG", "PNG"}:
                raise InvalidAvatarError("avatar format is invalid")
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise InvalidAvatarError("avatar content is invalid") from error
    fitted = ImageOps.fit(image, (200, 200), method=Image.Resampling.LANCZOS)
    destination = store.profile_path(user_id, "avatar.jpg")
    temporary = store.profile_path(user_id, "avatar.pending.jpg")
    try:
        fitted.save(temporary, format="JPEG", quality=88, optimize=True)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return store.relative_path(destination)
