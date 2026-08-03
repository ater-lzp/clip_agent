# Clip Agent HTTP API 契约

## 1. 通用约定

- API 版本前缀：`/api/v1`。
- 请求与响应正文使用 UTF-8 JSON；媒体端点除外。
- 时间为带时区的 UTC ISO 8601，例如 `2026-08-03T02:15:30Z`。
- 时长传输单位为秒；工作流内部时间轴使用整数毫秒。BGM 音量统一为 `0.0..1.0` 的线性增益。
- 资源 ID 是 UUID 字符串。客户端不得从 ID 推测所有权。
- 长任务使用轮询：任务处于非终态时，客户端建议每 2 秒调用详情端点；页面离开后停止轮询。没有 SSE/WebSocket 契约。
- 所有响应包含 `X-Request-ID`。客户端可以发送合法的 `X-Request-ID`，否则服务端生成。
- 创建任务可以发送最多 128 字符的 `Idempotency-Key`。同一用户、同一键、同一请求返回原任务；同一键但请求不同返回 `409 IDEMPOTENCY_CONFLICT`。

### 1.1 会话与 CSRF

认证使用服务端会话和 `clip_session` HttpOnly Cookie。注册或登录成功还会设置可读的 `clip_csrf` Cookie。除注册、登录外，所有 `POST`、`PUT`、`PATCH`、`DELETE` 请求必须将该值原样放入 `X-CSRF-Token` 请求头。Cookie 使用 `SameSite=Lax`；生产环境通过配置启用 `Secure`。

所有用户、设置、任务、审核、预览、导出和删除资源均按当前会话所有者隔离。为了避免资源枚举，访问其他用户的任务统一返回 `404 TASK_NOT_FOUND`。

### 1.2 错误格式

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求字段无效",
    "request_id": "25bc867d-89e5-4cc0-8272-8c4deab340d7",
    "fields": [{"field": "target_duration_seconds", "message": "必须介于 10 和 180 之间"}],
    "retryable": false
  }
}
```

`fields` 仅用于字段错误，可以省略。服务端不会返回堆栈、内部文件路径、凭据或供应商原始错误。

稳定错误码：

| HTTP | code | 含义 |
| --- | --- | --- |
| 400 | `INVALID_REQUEST` | 请求语义无效 |
| 401 | `AUTHENTICATION_REQUIRED`、`INVALID_CREDENTIALS` | 未登录或登录失败 |
| 403 | `CSRF_FAILED` | CSRF 校验失败 |
| 404 | `TASK_NOT_FOUND`、`MEDIA_NOT_FOUND` | 当前用户不可见的资源不存在 |
| 409 | `EMAIL_EXISTS`、`STATE_CONFLICT`、`VERSION_CONFLICT`、`IDEMPOTENCY_CONFLICT` | 唯一性、状态或并发版本冲突 |
| 413 | `PAYLOAD_TOO_LARGE` | 请求或下载资源超过限制 |
| 422 | `VALIDATION_ERROR` | 字段校验失败 |
| 429 | `RATE_LIMITED` | 暂时限流 |
| 502 | `PROVIDER_ERROR` | 外部服务永久失败 |
| 503 | `PROVIDER_UNAVAILABLE` | 外部服务暂时不可用，可重试 |
| 500 | `INTERNAL_ERROR` | 已脱敏的内部错误 |

## 2. 领域枚举与结构

### 2.1 任务状态 `TaskStatus`

```text
queued
generating_script
awaiting_script_review
generating_storyboard
awaiting_storyboard_review
synthesizing_audio
building_timeline
fetching_assets
aligning_timeline
rendering_preview
awaiting_bgm_decision
processing_bgm
completed
failed
```

终态是 `completed`、`failed`。`awaiting_script_review`、`awaiting_storyboard_review`、`awaiting_bgm_decision` 是正常、可恢复且需要用户操作的中断状态，不是失败。

### 2.2 输入与生成产物

```ts
type AspectRatio = "16:9" | "9:16";
type ReviewAction = "approve" | "reject";
type BgmAction = "no_add" | "add";
type ProviderMode = "real" | "fake";
type MimoVoiceId =
  | "mimo_default"
  | "冰糖"
  | "茉莉"
  | "苏打"
  | "白桦"
  | "Mia"
  | "Chloe"
  | "Milo"
  | "Dean";

interface ScriptSegment {
  id: string;
  order: number;
  location: string;
  narration: string;
  narration_char_count: number;
  visual_intent: string;
  emotion: string;
  audio_cue: string;
  speed_tier: "慢速" | "中速" | "快速" | null;
  speed_value: number | null;
  estimated_duration_seconds: number;
}

interface ScriptArtifact {
  version: number;
  title: string;
  platform: string;
  aspect_ratio: AspectRatio;
  total_duration_seconds: number;
  hook: string;
  segments: ScriptSegment[];
  closing: string;
  bgm_query: string;
}

