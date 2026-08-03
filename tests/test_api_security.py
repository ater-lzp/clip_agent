from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import csrf_headers, register_user, wait_for_status
from tests.test_e2e_workflow import create_video


def test_session_csrf_settings_and_logout(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    user = register_user(client)
    assert client.get("/api/v1/auth/me").json()["id"] == user["id"]
    assert (
        client.put(
            "/api/v1/settings",
            json={
                "default_aspect_ratio": "16:9",
                "default_duration_seconds": 45,
                "default_bgm_volume": 0.3,
                "preferred_voice": "白桦",
            },
        ).status_code
        == 403
    )
    update = client.put(
        "/api/v1/settings",
        headers=csrf_headers(client),
        json={
            "default_aspect_ratio": "16:9",
            "default_duration_seconds": 45,
            "default_bgm_volume": 0.3,
            "preferred_voice": "白桦",
        },
    )
    assert update.status_code == 200
    assert "api_key" not in update.text.lower()
    assert client.delete("/api/v1/auth/session", headers=csrf_headers(client)).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_capabilities_and_task_voice_are_explicit(authenticated_client: TestClient) -> None:
    client = authenticated_client
    capabilities = client.get("/api/v1/capabilities")
    assert capabilities.status_code == 200
    payload = capabilities.json()
    assert payload["provider_mode"] == "fake"
    assert payload["external_requests_enabled"] is False
    assert {voice["id"] for voice in payload["voices"]} == {
        "mimo_default",
        "冰糖",
        "茉莉",
        "苏打",
        "白桦",
        "Mia",
        "Chloe",
        "Milo",
        "Dean",
    }

    response = client.post(
        "/api/v1/tasks",
        headers={**csrf_headers(client), "Idempotency-Key": "voice-selection"},
        json={
            "topic": "音色选择测试",
            "target_duration_seconds": 10,
            "aspect_ratio": "9:16",
            "voice_id": "白桦",
        },
    )
    assert response.status_code == 201
    assert response.json()["voice_id"] == "白桦"
    assert response.json()["provider_mode"] == "fake"


def test_user_isolation_and_safe_delete(authenticated_client: TestClient) -> None:
    owner = authenticated_client
    task_id = create_video(owner, "只属于用户甲的任务")["id"]
    wait_for_status(owner, task_id, "awaiting_script_review")

    owner_session = owner.cookies.get("clip_session")
    owner_csrf = owner.cookies.get("clip_csrf")
    owner.cookies.clear()
    register_user(owner, "intruder@example.com")
    assert owner.get(f"/api/v1/tasks/{task_id}").status_code == 404
    assert owner.get(f"/api/v1/tasks/{task_id}/preview").status_code == 404
    assert owner.delete(f"/api/v1/tasks/{task_id}", headers=csrf_headers(owner)).status_code == 404
    owner.cookies.clear()
    owner.cookies.set("clip_session", owner_session)
    owner.cookies.set("clip_csrf", owner_csrf)

    response = owner.delete(f"/api/v1/tasks/{task_id}", headers=csrf_headers(owner))
    assert response.status_code == 204
    assert owner.get(f"/api/v1/tasks/{task_id}").status_code == 404


def test_idempotency_and_version_conflicts(authenticated_client: TestClient) -> None:
    client = authenticated_client
    headers = {**csrf_headers(client), "Idempotency-Key": "stable-create-key"}
    payload = {"topic": "幂等测试", "target_duration_seconds": 10, "aspect_ratio": "16:9"}
    first = client.post("/api/v1/tasks", headers=headers, json=payload)
    second = client.post("/api/v1/tasks", headers=headers, json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    conflict = client.post(
        "/api/v1/tasks", headers=headers, json={**payload, "topic": "另一个主题"}
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    detail = wait_for_status(client, first.json()["id"], "awaiting_script_review")
    stale = client.post(
        f"/api/v1/tasks/{detail['id']}/reviews/script",
        headers=csrf_headers(client),
        json={"version": 99, "action": "approve", "feedback": None},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"


def test_input_limits_and_consistent_error_shape(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        "/api/v1/tasks",
        headers=csrf_headers(authenticated_client),
        json={"topic": "x", "target_duration_seconds": 500, "aspect_ratio": "4:3"},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert {item["field"] for item in error["fields"]} >= {
        "topic",
        "target_duration_seconds",
        "aspect_ratio",
    }


def test_retry_resumes_from_last_safe_checkpoint(authenticated_client: TestClient) -> None:
    client = authenticated_client
    task_id = create_video(client, "可重试失败")["id"]
    first = wait_for_status(client, task_id, "awaiting_script_review")
    client.app.state.repository.mark_failed(
        task_id,
        code="PROVIDER_UNAVAILABLE",
        message="供应商暂时不可用",
        retryable=True,
        failed_stage="generating_script",
    )
    response = client.post(
        f"/api/v1/tasks/{task_id}/retry",
        headers=csrf_headers(client),
    )
    assert response.status_code == 202
    restored = wait_for_status(client, task_id, "awaiting_script_review")
    assert restored["pending_review"]["version"] == first["pending_review"]["version"]
