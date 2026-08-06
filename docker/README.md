# Clip Agent Docker 打包

本目录提供把项目打成 Docker 镜像的配置。采用三服务 Compose：后端（FastAPI/uvicorn）、前端（Vue 构建产物 + nginx）、管理台（Vue 构建产物 + nginx）。**只负责打包与运行编排，不修改任何源码。**

```text
docker/
├── Dockerfile.backend     # python:3.10-slim + 项目依赖；FFmpeg 由 imageio-ffmpeg 自带
├── Dockerfile.frontend    # node 构建前端 → nginx 运行
├── Dockerfile.admin       # node 构建管理台 → nginx 运行
├── docker-compose.yml     # backend / frontend / admin 三服务编排
├── nginx/
│   ├── frontend.conf      # 前端站点：/api 代理到 backend
│   └── admin.conf         # 管理台站点：/api 代理到 backend
├── .env.example           # 部署环境变量示例（无真实凭据）
└── README.md
```

## 架构

- 前端与管理台的生产构建走同源代理：浏览器访问 `http://localhost:8080/api/...`，由 nginx 转发到内部 `backend:8000`。API 客户端默认相对路径，无需配置 `VITE_API_BASE_URL`。
- 后端数据（业务 SQLite、LangGraph 检查点、任务媒体）写入 `/data`，由 compose 命名卷 `clip-data` 持久化。
- 后端镜像自带 `imageio-ffmpeg` 的静态 FFmpeg 二进制与 `backend/bgms` 内置许可曲库，无需额外安装 FFmpeg。
- `docker-compose.yml` 中 `build.context` 指向仓库根 `..`，根目录的 `.dockerignore` 排除了本地开发文件与产物。

## 打包（不运行）

前置：已安装 Docker 与 Docker Compose（`docker --version`、`docker compose version`）。

1. 准备环境变量：

   ```powershell
   Copy-Item docker\.env.example docker\.env
   ```

   编辑 `docker\.env`：`real` 模式必须填写 LLM / MiMo TTS / Pexels 的 `BASE_URL`、`API_KEY`、`NAME`；仅测试时可显式改为 `CLIP_PROVIDER_MODE=fake`。不要提交任何真实凭据。

2. 构建镜像：

   ```powershell
   docker compose -f docker\docker-compose.yml build
   ```

   只执行打包，不会启动容器。

## 运行（按需）

```powershell
docker compose -f docker\docker-compose.yml up -d
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:8080 |
| 管理台 | http://localhost:8081 |

首次使用管理台前创建管理员（密码通过隐藏的交互输入读取，不要放进命令行或脚本历史）：

```powershell
docker compose -f docker\docker-compose.yml exec backend python -m backend.tools.manage_admin --email admin@example.com
```

停止并移除容器：

```powershell
docker compose -f docker\docker-compose.yml down
```

如需同时清空数据卷（会删除数据库、检查点与全部任务媒体）：

```powershell
docker compose -f docker\docker-compose.yml down -v
```

## 数据与安全

- 数据保存在命名卷 `clip-data`，实际位置可用 `docker volume inspect clip_agent_clip-data` 查看；重建容器不会丢失数据。
- 公网生产必须通过 HTTPS 访问，并将 `docker\.env` 中的 `CLIP_COOKIE_SECURE` 改为 `true`；同时按实际域名调整 `CLIP_ALLOWED_ORIGINS` 与 `CLIP_ALLOWED_HOSTS` 白名单，不允许 `*`。
- 详细环境变量说明见仓库根 `README.md` 的「配置」小节。
