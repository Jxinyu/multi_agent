"""独立的真实 LLM 评估脚本。

用途：
- 单独跑真实模型，不影响 pytest 回归测试。
- 读取 `tests/supervisor_intent_dispatch_cases.json`。
- 评估 supervisor 是否遵守单一流程：
  1. 先分析信息是否足够；
  2. 需要调子 agent 时，先调用 `get_sub_agent_list`；
  3. 再调用 `invoke_sub_agent`；
  4. 信息不够时调用 `human_in_loop`。
- 把评估结果写入 `tests/supervisor_intent_dispatch_llm_scores.json`。

运行方式示例：

```bash
python -m multi_domain_enterprise_project.tests.eval_supervisor_llm
```

说明：
- 这是评估脚本，不是单元测试。
- 这里不做固定措辞断言，只评估工具调用顺序和动作空间。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from multi_domain_enterprise_project.agent.supervisor_agent import get_sub_agent_list, human_in_loop, invoke_sub_agent
from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum

TESTS_DIR = Path(__file__).resolve().parent
DATASET_PATH = TESTS_DIR / "supervisor_intent_dispatch_cases.json"
OUTPUT_PATH = TESTS_DIR / "supervisor_intent_dispatch_llm_scores2.json"

SYSTEM_PROMPT = """
# 角色定位
你是多代理系统的“交通枢纽”，负责接收用户问题，并将其路由给合适的领域专家Agent。**你不需要直接回答用户，只负责“分发任务”或“向用户追问”。**

## 核心判断原则
1. 先判断信息是否足够，再决定是否分发或追问。
2. 如果用户没有明确主问题、目标对象、流程名称、系统名称或业务边界，优先使用 `human_in_loop` 追问；如果仍可合理分发，就不要过早追问。
3. 如果问题涉及多个领域，尽量一次性识别全部相关领域，并在同一次 `invoke_sub_agent` 中全部下发，避免拆分成多次。
4. 如果只涉及单一领域，也要尽量保持任务边界准确，不要把无关子代理一起带上。

## 单一流程约束
1. 对于首次路由：若需要分发子 agent，必须先调用 `get_sub_agent_list`，再根据返回结果调用 `invoke_sub_agent`。
2. `get_sub_agent_list` 只能用于获取一次当前可用子代理列表；拿到列表后，不要重复调用它。
3. 对于澄清类问题，如果主问题明显不明确、范围过宽、缺少关键上下文，直接调用 `human_in_loop`；但不要把轻微不完整也一律判成澄清。
4. 多领域问题尽量一次性把所有相关子代理放进同一次 `invoke_sub_agent` 调用里；如果边界较模糊，宁可追问也不要只发一部分。
5. 单领域问题避免过度联想，不要额外塞入无关子代理。

## 审计重试约束
1. 当上下文中出现审计反馈时，进入“重试模式”。
2. 重试模式下，优先直接调用 `invoke_sub_agent`，把修正后的任务一次性下发给需要修正的子代理。
3. 重试模式下，不要再次调用 `get_sub_agent_list`。
4. 如果审计反馈明确要求先向用户追问，才可以使用 `human_in_loop`；否则不要再次澄清。
5. 重试时必须保留原始问题意图，并结合审计反馈补充遗漏内容、修正错误范围或错误对象。
6. 重试指令要具体、可执行、可落地，不要只说“重新处理”“继续跟进”。

