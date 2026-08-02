# Project Overview

本项目将已登录用户提供的主题转换为可审核、可追溯的短视频成片，编排脚本生成、两阶段人工审核、分镜规划、MiMo 语音合成、修复循环与视频合成。系统边界止于成片生成和历史记录持久化，不自动发布内容、不绕过人工审核、不在图状态中保存明文密钥。

# Tech Stack

- Backend:  `clip_agent\.venv`、Python 3.10.9、LangChain latest、LangGraph latest
- Frontend: Node.js v24.18.1、npm 11.16.0、Vue 3.5+、TypeScript 5.6+
- Database: SQLite 3.45+、LangGraph SQLite Checkpointer
- Testing & Quality: pytest 8+、Ruff 0.12+

# Project Structure

```text
clip_agent/
├── AGENTS.md                         # 核心约束与按需阅读导航
├── harness.yaml                      # 环境、MiMo 工具及最小权限配置
├── pyproject.toml                    # Python 版本、运行与开发依赖
├── PROGRESS.md                       # 实施状态与阻塞项
├── README.md                         # 项目描述文件
├── backend/
│   ├── __init__.py                   # 后端包边界
│   ├── main.py                       # 最小 ASGI 开发入口
│   └── workflow.py                   # 可执行状态、路由与图构建实现
├── frontend/
│   ├── index.html                    # Vite HTML 入口
│   ├── package.json                  # Vue 开发与构建依赖
│   ├── tsconfig.json                 # TypeScript 严格模式配置
│   ├── vite.config.ts                # Vue Vite 插件配置
│   └── src/
│       ├── App.vue                   # 根组件
│       └── main.ts                   # Vue 应用挂载入口
├── docs/
│   └── architecture.md               # AgentState、路由、HITL 与中间件契约
├── agents/
│   ├── script_generator.md           # 脚本生成节点契约
│   ├── human_review_script.md        # 脚本人工审核节点契约
│   ├── storyboard_planner.md         # 分镜规划节点契约
│   ├── human_review_storyboard.md    # 分镜人工审核节点契约
│   ├── tts_synthesizer.md            # Xiaomi MiMo TTS 节点契约
│   ├── video_composer.md             # 视频合成节点契约
│   └── repair_agent.md               # 驳回修复与回审节点契约
└── tests/
    └── test_workflow.py              # 状态、审核中断和真实路由测试
```

职责分离：本文件仅保存全局约束与导航；状态、路由、提示词和测试细节分别由对应子文件维护。

# Build & Test Commands

```powershell
.\.venv\Scripts\python.exe -m ensurepip --upgrade
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
npm --prefix frontend install
npm --prefix frontend run dev
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check .
```

# Safety & Constraints

- 禁止在代码、提示词、图状态、日志、测试夹具或版本库中硬编码 API 密钥、令牌和用户密码。
- 禁止使用 `eval`、`exec`、不受限动态导入，或将用户输入直接拼接为系统命令、SQL 和文件路径。
- 所有业务请求必须先通过认证与资源归属中间件；节点只能访问当前 `user_id` 的配置、历史和媒体。
- 用户密钥必须加密存储并按引用获取；密钥值不得进入 `AgentState`、检查点或审计事件。
- 人工审核必须使用 LangGraph `interrupt()`、持久化 SQLite checkpointer 和稳定 `thread_id`；恢复时必须复用原线程。
- `approval_status` 仅允许 `PENDING`、`APPROVED`、`REJECTED`；`REJECTED` 必须进入 `repair_agent`，不得绕过回审。
- 修复次数必须在开始新一轮修复前校验；达到上限后进入失败终态，禁止无限循环。
- 节点只能读写其契约声明的状态字段；跨节点追加字段必须配置显式 reducer。
- MiMo 调用只能使用 `harness.yaml` 中的模型、Voice ID、域名和输出格式白名单。
- 文件与网络访问遵循最小权限；日志只记录脱敏元数据，严禁跨用户路径和私网探测。

# Navigation Map

| Path | Core purpose |
| --- | --- |
| `harness.yaml` | 环境变量、MiMo 模型与音色、文件和网络权限。 |
| `pyproject.toml` | Python 3.10.9 及运行、测试、检查依赖。 |
| `PROGRESS.md` | 读取任务状态、完成标准和阻塞项。 |
| `backend/__init__.py` | 声明后端 Python 包边界。 |
| `backend/main.py` | 后端开发服务器入口与健康检查。 |
| `backend/workflow.py` | 测试和运行时共用的真实状态、路由与图构建实现。 |
| `frontend/index.html` | Vite 页面入口。 |
| `frontend/package.json` | Vue3 前端开发与构建命令。 |
| `frontend/tsconfig.json` | TypeScript 编译与严格类型设置。 |
| `frontend/vite.config.ts` | Vite 和 Vue 插件配置。 |
| `frontend/src/App.vue` | 前端根组件。 |
| `frontend/src/main.ts` | Vue 应用启动入口。 |
| `docs/architecture.md` | 修改 AgentState、LangGraph 路由、HITL 或中间件前必读。 |
| `agents/script_generator.md` | 脚本生成的字段、提示词和约束。 |
| `agents/human_review_script.md` | 脚本审核中断、审批结果和反馈契约。 |
| `agents/storyboard_planner.md` | 分镜生成的字段、提示词和约束。 |
| `agents/human_review_storyboard.md` | 分镜审核中断、审批结果和反馈契约。 |
| `agents/tts_synthesizer.md` | Xiaomi MiMo Voice ID 选择与音频合成契约。 |
| `agents/video_composer.md` | 已审核分镜、音频和素材的成片合成契约。 |
| `agents/repair_agent.md` | 按审核目标修复并返回对应审核节点的契约。 |
| `tests/test_workflow.py` | 导入真实路由实现，验证通过、驳回、恢复和上限行为。 |

# 重要提醒
- 每一次修改都需要检查是否需要修改readme.md文件，如需修改则修改
