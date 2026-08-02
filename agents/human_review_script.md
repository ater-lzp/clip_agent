# Human Review Script Contract

## Role

暂停工作流并仅接受当前登录用户对脚本作出的批准或带反馈驳回决定。

## State Input/Output

| Direction | AgentState field | Contract |
| --- | --- | --- |
| Read | `request_id`, `user_id` | 校验审核线程与当前登录用户归属。 |
| Read | `script` | 向审核界面展示待审脚本。 |
| Read | `repair_attempts`, `max_repair_attempts` | 展示当前修复轮次和剩余次数。 |
| Read | `workflow_status`, `current_stage` | 必须分别为 `WAITING_REVIEW` 和 `script_review`。 |
| Write | `approval_status` | 仅写入 `APPROVED` 或 `REJECTED`。 |
| Write | `review_target` | 固定写入 `script`。 |
| Write | `review_feedback` | 驳回时必须为非空；批准时允许为空字符串。 |
| Write | `workflow_status` | 有效恢复后写入 `RUNNING`。 |
| Write | `audit_events` | 追加审核结果的脱敏事件，不记录脚本全文。 |

## Prompt Template

### System Prompt

```text
这是人工审核关卡，不允许语言模型代替用户作出决定。
系统必须暂停并展示脚本，只接受当前线程所有者提交的 APPROVED 或 REJECTED。
REJECTED 必须附带明确、可执行的修改反馈；任何其他状态或空反馈均拒绝恢复。
```

### User Prompt

```text
请求编号：{request_id}
当前修复次数：{repair_attempts}/{max_repair_attempts}
待审核脚本：
{script}

请提交：
- approval_status：{approval_status}
- review_feedback：{review_feedback}
```

## Tools & Constraints

- 使用 LangGraph `interrupt()` 暂停，使用持久化 SQLite checkpointer 保存状态。
- `interrupt()` 每次节点执行只调用一次，不得包裹在 `try/except` 中，也不得在调用前产生非幂等副作用。
- 恢复必须使用原 `thread_id`，并再次验证登录用户拥有该线程。
- 审核载荷必须经过 `ReviewDecision` 运行时校验；禁止 `PENDING` 作为恢复决定。
- 本节点不得编辑脚本、增加修复次数、调用模型、调用 TTS 或生成视频。
