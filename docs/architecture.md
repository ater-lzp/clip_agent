# Architecture Contract

本文件是全局状态、节点边界、审核恢复和路由行为的唯一架构事实来源。节点提示词保存在 `agents/`，业务实现必须导入同一套路由函数，测试不得复制路由逻辑。

## Global State Schema (AgentState)

```python
from __future__ import annotations

import operator
from collections.abc import Mapping
from typing import Annotated, Literal, cast

from pydantic import TypeAdapter
from typing_extensions import NotRequired, TypedDict


ApprovalStatus = Literal["PENDING", "APPROVED", "REJECTED"]
ReviewApprovalStatus = Literal["APPROVED", "REJECTED"]
ReviewTarget = Literal["script", "storyboard"]
WorkflowStatus = Literal[
    "RUNNING",
    "WAITING_REVIEW",
    "COMPLETED",
    "FAILED",
]
WorkflowStage = Literal[
    "script_generation",
    "script_review",
    "storyboard_planning",
    "storyboard_review",
    "repair",
    "tts_synthesis",
    "video_composition",
    "completed",
    "failed",
]
VoiceName = Literal[
    "冰糖",
    "茉莉",
    "苏打",
    "白桦",
    "Mia",
    "Chloe",
    "Milo",
    "Dean",
]


class UserPreferences(TypedDict, total=False):
    target_audience: str
    content_style: str
    target_duration_seconds: int
    language: Literal["zh-CN", "en-US"]
    visual_style: str
    aspect_ratio: Literal["9:16", "16:9", "1:1"]
    requested_voice_name: VoiceName
    speech_rate: float
    audio_format: Literal["wav", "mp3", "pcm16"]


class StoryboardShot(TypedDict):
    shot_id: str
    duration_seconds: float
    visual_description: str
    narration: str
    asset_refs: list[str]


class ReviewDecision(TypedDict):
    approval_status: ReviewApprovalStatus
    feedback: str


class AuditEvent(TypedDict):
    event_type: str
    node: str
    request_id: str
    occurred_at: str


class AgentState(TypedDict):
    # 身份和请求上下文：仅由认证中间件初始化，节点只读。
    request_id: str
    user_id: str
    topic: str
    user_preferences: UserPreferences
    tts_secret_ref: str
    history_record_id: NotRequired[str]
    authorized_history_summary: NotRequired[str]
    authorized_asset_refs: list[str]

    # 工作流控制：审核、修复和终态节点按契约更新。
    workflow_status: WorkflowStatus
    current_stage: WorkflowStage
    approval_status: ApprovalStatus
    review_target: NotRequired[ReviewTarget]
    review_feedback: NotRequired[str]
    repair_attempts: int
    max_repair_attempts: int
    error_code: NotRequired[str]
    error_message: NotRequired[str]

    # 业务产物：生产节点只能写入其拥有的字段。
    script: NotRequired[str]
    storyboard: NotRequired[list[StoryboardShot]]
    selected_voice_id: NotRequired[VoiceName]
    audio_url: NotRequired[str]
    video_url: NotRequired[str]

    # 追加型审计字段使用 reducer，禁止节点原地修改列表。
    audit_events: Annotated[list[AuditEvent], operator.add]


AGENT_STATE_ADAPTER = TypeAdapter(AgentState)
STATE_FIELDS = frozenset(AgentState.__annotations__)
PREFERENCE_FIELDS = frozenset(UserPreferences.__annotations__)
MAX_REPAIR_ATTEMPTS = 5


def validate_agent_state(state: Mapping[str, object]) -> AgentState:
    unknown_fields = set(state) - STATE_FIELDS
    if unknown_fields:
        raise ValueError(f"unknown AgentState fields: {sorted(unknown_fields)}")
    validated = cast(AgentState, AGENT_STATE_ADAPTER.validate_python(dict(state)))
    if set(validated["user_preferences"]) - PREFERENCE_FIELDS:
        raise ValueError("unknown UserPreferences fields")
    if not 1 <= validated["max_repair_attempts"] <= MAX_REPAIR_ATTEMPTS:
        raise ValueError("max_repair_attempts is outside the safe range")
    if not 0 <= validated["repair_attempts"] <= validated["max_repair_attempts"]:
        raise ValueError("repair_attempts is outside the valid range")
    if validated["approval_status"] == "REJECTED":
        if validated.get("review_target") not in ("script", "storyboard"):
            raise ValueError("REJECTED requires review_target")
        if not validated.get("review_feedback", "").strip():
            raise ValueError("REJECTED requires non-empty review_feedback")
    return validated


def validate_node_update(
    state: AgentState,
    update: Mapping[str, object],
) -> dict[str, object]:
    unknown_fields = set(update) - STATE_FIELDS
    if unknown_fields:
        raise ValueError(f"unknown node update fields: {sorted(unknown_fields)}")
    merged = dict(state)
    merged.update(update)
    if "audit_events" in update:
        merged["audit_events"] = list(state["audit_events"]) + list(
            update["audit_events"]
        )
    validate_agent_state(merged)
    return dict(update)
```

