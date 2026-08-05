from __future__ import annotations

import argparse
import getpass

from backend.config import get_settings
from backend.db.repository import DuplicateEmailError, Repository
from backend.infrastructure.security import hash_password, normalize_email


def main() -> int:
    parser = argparse.ArgumentParser(description="创建或提升 Clip Agent 管理员")
    parser.add_argument("--email", required=True, help="管理员邮箱")
    args = parser.parse_args()
    try:
        email = normalize_email(args.email)
    except ValueError as error:
        parser.error("邮箱格式无效")
        raise error

    repository = Repository(get_settings().database_path)
    repository.initialize()
    user = repository.get_user_by_email(email)
    if user is None:
        password = getpass.getpass("新管理员登录密码: ")
        confirmation = getpass.getpass("再次输入密码: ")
        if password != confirmation or len(password) < 8:
            parser.error("密码必须一致且至少 8 个字符")
        try:
            user = repository.create_user(email, hash_password(password))
        except DuplicateEmailError:
            user = repository.get_user_by_email(email)
    assert user is not None
    repository.promote_admin(user["id"])
    print(f"管理员已就绪: {email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
