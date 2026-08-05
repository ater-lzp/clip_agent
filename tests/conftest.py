from __future__ import annotations

import time
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from tests.fakes import FastRenderer


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    bgm_library = tmp_path / "bgms"
    bgm_library.mkdir()
    with wave.open(str(bgm_library / "test-calm.wav"), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(44_100)
        audio.writeframes(b"\0\0\0\0" * 44_100)
    return Settings(
        environment="test",
        database_path=tmp_path / "application.sqlite3",
        checkpoint_path=tmp_path / "checkpoints.sqlite3",
        media_root=tmp_path / "media",
        provider_mode="fake",
        allowed_origins=["http://testserver"],
        allowed_hosts=["testserver", "localhost"],
        bgm_library_dir=bgm_library,
    )


@pytest.fixture
def client(test_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    import backend.application.workflow_service as workflow_service_module

    original_builder = workflow_service_module.build_adapters

    def build_test_adapters(settings, store):
        llm, tts, materials, _ = original_builder(settings, store)
        return llm, tts, materials, FastRenderer()

    monkeypatch.setattr(workflow_service_module, "build_adapters", build_test_adapters)
    from backend.main import create_app

    application = create_app(test_settings)
    with TestClient(application) as active_client:
        yield active_client


def register_user(client: TestClient, email: str = "creator@example.com") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "a-secure-test-password"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("clip_csrf")
    assert token
    return {"X-CSRF-Token": token}


def wait_for_status(
    client: TestClient,
    task_id: str,
    expected: str,
    *,
    timeout_seconds: float = 8,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last: dict | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/tasks/{task_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] == expected:
            return last
        time.sleep(0.02)
    raise AssertionError(f"task did not reach {expected}; last={last}")


@pytest.fixture
def authenticated_client(client: TestClient) -> TestClient:
    register_user(client)
    return client
