from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from backend.infrastructure.security import verify_password
from tests.conftest import csrf_headers, register_user


def create_task(client: TestClient, key: str) -> object:
    return client.post(
        "/api/v1/tasks",
        headers={**csrf_headers(client), "Idempotency-Key": key},
        json={
            "topic": f"额度测试主题 {key}",
            "target_duration_seconds": 10,
            "aspect_ratio": "9:16",
        },
    )


def test_free_quota_is_atomic_and_idempotent(client: TestClient) -> None:
    register_user(client, "quota@example.com")
    first = create_task(client, "quota-1")
    assert first.status_code == 201, first.text
    repeated = create_task(client, "quota-1")
    assert repeated.status_code == 201
    assert repeated.json()["id"] == first.json()["id"]
    for index in range(2, 6):
        assert create_task(client, f"quota-{index}").status_code == 201
    exhausted = create_task(client, "quota-6")
    assert exhausted.status_code == 409
    assert exhausted.json()["error"]["code"] == "QUOTA_EXHAUSTED"
    account = client.get("/api/v1/account").json()["account"]
    assert account["generation_quota"] == 5
    assert account["generations_used"] == 5
    assert account["generations_remaining"] == 0


def test_cdk_recharge_payment_and_admin_visibility(client: TestClient) -> None:
    admin = register_user(client, "admin@example.com")
    client.app.state.repository.promote_admin(admin["id"])
    assert client.get("/api/v1/auth/me").json()["role"] == "admin"
    generated = client.post(
        "/api/v1/admin/cdks",
        headers=csrf_headers(client),
        json={"amount_cents": 10_000, "count": 1},
    )
    assert generated.status_code == 201, generated.text
    code = generated.json()["items"][0]["code"]

    client.delete("/api/v1/auth/session", headers=csrf_headers(client))
    user = register_user(client, "buyer@example.com")
    ordinary_admin = client.get("/api/v1/admin/dashboard")
    assert ordinary_admin.status_code == 403
    assert ordinary_admin.json()["error"]["code"] == "ADMIN_REQUIRED"

    redeemed = client.post(
        "/api/v1/account/redeem-cdk", headers=csrf_headers(client), json={"code": code}
    )
    assert redeemed.status_code == 200
    assert redeemed.json()["balance_cents"] == 10_000
    reused = client.post(
        "/api/v1/account/redeem-cdk", headers=csrf_headers(client), json={"code": code}
    )
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "CDK_USED"

    needs_password = client.post(
        "/api/v1/account/memberships",
        headers=csrf_headers(client),
        json={"tier": "vip", "payment_password": "123456"},
    )
    assert needs_password.status_code == 409
    set_password = client.post(
        "/api/v1/account/payment-password",
        headers=csrf_headers(client),
        json={
            "account_password": "a-secure-test-password",
            "payment_password": "123456",
            "confirm_password": "123456",
        },
    )
    assert set_password.status_code == 204
    headers = {**csrf_headers(client), "Idempotency-Key": "vip-order-1"}
    purchased = client.post(
        "/api/v1/account/memberships",
        headers=headers,
        json={"tier": "vip", "payment_password": "123456"},
    )
    assert purchased.status_code == 201, purchased.text
    assert purchased.json()["account"]["balance_cents"] == 7010
    assert purchased.json()["account"]["membership_tier"] == "vip"
    assert purchased.json()["account"]["generation_quota"] == 35
    replay = client.post(
        "/api/v1/account/memberships",
        headers=headers,
        json={"tier": "vip", "payment_password": "123456"},
    )
    assert replay.json()["order"]["id"] == purchased.json()["order"]["id"]
    assert replay.json()["account"]["balance_cents"] == 7010

    client.delete("/api/v1/auth/session", headers=csrf_headers(client))
    client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "a-secure-test-password"},
    )
    listed = client.get("/api/v1/admin/cdks?status=used").json()
    assert listed["items"][0]["used_by"] == user["id"]
    assert listed["items"][0]["used_by_email"] == "buyer@example.com"
    assert "code" not in listed["items"][0]
    with sqlite3.connect(client.app.state.settings.database_path) as connection:
        stored_hash, hint = connection.execute("SELECT code_hash,code_hint FROM cdks").fetchone()
    assert code not in stored_hash
    assert code not in hint