interface StoryboardShot {
  id: string;
  segment_id: string;
  order: number;
  narration: string;
  visual_description: string;
  material_query: string;
  keywords_en: string[];
  keywords_cn: string[];
  shot_type: "wide" | "medium" | "close-up";
  mood: string;
  transition_in: "cut" | "dissolve" | "fade" | "wipe";
  audio_note: string;
  orientation: AspectRatio;
  estimated_duration_seconds: number;
}

interface StoryboardArtifact {
  version: number;
  total_duration_seconds: number;
  total_shots: number;
  shots: StoryboardShot[];
}
```

数组顺序只用于展示；跨产物关联必须使用稳定的 `id` / `segment_id`。

### 2.3 任务摘要与详情

```ts
interface TaskProgress {
  current_step: string;
  completed_steps: number;
  total_steps: 12;
}

interface SafeTaskError {
  code: string;
  message: string;
  retryable: boolean;
  failed_stage: string;
}

interface TaskSummary {
  id: string;
  topic: string;
  target_duration_seconds: number;
  aspect_ratio: AspectRatio;
  voice_id: MimoVoiceId;
  provider_mode: ProviderMode;
  status: TaskStatus;
  progress: TaskProgress;
  created_at: string;
  updated_at: string;
  preview_ready: boolean;
  export_ready: boolean;
  error: SafeTaskError | null;
}

type PendingReview =
  | {kind: "script"; version: number; allowed_actions: ReviewAction[]; script: ScriptArtifact}
  | {kind: "storyboard"; version: number; allowed_actions: ReviewAction[]; storyboard: StoryboardArtifact}
  | {kind: "bgm"; version: number; allowed_actions: BgmAction[]; suggested_query: string; default_volume: number};

interface TaskDetail extends TaskSummary {
  thread_id: string;
  script: ScriptArtifact | null;
  storyboard: StoryboardArtifact | null;
  pending_review: PendingReview | null;
  preview_url: string | null;
  export_url: string | null;
  final_duration_seconds: number | null;
  bgm_added: boolean | null;
}
```

`thread_id` 是安全的随机标识，只用于诊断关联，不可用来访问检查点。媒体 URL 始终是本 API 的授权相对路径，不返回本地文件路径或任意远程 URL。

`provider_mode` 在任务创建时固化，用于明确区分真实供应商任务与测试任务。`real` 会发起 LLM、MiMo TTS 和 Pexels 请求；`fake` 只允许作为显式启用的本地测试模式，客户端必须醒目提示它不会调用外部服务。

## 3. 认证接口

### `POST /auth/register`

无需认证。请求：

```json
{"email":"creator@example.com","password":"correct horse battery staple"}
```

- 邮箱去除首尾空白并转为小写，最大 254 字符。
- 密码 10–128 字符。
- 成功：`201`，设置会话/CSRF Cookie，返回 `UserResponse`。
- 失败：`409 EMAIL_EXISTS`、`422 VALIDATION_ERROR`。

### `POST /auth/login`

无需认证。请求字段与注册相同。成功 `200` 并轮换会话；失败统一返回 `401 INVALID_CREDENTIALS`，不泄露邮箱是否存在。

### `GET /auth/me`

需要认证。成功 `200`：

```json
{"id":"b55f...","email":"creator@example.com","created_at":"2026-08-03T02:15:30Z"}
```

### `DELETE /auth/session`

需要认证与 CSRF。删除当前服务端会话、清除 Cookie，成功 `204`；无会话或会话已失效时返回 `401`。

## 4. 用户设置

设置只包含非敏感偏好；供应商端点、模型和密钥不通过此 API 读写。

```ts
interface UserSettings {
  default_aspect_ratio: AspectRatio;
  default_duration_seconds: number; // 10..180
  default_bgm_volume: number;        // 0.0..1.0
  preferred_voice: MimoVoiceId;
}
```

- `GET /settings`：认证，`200 UserSettings`。
- `PUT /settings`：认证与 CSRF，完整请求体，`200 UserSettings`；非法字段返回 `422`。

## 5. 服务能力

### `GET /capabilities`

需要认证。只返回非敏感运行能力，不返回模型名、端点或密钥：

```ts
interface VoiceOption {
  id: MimoVoiceId;
  name: string;
  language: "中文" | "英文" | "因部署集群而异";
  gender: "女性" | "男性" | "因部署集群而异";
}

