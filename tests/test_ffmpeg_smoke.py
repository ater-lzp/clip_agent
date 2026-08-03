from __future__ import annotations

from backend.application.workflow_service import WorkflowService
from backend.db.repository import Repository
from backend.infrastructure.security import hash_password


def test_default_fake_providers_render_a_playable_mp4(test_settings) -> None:
    test_settings.ensure_directories()
    repository = Repository(test_settings.database_path)
    repository.initialize()
    user = repository.create_user("ffmpeg@example.com", hash_password("a-secure-password"))
    task, _ = repository.create_task(
        user_id=user["id"],
        topic="本地渲染冒烟测试",
        target_duration_seconds=10,
        aspect_ratio="16:9",
        voice_id="mimo_default",
        provider_mode="fake",
        idempotency_key=None,
        default_bgm_volume=0.2,
    )
    service = WorkflowService(test_settings, repository)
    try:
        service.run_now(task["id"])
        repository.claim_review(
            user_id=user["id"],
            task_id=task["id"],
            kind="script",
            version=1,
            action="approve",
        )
        service.run_now(task["id"])
        repository.claim_review(
            user_id=user["id"],
            task_id=task["id"],
            kind="storyboard",
            version=1,
            action="approve",
        )
        service.run_now(task["id"])
        review = repository.get_task(user["id"], task["id"])
        preview_path = service.store.resolve_registered_path(
            user["id"], task["id"], review["preview_relative_path"]
        )
        assert preview_path.stat().st_size > 1000
        assert preview_path.read_bytes()[4:8] == b"ftyp"

        repository.claim_review(
            user_id=user["id"],
            task_id=task["id"],
            kind="bgm",
            version=1,
            action="add",
            volume=0.2,
        )
        service.run_now(task["id"])
        completed = repository.get_task(user["id"], task["id"])
        assert completed["status"] == "completed"
        assert completed["bgm_added"] is True
        final_path = service.store.resolve_registered_path(
            user["id"], task["id"], completed["final_relative_path"]
        )
        assert final_path.read_bytes()[4:8] == b"ftyp"
    finally:
        service.close()
