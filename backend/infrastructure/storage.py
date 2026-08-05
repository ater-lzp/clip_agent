from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID


class UnsafePathError(ValueError):
    pass


class ArtifactStore:
    def __init__(self, media_root: Path) -> None:
        self.media_root = media_root.resolve()
        self.media_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _uuid_component(value: str) -> str:
        parsed = UUID(value)
        if str(parsed) != value.lower():
            raise UnsafePathError("resource id is not canonical")
        return str(parsed)

    def task_directory(self, user_id: str, task_id: str, create: bool = True) -> Path:
        safe_user = self._uuid_component(user_id)
        safe_task = self._uuid_component(task_id)
        user_dir = self.media_root / safe_user
        raw_task_dir = user_dir / safe_task
        for candidate in (user_dir, raw_task_dir):
            if (candidate.exists() or candidate.is_symlink()) and _is_link_or_reparse(candidate):
                raise UnsafePathError("task directory contains a link or reparse point")
        task_dir = raw_task_dir.resolve()
        if os.path.commonpath([str(self.media_root), str(task_dir)]) != str(self.media_root):
            raise UnsafePathError("task directory escapes the media root")
        if create:
            task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir

    def profile_path(self, user_id: str, filename: str, create: bool = True) -> Path:
        safe_user = self._uuid_component(user_id)
        if not re_safe_component(filename):
            raise UnsafePathError("profile filename is unsafe")
        user_dir = self.media_root / safe_user
        profile_dir = user_dir / "profile"
        for candidate in (user_dir, profile_dir):
            if (candidate.exists() or candidate.is_symlink()) and _is_link_or_reparse(candidate):
                raise UnsafePathError("profile directory contains a link or reparse point")
        if create:
            profile_dir.mkdir(parents=True, exist_ok=True)
        profile_dir = profile_dir.resolve()
        if os.path.commonpath([str(self.media_root), str(profile_dir)]) != str(self.media_root):
            raise UnsafePathError("profile directory escapes media root")
        return profile_dir / filename

    def resolve_profile_path(self, user_id: str, relative_path: str) -> Path:
        expected = self.profile_path(user_id, "avatar.jpg", create=False).resolve()
        candidate = (self.media_root / Path(relative_path)).resolve(strict=True)
        if candidate != expected or not candidate.is_file():
            raise UnsafePathError("profile artifact is not registered")
        return candidate

    def artifact_path(
        self, user_id: str, task_id: str, category: str, filename: str, create: bool = True
    ) -> Path:
        if not re_safe_component(category) or not re_safe_component(filename):
            raise UnsafePathError("artifact path component is unsafe")
        task_dir = self.task_directory(user_id, task_id, create=create)
        category_dir = task_dir / category
        if create:
            category_dir.mkdir(parents=True, exist_ok=True)
        artifact = (category_dir / filename).resolve()
        if os.path.commonpath([str(task_dir), str(artifact)]) != str(task_dir):
            raise UnsafePathError("artifact escapes task directory")
        return artifact

    def relative_path(self, path: Path) -> str:
        resolved = path.resolve()
        if os.path.commonpath([str(self.media_root), str(resolved)]) != str(self.media_root):
            raise UnsafePathError("artifact escapes media root")
        return resolved.relative_to(self.media_root).as_posix()

    def resolve_registered_path(self, user_id: str, task_id: str, relative_path: str) -> Path:
        if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            raise UnsafePathError("registered path is unsafe")
        task_dir = self.task_directory(user_id, task_id, create=False)
        candidate = (self.media_root / Path(relative_path)).resolve(strict=True)
        if os.path.commonpath([str(task_dir), str(candidate)]) != str(task_dir):
            raise UnsafePathError("registered path is outside the task directory")
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        return candidate

    def load_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_json_atomic(self, path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                json.dump(value, temporary, ensure_ascii=False, sort_keys=True)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def checksum(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def delete_task_directory(self, user_id: str, task_id: str) -> None:
        task_dir = self.validate_task_directory(user_id, task_id)
        if task_dir is not None:
            shutil.rmtree(task_dir)

    def validate_task_directory(self, user_id: str, task_id: str) -> Path | None:
        task_dir = self.task_directory(user_id, task_id, create=False)
        if not task_dir.exists():
            return None
        for root, directories, files in os.walk(task_dir, topdown=True, followlinks=False):
            for name in [*directories, *files]:
                candidate = Path(root) / name
                if _is_link_or_reparse(candidate):
                    raise UnsafePathError("task directory contains a link or reparse point")
        return task_dir


def re_safe_component(value: str) -> bool:
    if not value or value in {".", ".."}:
        return False
    return all(character.isalnum() or character in {"-", "_", "."} for character in value)


def _is_link_or_reparse(path: Path) -> bool:
    metadata = path.lstat()
    is_reparse = bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )
    return path.is_symlink() or is_reparse