## 工作方式
- 首次路由：先判断是否足够明确；不明确就直接追问，明确且需要分发时，先获取子代理列表，再分派。
- 重试路由：有审计反馈时优先直接修正派发，不再重复走首次路由。
- 你只输出工具调用，不输出自然语言回复。
""".strip()

VALID_SUB_AGENTS = {item.value for item in SubAgentEnum}


@dataclass(frozen=True)
class RouteCase:
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


@dataclass
class LLMCaseResult:
    case_id: str
    expected_tool_chain: list[str]
    actual_tool_chain: list[str]
    passed: bool
    reason: str
    expected_agents: list[str]
    actual_agents: list[str]
    clarification_text: str | None = None
    mode: str = "first_pass"


def load_cases() -> list[RouteCase]:
    raw_cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    cases: list[RouteCase] = []
    for item in raw_cases:
        item = dict(item)
        cases.append(RouteCase(**item))
    return cases


async def _call_model(agent, messages: list[Any]) -> AIMessage:
    response = await agent.ainvoke(messages)
    if isinstance(response, AIMessage):
        return response
    return AIMessage(content=str(response))


def _build_retry_messages(case: RouteCase, first_pass_result: LLMCaseResult) -> list[Any]:
    audit_text = case.audit_feedback or "审计反馈要求修正当前分发结果"
    retry_prompt = (
        f"{case.query}\n\n"
        f"首次分发结果：{first_pass_result.actual_tool_chain} -> {first_pass_result.actual_agents}\n"
        f"审计反馈：{audit_text}\n"
        f"请根据审计反馈修正后，直接重新调用对应工具。"
    )
    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=retry_prompt),
    ]


async def run_one_case(model, case: RouteCase) -> LLMCaseResult:
    """对单个样本做一次真实 LLM 路由评估。

    评估原则：
    - strict 样本：硬性检查工具链顺序。
    - boundary 样本：如果模型选择更保守的路径，也只做统计，不一票否决。
    - 含审计反馈的样本：额外检查重试轮是否直接进入 invoke_sub_agent。
    """
    agent = model.bind_tools(tools=[get_sub_agent_list, invoke_sub_agent, human_in_loop])
    messages: list[Any] = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=case.query)]
    actual_tool_chain: list[str] = []
    actual_agents: list[str] = []
    clarification_text: str | None = None

    # 第一次决策：必须先判断信息是否足够；如果要调子 agent，应该先走 get_sub_agent_list。
    first = await _call_model(agent, messages)
    first_tools = first.tool_calls or []
    if not first_tools:
        passed = case.evaluation_tier == "boundary"
        return LLMCaseResult(
            case_id=case.case_id,
            expected_tool_chain=["human_in_loop"] if case.needs_clarification else ["get_sub_agent_list", "invoke_sub_agent"],
            actual_tool_chain=actual_tool_chain,
            passed=passed,
            reason="模型未输出 tool call",
            expected_agents=case.expected_agents,
            actual_agents=actual_agents,
        )

    first_tool = first_tools[0]["name"]
    actual_tool_chain.append(first_tool)

    if first_tool == "human_in_loop":
        clarification_text = first_tools[0]["args"].get("content", "")
        clarifying = bool(clarification_text.strip())
        passed = clarifying if case.needs_clarification else case.evaluation_tier == "boundary"
        return LLMCaseResult(
            case_id=case.case_id,
            expected_tool_chain=["human_in_loop"] if case.needs_clarification else ["get_sub_agent_list", "invoke_sub_agent"],
            actual_tool_chain=actual_tool_chain,
            passed=passed,
            reason="调用了 human_in_loop" if clarifying else "澄清文本为空",
            expected_agents=case.expected_agents,
            actual_agents=actual_agents,
            clarification_text=clarification_text,
        )

    if first_tool != "get_sub_agent_list":
        # 严格要求：如果要调子 agent，第一步必须先取列表。
        passed = case.evaluation_tier == "boundary"
        return LLMCaseResult(
            case_id=case.case_id,
            expected_tool_chain=["human_in_loop"] if case.needs_clarification else ["get_sub_agent_list", "invoke_sub_agent"],
            actual_tool_chain=actual_tool_chain,
            passed=passed,
            reason="未先调用 get_sub_agent_list",
            expected_agents=case.expected_agents,
            actual_agents=actual_agents,
        )

    sub_agent_list = [
        {"sub_agent_name": item.value, "description": item.description}
        for item in SubAgentEnum
    ]
    actual_tool_chain.append("get_sub_agent_list")
    messages = messages + [
        first,
        ToolMessage(content=json.dumps(sub_agent_list, ensure_ascii=False), tool_call_id=first_tools[0]["id"]),
    ]
    second = await _call_model(agent, messages)
    second_tools = second.tool_calls or []
    if not second_tools:
        passed = case.evaluation_tier == "boundary"
        return LLMCaseResult(
            case_id=case.case_id,
            expected_tool_chain=["human_in_loop"] if case.needs_clarification else ["get_sub_agent_list", "invoke_sub_agent"],
            actual_tool_chain=actual_tool_chain,
            passed=passed,
            reason="第二步未输出 tool call",
            expected_agents=case.expected_agents,
            actual_agents=actual_agents,
        )

    second_tool = second_tools[0]["name"]
    actual_tool_chain.append(second_tool)

    if case.needs_clarification:
        passed = case.evaluation_tier == "boundary" and second_tool == "human_in_loop"
        if second_tool == "human_in_loop":
            clarification_text = second_tools[0]["args"].get("content", "")
        return LLMCaseResult(
            case_id=case.case_id,
            expected_tool_chain=["human_in_loop"],
            actual_tool_chain=actual_tool_chain,
            passed=passed,
            reason="澄清类样本不应先取子代理列表后再分发",
            expected_agents=case.expected_agents,
            actual_agents=actual_agents,
            clarification_text=clarification_text,
        )

    if second_tool != "invoke_sub_agent":
        passed = case.evaluation_tier == "boundary"
        return LLMCaseResult(
            case_id=case.case_id,
            expected_tool_chain=["get_sub_agent_list", "invoke_sub_agent"],
            actual_tool_chain=actual_tool_chain,
            passed=passed,
            reason="第二步未调用 invoke_sub_agent",
            expected_agents=case.expected_agents,
            actual_agents=actual_agents,
        )

    args = second_tools[0]["args"]
    actual_agents = [item["sub_agent_name"] for item in args.get("sub_agents", [])]
    agent_set_ok = set(actual_agents) == set(case.expected_agents) and len(actual_agents) == len(set(actual_agents))
    if case.scenario_type == "multi":
        agent_set_ok = agent_set_ok and len(actual_agents) >= 2

    passed = agent_set_ok or case.evaluation_tier == "boundary"
    first_pass_result = LLMCaseResult(
        case_id=case.case_id,
        expected_tool_chain=["get_sub_agent_list", "invoke_sub_agent"],
        actual_tool_chain=actual_tool_chain,
        passed=passed,
        reason="工具链与派发内容匹配" if agent_set_ok else "派发子代理不符合预期",
        expected_agents=case.expected_agents,
        actual_agents=actual_agents,
    )

    if not case.audit_feedback:
        return first_pass_result

    retry_expected_agents = case.retry_expected_agents or case.expected_agents
    retry_expected_chain = case.retry_expected_tool_chain or ["invoke_sub_agent"]
    retry_messages = _build_retry_messages(case, first_pass_result)
    retry_first = await _call_model(agent, retry_messages)
    retry_tools = retry_first.tool_calls or []
    retry_actual_chain: list[str] = []
    retry_actual_agents: list[str] = []
    retry_passed = False
    retry_reason = "重试轮未输出 tool call"

    if retry_tools:
        retry_tool_name = retry_tools[0]["name"]
        retry_actual_chain.append(retry_tool_name)
        if retry_tool_name == "invoke_sub_agent":
            retry_args = retry_tools[0]["args"]
            retry_actual_agents = [item["sub_agent_name"] for item in retry_args.get("sub_agents", [])]
            retry_passed = retry_tool_name in retry_expected_chain and set(retry_actual_agents) == set(retry_expected_agents)
            retry_reason = "重试轮已按审计反馈直接重分发" if retry_passed else "重试轮分发子代理不符合预期"
        elif retry_tool_name == "human_in_loop":
            retry_passed = retry_tool_name in retry_expected_chain
            retry_reason = "重试轮按审计反馈转为继续澄清" if retry_passed else "重试轮不应再次澄清"
        else:
            retry_reason = f"重试轮调用了 {retry_tool_name}，但期望 {retry_expected_chain}"

    expected_chain = ["get_sub_agent_list", "invoke_sub_agent", retry_expected_chain[0]]
    return LLMCaseResult(
        case_id=case.case_id,
        expected_tool_chain=expected_chain,
        actual_tool_chain=actual_tool_chain + retry_actual_chain,
        passed=first_pass_result.passed and retry_passed,
        reason=retry_reason,
        expected_agents=retry_expected_agents,
        actual_agents=retry_actual_agents,
        mode="retry_after_audit",
    )


async def main() -> None:
    cases = load_cases()
    model = await qwen_model("qwen-flash")

    results: list[LLMCaseResult] = []
    for case in cases:
        result = await run_one_case(model, case)
        results.append(result)
        print(f"[{result.case_id}] chain={result.actual_tool_chain} passed={result.passed} reason={result.reason}")

    passed = sum(1 for item in results if item.passed)
    strict_total = sum(1 for item in cases if item.evaluation_tier == "strict")
    strict_passed = sum(1 for item, case in zip(results, cases, strict=False) if item.passed and case.evaluation_tier == "strict")
    boundary_total = sum(1 for item in cases if item.evaluation_tier == "boundary")
    boundary_passed = sum(1 for item, case in zip(results, cases, strict=False) if item.passed and case.evaluation_tier == "boundary")
    payload = {
        "total_cases": len(results),
        "passed_cases": passed,
        "failed_cases": [item.__dict__ for item in results if not item.passed],
        "pass_rate": (passed / len(results)) if results else 0,
        "strict_total": strict_total,
        "strict_passed": strict_passed,
        "boundary_total": boundary_total,
        "boundary_passed": boundary_passed,
        "scoring_rule": {
            "name": "supervisor_real_llm_eval_two_stage_with_retry",
            "summary": "真实 LLM 评估首次路由与 audit 失败后的重试分发：首次先分析是否需要澄清或分发；重试时应直接 invoke_sub_agent。",
            "allowed_actions": ["get_sub_agent_list", "invoke_sub_agent", "human_in_loop"],
            "allowed_sub_agents": sorted(VALID_SUB_AGENTS),
            "tiers": {
                "strict": "语义明确、标签稳定，适合硬性评估",
                "boundary": "边界/模糊/歧义样本，仅统计不一票否决",
                "retry": "audit 失败后的修正路由，重点检查是否直接重分发",
            },
        },
        "results": [item.__dict__ for item in results],
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved score report to: {OUTPUT_PATH}")
    print(f"Pass rate: {payload['pass_rate']:.2%}")


if __name__ == "__main__":
    asyncio.run(main())
