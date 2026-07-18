import asyncio

from multi_domain_enterprise_project.agent import audit_agent as audit_module
from multi_domain_enterprise_project.core.task_state import TaskState, TaskStatus


def _stub_audit_result(monkeypatch, *, is_pass: bool, correction_targets: str = ""):
    class FakeAgent:
        async def ainvoke(self, input, config):
            return {
                "structured_response": audit_module.AuditOutputFormat(
                    is_pass=is_pass,
                    correction_targets=correction_targets,
                )
            }

    async def fake_qwen_model(*args, **kwargs):
        return object()

    monkeypatch.setattr(audit_module, "qwen_model", fake_qwen_model)
    monkeypatch.setattr(
        audit_module,
        "create_agent",
        lambda **kwargs: FakeAgent(),
    )


def _auditable_state(**overrides) -> TaskState:
    values = {
        "task_status": TaskStatus.AUDITING,
        "requested_agents": ["finance"],
        "pending_sub_agents": ["finance"],
        "finished_sub_agents": ["finance"],
        "sub_agent_response": {
            "aggregator": {
                "回复内容": "聚合回复",
                "参考资料": ["内部制度"],
            }
        },
    }
    values.update(overrides)
    return TaskState(**values)


def test_audit_rejection_retries_while_budget_remains(monkeypatch):
    _stub_audit_result(
        monkeypatch,
        is_pass=False,
        correction_targets="finance 补充来源",
    )
    state = _auditable_state(retry_count=1, max_retries=3)

    update = asyncio.run(audit_module.audit_agent(state, {}))

    assert update["task_status"] == TaskStatus.RETRYING
    assert update["retry_count"] == 2
    assert update["audit_feedback"]["correction_targets"] == "finance 补充来源"


def test_audit_rejection_fails_when_retry_budget_is_exhausted(monkeypatch):
    _stub_audit_result(
        monkeypatch,
        is_pass=False,
        correction_targets="finance 删除敏感信息",
    )
    state = _auditable_state(
        retry_count=3,
        max_retries=3,
        result={"最终回复": "上一轮结果", "参考资料": []},
    )

    update = asyncio.run(audit_module.audit_agent(state, {}))

    assert update["task_status"] == TaskStatus.FAILED
    assert update["retry_count"] == 3
    assert update["result"] is None
    assert update["audit_feedback"]["correction_targets"] == "finance 删除敏感信息"
    assert "最大重试次数" in update["messages"][-1].content


def test_audit_pass_clears_all_round_scoped_dispatch_state(monkeypatch):
    _stub_audit_result(monkeypatch, is_pass=True)
    state = _auditable_state()

    update = asyncio.run(audit_module.audit_agent(state, {}))

    assert update["task_status"] == TaskStatus.COMPLETED
    assert update["requested_agents"] == []
    assert update["pending_sub_agents"] == []
    assert update["finished_sub_agents"] == []
    assert update["sub_agent_response"] == {}
