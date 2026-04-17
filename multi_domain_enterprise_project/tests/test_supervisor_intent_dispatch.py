"""监督器 supervisor 的路由规则测试。

这个测试文件不再把真实 LLM 的输出当成唯一正确答案，而是把测试重点放回到：
1. 数据集本身是否干净、可复核。
2. supervisor 允许选择的动作空间是否完整。
3. 每类样本是否覆盖到单域、多域、澄清、刁钻边界等不同场景。

说明：
- 这里测试的是“路由规则与样本质量”，不是固定自然语言措辞。
- 真实 LLM 的效果评估应单独做成实验脚本，而不是放在这个会持续回归的测试文件里。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum

TESTS_DIR = Path(__file__).resolve().parent
DATASET_PATH = TESTS_DIR / "supervisor_intent_dispatch_cases.json"
SCORES_PATH = TESTS_DIR / "supervisor_intent_dispatch_scores.json"

VALID_SUB_AGENTS = {item.value for item in SubAgentEnum}
VALID_DIFFICULTY = {"easy", "medium", "hard"}
VALID_SCENARIO = {"single", "multi", "clarify"}
VALID_PRIORITY = {"low", "normal", "high", "urgent"}
VALID_EVALUATION_TIER = {"strict", "boundary", "retry"}


@dataclass(frozen=True)
class RouteCase:
    """单条路由样本。

    字段含义：
    - case_id: 样本唯一标识。
    - query: 用户问题原文。
    - expected_agents: 期望路由到的子代理集合。
    - needs_clarification: 是否应先追问用户。
    - domain_tags: 样本涉及的领域标签，用于人工审查。
    - difficulty: 样本难度等级。
    - scenario_type: 单域 / 多域 / 澄清。
    - priority: 样本优先级。
    - expected_clarification_focus: 澄清类样本应关注的追问点。
    """

    case_id: str
    query: str
    expected_agents: list[str]
    needs_clarification: bool
    domain_tags: list[str]
    difficulty: str
    scenario_type: str = "single"
    priority: str = "normal"
    expected_clarification_focus: list[str] = field(default_factory=list)
    evaluation_tier: str = "strict"
    audit_feedback: str | None = None
    retry_expected_agents: list[str] = field(default_factory=list)
    retry_expected_tool_chain: list[str] = field(default_factory=list)


def load_cases() -> list[RouteCase]:
    """从 JSON 文件读取测试样本。

    所有样本都必须来自外部 JSON，便于：
    - 人工复核
    - 增量维护
    - 分离代码和数据
    """
    raw_cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    return [RouteCase(**item) for item in raw_cases]


TEST_CASES = load_cases()


@pytest.fixture(scope="session")
def scoreboard() -> list[dict[str, Any]]:
    """汇总每个 case 的检查结果，最后统一写入评分文件。"""
    return []


@pytest.fixture(scope="session", autouse=True)
def persist_scores(scoreboard: list[dict[str, Any]]):
    """测试结束后输出评分 JSON。"""
    yield
    passed = sum(1 for item in scoreboard if item["passed"])
    payload = {
        "total_cases": len(scoreboard),
        "passed_cases": passed,
        "failed_cases": [item for item in scoreboard if not item["passed"]],
        "pass_rate": (passed / len(scoreboard)) if scoreboard else 0,
        "scoring_rule": {
            "name": "supervisor_route_space",
            "summary": "只验证可选动作空间、样本覆盖和标签一致性，不把自然语言措辞作为硬断言。",
            "allowed_actions": ["get_sub_agent_list", "invoke_sub_agent", "human_in_loop"],
            "allowed_sub_agents": sorted(VALID_SUB_AGENTS),
            "tiers": {
                "strict": "首次路由样本",
                "boundary": "边界样本",
                "retry": "审计反馈后重试样本",
            },
        },
    }
    SCORES_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize("case", TEST_CASES, ids=[case.case_id for case in TEST_CASES])
def test_case_schema_is_valid(case: RouteCase) -> None:
    """校验单条样本的数据结构是否有效。"""
    assert case.case_id.strip()
    assert case.query.strip()
    assert case.difficulty in VALID_DIFFICULTY
    assert case.scenario_type in VALID_SCENARIO
    assert case.priority in VALID_PRIORITY
    assert case.evaluation_tier in VALID_EVALUATION_TIER
    assert len(case.expected_agents) == len(set(case.expected_agents))
    for agent in case.expected_agents:
        assert agent in VALID_SUB_AGENTS
    if case.needs_clarification:
        assert case.scenario_type == "clarify"
        assert case.expected_agents == []
        assert not case.retry_expected_agents
        assert not case.retry_expected_tool_chain
    else:
        assert case.scenario_type in {"single", "multi"}
        if case.evaluation_tier == "retry":
            assert case.audit_feedback and case.retry_expected_tool_chain
            if case.retry_expected_tool_chain == ["invoke_sub_agent"]:
                assert case.retry_expected_agents
            elif case.retry_expected_tool_chain == ["human_in_loop"]:
                assert not case.retry_expected_agents
            else:
                raise AssertionError("retry_expected_tool_chain must be invoke_sub_agent or human_in_loop")


def test_dataset_has_sufficient_coverage() -> None:
    """检查测试集是否覆盖足够丰富的路由空间。"""
    assert len(TEST_CASES) >= 140

    single_cases = [c for c in TEST_CASES if c.scenario_type == "single"]
    multi_cases = [c for c in TEST_CASES if c.scenario_type == "multi"]
    clarify_cases = [c for c in TEST_CASES if c.scenario_type == "clarify"]
    hard_cases = [c for c in TEST_CASES if c.difficulty == "hard"]
    retry_cases = [c for c in TEST_CASES if c.evaluation_tier == "retry"]

    assert len(single_cases) >= 40
    assert len(multi_cases) >= 40
    assert len(clarify_cases) >= 40
    assert len(hard_cases) >= 40
    assert len(retry_cases) >= 3

    covered_agents = set()
    for case in TEST_CASES:
        covered_agents.update(case.expected_agents)
        covered_agents.update(case.retry_expected_agents)
    assert covered_agents == VALID_SUB_AGENTS


@pytest.mark.parametrize("case", TEST_CASES, ids=[case.case_id for case in TEST_CASES])
def test_route_labels_match_scenario(case: RouteCase, scoreboard: list[dict[str, Any]]) -> None:
    """检查样本标签是否和场景类型一致。

    这里不调用 LLM，只验证路由真值标签是否自洽：
    - 澄清类样本必须没有 expected_agents
    - 单域样本应只包含一个 agent
    - 多域样本应包含两个或以上 agent
    """
    if case.scenario_type == "clarify":
        assert case.needs_clarification is True
        assert case.expected_agents == []
        assert case.expected_clarification_focus
        predicted_action = "human_in_loop"
    elif case.evaluation_tier == "retry":
        assert case.needs_clarification is False
        if case.retry_expected_tool_chain == ["invoke_sub_agent"]:
            assert case.retry_expected_agents
            predicted_action = "invoke_sub_agent"
        elif case.retry_expected_tool_chain == ["human_in_loop"]:
            predicted_action = "human_in_loop"
        else:
            raise AssertionError("retry_expected_tool_chain must be invoke_sub_agent or human_in_loop")
    elif case.scenario_type == "single":
        assert case.needs_clarification is False
        assert len(case.expected_agents) == 1
        predicted_action = "invoke_sub_agent"
    else:
        assert case.needs_clarification is False
        assert len(case.expected_agents) >= 2
        predicted_action = "invoke_sub_agent"

    scoreboard.append(
        {
            "case_id": case.case_id,
            "passed": True,
            "scenario_type": case.scenario_type,
            "predicted_action": predicted_action,
            "expected_agents": case.expected_agents,
        }
    )
