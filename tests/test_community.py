from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import csrf_headers, register_user, wait_for_status
from tests.test_e2e_workflow import create_video, submit_review


def complete_video(client: TestClient) -> str:
    task_id = create_video(client, "社区发布测试视频")["id"]
    script = wait_for_status(client, task_id, "awaiting_script_review")
    submit_review(client, task_id, "script", script["pending_review"]["version"], "approve")
    storyboard = wait_for_status(client, task_id, "awaiting_storyboard_review")
    submit_review(client, task_id, "storyboard", storyboard["pending_review"]["version"], "approve")
    bgm = wait_for_status(client, task_id, "awaiting_bgm_decision")
    response = client.post(
        f"/api/v1/tasks/{task_id}/bgm-decision",
        headers=csrf_headers(client),
        json={"version": bgm["pending_review"]["version"], "action": "no_add", "volume": None},
    )
    assert response.status_code == 202
    wait_for_status(client, task_id, "completed")
    return task_id


def test_community_publish_comment_reply_like_share_favorite_and_delete(client: TestClient) -> None:
    owner = register_user(client, "community-owner@example.com")
    task_id = complete_video(client)
    published = client.post(
        "/api/v1/community/posts",
        headers=csrf_headers(client),
        json={
            "task_id": task_id,
            "title": "海洋作品",
            "description": "一条完整生成的视频",
            "prompt_public": True,
            "tags": ["AI", "海洋"],
        },
    )
    assert published.status_code == 201, published.text
    post = published.json()
    post_id = post["id"]
    assert post["generation_prompt"] == "社区发布测试视频"
    assert client.get(post["video_url"]).status_code == 200

    root = client.post(
        f"/api/v1/community/posts/{post_id}/comments",
        headers=csrf_headers(client),
        json={"content": "作者评论", "parent_id": None},
    ).json()
    assert client.put(
        f"/api/v1/community/comments/{root['id']}/like", headers=csrf_headers(client)
    ).json() == {"liked": True}
    assert client.put(
        f"/api/v1/community/posts/{post_id}/favorite", headers=csrf_headers(client)
    ).json() == {"favorited": True}

    owner_session = client.cookies.get("clip_session")
    owner_csrf = client.cookies.get("clip_csrf")
    client.cookies.clear()
    recipient = register_user(client, "community-recipient@example.com")
    reply = client.post(
        f"/api/v1/community/posts/{post_id}/comments",
        headers=csrf_headers(client),
        json={"content": "回复作者", "parent_id": root["id"]},
    )
    assert reply.status_code == 201
    nested = client.post(
        f"/api/v1/community/posts/{post_id}/comments",
        headers=csrf_headers(client),
        json={"content": "不允许三级回复", "parent_id": reply.json()["id"]},
    )
    assert nested.status_code == 409

    client.cookies.clear()
    client.cookies.set("clip_session", owner_session)
    client.cookies.set("clip_csrf", owner_csrf)
    shared = client.post(
        f"/api/v1/community/posts/{post_id}/shares",
        headers=csrf_headers(client),
        json={"recipient_id": recipient["id"]},
    )
    assert shared.status_code == 201
    assert (
        client.delete(
            f"/api/v1/community/comments/{root['id']}", headers=csrf_headers(client)
        ).status_code
        == 204
    )
    assert client.get(f"/api/v1/community/posts/{post_id}/comments").json()["items"] == []

    assert (
        client.delete(
            f"/api/v1/community/posts/{post_id}", headers=csrf_headers(client)
        ).status_code
        == 204
    )
    assert client.get(f"/api/v1/community/posts/{post_id}").status_code == 404
    assert client.get("/api/v1/community/posts?scope=mine").json()["total"] == 0
    assert owner["id"] != recipient["id"]
