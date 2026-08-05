from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _path_from_env(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


class Settings(BaseModel):
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    database_path: Path = PROJECT_ROOT / "data" / "clip_agent.sqlite3"
    checkpoint_path: Path = PROJECT_ROOT / "data" / "checkpoints.sqlite3"
    media_root: Path = PROJECT_ROOT / "data" / "media"
    session_ttl_hours: int = 168
    cookie_secure: bool = False
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    provider_mode: str = "real"
    llm_timeout_seconds: float = Field(default=120.0, ge=10, le=600)
    tts_timeout_seconds: float = Field(default=90.0, ge=10, le=300)
    pexels_timeout_seconds: float = Field(default=20.0, ge=5, le=120)
    provider_max_retries: int = 2
    max_download_bytes: int = 52_428_800
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_name: str = ""
    tts_base_url: str = ""
    tts_api_key: str = ""
    tts_name: str = ""
    pexels_base_url: str = ""
    pexels_api_key: str = ""
    pexels_max_queries: int = Field(default=6, ge=1, le=6)
    pexels_per_page: int = Field(default=15, ge=1, le=80)
    bgm_library_dir: Path = PROJECT_ROOT / "backend" / "bgms"

    @field_validator("provider_mode")
    @classmethod
    def validate_provider_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"fake", "real"}:
            raise ValueError("CLIP_PROVIDER_MODE must be fake or real")
        return normalized

    @field_validator("allowed_origins", "allowed_hosts")
    @classmethod
    def reject_wildcards(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if "*" in cleaned:
            raise ValueError("wildcard origins and hosts are not allowed")
        return cleaned

    @model_validator(mode="after")
    def validate_real_provider_configuration(self) -> Settings:
        if self.provider_mode == "real":
            required = {
                "LLM_BASE_URL": self.llm_base_url,
                "LLM_API_KEY": self.llm_api_key,
                "LLM_NAME": self.llm_name,
                "TTS_BASE_URL": self.tts_base_url,
                "TTS_API_KEY": self.tts_api_key,
                "TTS_NAME": self.tts_name,
                "PEXELS_BASE_URL": self.pexels_base_url,
                "PEXELS_API_KEY": self.pexels_api_key,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"real provider mode is missing: {', '.join(missing)}")
        return self

    @classmethod
    def from_environment(cls) -> Settings:
        load_dotenv(PROJECT_ROOT / ".env", override=False)

        def csv(name: str, default: str) -> list[str]:
            return os.getenv(name, default).split(",")

        bgm_value = os.getenv("BGM_LIBRARY_DIR", "").strip() or "./backend/bgms"
        return cls(
            environment=os.getenv("CLIP_ENV", "development"),
            host=os.getenv("CLIP_HOST", "127.0.0.1"),
            port=int(os.getenv("CLIP_PORT", "8000")),
            database_path=_path_from_env(
                os.getenv("CLIP_DATABASE_PATH", "./data/clip_agent.sqlite3")
            ),
            checkpoint_path=_path_from_env(
                os.getenv("CLIP_CHECKPOINT_PATH", "./data/checkpoints.sqlite3")
            ),
            media_root=_path_from_env(os.getenv("CLIP_MEDIA_ROOT", "./data/media")),
            session_ttl_hours=int(os.getenv("CLIP_SESSION_TTL_HOURS", "168")),
            cookie_secure=os.getenv("CLIP_COOKIE_SECURE", "false").lower() == "true",
            allowed_origins=csv("CLIP_ALLOWED_ORIGINS", "http://localhost:5173"),
            allowed_hosts=csv("CLIP_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver"),
            provider_mode=os.getenv("CLIP_PROVIDER_MODE", "real"),
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
            tts_timeout_seconds=float(os.getenv("TTS_TIMEOUT_SECONDS", "90")),
            pexels_timeout_seconds=float(os.getenv("PEXELS_TIMEOUT_SECONDS", "20")),
            provider_max_retries=int(os.getenv("CLIP_PROVIDER_MAX_RETRIES", "2")),
            max_download_bytes=int(os.getenv("CLIP_MAX_DOWNLOAD_BYTES", "52428800")),
            llm_base_url=os.getenv("LLM_BASE_URL", ""),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_name=os.getenv("LLM_NAME", ""),
            tts_base_url=os.getenv("TTS_BASE_URL", ""),
            tts_api_key=os.getenv("TTS_API_KEY", ""),
            tts_name=os.getenv("TTS_NAME", ""),
            pexels_base_url=os.getenv("PEXELS_BASE_URL", ""),
            pexels_api_key=os.getenv("PEXELS_API_KEY", ""),
            pexels_max_queries=int(os.getenv("PEXELS_MAX_QUERIES", "6")),
            pexels_per_page=int(os.getenv("PEXELS_PER_PAGE", "15")),
            bgm_library_dir=_path_from_env(bgm_value),
        )

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.bgm_library_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_environment()
