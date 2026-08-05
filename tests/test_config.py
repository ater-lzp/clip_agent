from pathlib import Path

from backend.config import Settings


def test_blank_bgm_library_environment_uses_project_default(monkeypatch) -> None:
    monkeypatch.setenv("CLIP_PROVIDER_MODE", "fake")
    monkeypatch.setenv("BGM_LIBRARY_DIR", "")
    settings = Settings.from_environment()
    assert settings.bgm_library_dir == (Path(__file__).resolve().parents[1] / "backend" / "bgms")
