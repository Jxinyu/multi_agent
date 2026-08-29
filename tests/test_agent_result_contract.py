import pytest

from multi_domain_enterprise_project.agent.agent_main import _extract_failure_message, _extract_result
from multi_domain_enterprise_project.core.task_state import TaskStatus


def test_extract_result_requires_structured_terminal_output() -> None:
    with pytest.raises(RuntimeError, match="结构化 result"):
        _extract_result({"messages": ["unstructured answer"]})


def test_extract_result_rejects_empty_reply() -> None:
    with pytest.raises(RuntimeError, match="最终回复"):
        _extract_result({"result": {"最终回复": "", "参考资料": []}})


def test_extract_result_returns_normalized_references() -> None:
    reply, references = _extract_result({"result": {"最终回复": "答案", "参考资料": [1, "doc"]}})
    assert reply == "答案"
    assert references == ["1", "doc"]


def test_extract_failure_message_exposes_audit_reason() -> None:
    message = _extract_failure_message(
        {
            "task_status": TaskStatus.FAILED,
            "audit_feedback": {"correction_targets": "finance 补充来源"},
        }
    )

    assert message == "回答未通过合规审计：finance 补充来源"


def test_extract_failure_message_ignores_non_terminal_state() -> None:
    assert _extract_failure_message({"task_status": TaskStatus.AUDITING}) is None
