# Clip Agent

Clip Agent 是一个可本地运行的短视频生成智能体 MVP。它用 FastAPI 提供鉴权与任务 API，用 LangGraph 编排可中断、可检查点恢复的生成流程，用 Vue 3 提供剧本审核、分镜审核、预览和 BGM 决策界面。正常运行默认使用 `real` 供应商模式，真实请求 LLM、MiMo TTS 和 Pexels；确定性 `fake` 只能显式开启，用于开发和自动化测试。任务详情会显示创建时固化的供应商模式，避免把测试产物误认为真实调用结果。

## 已实现的用户流程

1. 使用邮箱和 8–128 位密码注册或登录。认证使用 HttpOnly 会话 Cookie，修改请求使用双提交 CSRF 保护。
2. 输入 3–1000 字符的主题、10–180 秒目标时长、`16:9` 或 `9:16` 比例，并选择 MiMo 音色；也可用冷知识科普、产品种草、历史人物、旅行攻略、读书分享或 AI 前沿模板一键填入创作主题。
3. LangGraph 生成结构化剧本，并通过 `interrupt` 暂停等待审核。退回时必须给出反馈；新剧本保留并递增版本。
4. 批准剧本后解析结构，生成结构化分镜，再次通过 `interrupt` 审核。退回分镜同样生成新版本。
5. 批准分镜后按稳定片段 ID 调用 MiMo `chat/completions` TTS。每段请求携带剧本的情绪/语速指令和任务音色；系统解码返回的 Base64 音频并转换为 WAV。由于情绪、停顿和标点会使供应商实际语速波动，系统再按各段原始时长比例通过 FFmpeg `atempo`（保持音高）校准到用户选择的总时长，以校准后 WAV 的真实整数毫秒时长建立时间轴。原始/校准音频和清单均独立保存，重试时校验复用。
6. Pexels 素材获取与按字符比例生成 SRT 在 LangGraph 中并行执行。每个镜头会进行分层英文查询，按查询相关度、真实音频目标时长、画面方向和清晰度评分，下载最优素材并计算裁剪起止点或循环参数；两支都完成后才汇合校验。
7. FFmpeg 把 SRT 以白字黑边样式烧录到视频画面，同时保留 MP4 可选字幕轨，渲染包含口播但不含 BGM 的预览视频。系统第三次 `interrupt`，等待 BGM 决策。
8. 最终 BGM 阶段点击“添加背景音乐”后会打开曲库弹窗，动态列出 `backend/bgms` 中的许可音乐并支持逐首试听，也可上传最大 25 MiB 的 MP3/WAV/M4A；上传文件经过 FFmpeg 解码验证并规范化到当前任务目录。选择不添加时直接使用无 BGM 预览；选择音乐时按成片时长循环裁剪、淡入淡出、限幅并只混合音轨，不重复渲染画面。混音完成后，任务详情的同一个预览播放器会刷新为含 BGM 的最终成片，预览与导出不再使用不同音轨版本。
9. 历史页展示总任务、已完成、待处理、进行中和累计成片时长；支持 400ms 防抖的主题搜索及审核/生成/完成/失败状态组合筛选。每条任务可展开逐场景口播与情绪指令、完整分镜及 Pexels 检索关键词，也可恢复、预览、导出、安全删除，或确认后沿用主题、时长、画幅和音色幂等创建“再次创作”任务。批量管理栏支持逐条勾选或跨分页全选当前用户的全部记录；整个集合会先通过状态与路径预检，避免部分删除。
10. 已完成视频可发布到社区，支持公开提示词、最多 3 个标签、评论与一级回复、评论点赞、独立的作品点赞与收藏、站内转发、复制永久链接和发布者作品软删除。作者名称可进入用户主页查看作品、粉丝/关注统计并关注或取关；“关注动态”只展示已关注作者的作品。
11. 设置页支持唯一昵称、2MB 内 JPG/PNG 头像裁剪以及验证旧密码的密码更新；密码更新会使所有现有会话失效。导航栏提供持久化的亮暗主题切换。
12. 新用户获得 5 次免费生成额度。账户中心支持一次性 CDK 充值、设置独立 6 位支付密码、查看余额流水，并使用余额购买 VIP（¥29.90/30 天，增加 30 次）或 SVIP（¥79.90/30 天，增加 100 次）。会员卡片先显示“立即购买”，点击后才弹出套餐与余额确认框并要求输入支付密码。任务创建与额度扣减原子执行，幂等重放不会重复扣次。
13. 独立 `admin/` 管理控制台提供六个页面：运营概览 `/`、用户管理 `/users`、跨用户任务监控 `/tasks`、CDK 管理 `/cdks`、安全审计 `/audit-logs` 和广告管理 `/ads`。概览展示会员与任务状态分布；用户页支持邮箱/昵称、启停、角色和会员组合筛选、分页、任务/流水详情、额度、角色、启停和登录密码管理；任务页可按主题、用户、状态及真实/测试供应商模式排查；审计页可追踪管理员和用户的关键安全动作。CDK 面额在界面以“元”输入并转换为后端整数分，支持快捷面额、状态筛选、分页、复制本批兑换码和一次性 CSV 导出。管理员不能直接修改余额；CDK 原文只在创建响应中显示一次，数据库仅保存不可逆摘要。
14. 广告管理支持上传 JPG、PNG 或保留动画的 GIF，配置安全的 HTTP/HTTPS 跳转链接、自动或指定页面投放、启停、编辑、删除，并查看曝光与点击统计。前台在历史、社区、新建任务和任务详情中按广告位置动态请求，用户可关闭；服务端只向免费账户返回广告，VIP/SVIP 即使直接请求接口也不会获得创意或图片。广告文件最大 5 MiB，并限制边长、解码像素与 GIF 帧数，存放在 `CLIP_MEDIA_ROOT/ads/<ad-id>/` 受控目录。

