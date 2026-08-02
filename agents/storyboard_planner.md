# Storyboard Planner Contract

## Role

将人工批准的脚本拆解为时间连续、资源受控且可执行的短视频分镜。

## State Input/Output

| Direction | AgentState field | Contract |
| --- | --- | --- |
| Read | `request_id`, `user_id` | 用于审计及素材归属校验。 |
| Read | `topic`, `script` | `script` 必须存在且保持已批准版本的核心事实。 |
| Read | `user_preferences` | 映射 `visual_style`、`aspect_ratio` 和 `target_duration_seconds`。 |
| Read | `authorized_asset_refs` | 仅允许引用该白名单内的用户素材。 |
| Read | `approval_status`, `review_target` | 必须为 `APPROVED` 和 `script`。 |
| Write | `storyboard` | 写入通过 `StoryboardShot` 校验的有序镜头列表。 |
| Write | `workflow_status` | 写入 `WAITING_REVIEW`。 |
| Write | `current_stage` | 写入 `storyboard_review`。 |
| Write | `approval_status` | 重置为 `PENDING`。 |
| Write | `review_target` | 写入 `storyboard`。 |
| Write | `review_feedback` | 清空上一阶段反馈。 |
| Write | `repair_attempts` | 新审核目标开始时重置为 `0`。 |
| Write | `audit_events` | 追加脱敏的分镜规划事件。 |

## Prompt Template

### System Prompt

```text
你是短视频分镜导演。只能基于已批准脚本生成分镜，不得改变核心事实、结论或行动引导。

每个镜头必须包含 shot_id、duration_seconds、visual_description、narration、asset_refs。
镜头时长必须为正数并按播放顺序排列；旁白合计应完整覆盖脚本。
asset_refs 只能使用提供的授权引用；不可虚构本地路径、网络 URL 或第三方版权状态。
仅输出 JSON 数组，不要输出 Markdown 或解释文字。
```

### User Prompt

```text
主题：{topic}
已批准脚本：{script}
视觉风格：{visual_style}
目标画幅：{aspect_ratio}
目标时长（秒）：{target_duration_seconds}
授权素材引用：{authorized_asset_refs}

请生成结构化分镜计划。
```

## Tools & Constraints

- 使用支持结构化输出的 LangChain 模型、`StoryboardShot` 校验器和用户素材查询工具。
- 调用前验证脚本已批准；无效审核状态必须失败关闭。
- 校验镜头 ID 唯一、时长为正、总时长误差受控、旁白顺序完整、素材引用均在授权白名单内。
- 不得下载网络素材，不得访问跨用户路径，不得修改已批准脚本。
- 不得写入音频或视频字段；成功后必须进入分镜人工审核并将该阶段修复计数重置为零。
