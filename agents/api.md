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
| 400 | `INVALID_REQUEST`、`PAYMENT_PASSWORD_INVALID` | 请求语义无效或支付密码错误 |
| 401 | `AUTHENTICATION_REQUIRED`、`INVALID_CREDENTIALS` | 未登录或登录失败 |
| 403 | `CSRF_FAILED`、`ADMIN_REQUIRED`、`ACCOUNT_DISABLED` | CSRF 校验失败、非管理员或账户停用 |
| 404 | `TASK_NOT_FOUND`、`MEDIA_NOT_FOUND`、`POST_NOT_FOUND`、`COMMENT_NOT_FOUND`、`USER_NOT_FOUND`、`CDK_NOT_FOUND`、`AD_NOT_FOUND` | 当前用户不可见的资源不存在 |
| 409 | `EMAIL_EXISTS`、`NICKNAME_EXISTS`、`STATE_CONFLICT`、`VERSION_CONFLICT`、`IDEMPOTENCY_CONFLICT`、`SHARE_EXISTS`、`CDK_USED`、`PAYMENT_PASSWORD_REQUIRED`、`INSUFFICIENT_BALANCE`、`QUOTA_EXHAUSTED` | 唯一性、状态、额度或并发版本冲突 |
| 413 | `PAYLOAD_TOO_LARGE` | 请求或下载资源超过限制 |
| 422 | `VALIDATION_ERROR`、`INVALID_IMAGE`、`INVALID_AD_IMAGE`、`INVALID_LINK_URL` | 字段或上传内容校验失败 |
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
  cover_url: string | null;
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

