from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from PIL import Image

from tests.conftest import csrf_headers, register_user


def animated_gif() -> bytes:
    output = io.BytesIO()
    frames = [Image.new("RGB", (320, 120), color) for color in ("#0f766e", "#0284c7")]
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=120,
        loop=0,
    )
    return output.getvalue()


def create_admin_ad(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/admin/ads",
        headers=csrf_headers(client),
        data={
            "title": "创作工具限时体验",
            "link_url": "https://example.com/campaign",
            "placement": "auto",
            "is_active": "true",
        },
        files={"file": ("campaign.gif", animated_gif(), "image/gif")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_manages_ads_and_only_free_users_receive_them(client: TestClient) -> None:
    admin = register_user(client, "ads-admin@example.com")
    client.app.state.repository.promote_admin(admin["id"])
    ad = create_admin_ad(client)
    assert ad["image_media_type"] == "image/gif"
    assert ad["impressions"] == 0
    assert ad["clicks"] == 0

    admin_image = client.get(ad["image_url"])
    assert admin_image.status_code == 200
    assert admin_image.headers["content-type"].startswith("image/gif")
    assert admin_image.headers["cache-control"] == "private, no-store"
    assert admin_image.content.startswith(b"GIF")
    listed = client.get("/api/v1/admin/ads?active=true&placement=auto")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == ad["id"]

    client.delete("/api/v1/auth/session", headers=csrf_headers(client))
    free_user = register_user(client, "ad-viewer@example.com")
    selection = client.get("/api/v1/ads?slot=history")
    assert selection.status_code == 200
    creative = selection.json()["item"]
    assert creative["id"] == ad["id"]
    assert "impressions" not in creative
    public_image = client.get(creative["image_url"])
    assert public_image.status_code == 200
    assert public_image.headers["cache-control"] == "private, no-store"
    for event in ("impression", "click"):
        result = client.post(
            f"/api/v1/ads/{ad['id']}/events",
            headers=csrf_headers(client),
            json={"event": event},
        )
        assert result.status_code == 204

    expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat().replace("+00:00", "Z")
    with client.app.state.repository.transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE users SET membership_tier='vip', membership_expires_at=? WHERE id=?",
            (expires, free_user["id"]),
        )
    assert client.get("/api/v1/ads?slot=history").json() == {"item": None}
    assert client.get(creative["image_url"]).status_code == 404
    denied_event = client.post(
        f"/api/v1/ads/{ad['id']}/events",
        headers=csrf_headers(client),
        json={"event": "click"},
    )
    assert denied_event.status_code == 404

    client.delete("/api/v1/auth/session", headers=csrf_headers(client))
    client.post(
        "/api/v1/auth/login",
        json={"email": "ads-admin@example.com", "password": "a-secure-test-password"},
    )
    refreshed = client.get("/api/v1/admin/ads").json()["items"][0]
    assert refreshed["impressions"] == 1
    assert refreshed["clicks"] == 1
    disabled = client.patch(
        f"/api/v1/admin/ads/{ad['id']}",
        headers=csrf_headers(client),
        json={"is_active": False, "placement": "community"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert disabled.json()["placement"] == "community"
    deleted = client.delete(f"/api/v1/admin/ads/{ad['id']}", headers=csrf_headers(client))
    assert deleted.status_code == 204
    assert client.get(ad["image_url"]).status_code == 404


def test_ad_upload_validates_admin_image_and_external_link(client: TestClient) -> None:
    register_user(client, "ordinary-ad-user@example.com")
    forbidden = client.post(
        "/api/v1/admin/ads",
        headers=csrf_headers(client),
        data={"title": "无权上传", "link_url": "https://example.com"},
        files={"file": ("creative.gif", animated_gif(), "image/gif")},
    )
    assert forbidden.status_code == 403

    client.app.state.repository.promote_admin(client.get("/api/v1/auth/me").json()["id"])
    invalid_link = client.post(
        "/api/v1/admin/ads",
        headers=csrf_headers(client),
        data={"title": "危险链接", "link_url": "javascript:alert(1)"},
        files={"file": ("creative.gif", animated_gif(), "image/gif")},
    )
    assert invalid_link.status_code == 422
    assert invalid_link.json()["error"]["code"] == "INVALID_LINK_URL"
    invalid_image = client.post(
        "/api/v1/admin/ads",
        headers=csrf_headers(client),
        data={"title": "伪造图片", "link_url": "https://example.com"},
        files={"file": ("creative.gif", b"not-an-image", "image/gif")},
    )
    assert invalid_image.status_code == 422
    assert invalid_image.json()["error"]["code"] == "INVALID_AD_IMAGE"
