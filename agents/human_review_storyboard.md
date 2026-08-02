# Human Review Storyboard Contract

## Role

暂停工作流并仅接受当前登录用户对分镜作出的批准或带反馈驳回决定。

## State Input/Output

| Direction | AgentState field | Contract |
| --- | --- | --- |
| Read | `request_id`, `user_id` | 校验审核线程和用户归属。 |
| Read | `storyboard` | 向审核界面展示结构化分镜。 |
| Read | `repair_attempts`, `max_repair_attempts` | 展示当前修复轮次和剩余次数。 |
| Read | `workflow_status`, `current_stage` | 必须分别为 `WAITING_REVIEW` 和 `storyboard_review`。 |
| Write | `approval_status` | 仅写入 `APPROVED` 或 `REJECTED`。 |
| Write | `review_target` | 固定写入 `storyboard`。 |
| Write | `review_feedback` | 驳回时必须非空；批准时允许为空字符串。 |
| Write | `workflow_status` | 有效恢复后写入 `RUNNING`。 |
| Write | `audit_events` | 追加审核结果的脱敏事件，不记录完整分镜。 |

## Prompt Template

### System Prompt

```text
这是人工分镜审核关卡，不允许语言模型代替用户作出决定。
系统必须暂停并展示分镜，只接受当前线程所有者提交的 APPROVED 或 REJECTED。
REJECTED 必须说明需要调整的镜头、原因和预期结果；无效决定不得恢复图执行。
```

### User Prompt

```text
请求编号：{request_id}
当前修复次数：{repair_attempts}/{max_repair_attempts}
待审核分镜：
{storyboard}

请提交：
- approval_status：{approval_status}
- review_feedback：{review_feedback}
```

## Tools & Constraints

- 使用 LangGraph `interrupt()`、SQLite checkpointer 和审核载荷校验器。
- 恢复时必须复用原 `thread_id` 并验证当前用户拥有该线程。
- `interrupt()` 调用顺序固定，调用前的副作用必须幂等，不得捕获其中断异常。
- 禁止修改分镜、脚本、修复次数、音色或媒体 URL。
- 只有 `APPROVED` 才可进入 `tts_synthesizer`；有效 `REJECTED` 只能进入 `repair_agent` 或在上限耗尽时失败。
