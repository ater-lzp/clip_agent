from __future__ import annotations

import hashlib
from itertools import pairwise

from fastapi.testclient import TestClient

from tests.conftest import csrf_headers, wait_for_status


def create_video(client: TestClient, topic: str = "量子纠缠入门") -> dict:
    idempotency_key = hashlib.sha256(topic.encode("utf-8")).hexdigest()
    response = client.post(
        "/api/v1/tasks",
        headers={**csrf_headers(client), "Idempotency-Key": idempotency_key},
        json={
            "topic": topic,
            "target_duration_seconds": 10,
            "aspect_ratio": "9:16",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def submit_review(
    client: TestClient,
    task_id: str,
    kind: str,
    version: int,
    action: str,
    feedback: str | None = None,
) -> None:
    response = client.post(
        f"/api/v1/tasks/{task_id}/reviews/{kind}",
        headers=csrf_headers(client),
        json={"version": version, "action": action, "feedback": feedback},
    )
    assert response.status_code == 202, response.text


def test_full_fake_flow_with_both_rejection_branches_and_no_bgm(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    task = create_video(client)
    task_id = task["id"]

    first_script = wait_for_status(client, task_id, "awaiting_script_review")
    assert first_script["pending_review"]["version"] == 1
    submit_review(client, task_id, "script", 1, "reject", "让开场更直接")

    second_script = wait_for_status(client, task_id, "awaiting_script_review")
    assert second_script["pending_review"]["version"] == 2
    assert "让开场更直接" in second_script["script"]["segments"][0]["narration"]
    submit_review(client, task_id, "script", 2, "approve")

    first_storyboard = wait_for_status(client, task_id, "awaiting_storyboard_review")
    assert first_storyboard["pending_review"]["version"] == 1
    submit_review(client, task_id, "storyboard", 1, "reject", "增加更明亮的场景")

    second_storyboard = wait_for_status(client, task_id, "awaiting_storyboard_review")
    assert second_storyboard["pending_review"]["version"] == 2
    assert "更明亮" in second_storyboard["storyboard"]["shots"][0]["visual_description"]
    submit_review(client, task_id, "storyboard", 2, "approve")

    bgm_review = wait_for_status(client, task_id, "awaiting_bgm_decision")
    preview = client.get(bgm_review["preview_url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("video/mp4")

    response = client.post(
        f"/api/v1/tasks/{task_id}/bgm-decision",
        headers=csrf_headers(client),
        json={
            "version": bgm_review["pending_review"]["version"],
            "action": "no_add",
            "volume": None,
        },
    )
    assert response.status_code == 202, response.text
    completed = wait_for_status(client, task_id, "completed")
    assert completed["bgm_added"] is False
    assert completed["export_ready"] is True
    assert client.get(completed["export_url"]).status_code == 200


def test_add_bgm_branch_and_timeline_is_real_audio_driven(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    task_id = create_video(client, "海洋生态")["id"]
    script = wait_for_status(client, task_id, "awaiting_script_review")
    submit_review(client, task_id, "script", script["pending_review"]["version"], "approve")
    storyboard = wait_for_status(client, task_id, "awaiting_storyboard_review")
    submit_review(client, task_id, "storyboard", storyboard["pending_review"]["version"], "approve")
    bgm = wait_for_status(client, task_id, "awaiting_bgm_decision")
    response = client.post(
        f"/api/v1/tasks/{task_id}/bgm-decision",
        headers=csrf_headers(client),
        json={"version": bgm["pending_review"]["version"], "action": "add", "volume": 0.25},
    )
    assert response.status_code == 202
    completed = wait_for_status(client, task_id, "completed")
    assert completed["bgm_added"] is True
    assert completed["final_duration_seconds"] == 10.0

    row = client.app.state.repository.get_task_internal(task_id)
    timeline = row["timeline"]
    assert timeline[0]["start_ms"] == 0
    assert timeline[-1]["end_ms"] == 10_000
    assert all(
        previous["end_ms"] == current["start_ms"] for previous, current in pairwise(timeline)
    )
    subtitle_path = client.app.state.workflow_service.store.resolve_registered_path(
        row["user_id"], task_id, f"{row['user_id']}/{task_id}/subtitles/captions.srt"
    )
    subtitle_text = subtitle_path.read_text(encoding="utf-8")
    assert "00:00:00,000 -->" in subtitle_text
    assert "00:00:10,000" in subtitle_text
