from __future__ import annotations

from pathlib import Path

from backend.domain.models import BgmArtifact, VideoArtifact
from backend.infrastructure.adapters import RendererAdapter
from backend.infrastructure.storage import ArtifactStore


class FastRenderer(RendererAdapter):
    name = "fast-test-renderer"

    def render_preview(
        self,
        *,
        audio_segments,
        timeline,
        materials,
        subtitle,
        aspect_ratio,
        output_path: Path,
        store: ArtifactStore,
    ) -> VideoArtifact:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"deterministic-preview-mp4")
        return VideoArtifact(
            relative_path=store.relative_path(output_path),
            duration_ms=timeline[-1].end_ms,
            checksum=store.checksum(output_path),
            has_bgm=False,
        )

    def fetch_bgm(self, query: str, duration_ms: int, output_path: Path) -> BgmArtifact:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(f"bgm:{query}".encode())
        media_root = output_path.parents[3]
        store = ArtifactStore(media_root)
        return BgmArtifact(
            relative_path=store.relative_path(output_path),
            duration_ms=duration_ms,
            checksum=store.checksum(output_path),
            source="test fixture",
        )

    def mix_bgm(
        self,
        preview: VideoArtifact,
        bgm: BgmArtifact,
        volume: float,
        output_path: Path,
        store: ArtifactStore,
    ) -> VideoArtifact:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(f"mixed:{volume:.3f}".encode())
        return VideoArtifact(
            relative_path=store.relative_path(output_path),
            duration_ms=preview.duration_ms,
            checksum=store.checksum(output_path),
            has_bgm=True,
        )
