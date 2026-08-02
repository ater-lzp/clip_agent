# Script Generator Contract

## Role

根据已认证用户的主题与结构化偏好生成可供人工审核的短视频口播脚本。

## State Input/Output

| Direction | AgentState field | Contract |
| --- | --- | --- |
| Read | `request_id` | 仅用于审计事件关联。 |
| Read | `user_id` | 仅用于历史与资源归属校验，不进入提示词。 |
| Read | `topic` | 必填的脚本主题。 |
| Read | `user_preferences` | 映射 `target_audience`、`content_style`、`target_duration_seconds` 和 `language`。 |
| Read | `authorized_history_summary` | 可选，仅包含当前用户获授权的脱敏历史摘要。 |
| Write | `script` | 完整、非空、可直接审核的脚本文本。 |
| Write | `workflow_status` | 写入 `WAITING_REVIEW`。 |
| Write | `current_stage` | 写入 `script_review`。 |
| Write | `approval_status` | 写入 `PENDING`。 |
| Write | `review_target` | 写入 `script`。 |
| Write | `audit_events` | 追加一个符合 `AuditEvent` 的脱敏事件。 |
| Write | `error_code`, `error_message` | 仅在输入或生成结果验证失败时写入。 |

## Prompt Template

### System Prompt

```text
你是短视频脚本策划师。只根据已验证输入生成事实谨慎、适合口播且便于拆分分镜的脚本。

输出依次包含：标题、开场钩子、正文分段、结尾行动引导、建议总时长。
不得臆造事实、泄露个人信息或密钥、引用未授权历史，也不得输出工具调用痕迹。
信息不足时返回结构化缺失项，不得自行补造关键事实。
```

### User Prompt

```text
主题：{topic}
目标受众：{target_audience}
内容风格：{content_style}
目标时长（秒）：{target_duration_seconds}
语言：{language}
已授权历史摘要：{authorized_history_summary}

请生成可供人工审核的短视频口播脚本。
```

## Tools & Constraints

- 使用受控 LangChain 文本模型和运行时结构校验器。
- 模板变量必须从 `UserPreferences` 显式映射；缺失可选值使用已声明默认值，不得读取任意字典键。
- 不得把 `user_id`、`tts_secret_ref`、密钥值、完整历史或跨用户内容发送给模型。
- 输出前校验脚本非空、语言匹配，且估算口播时长位于目标时长允许误差内。
- 不得修改 `repair_attempts`、`max_repair_attempts`、音频、视频或用户身份字段。
- 成功输出后进入脚本人工审核中断，模型不得自行批准脚本。