interface CapabilitiesResponse {
  provider_mode: ProviderMode;
  external_requests_enabled: boolean;
  voices: VoiceOption[];
}
```

客户端使用此响应渲染音色列表；不得在前端源码中保存供应商端点、模型名或凭据。

## 6. 视频任务

### `POST /tasks`

认证与 CSRF。请求可带 `Idempotency-Key`：

```json
{
  "topic": "三分钟理解量子纠缠",
  "target_duration_seconds": 60,
  "aspect_ratio": "9:16",
  "voice_id": "白桦"
}
```

- `topic` 去除首尾空白后 3–1000 字符。
- `target_duration_seconds` 为 10–180 的整数。
- `target_duration_seconds` 是用户选择的生成目标和模型提示参数，不是模型估算结果的失败阈值。模型返回的场景估算总时长可以偏离该值；最终成片时长由实际 TTS 音频时间轴决定。
- `voice_id` 可选；提供时必须是 `MimoVoiceId`，省略时使用当前用户的 `preferred_voice`。任务创建后音色固化，不受后续设置修改影响。
- 成功：`201 TaskDetail`，初始状态为 `queued`，工作流在响应后异步执行。
- 失败：`409 IDEMPOTENCY_CONFLICT`、`422 VALIDATION_ERROR`。

### `GET /tasks`

认证。查询参数：`page` 默认 1、范围 1..10000；`page_size` 默认 20、范围 1..100；可选 `status=TaskStatus`。按 `created_at DESC, id DESC` 稳定排序。

```json
{"items":[],"page":1,"page_size":20,"total":0,"pages":0}
```

### `GET /tasks/{task_id}`

认证。成功 `200 TaskDetail`。待审核内容只在相应 `pending_review` 中出现；已生成的 `script` 和 `storyboard` 便于刷新恢复及历史追溯。失败 `404 TASK_NOT_FOUND`。

### `POST /tasks/{task_id}/retry`

认证与 CSRF。仅 `failed` 且 `error.retryable=true` 时允许。成功 `202 TaskDetail` 并从最后一个安全检查点继续；否则 `409 STATE_CONFLICT`。

### `DELETE /tasks/{task_id}`

认证与 CSRF。仅允许删除终态或等待人工操作的任务；正在执行时返回 `409 STATE_CONFLICT`。成功后在同一所有权检查下删除业务记录、检查点关联和任务专属媒体目录，返回 `204`。重复或越权删除返回 `404 TASK_NOT_FOUND`。

## 7. 人工审核与 BGM 决策

提交前必须先从任务详情读取当前 `pending_review.version`。所有成功响应是 `202 TaskDetail`；服务端先原子声明该版本，再在响应后恢复工作流。重复提交、过期页面或状态不匹配返回 `409`，客户端必须刷新详情。

### `POST /tasks/{task_id}/reviews/script`

```json
{"version":1,"action":"approve","feedback":null}
```

`reject` 时 `feedback` 去除空白后必须为 1–2000 字符；`approve` 时必须省略或为 `null`。错误：`409 VERSION_CONFLICT` / `STATE_CONFLICT`、`422 VALIDATION_ERROR`。

### `POST /tasks/{task_id}/reviews/storyboard`

请求和规则与剧本审核相同，版本对应当前分镜版本。

### `POST /tasks/{task_id}/bgm-decision`

```json
{"version":1,"action":"add","volume":0.2}
```

- `no_add` 时 `volume` 必须省略或为 `null`。
- `add` 时 `volume` 必须为 `0.0..1.0`。
- 错误：`409 VERSION_CONFLICT` / `STATE_CONFLICT`、`422 VALIDATION_ERROR`。

## 8. 授权媒体端点

### `GET /tasks/{task_id}/preview`

认证。预览生成后可用，包含口播和已烧录到画面像素的硬字幕，但不含 BGM；MP4 同时保留可选字幕轨。支持标准 HTTP Range 请求；成功 `200` 或 `206`，媒体类型 `video/mp4`。未就绪返回 `409 STATE_CONFLICT`，不存在返回 `404`。

### `GET /tasks/{task_id}/export`

认证。任务 `completed` 后可用。`no_add` 分支导出预览文件；`add` 分支导出混音文件。返回 `video/mp4` 和安全的 `Content-Disposition: attachment; filename="clip-<task-id>.mp4"`。未就绪返回 `409`。

媒体端点只从数据库中已登记、位于当前任务专属目录内的受控相对路径读取，不接受客户端文件名或 URL。

## 9. 状态推进与恢复语义

```text
queued → generating_script → awaiting_script_review
awaiting_script_review --reject→ generating_script → awaiting_script_review (version + 1)
awaiting_script_review --approve→ generating_storyboard → awaiting_storyboard_review
awaiting_storyboard_review --reject→ generating_storyboard → awaiting_storyboard_review (version + 1)
awaiting_storyboard_review --approve→ synthesizing_audio → building_timeline
  → fetching_assets（素材与 SRT 并行）→ aligning_timeline
  → rendering_preview → awaiting_bgm_decision
awaiting_bgm_decision --no_add→ completed
awaiting_bgm_decision --add→ processing_bgm → completed
```

每个任务绑定稳定的 LangGraph `thread_id`。审核中断会持久化到 SQLite Checkpointer。服务重启后，等待操作的任务保持原版本；执行中的任务从最后一个安全检查点继续。具有外部副作用的节点以 `task_id + node + artifact/version` 作为幂等键并复用已登记产物。素材和 SRT 并行写入不同状态字段，只有两支都完成后才进入最终对齐。