页面刷新、浏览器重新登录或后端重启不会丢失等待中的审核。执行中的任务会从最后一个安全检查点继续。

真实剧本节点采用 Dify 工作流同一套约束思路：提示词明确角色、主题、用户选择的目标时长、风格和画幅，要求每个场景提供地点、口播、纯字符数、视觉提示、完整 TTS 情绪指令、音频提示、语速档位、实际字/秒和估算时长。根据真实“冰糖”任务的 MiMo 音频表现，中文口播按约 3.15 个有效字符/秒计算动态总字数预算，例如 60 秒约 189 字；若模型实际字符数偏离预算，适配器会携带实际差值最多自动重写两次。服务端不信任模型自报时长，而按校准语速重算场景估算，并在 TTS 后以原始真实音频为依据做等比例节奏校准，确保用户目标时长、字幕和画面时间轴一致。分镜节点重新验证 `belongs_to_scene`、每场景 1–3 镜头、Pexels 英文查询词和画幅，并按剧本场景比例归一化计划时长。LLM 请求固定发送 `thinking: {"type":"disabled"}`；密钥、模型名和端点仍只来自服务端环境变量。

## 架构

```text
clip_agent/
├── agents/                         # 前端、后端和 HTTP API 契约
├── backend/
│   ├── api/                        # FastAPI DTO、依赖、错误与路由
│   ├── application/                # 后台执行、恢复与用例协调
│   ├── db/
│   │   └── migrations/             # 显式 SQLite 迁移
│   ├── domain/                     # 结构化剧本、分镜、时间轴等领域类型
│   ├── infrastructure/             # 鉴权、存储、供应商与 FFmpeg 适配器
│   ├── tools/                      # 显式执行的真实供应商验收工具
│   ├── workflow/                   # GraphState、节点、interrupt 与并行汇合
│   └── main.py                     # 应用入口
├── frontend/
│   ├── src/api/                    # 集中请求、CSRF 与错误映射
│   ├── src/components/             # 审核、BGM、状态与进度组件
│   ├── src/composables/            # 内存会话状态
│   ├── src/router/                 # 路由和访问控制
│   ├── src/types/                  # 与 API 契约一致的 TypeScript 类型
│   ├── src/views/                  # 登录、历史、新建、详情和设置页面
│   └── tests/                      # Vitest 组件与工具测试
├── admin/                           # 独立管理员控制台、测试与锁文件
├── tests/                          # 领域、API、安全、恢复和 fake E2E 测试
├── .env.example                    # 无凭据的部署配置示例
├── pyproject.toml / uv.lock        # Python 依赖及锁文件
└── frontend/package-lock.json      # 前端锁文件
```

业务 SQLite 和 LangGraph Checkpointer 使用两个数据库。工作流状态只保存小型、可序列化的引用与元数据；音频、字幕、素材、清单和视频位于 `CLIP_MEDIA_ROOT/<user-id>/<task-id>/`，广告创意位于 `CLIP_MEDIA_ROOT/ads/<ad-id>/`。外部副作用使用 `task_id + node + artifact/version` 对应的稳定清单，恢复或节点重试时会校验并复用已有产物。

