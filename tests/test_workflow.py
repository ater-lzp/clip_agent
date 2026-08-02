"""Executable workflow tests for state transitions and human-review routing."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest
import yaml
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from backend.workflow import (
    AgentState,
    WorkflowNodes,
    build_workflow,
    route_repair,
    route_script_review,
    route_storyboard_review,
    validate_agent_state,
    validate_node_update,
    validate_review_decision,
    validate_user_scope,
)


def _event(state: AgentState, node: str) -> list[dict[str, str]]:
    return [
        {
            "event_type": "completed",
            "node": node,
            "request_id": state["request_id"],
            "occurred_at": "2026-08-02T00:00:00+00:00",
        }
    ]


@pytest.fixture
def deterministic_nodes() -> WorkflowNodes:
    def script_generator(state: AgentState) -> dict[str, Any]:
        return {
            "script": f"Script: {state['topic']}",
            "workflow_status": "WAITING_REVIEW",
            "current_stage": "script_review",
            "approval_status": "PENDING",
            "review_target": "script",
            "repair_attempts": 0,
            "audit_events": _event(state, "script_generator"),
        }

    def storyboard_planner(state: AgentState) -> dict[str, Any]:
        return {
            "storyboard": [
                {
                    "shot_id": "shot-1",
                    "duration_seconds": 5.0,
                    "visual_description": "Opening shot",
                    "narration": state["script"],
                    "asset_refs": [],
                }
            ],
            "workflow_status": "WAITING_REVIEW",
            "current_stage": "storyboard_review",
            "approval_status": "PENDING",
            "review_target": "storyboard",
            "review_feedback": "",
            "repair_attempts": 0,
            "audit_events": _event(state, "storyboard_planner"),
        }

    def repair_agent(state: AgentState) -> dict[str, Any]:
        updates: dict[str, Any] = {
            "repair_attempts": state["repair_attempts"] + 1,
            "approval_status": "PENDING",
            "workflow_status": "WAITING_REVIEW",
            "audit_events": _event(state, "repair_agent"),
        }
        if state["review_target"] == "script":
            updates.update(
                {
                    "script": f"{state['script']} [repaired]",
                    "current_stage": "script_review",
                }
            )
        else:
            repaired = [dict(shot) for shot in state["storyboard"]]
            repaired[0]["narration"] = f"{repaired[0]['narration']} [repaired]"
            updates.update(
                {
                    "storyboard": repaired,
                    "current_stage": "storyboard_review",
                }
            )
        return updates

    def tts_synthesizer(state: AgentState) -> dict[str, Any]:
        return {
            "selected_voice_id": "冰糖",
            "audio_url": f"media://{state['user_id']}/audio.wav",
            "workflow_status": "RUNNING",
            "current_stage": "video_composition",
            "audit_events": _event(state, "tts_synthesizer"),
        }

    def video_composer(state: AgentState) -> dict[str, Any]:
        return {
            "video_url": f"media://{state['user_id']}/video.mp4",
            "workflow_status": "COMPLETED",
            "current_stage": "completed",
            "audit_events": _event(state, "video_composer"),
        }

    def failure_handler(state: AgentState) -> dict[str, Any]:
        return {
            "workflow_status": "FAILED",
            "current_stage": "failed",
            "error_code": "WORKFLOW_ROUTE_REJECTED",
            "error_message": "Workflow state failed closed",
            "audit_events": _event(state, "failure"),
        }

    return WorkflowNodes(
        script_generator=script_generator,
        storyboard_planner=storyboard_planner,
        repair_agent=repair_agent,
        tts_synthesizer=tts_synthesizer,
        video_composer=video_composer,
        failure_handler=failure_handler,
    )


@pytest.fixture
def initial_state() -> AgentState:
    return {
        "request_id": "request-1",
        "user_id": "user-1",
        "topic": "Harness Engineering",
        "user_preferences": {
            "language": "zh-CN",
            "requested_voice_name": "冰糖",
        },
        "tts_secret_ref": "secret-ref-1",
        "authorized_asset_refs": [],
        "workflow_status": "RUNNING",
        "current_stage": "script_generation",
        "approval_status": "PENDING",
        "repair_attempts": 0,
        "max_repair_attempts": 2,
        "audit_events": [],
    }


def _config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def test_approved_reviews_execute_complete_graph(
    tmp_path,
    deterministic_nodes: WorkflowNodes,
    initial_state: AgentState,
) -> None:
    with SqliteSaver.from_conn_string(str(tmp_path / "happy-path.db")) as saver:
        graph = build_workflow(deterministic_nodes, saver)
        config = _config("user-1:happy-path")

        script_review = graph.invoke(initial_state, config=config)
        assert script_review["__interrupt__"][0].value["review_target"] == "script"

        storyboard_review = graph.invoke(
            Command(resume={"approval_status": "APPROVED", "feedback": ""}),
            config=config,
        )
        assert storyboard_review["__interrupt__"][0].value["review_target"] == "storyboard"

        completed = graph.invoke(
            Command(resume={"approval_status": "APPROVED", "feedback": ""}),
            config=config,
        )

    assert completed["workflow_status"] == "COMPLETED"
    assert completed["current_stage"] == "completed"
    assert completed["video_url"] == "media://user-1/video.mp4"
    assert [event["node"] for event in completed["audit_events"]] == [
        "script_generator",
        "human_review_script",
        "storyboard_planner",
        "human_review_storyboard",
        "tts_synthesizer",
        "video_composer",
    ]


def test_rejected_script_is_repaired_and_re_reviewed(
    tmp_path,
    deterministic_nodes: WorkflowNodes,
    initial_state: AgentState,
) -> None:
    with SqliteSaver.from_conn_string(str(tmp_path / "script-repair.db")) as saver:
        graph = build_workflow(deterministic_nodes, saver)
        config = _config("user-1:script-repair")
        graph.invoke(initial_state, config=config)

        repaired_review = graph.invoke(
            Command(
                resume={"approval_status": "REJECTED", "feedback": "Improve hook"}
            ),
            config=config,
        )

    assert repaired_review["__interrupt__"][0].value["review_target"] == "script"
    assert repaired_review["repair_attempts"] == 1
    assert repaired_review["approval_status"] == "PENDING"
    assert repaired_review["script"].endswith("[repaired]")


def test_rejected_storyboard_is_repaired_and_re_reviewed(
    tmp_path,
    deterministic_nodes: WorkflowNodes,
    initial_state: AgentState,
) -> None:
    with SqliteSaver.from_conn_string(str(tmp_path / "storyboard-repair.db")) as saver:
        graph = build_workflow(deterministic_nodes, saver)
        config = _config("user-1:storyboard-repair")
        graph.invoke(initial_state, config=config)
        graph.invoke(
            Command(resume={"approval_status": "APPROVED", "feedback": ""}),
            config=config,
        )

        repaired_review = graph.invoke(
            Command(
                resume={"approval_status": "REJECTED", "feedback": "Fix shot one"}
            ),
            config=config,
        )

    assert repaired_review["__interrupt__"][0].value["review_target"] == "storyboard"
    assert repaired_review["repair_attempts"] == 1
    assert repaired_review["storyboard"][0]["narration"].endswith("[repaired]")


def test_last_allowed_repair_is_reviewed_before_failure(
    tmp_path,
    deterministic_nodes: WorkflowNodes,
    initial_state: AgentState,
) -> None:
    initial_state["max_repair_attempts"] = 1
    with SqliteSaver.from_conn_string(str(tmp_path / "repair-limit.db")) as saver:
        graph = build_workflow(deterministic_nodes, saver)
        config = _config("user-1:repair-limit")
        graph.invoke(initial_state, config=config)
        repaired_review = graph.invoke(
            Command(resume={"approval_status": "REJECTED", "feedback": "Repair"}),
            config=config,
        )
        assert repaired_review["repair_attempts"] == 1
        assert "__interrupt__" in repaired_review

        failed = graph.invoke(
            Command(
                resume={"approval_status": "REJECTED", "feedback": "Still wrong"}
            ),
            config=config,
        )

    assert failed["workflow_status"] == "FAILED"
    assert failed["repair_attempts"] == 1


@pytest.mark.parametrize(
    "decision",
    [
        {"approval_status": "PENDING", "feedback": ""},
        {"approval_status": "REJECTED", "feedback": "   "},
        {"approval_status": "UNKNOWN", "feedback": "invalid"},
        {"approval_status": "APPROVED", "feedback": "", "unexpected": True},
        "APPROVED",
    ],
)
def test_invalid_review_decisions_are_rejected(decision: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        validate_review_decision(decision, expected_target="script")


def test_route_functions_fail_closed_on_mismatched_state(
    initial_state: AgentState,
) -> None:
    state: AgentState = {
        **initial_state,
        "approval_status": "APPROVED",
        "review_target": "storyboard",
        "review_feedback": "",
    }
    assert route_script_review(state) == "failure"
    assert route_storyboard_review({**state, "review_target": "script"}) == "failure"
    assert route_repair({**state, "approval_status": "APPROVED"}) == "failure"


def test_agent_state_and_node_updates_are_runtime_validated(
    initial_state: AgentState,
) -> None:
    assert validate_agent_state(initial_state)["current_stage"] == "script_generation"

    with pytest.raises(ValueError):
        validate_agent_state({**initial_state, "unknown_field": "blocked"})
    with pytest.raises(ValueError):
        validate_agent_state({**initial_state, "current_stage": "not-a-stage"})
    with pytest.raises(ValueError):
        validate_node_update(initial_state, {"selected_voice_id": "not-a-voice"})
    with pytest.raises(ValueError):
        validate_node_update(initial_state, {"unknown_field": "blocked"})


def test_graph_rejects_invalid_node_update_before_routing(
    tmp_path,
    deterministic_nodes: WorkflowNodes,
    initial_state: AgentState,
) -> None:
    def invalid_script_generator(state: AgentState) -> dict[str, Any]:
        return {
            "current_stage": "not-a-stage",
            "audit_events": _event(state, "invalid_script_generator"),
        }

    invalid_nodes = replace(
        deterministic_nodes,
        script_generator=invalid_script_generator,
    )
    with SqliteSaver.from_conn_string(str(tmp_path / "invalid-update.db")) as saver:
        graph = build_workflow(invalid_nodes, saver)
        with pytest.raises(ValueError):
            graph.invoke(initial_state, config=_config("user-1:invalid-update"))


def test_user_scope_rejects_cross_user_resources(initial_state: AgentState) -> None:
    scoped_state: AgentState = {
        **initial_state,
        "history_record_id": "history-1",
        "authorized_asset_refs": ["asset-1"],
    }
    ownership = {
        "thread_owners": {"thread-1": "user-1"},
        "secret_owners": {"secret-ref-1": "user-1"},
        "history_owners": {"history-1": "user-1"},
        "asset_owners": {"asset-1": "user-1"},
    }
    validate_user_scope("user-1", "thread-1", scoped_state, **ownership)

    with pytest.raises(PermissionError):
        validate_user_scope("", "thread-1", scoped_state, **ownership)
    with pytest.raises(PermissionError):
        validate_user_scope("user-2", "thread-1", scoped_state, **ownership)
    with pytest.raises(PermissionError):
        validate_user_scope(
            "user-1",
            "thread-1",
            {**scoped_state, "tts_secret_ref": "secret-user-2"},
            **ownership,
        )
    with pytest.raises(PermissionError):
        validate_user_scope(
            "user-1",
            "thread-1",
            {**scoped_state, "history_record_id": "history-user-2"},
            **ownership,
        )
    with pytest.raises(PermissionError):
        validate_user_scope(
            "user-1",
            "thread-1",
            {**scoped_state, "authorized_asset_refs": ["asset-user-2"]},
            **ownership,
        )


def test_sqlite_checkpoints_remain_isolated_between_users(
    tmp_path,
    deterministic_nodes: WorkflowNodes,
    initial_state: AgentState,
) -> None:
    user_1_state = deepcopy(initial_state)
    user_2_state = deepcopy(initial_state)
    user_2_state.update(
        {
            "request_id": "request-2",
            "user_id": "user-2",
            "tts_secret_ref": "secret-ref-2",
        }
    )
    user_1_config = _config("thread-user-1")
    user_2_config = _config("thread-user-2")

    with SqliteSaver.from_conn_string(str(tmp_path / "user-isolation.db")) as saver:
        graph = build_workflow(deterministic_nodes, saver)
        graph.invoke(user_1_state, config=user_1_config)
        graph.invoke(user_2_state, config=user_2_config)

        graph.invoke(
            Command(resume={"approval_status": "APPROVED", "feedback": ""}),
            config=user_1_config,
        )
        user_2_checkpoint = graph.get_state(user_2_config).values

    assert user_2_checkpoint["user_id"] == "user-2"
    assert user_2_checkpoint["current_stage"] == "script_review"
    assert user_2_checkpoint["approval_status"] == "PENDING"


def test_harness_mimo_configuration_uses_official_values() -> None:
    with open("harness.yaml", encoding="utf-8") as stream:
        harness = yaml.safe_load(stream)

    mimo = harness["tools_config"]["mimo_tts"]
    assert mimo["model"] == "mimo-v2.5-tts"
    assert harness["environment_variables"]["MIMO_BASE_URL"]["example"] == (
        "https://api.xiaomimimo.com/v1"
    )
    assert [voice["voice_id"] for voice in mimo["voices"]] == [
        "冰糖",
        "茉莉",
        "苏打",
        "白桦",
        "Mia",
        "Chloe",
        "Milo",
        "Dean",
    ]
