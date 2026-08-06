# Clip Agent

Clip Agent 是一个可本地运行的短视频生成智能体 MVP：FastAPI 提供鉴权与任务 API，LangGraph 编排可中断、可检查点恢复的生成流程，Vue 3 提供剧本/分镜审核、预览和 BGM 决策界面。默认使用 `real` 供应商模式真实请求 LLM、MiMo TTS 和 Pexels；确定性 `fake` 模式仅用于开发和自动化测试。

## 功能一览

- 邮箱注册/登录（HttpOnly 会话 Cookie + 双提交 CSRF），昵称、头像、亮暗主题、密码更新等设置。
- 按主题、目标时长、画幅与音色创建任务；生成剧本与分镜并 `interrupt` 人工审核（退回需反馈，版本递增）。
- MiMo TTS 分段配音并按原时长比例经 FFmpeg `atempo` 校准，保证口播、字幕与画面时间轴一致。
- Pexels 分层查询、下载素材、按字符比例生成 SRT；FFmpeg 烧录字幕并渲染预览视频。
- BGM 阶段可从 `backend/bgms` 曲库选择或上传，混音后预览/导出使用同一份成片。
- 历史页筛选/搜索、恢复、预览、导出、安全删除与"再次创作"；已完成视频可发布到社区（评论、点赞、收藏、关注、转发）。
- 免费额度、CDK 充值、支付密码、余额购买 VIP/SVIP 会员。
- 独立 `admin/` 管理控制台：运营概览、用户/任务/CDK 管理、安全审计与广告管理。

## 架构

```text
clip_agent/
├── agents/                         # 前端、后端和 HTTP API 契约
├── backend/                        # FastAPI API、LangGraph 工作流、领域与基础设施适配器
├── frontend/                       # Vue 3 + TypeScript 用户端
├── admin/                          # 独立 Vue 3 管理员控制台
├── tests/                          # 领域、API、安全、恢复和 fake E2E 测试
├── docker/                         # Docker 打包配置（Dockerfile、compose、nginx）
├── .env.example                    # 无凭据的部署配置示例
└── pyproject.toml / uv.lock        # Python 依赖及锁文件
```

业务 SQLite 与 LangGraph 检查点使用两个数据库；音频、字幕、素材和视频位于 `CLIP_MEDIA_ROOT/<user-id>/<task-id>/`，广告创意位于 `CLIP_MEDIA_ROOT/ads/<ad-id>/`。外部副作用使用稳定清单校验复用，恢复或重试不重复产生副作用。完整 HTTP 方法、DTO、状态枚举与恢复语义见 [`agents/api.md`](agents/api.md)。

## Docker 部署（推荐）

打包与运行配置在 `docker/` 目录，详见 [`docker/README.md`](docker/README.md)。

```bash
cp docker/.env.example docker/.env   # 编辑并填写供应商凭据（测试可改 CLIP_PROVIDER_MODE=fake）
docker compose -f docker/docker-compose.yml build   # 打包
docker compose -f docker/docker-compose.yml up -d   # 运行
```

前端 `http://localhost:8080`，管理台 `http://localhost:8081`。首次创建管理员：

```bash
docker compose -f docker/docker-compose.yml exec backend python -m backend.tools.manage_admin --email admin@example.com
```

数据（SQLite、检查点、媒体）保存在命名卷 `clip-data`，重建容器不丢失。

## 本地开发

环境要求：Python 3.10.9、Node.js 24、npm 11。无需系统安装 FFmpeg（`imageio-ffmpeg` 提供受控可执行文件）。

```powershell
# 根目录：后端
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# frontend 目录
npm install && npm run dev          # 打开 http://127.0.0.1:5173

# admin 目录
npm install && npm run dev          # 打开 http://127.0.0.1:5174
```

健康检查 `http://127.0.0.1:8000/health`，OpenAPI 文档 `/docs`。也可用 `uv sync --extra dev --python 3.10.9` 安装。

### 配置

复制 `.env.example` 后填写真实供应商配置才能以默认 `real` 模式启动；只有本地开发或自动化测试才显式改为 `CLIP_PROVIDER_MODE=fake`（前端会显示醒目警告）。关键变量：

| 变量 | 默认/是否必填 | 用途 |
| --- | --- | --- |
| `CLIP_DATABASE_PATH` / `CLIP_CHECKPOINT_PATH` / `CLIP_MEDIA_ROOT` | `./data/...` | 业务库、检查点、媒体根目录 |
| `CLIP_ALLOWED_ORIGINS` / `CLIP_ALLOWED_HOSTS` | 本地地址 | 可信源与 Host 白名单，不允许 `*` |
| `CLIP_COOKIE_SECURE` | `false` | 公网 HTTPS 生产必须 `true` |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_NAME` | real 必填 | OpenAI 兼容结构输出端点 |
| `TTS_BASE_URL` / `TTS_API_KEY` / `TTS_NAME` | real 必填 | MiMo `chat/completions` TTS |
| `PEXELS_BASE_URL` / `PEXELS_API_KEY` | real 必填 | Pexels 素材检索 |
| `BGM_LIBRARY_DIR` | `./backend/bgms` | 只读本地许可音乐目录 |

MiMo 可选音色：`冰糖`、`茉莉`、`苏打`、`白桦`（中文），`Mia`、`Chloe`、`Milo`、`Dean`（英文）。服务端模型名、端点和凭据只由环境配置读取，普通用户不能读取或修改。

## 测试

后端命令在根目录，前端/管理台命令在各子目录：

```powershell
.\.venv\Scripts\python.exe -m ruff format --check backend tests
.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m pytest
npm run typecheck && npm test && npm run build     # frontend 与 admin 分别执行
```

无需外部密钥即可本地验证一条 60 秒成片（真实 FFmpeg 渲染）：

```powershell
.\.venv\Scripts\python.exe -m backend.tools.validate_fake_workflow --duration 60 --aspect-ratio 9:16 --bgm add
```

## 安全边界与 MVP 边界

- 密码使用 scrypt 哈希；日志脱敏，不记录凭据、完整提示词或媒体内容；数据库查询全部参数化，媒体访问只接受数据库登记的相对引用。
- 后台执行器适合单机 MVP；多进程/多实例部署应升级为带分布式租约的队列，SQLite 不应用作大规模生产数据库。
- 本地 BGM 目录必须只放置你有权使用的音乐。
- 会话 Cookie 本地开发可关闭 `Secure`；面向公网必须 HTTPS、启用 `CLIP_COOKIE_SECURE=true`，并配置准确的 Origin/Host 白名单。