运行时会记录不含提示词和凭据的逐节点耗时日志：`workflow node timing task_id=... node=... elapsed_ms=...`。性能关键路径已经做了三项约束：LLM 明确关闭思考；分段 TTS 最多 5 路并行；Pexels 查询按“精确查询失败才进入下一层”的真正回退策略执行，命中后不再无条件跑满 6 层。素材下载与 SRT 继续并行汇合，镜头预处理则使用最多 4 路 FFmpeg `veryfast` 编码，最后仅做无损拼接和音频/字幕封装。

完整 HTTP 方法、DTO、状态枚举、错误码、并发版本和恢复语义见 [`agents/api.md`](agents/api.md)。

## 环境要求

- Windows PowerShell（以下命令按此书写；其他平台使用等价命令）
- Python 3.10.9
- Node.js 24.18.1、npm 11.16.0
- 不需要系统安装 FFmpeg；`imageio-ffmpeg` 提供受控可执行文件

## 安装

在仓库根目录：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

也可以安装 `uv` 后使用锁文件：

```powershell
uv sync --extra dev --python 3.10.9
```

在 `frontend` 目录：

```powershell
npm install
```

在 `admin` 目录：

```powershell
npm install
```

`.env` 已被 `.gitignore` 忽略。不要提交真实密钥，也不要把供应商密钥写入任何 `VITE_*` 变量。若这个仓库的旧历史曾包含 `.env`，还应在协作平台轮换其中的真实凭据并按组织流程清理历史；仅加入 `.gitignore` 不能删除既有提交中的秘密。

## 配置

复制 `.env.example` 后必须填写真实供应商配置才能以默认 `real` 模式启动。只有本地开发或自动化测试才应显式改成 `CLIP_PROVIDER_MODE=fake`；前端在 fake 模式下会显示醒目警告。

| 变量 | 默认/是否必填 | 用途 |
| --- | --- | --- |
| `CLIP_PROVIDER_MODE` | `real` | `real` 发起真实 LLM、MiMo 和 Pexels 请求；`fake` 仅用于显式测试 |
| `CLIP_DATABASE_PATH` | `./data/clip_agent.sqlite3` | 用户、会话、设置、任务与审核数据库 |
| `CLIP_CHECKPOINT_PATH` | `./data/checkpoints.sqlite3` | LangGraph SQLite Checkpointer |
| `CLIP_MEDIA_ROOT` | `./data/media` | 受控任务媒体根目录 |
| `CLIP_SESSION_TTL_HOURS` | `168` | 服务端会话有效期 |
| `CLIP_COOKIE_SECURE` | 开发为 `false` | HTTPS 生产环境必须设为 `true` |
| `CLIP_ALLOWED_ORIGINS` | `http://localhost:5173` | 逗号分隔的可信前端源，不允许 `*` |
| `CLIP_ALLOWED_HOSTS` | 本地地址 | 逗号分隔的 Host 白名单 |
| `CLIP_PROVIDER_MAX_RETRIES` | `2` | 临时外部错误的有限退避重试次数 |
| `CLIP_MAX_DOWNLOAD_BYTES` | `52428800` | 单个远程素材最大字节数 |
| `LLM_BASE_URL` | real 必填 | OpenAI 兼容 API 根地址，代码调用 `chat/completions` |
| `LLM_API_KEY` | real 必填 | 只由服务端读取的 LLM 密钥 |
| `LLM_NAME` | real 必填 | 服务端模型名 |
| `LLM_TIMEOUT_SECONDS` | `120` | 单次 LLM 读取超时；连接/写入超时固定为 10 秒 |
| `TTS_BASE_URL` | real 必填 | MiMo API 根地址，适配器调用 `chat/completions` |
| `TTS_API_KEY` | real 必填 | 只由服务端读取，并以 `api-key` 请求头发送的 MiMo 密钥 |
| `TTS_NAME` | real 必填 | MiMo TTS 模型名；音色由每个任务选择，不从部署变量固定 |
| `TTS_TIMEOUT_SECONDS` | `90` | 单段 MiMo TTS 请求超时 |
| `PEXELS_BASE_URL` | real 必填 | Pexels API 根地址；下载仅允许 HTTPS 和 Pexels 媒体域名 |
| `PEXELS_API_KEY` | real 必填 | 只由服务端读取的 Pexels 密钥 |
| `PEXELS_TIMEOUT_SECONDS` | `20` | 单次 Pexels 搜索或素材下载读取超时 |
| `PEXELS_MAX_QUERIES` | `6` | 每镜头最多分层搜索次数，范围 1–6 |
| `PEXELS_PER_PAGE` | `15` | 每层候选数，范围 1–80 |
| `BGM_LIBRARY_DIR` | 可选 | 只读本地许可音乐目录，默认 `./backend/bgms`，支持 WAV/MP3/M4A；新增文件无需改代码或迁移 |

