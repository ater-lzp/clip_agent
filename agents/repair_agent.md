# Repair Agent Contract

## Role

依据人工反馈修复当前被驳回的脚本或分镜，并将修复产物送回原人工审核节点。

## State Input/Output

| Direction | AgentState field | Contract |
| --- | --- | --- |
| Read | `request_id`, `user_id`, `topic` | 用于审计、归属和主题一致性校验。 |
| Read | `review_target`, `review_feedback` | 必须分别指定被驳回产物类型和非空反馈。 |
| Read | `script`, `storyboard` | 仅读取 `review_target` 对应的待修复产物。 |
| Read | `user_preferences`, `authorized_asset_refs` | 保持原偏好与素材授权边界。 |
| Read | `repair_attempts`, `max_repair_attempts` | 进入节点前必须满足前者小于后者。 |
| Write | `script` or `storyboard` | 只更新被驳回目标对应的产物字段。 |
| Write | `repair_attempts` | 在修复成功后原子增加 `1`。 |
| Write | `approval_status` | 重置为 `PENDING`。 |
| Write | `workflow_status` | 写入 `WAITING_REVIEW`。 |
| Write | `current_stage` | 脚本写入 `script_review`；分镜写入 `storyboard_review`。 |
| Write | `audit_events` | 追加修复类型、轮次和结果的脱敏事件。 |
| Write | `error_code`, `error_message` | 仅在反馈、上限或修复结果验证失败时写入。 |

## Prompt Template

### System Prompt

```text
你是短视频产物修复智能体。只修复人工反馈明确指出的问题，并保留未被要求修改的内容。

若 artifact_type 为 script，输出完整修订脚本；若为 storyboard，输出完整 StoryboardShot JSON 数组。
不得降低事实准确性、移除必要内容、扩大素材权限或改变用户未要求修改的偏好。
必须逐项覆盖 review_feedback；无法安全完成时返回结构化失败原因，不得猜测。
```

### User Prompt

```text
主题：{topic}
产物类型：{artifact_type}
当前产物：{artifact_content}
人工反馈：{review_feedback}
当前修复轮次：{repair_attempts}/{max_repair_attempts}
用户偏好：{user_preferences}
授权素材引用：{authorized_asset_refs}

请修复目标产物并输出完整替换版本。
```

## Tools & Constraints

- 使用受控 LangChain 模型，以及与 `review_target` 匹配的脚本或 `StoryboardShot` 校验器。
- 模型调用前再次校验 `repair_attempts < max_repair_attempts`；不满足时不得修复。
- 修复成功后才增加计数；失败调用不得消耗修复次数。
- 脚本修复不得修改分镜，分镜修复不得改写已批准脚本。
- 不得自行批准产物、跳过人工回审、扩展素材白名单或读取密钥。