interface TaskStats {
  total: number;
  completed: number;
  failed: number;
  in_progress: number;
  awaiting_review: number;
  total_duration_seconds: number;
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
- 密码 8–128 字符。
- 成功：`201`，设置会话/CSRF Cookie，返回 `UserResponse`。
- 失败：`409 EMAIL_EXISTS`、`422 VALIDATION_ERROR`。

### `POST /auth/login`

无需认证。请求字段与注册相同。成功 `200` 并轮换会话；失败统一返回 `401 INVALID_CREDENTIALS`，不泄露邮箱是否存在。

### `GET /auth/me`

需要认证。成功 `200`：

```json
{"id":"b55f...","email":"creator@example.com","nickname":"海边创作者","avatar_url":"/api/v1/users/b55f.../avatar","role":"user","created_at":"2026-08-03T02:15:30Z"}
```

### `DELETE /auth/session`

需要认证与 CSRF。删除当前服务端会话、清除 Cookie，成功 `204`；无会话或会话已失效时返回 `401`。

## 4. 账户资料

### `PUT /profile`

认证与 CSRF。请求 `{"nickname":"海边创作者"}`。昵称去除首尾空白后必须为 2–12 个中文、英文字母或数字，且忽略大小写全局唯一。成功返回 `200 UserResponse`；冲突返回 `409 NICKNAME_EXISTS`。

### `POST /profile/avatar`

认证与 CSRF。使用 `multipart/form-data` 的 `file` 字段上传 JPG 或 PNG，最大 2 MiB。服务端验证真实图片内容、拒绝超大像素图并居中裁剪为 200×200 JPEG；成功返回更新后的 `UserResponse`。格式无效返回 `422 INVALID_IMAGE`，超过限制返回 `413 PAYLOAD_TOO_LARGE`。浏览器只接收授权头像 URL，不接收本地路径。

### `GET /users/{user_id}/avatar`

认证。返回该用户当前头像 `image/jpeg`；未设置或文件缺失返回 `404 MEDIA_NOT_FOUND`。

### `GET /users/{user_id}`

认证。返回安全的公开资料，不包含邮箱：

```ts
interface PublicUser {
  id: string;
  nickname: string | null;
  avatar_url: string | null;
  created_at: string;
  follower_count: number;
  following_count: number;
  post_count: number;
  is_following: boolean;
  is_self: boolean;
}
```

用户不存在返回 `404 USER_NOT_FOUND`。

### `PUT /users/{user_id}/follow`

认证与 CSRF。切换当前用户对目标用户的关注状态，成功返回
`{"following":true|false}`。不能关注自己，返回 `409 STATE_CONFLICT`；目标不存在返回
`404 USER_NOT_FOUND`。数据库同时通过唯一键和非自关注约束保护该关系。

### `POST /profile/password`

认证与 CSRF。请求：

```json
{"current_password":"旧密码","new_password":"NewPassword1","confirm_password":"NewPassword1"}
```

新密码为 8–128 字符，必须同时包含大写字母、小写字母和数字，且两次输入一致。旧密码错误返回 `400 CURRENT_PASSWORD_INVALID`。成功更新密码、记录安全审计、删除该用户所有服务端会话并清除 Cookie，返回 `204`；客户端随后跳转登录页。

## 5. 用户设置

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

## 6. 服务能力

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

## 7. 视频任务

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
- `target_duration_seconds` 是用户选择的生成目标和模型提示参数，不是模型估算结果的失败阈值。模型返回的场景估算总时长可以偏离该值。服务端取得每段真实 TTS 音频后按原始段落时长比例进行保持音高的节奏校准，再以校准后 WAV 的实际整数毫秒时长建立时间轴；因此最终口播、字幕和视频时长以该用户目标为准。
- `voice_id` 可选；提供时必须是 `MimoVoiceId`，省略时使用当前用户的 `preferred_voice`。任务创建后音色固化，不受后续设置修改影响。
- 成功：`201 TaskDetail`，初始状态为 `queued`，工作流在响应后异步执行。
- 每个新任务原子消耗 1 次生成额度；幂等键命中已有同请求时不重复消耗。额度不足返回 `409 QUOTA_EXHAUSTED`。
- 失败：`409 IDEMPOTENCY_CONFLICT`、`409 QUOTA_EXHAUSTED`、`422 VALIDATION_ERROR`。

### `GET /tasks`

认证。查询参数：`page` 默认 1、范围 1..10000；`page_size` 默认 20、范围 1..100；可选
`status=TaskStatus`、`status_group=in_progress` 和 `q`。`q` 去除首尾空白后为 1–200
字符，按主题包含关键词搜索；`status` 与 `status_group` 不能同时使用。`in_progress` 覆盖排队及所有
自动执行阶段，不包含三种人工中断、完成和失败状态。所有筛选可与 `q` 组合，结果按
`created_at DESC, id DESC` 稳定排序。历史页固定请求每页 40 条并通过无限滚动加载。

```json
{"items":[],"page":1,"page_size":20,"total":0,"pages":0}
```

### `GET /tasks/stats`

认证。统计仅覆盖当前用户任务，成功返回 `200 TaskStats`。`awaiting_review` 汇总待审剧本、待审
分镜和待选 BGM；`in_progress` 的范围与列表 `status_group=in_progress` 一致；
`total_duration_seconds` 只累加已完成任务的实际成片时长。

### `GET /tasks/{task_id}`

认证。成功 `200 TaskDetail`。待审核内容只在相应 `pending_review` 中出现；已生成的 `script` 和 `storyboard` 便于刷新恢复及历史追溯。失败 `404 TASK_NOT_FOUND`。

### `POST /tasks/{task_id}/duplicate`

认证与 CSRF。请求体为 `{}`，可携带最多 128 字符的 `Idempotency-Key`。仅允许复制当前用户已
完成的任务；新任务精确复制主题、目标时长、画幅和音色，以当前部署供应商模式进入异步工作流。
成功返回 `202 TaskDetail`。同一用户、同一幂等键和同一源任务返回首次创建的任务，不重复启动
工作流；该键被创建任务或另一源任务占用时返回 `409 IDEMPOTENCY_CONFLICT`。源任务不存在返回
`404 TASK_NOT_FOUND`，源任务未完成返回 `409 STATE_CONFLICT`。

### `POST /tasks/{task_id}/retry`

认证与 CSRF。仅 `failed` 且 `error.retryable=true` 时允许。成功 `202 TaskDetail` 并从最后一个安全检查点继续；否则 `409 STATE_CONFLICT`。

### `DELETE /tasks/{task_id}`

认证与 CSRF。仅允许删除终态或等待人工操作的任务；正在执行时返回 `409 STATE_CONFLICT`。成功后在同一所有权检查下删除业务记录、检查点关联和任务专属媒体目录，返回 `204`。重复或越权删除返回 `404 TASK_NOT_FOUND`。

### `POST /tasks/bulk-delete`

认证与 CSRF。用于历史页跨分页批量删除，必须在动态的 `/tasks/{task_id}` 路由之前注册。

```json
{"mode":"all","task_ids":[]}
```

- `mode=all` 删除当前用户的全部生成记录，忽略当前列表搜索和筛选；`task_ids` 必须为空。
- `mode=selected` 时 `task_ids` 必须包含 1–500 个不重复的任务 UUID，只删除明确选中的记录。
- 服务端先对整个集合做所有权、状态和媒体路径预检；任一任务正在执行时返回
  `409 STATE_CONFLICT` 且不删除任何记录，越权或不存在的选中任务返回
  `404 TASK_NOT_FOUND`。
- 成功返回 `200 {"deleted_count":12}`，并清理每个任务的业务记录、LangGraph 检查点和任务媒体目录；空账户的 `mode=all` 返回 `deleted_count=0`。

## 8. 人工审核与 BGM 决策

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
{"version":1,"action":"add","volume":0.2,"track_id":"library:0123456789abcdef01234567"}
```

- `no_add` 时 `volume` 与 `track_id` 必须省略或为 `null`。
- `add` 时 `volume` 必须为 `0.0..1.0`，`track_id` 必须是当前曲库列表或当前任务上传接口返回的标识；服务端在原子声明审核版本前再次解析标识，不接受客户端路径、文件名或 URL。
- 错误：`409 VERSION_CONFLICT` / `STATE_CONFLICT`、`422 VALIDATION_ERROR`。

### `GET /bgms`

认证。动态扫描部署配置的本地曲库目录（默认 `backend/bgms`）第一层，返回
`200 {"items": BgmTrack[]}`。新增受支持的 `.mp3`、`.wav`、`.m4a` 文件后无需修改代码即可出现；
符号链接、重解析点、子目录和其他扩展名会被忽略。`BgmTrack` 为：

```json
{
  "id":"library:0123456789abcdef01234567",
  "name":"relax 60sec",
  "source":"library",
  "duration_seconds":60.0,
  "preview_url":"/api/v1/bgms/library:0123456789abcdef01234567/audio"
}
```

ID 是服务端生成的稳定不透明标识，响应不泄露本地路径。

### `GET /bgms/{track_id}/audio`

认证。只允许读取当前曲库扫描结果中的标识，成功返回相应音频；未知或失效标识返回
`404 BGM_NOT_FOUND`。客户端不得提交路径。

### `POST /tasks/{task_id}/bgm-upload`

认证与 CSRF，仅任务处于 `awaiting_bgm_decision` 时接受单个 multipart 字段 `file`。允许
MP3/WAV/M4A，最大 25 MiB；服务端不信任 MIME、扩展名和原文件名，必须通过受限 FFmpeg
解码验证，规范化为任务专属目录中的 WAV，并记录校验和与实际时长。成功返回 `201 BgmTrack`，
其中 `source=upload`、`id` 绑定任务和当前预览版本；再次上传会原子替换该版本的上一首上传曲。
无效音频返回 `422 INVALID_BGM_FILE`，过大返回 `413 PAYLOAD_TOO_LARGE`，错误状态返回
`409 STATE_CONFLICT`。

### `GET /tasks/{task_id}/bgm-upload/audio`

认证。返回当前用户该任务已规范化的上传音频；未上传返回 `404 BGM_NOT_FOUND`。任务详情处于
待选 BGM 时，其 `pending_review.uploaded_track` 返回相同的 `BgmTrack`，用于刷新恢复。

## 9. 授权媒体端点

### `GET /tasks/{task_id}/preview`

认证。无 BGM 预览生成后即可使用；任务仍在待选 BGM 时返回包含口播和硬字幕、但不含 BGM 的
预览文件。任务选择 `add` 且混音完成后，同一端点必须切换为返回 `final_relative_path` 对应的已混音
成片；选择 `no_add` 时继续返回原预览。MP4 同时保留可选字幕轨。支持标准 HTTP Range 请求；
成功 `200` 或 `206`，媒体类型 `video/mp4`。未就绪返回 `409 STATE_CONFLICT`，不存在返回 `404`。

### `GET /tasks/{task_id}/cover`

认证。视频预览生成后可用。服务端从该任务视频的第一帧提取并缓存 JPEG 封面，成功返回 `200 image/jpeg`。视频尚未就绪返回 `409 STATE_CONFLICT`；源视频缺失或提取失败返回 `404 MEDIA_NOT_FOUND`，客户端必须显示默认占位封面。该端点同样校验当前用户所有权。

### `GET /tasks/{task_id}/export`

认证。任务 `completed` 后可用。`no_add` 分支导出预览文件；`add` 分支导出混音文件。返回 `video/mp4` 和安全的 `Content-Disposition: attachment; filename="clip-<task-id>.mp4"`。未就绪返回 `409`。

媒体端点只从数据库中已登记、位于当前任务专属目录内的受控相对路径读取，不接受客户端文件名或 URL。

## 10. 社区

所有社区接口均需登录，写操作还需 CSRF。作品 ID、评论 ID 和用户 ID 都是 UUID；已软删除作品统一返回 `404 POST_NOT_FOUND`。

- `POST /community/posts`：发布当前用户已完成的视频。请求包含 `task_id`、1–50 字标题、最多 500 字描述、`prompt_public` 和最多 3 个标签。成功 `201 CommunityPost`。
- `GET /community/posts`：分页列表，参数 `scope=all|mine|favorites|shared|following`、`page`、`page_size<=40`、可选 `tag` 及可选 `owner_id`；`shared` 返回转发给当前用户的作品，`following` 只返回当前用户已关注作者的作品，`owner_id` 用于用户主页的公开作品列表；其余范围按发布时间倒序。
- `GET /community/posts/{post_id}`：作品详情。提示词仅在作者本人或 `prompt_public=true` 时返回。
- `DELETE /community/posts/{post_id}`：仅发布者可软删除；评论、点赞、转发和收藏引用同时清理，并记录审计。
- `GET /community/posts/{post_id}/video|cover`：返回授权视频或第一帧封面。
- `GET|POST /community/posts/{post_id}/comments`：评论列表支持 `sort=latest|hot`；发布内容最长 200 字，`parent_id` 只允许指向一级评论。
- `PUT /community/comments/{comment_id}/like`：幂等语义为切换当前用户点赞，返回 `{"liked":true|false}`。
- `DELETE /community/comments/{comment_id}`：评论作者或作品发布者可删除；一级评论删除时级联回复与点赞。
- `PUT /community/posts/{post_id}/favorite`：切换收藏；收藏列表通过 `scope=favorites` 查询。
- `PUT /community/posts/{post_id}/like`：认证与 CSRF，无请求体；独立切换当前用户的作品点赞，成功 `200` 返回 `{"liked":true|false}`，作品不存在返回 `404 POST_NOT_FOUND`；不得改变收藏状态或收藏计数。
- `GET /community/users/search?q=`：按昵称或邮箱搜索最多 20 个站内转发目标。
- `POST /community/posts/{post_id}/shares`：请求 `{"recipient_id":"uuid"}`；同一发送者不能重复向同一用户转发同一作品，成功 `201` 并增加分享统计。

`CommunityPost` 包含作者安全公开资料、视频/封面授权 URL、标签、评论/分享/收藏/点赞数、当前用户收藏与点赞状态及所有权标记。所有发布时间仍以 UTC ISO 8601 传输，客户端固定按 Asia/Shanghai 显示。

## 11. 状态推进与恢复语义

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

## 12. 账户、会员、CDK 与管理员

金额统一使用人民币分的整数传输和存储，不使用浮点数。新用户默认 `free`，余额 0 分，总生成
额度 5 次。VIP 价格 2990 分/30 天并增加 30 次额度；SVIP 价格 7990 分/30 天并增加
100 次额度。续费叠加额度；同档有效会员从当前到期时间延长，否则从支付时间起计算 30 天。
任务失败或删除不返还已经消耗的生成次数。

```ts
type MembershipTier = "free" | "vip" | "svip";
type UserRole = "user" | "admin";

interface AccountSummary {
  membership_tier: MembershipTier;
  membership_expires_at: string | null;
  balance_cents: number;
  generation_quota: number;
  generations_used: number;
  generations_remaining: number;
  has_payment_password: boolean;
}
```

### `GET /account`

认证。返回 `200 AccountSummary` 及固定服务端套餐列表
`plans: [{tier,name,price_cents,duration_days,generation_credits}]`。到期会员在响应前降为 `free`，
已获得但未使用的生成额度保留。

### `POST /account/payment-password`

认证与 CSRF。请求
`{"account_password":"登录密码","payment_password":"123456","confirm_password":"123456"}`。
支付密码必须恰好 6 位数字，两次一致，并要求再次验证登录密码；只保存独立 scrypt 哈希。
成功返回 `204`。登录密码错误返回 `400 CURRENT_PASSWORD_INVALID`。

### `POST /account/redeem-cdk`

认证与 CSRF。请求 `{"code":"CLIP-ABCD-EFGH-JKLM-NPQR"}`。格式无效或不存在统一返回
`404 CDK_NOT_FOUND`；已使用返回 `409 CDK_USED`。服务端在单个立即事务中校验摘要、声明使用者、
增加余额并写入账本，成功返回更新后的 `200 AccountSummary`。CDK 原文不写日志或数据库。

### `POST /account/memberships`

认证与 CSRF，可携带 `Idempotency-Key`。请求
`{"tier":"vip","payment_password":"123456"}`，只允许 `vip|svip`。未设置支付密码返回
`409 PAYMENT_PASSWORD_REQUIRED`，密码错误返回 `400 PAYMENT_PASSWORD_INVALID`，余额不足返回
`409 INSUFFICIENT_BALANCE`。扣余额、建立已支付订单、增加额度、更新会员有效期和写账本在同一事务
完成；幂等重放返回原订单且不重复扣款。成功 `201 {order,account}`。

### `GET /account/ledger`

认证。分页参数 `page`、`page_size<=100`，返回当前用户余额流水，字段包含 `id`、`kind`、
`amount_cents`、`balance_after_cents`、安全的 `reference_type`、`created_at`，不返回 CDK 原文。

### 管理员认证与边界

管理员使用相同会话接口；`UserResponse.role` 为 `user|admin`。所有 `/admin/*` 接口要求数据库
角色为 `admin`，写操作还要求 CSRF；普通用户统一返回 `403 ADMIN_REQUIRED`。停用用户的现有会话
失效。首个管理员仅能通过本地命令 `python -m backend.tools.manage_admin --email ...` 创建或提升，
HTTP 接口不能匿名提升权限。

### `GET /admin/dashboard`

管理员认证。返回用户总数/启用数、VIP/SVIP 用户数、任务总数及完成/失败/进行中/待人工处理数、
今日新增用户、已支付会员订单总额、CDK 已生成/已使用数。任务分类口径与普通任务统计一致，所有
计数均为全站运营数据。

### `GET /admin/users` 与 `GET /admin/users/{user_id}`

管理员认证。列表支持 `page`、`page_size<=100`、`q`（邮箱/昵称）、`active=true|false`、
`role=user|admin`、`membership=free|vip|svip`，可组合筛选并按注册时间倒序。每条记录包含任务数。
详情返回邮箱、角色、启用状态、会员/额度/余额摘要、任务总数/完成数/失败数和最近 10 条余额流水。

### `PATCH /admin/users/{user_id}`

管理员认证与 CSRF。请求可包含 `is_active`、`role`、`generation_quota`；至少一个字段。
额度总数不得低于已使用数。不能停用或降级当前管理员自己。该接口不能修改余额；余额充值只能使用
CDK。成功返回用户详情并写审计记录。

### `POST /admin/users/{user_id}/password`

管理员认证与 CSRF。请求
`{"new_password":"NewPassword1","confirm_password":"NewPassword1"}`。新密码为 8–128 字符，
必须同时包含大写字母、小写字母和数字且两次一致。服务端只保存新的 scrypt 哈希，删除目标用户
的全部现有会话并写入包含操作者和目标用户的审计记录；响应不返回密码或哈希。成功 `204`，目标
不存在返回 `404 USER_NOT_FOUND`。管理员控制台不得把密码放入 URL、本地存储或日志。

### `POST /admin/cdks`

管理员认证与 CSRF。请求 `{"amount_cents":10000,"count":5}`，金额 1–1,000,000 分，数量
1–100。成功 `201` 返回本批次 CDK 原文、金额和创建时间；原文只在此响应出现一次，数据库仅保存
带领域前缀的 SHA-256 摘要及末四位提示。HTTP 与数据库始终使用整数分；管理员界面必须以人民币
元输入，最多两位小数，并在提交前精确换算为 `amount_cents`，例如 `100.00 元 → 10000 分`。

### `GET /admin/cdks`

管理员认证。支持 `page`、`page_size<=100`、`status=unused|used`，返回掩码提示、金额、状态、
创建时间、使用时间及使用者 ID/邮箱/昵称；不返回可兑换的完整 CDK。

### `GET /admin/tasks`

管理员认证。跨用户任务监控列表，支持 `page`、`page_size<=100`、`q`（主题/用户邮箱/昵称）、
`status=TaskStatus`、`provider_mode=real|fake` 和 `user_id=UUID`，所有条件可组合；按
`created_at DESC,id DESC` 排序。响应：

```ts
interface AdminTaskSummary {
  id: string;
  user_id: string;
  user_email: string;
  user_nickname: string | null;
  topic: string;
  status: TaskStatus;
  current_stage: string;
  provider_mode: ProviderMode;
  target_duration_seconds: number;
  final_duration_seconds: number | null;
  aspect_ratio: AspectRatio;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}
```

返回标准分页结构。该接口只提供脱敏运营摘要，不返回完整提示词、检查点、内部路径或供应商响应。

### `GET /admin/audit-logs`

管理员认证。审计列表支持 `page`、`page_size<=100`、`q`（操作者邮箱/昵称、动作、目标标识）、
`action` 精确筛选，按 `created_at DESC,id DESC` 排序。每项包含 `id`、操作者安全身份
`actor_id/actor_email/actor_nickname`、`action`、`target_type`、`target_id`、截断后的 `ip_address`
和 `created_at`。不返回密码、Cookie、令牌、CDK 原文、完整提示词或媒体内容。

## 13. 广告投放与管理

广告创意只存放在服务端受控媒体目录，API 不接受或返回文件系统路径。当前支持 JPEG、PNG 和
保留动画的 GIF；单文件不超过 5 MiB，解码后总像素不超过 20,000,000，边长不超过 4096，GIF
不超过 300 帧。跳转地址必须是无用户名密码的绝对 `http` 或 `https` URL，最长 2048 字符。

```ts
type AdPlacement = "auto" | "history" | "community" | "new_task" | "task_detail";
type AdEvent = "impression" | "click";

interface AdCreative {
  id: string;
  title: string;
  link_url: string;
  placement: AdPlacement;
  image_url: string;
  image_media_type: "image/jpeg" | "image/png" | "image/gif";
}

interface AdminAd extends AdCreative {
  is_active: boolean;
  impressions: number;
  clicks: number;
  created_at: string;
  updated_at: string;
}
```

### `GET /ads`

认证。查询参数 `slot=history|community|new_task|task_detail`。服务端先结算会员到期状态；仅当前
会员为 `free` 时从启用且 `placement=slot|auto` 的广告中随机返回 `200 {"item":AdCreative}`，
没有可投放广告或当前用户为 VIP/SVIP 时统一返回 `200 {"item":null}`。客户端不得仅依赖前端
会员状态隐藏广告。

### `GET /ads/{ad_id}/image`

认证。仅免费用户可读取仍处于启用状态的广告图片；VIP/SVIP、已停用或不存在的广告统一返回
`404 AD_NOT_FOUND`。响应媒体类型必须与已验证的创意格式一致。

### `POST /ads/{ad_id}/events`

认证与 CSRF。请求 `{"event":"impression"|"click"}`。只记录免费用户对仍启用广告的曝光或
点击，成功 `204`；无权查看或广告不存在统一返回 `404 AD_NOT_FOUND`。计数是运营用的尽力统计，
不得作为支付或授权依据。

### `POST /admin/ads`

管理员认证与 CSRF，`multipart/form-data`：`file`、`title`（1–80 字）、`link_url`、
`placement`（默认 `auto`）及 `is_active`（默认 `true`）。服务端必须依据实际文件内容验证格式、
尺寸、像素和 GIF 帧数，并使用服务端生成的 UUID 目录和固定安全文件名保存。成功返回
`201 AdminAd`。非法链接返回 `422 INVALID_LINK_URL`，非法图片返回 `422 INVALID_AD_IMAGE`。

### `GET /admin/ads`

管理员认证。支持 `page`、`page_size<=100`、可选 `active=true|false` 和
`placement=AdPlacement`，按 `created_at DESC,id DESC` 返回标准分页结构。

### `GET /admin/ads/{ad_id}/image`

管理员认证。用于后台预览，不受启停状态影响；不存在返回 `404 AD_NOT_FOUND`。

### `PATCH /admin/ads/{ad_id}`

管理员认证与 CSRF。可修改 `title`、`link_url`、`placement`、`is_active`，至少一个字段；图片
替换需删除后重新创建广告，避免媒体写入与元数据更新产生半完成状态。成功返回 `200 AdminAd`。

### `DELETE /admin/ads/{ad_id}`

管理员认证与 CSRF。删除数据库记录后仅清理该广告 UUID 对应的受控媒体目录并写审计记录，成功
返回 `204`；不存在返回 `404 AD_NOT_FOUND`。不得根据客户端路径执行删除。