普通用户设置仅包含默认比例、时长、BGM 线性音量和 MiMo 音色偏好。前端及设置 API 都不能读取或修改上述服务端模型、端点和凭据；`GET /api/v1/capabilities` 只返回 `real/fake` 模式和非敏感音色列表。

MiMo 可选音色：

| 显示名 | Voice ID | 语言 | 性别 |
| --- | --- | --- | --- |
| MiMo-默认 | `mimo_default` | 因部署集群而异 | 因部署集群而异 |
| 冰糖 | `冰糖` | 中文 | 女性 |
| 茉莉 | `茉莉` | 中文 | 女性 |
| 苏打 | `苏打` | 中文 | 男性 |
| 白桦 | `白桦` | 中文 | 男性 |
| Mia | `Mia` | 英文 | 女性 |
| Chloe | `Chloe` | 英文 | 女性 |
| Milo | `Milo` | 英文 | 男性 |
| Dean | `Dean` | 英文 | 男性 |

## 运行

先在仓库根目录启动后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

再在 `frontend` 目录启动前端：

```powershell
npm run dev
```

打开 `http://127.0.0.1:5173`。Vite 会把 `/api` 代理到本地后端。后端健康检查位于 `http://127.0.0.1:8000/health`，OpenAPI 文档位于 `/docs`。

首次使用管理后台前，在仓库根目录运行以下命令。密码通过隐藏的交互输入读取，不要放进命令行、环境变量或脚本历史；已有用户会被安全提升，新邮箱会创建管理员：

```powershell
.\.venv\Scripts\python.exe -m backend.tools.manage_admin --email admin@example.com
```

随后在 `admin` 目录启动独立控制台并打开 `http://127.0.0.1:5174`。登录后的概览、用户管理、任务监控、CDK 管理、审计日志和广告管理地址分别为 `/`、`/users`、`/tasks`、`/cdks`、`/audit-logs`、`/ads`：

```powershell
npm run dev
```

若 Windows 报 `WinError 10013`，通常是本机端口被系统保留、安全软件拦截或已有进程占用，并非 FastAPI 路由错误。可先改用未占用端口验证：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8765
```

前端可在 `frontend/.env.local` 设置 `VITE_API_BASE_URL=http://127.0.0.1:8765`；不要为了绕过该错误把后端绑定到公网地址。本仓库已用 8765 端口完成本地 `/health` 探活，但端口是否空闲仍取决于你的机器。

## 验证与测试

