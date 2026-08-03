from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, Request

from backend.api.errors import ApiError
from backend.db.repository import Repository
from backend.infrastructure.security import token_hash


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    email: str
    user_created_at: str
    session_hash: str
    csrf_hash: str


def get_repository(request: Request) -> Repository:
    return request.app.state.repository


def require_auth(
    repository: Repository = Depends(get_repository),
    clip_session: str | None = Cookie(default=None),
) -> AuthContext:
    if not clip_session:
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "请先登录")
    session_hash = token_hash(clip_session)
    session = repository.get_session(session_hash)
    if not session:
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "登录已失效，请重新登录")
    return AuthContext(
        user_id=session["user_id"],
        email=session["email"],
        user_created_at=session["user_created_at"],
        session_hash=session_hash,
        csrf_hash=session["csrf_hash"],
    )


def require_csrf(
    context: AuthContext = Depends(require_auth),
    clip_csrf: str | None = Cookie(default=None),
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> AuthContext:
    if (
        not clip_csrf
        or not csrf_header
        or not hmac.compare_digest(clip_csrf, csrf_header)
        or not hmac.compare_digest(token_hash(csrf_header), context.csrf_hash)
    ):
        raise ApiError(403, "CSRF_FAILED", "安全校验失败，请刷新页面后重试")
    return context
