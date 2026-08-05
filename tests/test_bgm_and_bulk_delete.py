from __future__ import annotations

import io
import wave

from fastapi.testclient import TestClient

from tests.conftest import csrf_headers, register_user, wait_for_status
from tests.test_e2e_workflow import create_video, submit_review


def _wav_bytes(seconds: float = 0.2) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\0\0" * round(16_000 * seconds))
    return output.getvalue()


def _reach_bgm(client: TestClient, topic: str) -> dict:
    task_id = create_video(client, topic)["id"]
    script = wait_for_status(client, task_id, "awaiting_script_review")
    submit_review(client, task_id, "script", script["pending_review"]["version"], "approve")
    storyboard = wait_for_status(client, task_id, "awaiting_storyboard_review")
    submit_review(client, task_id, "storyboard", storyboard["pending_review"]["version"], "approve")
    return wait_for_status(client, task_id, "awaiting_bgm_decision")


def test_library_tracks_are_selectable_and_path_is_not_exposed(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    response = client.get("/api/v1/bgms")
    assert response.status_code == 200
    track = response.json()["items"][0]
    assert track["id"].startswith("library:")
    assert "relative_path" not in track
    assert client.get(track["preview_url"]).status_code == 200

    bgm = _reach_bgm(client, "library choice")
    decision = client.post(
        f"/api/v1/tasks/{bgm['id']}/bgm-decision",
        headers=csrf_headers(client),
        json={
            "version": bgm["pending_review"]["version"],
            "action": "add",
            "volume": 0.2,
            "track_id": track["id"],
        },
    )
    assert decision.status_code == 202, decision.text
    assert wait_for_status(client, bgm["id"], "completed")["bgm_added"] is True


def test_uploaded_bgm_survives_refresh_and_can_be_selected(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    bgm = _reach_bgm(client, "uploaded choice")
    response = client.post(
        f"/api/v1/tasks/{bgm['id']}/bgm-upload",
        headers=csrf_headers(client),
        files={"file": ("my-music.wav", _wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 201, response.text
    track = response.json()
    refreshed = client.get(f"/api/v1/tasks/{bgm['id']}").json()
    assert refreshed["pending_review"]["uploaded_track"] == track
    assert client.get(track["preview_url"]).status_code == 200

    decision = client.post(
        f"/api/v1/tasks/{bgm['id']}/bgm-decision",
        headers=csrf_headers(client),
        json={
            "version": bgm["pending_review"]["version"],
            "action": "add",
            "volume": 0.15,
            "track_id": track["id"],
        },
    )
    assert decision.status_code == 202, decision.text
    assert wait_for_status(client, bgm["id"], "completed")["bgm_added"] is True


def test_bulk_delete_all_is_user_isolated_and_cross_page(
    client: TestClient,
) -> None:
    register_user(client, "first@example.com")
    first_ids = [create_video(client, f"first-{index}")["id"] for index in range(3)]
    for task_id in first_ids:
        wait_for_status(client, task_id, "awaiting_script_review")
    response = client.post(
        "/api/v1/tasks/bulk-delete",
        headers=csrf_headers(client),
        json={"mode": "all", "task_ids": []},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted_count": 3}
    assert client.get("/api/v1/tasks").json()["total"] == 0