后端命令在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -m ruff format --check backend tests
.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip check
```

前端命令在 `frontend` 目录运行：

```powershell
npm run typecheck
npm test
npm run build
```

管理员控制台命令在 `admin` 目录运行：

```powershell
npm run typecheck
npm run test
npm run build
```

无需外部密钥即可生成并严格探测一条 60 秒本地成片。该命令使用真正的 FFmpeg 渲染和项目
BGM，验证每段 WAV、连续时间线、SRT 全文与边界、画面切换、烧录字幕、MP4 音频/字幕流、画幅、
最终时长以及 BGM 混音；产物保存在 `data/fake-validation/<run-id>/`：

```powershell
.\.venv\Scripts\python.exe -m backend.tools.validate_fake_workflow --duration 60 --aspect-ratio 9:16 --bgm add
```

填写真实凭据后，可以显式执行完整真实验收。该命令会实际消耗 LLM、MiMo 和 Pexels 额度，自动批准剧本和分镜、选择“不添加 BGM”，保留独立数据库、检查点和媒体，并验证 WAV、时间轴、SRT、Pexels 文件及 MP4 音视频流：

```powershell
.\.venv\Scripts\python.exe -m backend.tools.validate_real_workflow --duration 60 --voice 冰糖
```

验收会额外检查校准后 MiMo 口播与用户目标时长、字幕尾时间和视频时长的误差，并探测画面非空、音轨有效和内嵌字幕轨。成功产物位于 `data/real-validation/<run-id>/`。若进程在外部调用或渲染阶段中断，可使用输出目录名从原 LangGraph 检查点恢复：

```powershell
.\.venv\Scripts\python.exe -m backend.tools.validate_real_workflow --resume-run-id <run-id>
```

后端测试不会调用付费服务，覆盖注册/会话/CSRF、用户越权、免费额度与幂等扣次、CDK 一次性充值、支付密码、会员余额支付、管理员越权/用户管理与强制改密、管理员组合筛选/全站任务监控/审计日志、广告上传验证/免费会员隔离/启停/统计/安全删除、音色与供应商模式、版本冲突、剧本和分镜退回/批准、内置与上传 BGM、BGM 两条分支、混音后预览/导出一致性、跨分页全选删除、检查点重启恢复、节点产物幂等复用、真实音频节奏校准/时间轴、SRT、并行汇合、对齐失败、路径穿越、SSRF、日志脱敏和任务删除。真实适配器通过本地 HTTP Mock 明确断言 LLM 请求、MiMo 的 `api-key`/音色/Base64 音频协议，以及 Pexels 多层请求/评分/裁剪计算；完整 fake E2E 和本地 FFmpeg MP4 冒烟测试仍保留。前台与管理员控制台分别包含 Vitest 组件测试和 TypeScript 生产构建验证。

## fake 与真实供应商边界

- `fake` LLM 根据输入稳定生成 Pydantic 剧本和分镜；fake TTS 生成具有真实可测时长的 WAV；fake Pexels 生成测试素材元数据。它不会发起任何外部供应商请求，前端和任务响应都会明确标记 `provider_mode=fake`。FFmpeg 仍会生成真正的 MP4，而不是空文件。
- `real` LLM 使用服务端配置的 OpenAI 兼容 `chat/completions`，剧本与分镜提示词完整约束字段、语速/时长、声画顺序和 Pexels 可检索性；模型 JSON 还必须通过服务端的 Pydantic 及交叉字段重算校验。
- `real` MiMo TTS 使用独立适配器调用 `chat/completions`，通过 `api-key` 鉴权，从 `choices[0].message.audio.data` 解码音频。它不是通用 `/audio/speech` 适配器。
- Pexels 实现会校验 HTTPS、允许域名、公开 DNS 地址、重定向、内容类型、响应大小和超时。素材作者、Pexels ID、许可、原始/目标时长、匹配查询、评分及裁剪参数写入任务清单。
- 本地 BGM 目录必须只放置你有权使用的音乐。当前 MVP 不替你取得第三方音乐许可。

真实供应商功能只有在填写相应部署级环境变量后才能人工验证。自动测试故意不会读取或调用这些密钥；使用 `CLIP_PROVIDER_MODE=real` 前请确认供应商账户额度和素材使用许可。若修改运行中的供应商模式，旧任务不会跨模式恢复，而会以 `PROVIDER_MODE_CHANGED` 安全失败，防止同一任务混用 fake 与 real 产物。

## 安全说明与 MVP 边界

- 密码使用带随机盐的 scrypt 哈希；登录失败不区分邮箱是否存在。
- 登录密码和支付密码使用相互独立、带领域前缀的 scrypt 哈希。金额只用人民币分整数；CDK 使用密码学安全随机源生成，只保存带领域前缀的 SHA-256 摘要和末四位提示。余额、订单、额度和 CDK 状态在 SQLite `BEGIN IMMEDIATE` 事务中更新，关键动作写审计记录。
- 所有数据库查询参数化；所有任务访问再次检查当前用户所有权。
- 媒体访问只接受数据库登记的相对引用。删除前验证目录边界并拒绝符号链接和 Windows reparse point。
- 日志过滤 Authorization、Cookie、密码、令牌和 API key；不会记录完整用户提示词、完整供应商响应或媒体内容。
- 后台执行器适合单机 MVP。多进程/多实例部署应把任务声明和执行队列升级为具备分布式租约的队列；SQLite 仍可用于本地开发，但不应直接当作大规模生产数据库。
- MVP 使用轮询（建议 2 秒）而非 SSE/WebSocket。前端在等待人工操作或终态时停止轮询。
- 会话 Cookie 在本地 HTTP 开发时可关闭 `Secure`；面向公网必须使用 HTTPS、启用 `CLIP_COOKIE_SECURE=true`，并配置准确的 Origin/Host 白名单。