状态契约规则：

- `tts_secret_ref` 只保存加密密钥引用，绝不保存 API Key 值。
- `approval_status="REJECTED"` 时，`review_target` 和非空 `review_feedback` 必填。
- `repair_attempts` 表示已经完成的修复次数；是否允许下一次修复必须在进入 `repair_agent` 前判断。
- `max_repair_attempts` 必须为正整数，并由中间件限制在安全上限内。
- `audit_events` 通过 reducer 合并；节点返回新增事件列表，不得复制或覆盖既有事件。
- Python 3.10 必须从 `typing_extensions` 导入 `TypedDict`，并以 Pydantic `TypeAdapter` 对完整状态和合并后的节点更新执行运行时校验。

## Graph Nodes & Routing Logic

```python
from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


def human_review_script(state: AgentState) -> dict:
    validate_agent_state(state)
    decision: ReviewDecision = interrupt(
        {
            "review_target": "script",
            "artifact": state["script"],
            "allowed_statuses": ["APPROVED", "REJECTED"],
        }
    )
    validated = validate_review_decision(decision, expected_target="script")
    update = {
        "workflow_status": "RUNNING",
        "approval_status": validated["approval_status"],
        "review_target": "script",
        "review_feedback": validated["feedback"],
    }
    return validate_node_update(state, update)


def human_review_storyboard(state: AgentState) -> dict:
    validate_agent_state(state)
    decision: ReviewDecision = interrupt(
        {
            "review_target": "storyboard",
            "artifact": state["storyboard"],
            "allowed_statuses": ["APPROVED", "REJECTED"],
        }
    )
    validated = validate_review_decision(decision, expected_target="storyboard")
    update = {
        "workflow_status": "RUNNING",
        "approval_status": validated["approval_status"],
        "review_target": "storyboard",
        "review_feedback": validated["feedback"],
    }
    return validate_node_update(state, update)


def validated_node(node):
    def run(state: AgentState) -> dict:
        validate_agent_state(state)
        return validate_node_update(state, node(state))

    return run


def route_script_review(
    state: AgentState,
) -> Literal["storyboard_planner", "repair_agent", "failure"]:
    validate_agent_state(state)
    if (
        state["approval_status"] == "APPROVED"
        and state.get("review_target") == "script"
    ):
        return "storyboard_planner"
    if (
        state["approval_status"] == "REJECTED"
        and state.get("review_target") == "script"
        and bool(state.get("review_feedback", "").strip())
        and state["repair_attempts"] < state["max_repair_attempts"]
    ):
        return "repair_agent"
    return "failure"


def route_storyboard_review(
    state: AgentState,
) -> Literal["tts_synthesizer", "repair_agent", "failure"]:
    validate_agent_state(state)
    if (
        state["approval_status"] == "APPROVED"
        and state.get("review_target") == "storyboard"
    ):
        return "tts_synthesizer"
    if (
        state["approval_status"] == "REJECTED"
        and state.get("review_target") == "storyboard"
        and bool(state.get("review_feedback", "").strip())
        and state["repair_attempts"] < state["max_repair_attempts"]
    ):
        return "repair_agent"
    return "failure"


def route_repair(
    state: AgentState,
) -> Literal["human_review_script", "human_review_storyboard", "failure"]:
    validate_agent_state(state)
    if state["approval_status"] != "PENDING":
        return "failure"
    if state["repair_attempts"] > state["max_repair_attempts"]:
        return "failure"
    if state.get("review_target") == "script":
        return "human_review_script"
    if state.get("review_target") == "storyboard":
        return "human_review_storyboard"
    return "failure"


def build_workflow(checkpointer: BaseCheckpointSaver):
    workflow = StateGraph(AgentState)
    workflow.add_node("script_generator", validated_node(script_generator))
    workflow.add_node("human_review_script", human_review_script)
    workflow.add_node("storyboard_planner", validated_node(storyboard_planner))
    workflow.add_node("human_review_storyboard", human_review_storyboard)
    workflow.add_node("repair_agent", validated_node(repair_agent))
    workflow.add_node("tts_synthesizer", validated_node(tts_synthesizer))
    workflow.add_node("video_composer", validated_node(video_composer))
    workflow.add_node("failure", validated_node(failure_handler))

    workflow.add_edge(START, "script_generator")
    workflow.add_edge("script_generator", "human_review_script")
    workflow.add_conditional_edges(
        "human_review_script",
        route_script_review,
        {
            "storyboard_planner": "storyboard_planner",
            "repair_agent": "repair_agent",
            "failure": "failure",
        },
    )
    workflow.add_edge("storyboard_planner", "human_review_storyboard")
    workflow.add_conditional_edges(
        "human_review_storyboard",
        route_storyboard_review,
        {
            "tts_synthesizer": "tts_synthesizer",
            "repair_agent": "repair_agent",
            "failure": "failure",
        },
    )
    workflow.add_conditional_edges(
        "repair_agent",
        route_repair,
        {
            "human_review_script": "human_review_script",
            "human_review_storyboard": "human_review_storyboard",
            "failure": "failure",
        },
    )
    workflow.add_edge("tts_synthesizer", "video_composer")
    workflow.add_edge("video_composer", END)
    workflow.add_edge("failure", END)
    return workflow.compile(checkpointer=checkpointer)


# 应用生命周期内创建持久化 SQLite checkpointer。
with SqliteSaver.from_conn_string("./data/checkpoints/workflow.db") as checkpointer:
    short_video_graph = build_workflow(checkpointer)

    graph_config = {
        "configurable": {
            "thread_id": authenticated_thread_id,
        }
    }
    paused = short_video_graph.invoke(initial_state, config=graph_config)
    resumed = short_video_graph.invoke(
        Command(resume=validated_review_decision),
        config=graph_config,
    )
```

