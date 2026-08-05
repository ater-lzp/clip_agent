from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import csrf_headers, register_user, wait_for_status
from tests.test_community import complete_video


def publish_completed_video(client: TestClient) -> dict:
    task_id = complete_video(client)
    response = client.post(
        "/api/v1/community/posts",
        headers=csrf_headers(client),
        json={
            "task_id": task_id,
            "title": "点赞测试作品",
            "description": "用于测试点赞与关注",
            "prompt_public": False,
            "tags": ["测试"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_task_stats_and_keyword_search(client: TestClient) -> None:
    user = register_user(client)
    created = client.post(
        "/api/v1/tasks",
        headers=csrf_headers(client),
        json={"topic": "量子纠缠浅谈", "target_duration_seconds": 10, "aspect_ratio": "9:16"},
    )
    assert created.status_code == 201, created.text
    created2 = client.post(
        "/api/v1/tasks",
        headers=csrf_headers(client),
        json={"topic": "如何给猫咪洗澡", "target_duration_seconds": 15, "aspect_ratio": "16:9"},
    )
    assert created2.status_code == 201, created2.text

    queued, _ = client.app.state.repository.create_task(
        user_id=user["id"],
        topic="100%真实的素材测试",
        target_duration_seconds=20,
        aspect_ratio="9:16",
        voice_id="mimo_default",
        provider_mode="fake",
        idempotency_key=None,
        default_bgm_volume=0.2,
    )

    stats = client.get("/api/v1/tasks/stats").json()
    assert stats["total"] == 3
    assert stats["total_duration_seconds"] == 0

    matched = client.get("/api/v1/tasks?q=猫咪").json()
    assert matched["total"] == 1
    assert matched["items"][0]["topic"] == "如何给猫咪洗澡"

    matched_none = client.get("/api/v1/tasks?q=不存在关键词").json()
    assert matched_none["total"] == 0

    literal_wildcard = client.get("/api/v1/tasks?q=%25").json()
    assert literal_wildcard["total"] == 1
    assert literal_wildcard["items"][0]["id"] == queued["id"]

    blank_query = client.get("/api/v1/tasks?q=%20%20%20")
    assert blank_query.status_code == 422

    conflicting_filters = client.get("/api/v1/tasks?status=completed&status_group=in_progress")
    assert conflicting_filters.status_code == 422

    filtered = client.get("/api/v1/tasks?status=completed").json()
    assert filtered["total"] == 0

    wait_for_status(client, created.json()["id"], "awaiting_script_review")
    wait_for_status(client, created2.json()["id"], "awaiting_script_review")
    stats_after = client.get("/api/v1/tasks/stats").json()
    assert stats_after["awaiting_review"] == 2
    assert stats_after["in_progress"] == 1
    assert stats_after["completed"] == 0

    active = client.get("/api/v1/tasks?status_group=in_progress").json()
    assert active["total"] == 1
    assert active["items"][0]["id"] == queued["id"]


def test_duplicate_task_creates_new_queued_task(client: TestClient) -> None:
    register_user(client)
    task_id = complete_video(client)
    original = client.get(f"/api/v1/tasks/{task_id}").json()

    idempotency_headers = {**csrf_headers(client), "Idempotency-Key": "repeat-completed-task"}
    duplicated = client.post(
        f"/api/v1/tasks/{task_id}/duplicate",
        headers=idempotency_headers,
        json={},
    )
    assert duplicated.status_code == 202, duplicated.text
    new_task = duplicated.json()
    assert new_task["id"] != task_id
    assert new_task["topic"] == original["topic"]
    assert new_task["target_duration_seconds"] == original["target_duration_seconds"]
    assert new_task["aspect_ratio"] == original["aspect_ratio"]
    assert new_task["voice_id"] == original["voice_id"]
    assert new_task["status"] in ("queued", "generating_script")

    repeated = client.post(
        f"/api/v1/tasks/{task_id}/duplicate",
        headers=idempotency_headers,
        json={},
    )
    assert repeated.status_code == 202
    assert repeated.json()["id"] == new_task["id"]

    rejected_override = client.post(
        f"/api/v1/tasks/{task_id}/duplicate",
        headers=csrf_headers(client),
        json={"topic": "不能在复制接口覆盖主题"},
    )
    assert rejected_override.status_code == 422

    unfinished = client.post(
        "/api/v1/tasks",
        headers=csrf_headers(client),
        json={"topic": "尚未完成的任务", "target_duration_seconds": 10, "aspect_ratio": "9:16"},
    )
    assert unfinished.status_code == 201
    unfinished_duplicate = client.post(
        f"/api/v1/tasks/{unfinished.json()['id']}/duplicate",
        headers=csrf_headers(client),
        json={},
    )
    assert unfinished_duplicate.status_code == 409

    duplicate_not_found = client.post(
        "/api/v1/tasks/00000000-0000-0000-0000-000000000000/duplicate",
        headers=csrf_headers(client),
        json={},
    )
    assert duplicate_not_found.status_code == 404


def test_post_like_toggle(client: TestClient) -> None:
    register_user(client)
    post = publish_completed_video(client)
    post_id = post["id"]
    assert post["like_count"] == 0
    assert post["liked"] is False
    assert post["favorited"] is False

    liked = client.put(f"/api/v1/community/posts/{post_id}/like", headers=csrf_headers(client))
    assert liked.status_code == 200
    assert liked.json() == {"liked": True}

    detail = client.get(f"/api/v1/community/posts/{post_id}").json()
    assert detail["like_count"] == 1
    assert detail["liked"] is True
    assert detail["favorite_count"] == 0
    assert detail["favorited"] is False

    unliked = client.put(f"/api/v1/community/posts/{post_id}/like", headers=csrf_headers(client))
    assert unliked.json() == {"liked": False}
    assert client.get(f"/api/v1/community/posts/{post_id}").json()["like_count"] == 0


def test_user_profile_and_follow(client: TestClient) -> None:
    owner = register_user(client, "follow-target@example.com")
    post = publish_completed_video(client)
    owner_id = owner["id"]

    viewer_session = client.cookies.get("clip_session")
    viewer_csrf = client.cookies.get("clip_csrf")
    client.cookies.clear()
    viewer = register_user(client, "follower@example.com")

    profile = client.get(f"/api/v1/users/{owner_id}").json()
    assert profile["id"] == owner_id
    assert profile["post_count"] == 1
    assert profile["is_following"] is False
    assert profile["is_self"] is False

    followed = client.put(f"/api/v1/users/{owner_id}/follow", headers=csrf_headers(client))
    assert followed.status_code == 200
    assert followed.json() == {"following": True}

    profile_after = client.get(f"/api/v1/users/{owner_id}").json()
    assert profile_after["follower_count"] == 1
    assert profile_after["is_following"] is True

    following_feed = client.get("/api/v1/community/posts?scope=following").json()
    assert following_feed["total"] == 1
    assert following_feed["items"][0]["id"] == post["id"]

    unfollowed = client.put(f"/api/v1/users/{owner_id}/follow", headers=csrf_headers(client))
    assert unfollowed.json() == {"following": False}
    assert client.get("/api/v1/community/posts?scope=following").json()["total"] == 0

    self_follow = client.put(f"/api/v1/users/{viewer['id']}/follow", headers=csrf_headers(client))
    assert self_follow.status_code == 409

    client.cookies.set("clip_session", viewer_session)
    client.cookies.set("clip_csrf", viewer_csrf)
    missing = client.get("/api/v1/users/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