def test_admin_can_manage_users_but_not_balance_or_self_lockout(client: TestClient) -> None:
    admin = register_user(client, "manager@example.com")
    client.app.state.repository.promote_admin(admin["id"])
    client.delete("/api/v1/auth/session", headers=csrf_headers(client))
    managed = register_user(client, "managed@example.com")
    client.delete("/api/v1/auth/session", headers=csrf_headers(client))
    client.post(
        "/api/v1/auth/login",
        json={"email": "manager@example.com", "password": "a-secure-test-password"},
    )
    reset = client.post(
        f"/api/v1/admin/users/{managed['id']}/password",
        headers=csrf_headers(client),
        json={"new_password": "ManagedNew1", "confirm_password": "ManagedNew1"},
    )
    assert reset.status_code == 204
    credentials = client.app.state.repository.get_user_credentials(managed["id"])
    assert credentials and verify_password("ManagedNew1", credentials["password_hash"])
    assert not verify_password("a-secure-test-password", credentials["password_hash"])
    updated = client.patch(
        f"/api/v1/admin/users/{managed['id']}",
        headers=csrf_headers(client),
        json={"is_active": False, "generation_quota": 20},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_active"] is False
    assert updated.json()["generation_quota"] == 20
    self_lockout = client.patch(
        f"/api/v1/admin/users/{admin['id']}",
        headers=csrf_headers(client),
        json={"is_active": False},
    )
    assert self_lockout.status_code == 409
    forbidden_balance = client.patch(
        f"/api/v1/admin/users/{managed['id']}",
        headers=csrf_headers(client),
        json={"balance_cents": 999_999},
    )
    assert forbidden_balance.status_code == 422


def test_admin_operations_pages_support_filters_and_safe_details(client: TestClient) -> None:
    admin = register_user(client, "operations@example.com")
    client.app.state.repository.promote_admin(admin["id"])
    client.delete("/api/v1/auth/session", headers=csrf_headers(client))
    member = register_user(client, "creator@example.com")
    task, _ = client.app.state.repository.create_task(
        user_id=member["id"],
        topic="后台监控任务",
        target_duration_seconds=30,
        aspect_ratio="16:9",
        voice_id="mimo_default",
        provider_mode="fake",
        idempotency_key=None,
        default_bgm_volume=0.2,
    )
    client.delete("/api/v1/auth/session", headers=csrf_headers(client))
    client.post(
        "/api/v1/auth/login",
        json={"email": "operations@example.com", "password": "a-secure-test-password"},
    )

    dashboard = client.get("/api/v1/admin/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["task_total"] == 1
    assert dashboard.json()["in_progress_tasks"] == 1
    assert dashboard.json()["vip_users"] == 0

    users = client.get("/api/v1/admin/users?q=creator&active=true&role=user&membership=free")
    assert users.status_code == 200
    assert users.json()["items"][0]["task_count"] == 1
    detail = client.get(f"/api/v1/admin/users/{member['id']}")
    assert detail.status_code == 200
    assert detail.json()["task_count"] == 1
    assert detail.json()["completed_task_count"] == 0
    assert detail.json()["recent_ledger"] == []

    tasks = client.get("/api/v1/admin/tasks?q=creator&status=queued&provider_mode=fake")
    assert tasks.status_code == 200
    assert tasks.json()["items"][0]["id"] == task["id"]
    assert tasks.json()["items"][0]["user_email"] == "creator@example.com"
    assert "thread_id" not in tasks.json()["items"][0]

    client.patch(
        f"/api/v1/admin/users/{member['id']}",
        headers=csrf_headers(client),
        json={"generation_quota": 10},
    )
    audits = client.get("/api/v1/admin/audit-logs?action=admin_user_updated")
    assert audits.status_code == 200
    assert audits.json()["items"][0]["actor_email"] == "operations@example.com"
    assert audits.json()["items"][0]["target_id"] == member["id"]