路由与恢复约束：

- `human_review_*` 节点只调用一次固定顺序的 `interrupt()`，且不得用 `try/except` 包裹。
- 审核恢复必须使用同一 `thread_id`；恢复载荷先经过枚举、反馈和用户归属校验。
- 修复节点完成一次修复后，将 `repair_attempts` 加一、`approval_status` 重置为 `PENDING`，再由 `route_repair` 返回原审核节点。
- 达到修复上限后的再次驳回进入 `failure`；最后一次允许的修复仍会经过人工回审。
- `video_composer` 成功时写入 `workflow_status="COMPLETED"` 和 `current_stage="completed"`；失败处理器写入对应失败终态。

## Middleware Design

请求在调用图之前按以下顺序执行：

1. **强制认证**：验证会话或访问令牌；未登录请求返回 401，且不创建状态、历史或检查点。
2. **线程归属校验**：服务端生成 `request_id` 和不可猜测的 `thread_id`，将线程绑定至当前 `user_id`；客户端不得自行指定其他用户线程。
3. **用户配置装载**：从 SQLite 读取语言、时长、画幅、音色等配置，并将其解析为 `UserPreferences`；未知字段、非法枚举和越界数值立即拒绝。
4. **密钥引用装载**：从加密用户配置中取得 `tts_secret_ref`。只有 TTS 工具适配器可在调用瞬间解析密钥值，图状态、检查点和日志只能看到引用。
5. **历史与素材授权**：按 `user_id` 查询历史摘要和素材引用；拒绝跨用户记录、路径穿越、符号链接逃逸和未授权 URL。
6. **状态初始化**：设置 `workflow_status="RUNNING"`、`current_stage="script_generation"`、`approval_status="PENDING"`、`repair_attempts=0`，并配置受限的 `max_repair_attempts`。
7. **图执行与暂停**：使用绑定线程的配置调用图；收到审核中断后，只向该用户返回可序列化的审核载荷，并把历史状态保存在 SQLite checkpointer。
8. **审核恢复**：验证登录用户仍拥有该线程，校验 `ReviewDecision`，再以 `Command(resume=...)` 和原 `thread_id` 恢复。
9. **结果持久化**：完成或失败后，按 `user_id` 保存产物 URL、审核结论和脱敏审计摘要；禁止持久化 API Key、完整供应商响应和跨用户绝对路径。

运行时通过 `validate_user_scope` 同时校验登录用户、线程所有者、状态用户、密钥引用、历史记录和全部素材引用的所有权映射。节点返回的所有状态更新必须在进入下一条边之前通过 TypedDict 对应的 Pydantic 运行时模式校验。认证失败、状态字段缺失、线程归属不一致、修复上限耗尽或产物归属异常均采用失败关闭策略。
