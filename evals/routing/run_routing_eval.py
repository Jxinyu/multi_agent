from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import re
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from multi_domain_enterprise_project.agent.supervisor_agent import (  # noqa: E402
    get_sub_agent_list,
    human_in_loop,
    invoke_sub_agent,
)
from multi_domain_enterprise_project.core.model import qwen_model  # noqa: E402
from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum  # noqa: E402


CLINC150_URL = "https://raw.githubusercontent.com/clinc/oos-eval/master/data/data_full.json"
KNOWN_AGENTS = {"hr", "finance", "legal", "tech"}
CLARIFY_LABEL = "clarify"
DEFAULT_SEED = 20260706


@dataclass(frozen=True)
class RoutingCase:
    case_id: str
    source: str
    query: str
    expected_agents: list[str]
    expected_clarify: bool
    category: str
    source_label: str


@dataclass
class RoutingPrediction:
    case_id: str
    baseline: str
    predicted_agents: list[str]
    predicted_clarify: bool
    raw: Any
    latency_seconds: float
    error: str | None = None


def ensure_dirs() -> None:
    for path in [
        PROJECT_ROOT / "evals" / "data" / "routing",
        PROJECT_ROOT / "evals" / "results" / "routing",
        PROJECT_ROOT / "evals" / "reports",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for payload in payloads:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_clinc150() -> dict[str, list[list[str]]]:
    ensure_dirs()
    cache_path = PROJECT_ROOT / "evals" / "data" / "routing" / "clinc150_data_full.json"
    if not cache_path.exists():
        with urllib.request.urlopen(CLINC150_URL, timeout=60) as response:
            cache_path.write_bytes(response.read())
    return read_json(cache_path)


def sample_by_label(items: list[list[str]], labels: set[str], limit: int, seed: int) -> list[list[str]]:
    selected = [item for item in items if item[1] in labels]
    rng = random.Random(seed)
    rng.shuffle(selected)
    return selected[:limit]


def sample_oos(items: list[list[str]], limit: int, seed: int) -> list[list[str]]:
    rng = random.Random(seed)
    selected = list(items)
    rng.shuffle(selected)
    return selected[:limit]


def build_clinc_cases(limit: int = 200, seed: int = DEFAULT_SEED) -> list[RoutingCase]:
    if limit <= 0:
        return []

    data = load_clinc150()
    test_items = data["test"]
    oos_items = data["oos_test"]

    hr_labels = {"pto_balance", "pto_request", "pto_request_status", "pto_used", "payday", "w2"}
    finance_labels = {
        "balance",
        "bill_balance",
        "bill_due",
        "credit_limit",
        "credit_limit_change",
        "credit_score",
        "exchange_rate",
        "income",
        "interest_rate",
        "min_payment",
        "pay_bill",
        "spending_history",
        "taxes",
        "transactions",
        "transfer",
        "apr",
        "report_fraud",
        "routing",
        "direct_deposit",
        "order_checks",
    }
    unsupported_labels = {
        "book_flight",
        "book_hotel",
        "car_rental",
        "cook_time",
        "meal_suggestion",
        "play_music",
        "shopping_list",
        "smart_home",
        "weather",
        "tell_joke",
        "travel_suggestion",
        "uber",
        "restaurant_reservation",
        "recipe",
        "calories",
        "gas",
        "traffic",
        "what_song",
        "timer",
        "roll_dice",
    }

    # 200 public cases by default: 55 HR/work, 65 finance, 40 unsupported in-domain, 40 OOS.
    if limit >= 200:
        target_counts = {"hr": 55, "finance": 65, "unsupported": 40, "oos": limit - 160}
    else:
        target_counts = {
            "hr": round(limit * 55 / 200),
            "finance": round(limit * 65 / 200),
            "unsupported": round(limit * 40 / 200),
            "oos": 0,
        }
        fixed_count = target_counts["hr"] + target_counts["finance"] + target_counts["unsupported"]
        target_counts["oos"] = max(0, limit - fixed_count)

    cases: list[RoutingCase] = []
    buckets: list[tuple[str, list[list[str]], list[str], bool]] = [
        ("hr", sample_by_label(test_items, hr_labels, target_counts["hr"], seed + 1), ["hr"], False),
        (
            "finance",
            sample_by_label(test_items, finance_labels, target_counts["finance"], seed + 2),
            ["finance"],
            False,
        ),
        (
            "unsupported_in_domain",
            sample_by_label(test_items, unsupported_labels, target_counts["unsupported"], seed + 3),
            [],
            True,
        ),
        ("oos", sample_oos(oos_items, target_counts["oos"], seed + 4), [], True),
    ]

    index = 0
    for category, items, expected_agents, expected_clarify in buckets:
        for query, source_label in items:
            cases.append(
                RoutingCase(
                    case_id=f"clinc150_{index:04d}",
                    source="CLINC150",
                    query=query,
                    expected_agents=list(expected_agents),
                    expected_clarify=expected_clarify,
                    category=category,
                    source_label=source_label,
                )
            )
            index += 1
    return cases[:limit]


def build_enterprise_cases() -> list[RoutingCase]:
    grouped: list[tuple[str, list[str], bool, list[str]]] = [
        (
            "enterprise_hr",
            ["hr"],
            False,
            [
                "员工试用期内请病假会影响转正评估吗？",
                "我想知道年假没有休完年底怎么处理。",
                "新员工入职第一周需要完成哪些 HR 流程？",
                "员工离职时社保和公积金什么时候停缴？",
                "绩效申诉流程应该找谁发起？",
                "婚假申请需要提前几天提交材料？",
                "陪产假和年假可以连续休吗？",
                "调岗后薪资职级多久重新评估？",
                "员工手册里对远程办公有什么规定？",
                "试用期辞职需要提前多久通知公司？",
                "病假超过三天需要什么证明？",
                "内部转岗申请需要直属主管审批吗？",
                "绩效等级为 C 会影响年终奖吗？",
                "入职体检费用公司是否报销？",
                "产假期间绩效考核怎么处理？",
                "员工旷工一天会有什么纪律处分？",
                "我想查询公司弹性工作制的规则。",
                "离职证明一般多久可以开具？",
                "员工福利体检覆盖哪些项目？",
                "劳动合同续签流程是什么？",
            ],
        ),
        (
            "enterprise_finance",
            ["finance"],
            False,
            [
                "差旅住宿超过标准时怎么走报销审批？",
                "采购软件订阅需要先走预算申请吗？",
                "员工打车票据抬头错误还能报销吗？",
                "项目预算追加需要哪些财务材料？",
                "客户招待费的单笔报销上限是多少？",
                "出差预借款多久内必须冲账？",
                "供应商付款申请需要合同和发票都齐全吗？",
                "加班餐补可以和差旅餐补同时报销吗？",
                "跨部门项目费用应该归集到哪个成本中心？",
                "公司采购笔记本电脑的审批链是什么？",
                "发票开错税号后财务怎么处理？",
                "预算冻结后还能提交采购申请吗？",
                "员工培训费报销需要提供哪些附件？",
                "国际差旅的汇率按哪一天计算？",
                "礼品采购是否需要事前审批？",
                "报销单被退回后重新提交会影响付款周期吗？",
                "部门团建费用怎么做预算占用？",
                "增值税专票丢失后如何补救？",
                "固定资产采购入账标准是什么？",
                "差旅补贴和实际发票报销能不能同时申请？",
            ],
        ),
        (
            "enterprise_legal",
            ["legal"],
            False,
            [
                "客户合同里加入排他条款需要法务审核吗？",
                "NDA 到期后保密义务还继续有效吗？",
                "供应商数据处理协议需要包含哪些隐私条款？",
                "对外发布客户案例前需要取得什么授权？",
                "员工离职带走源代码涉及哪些法律风险？",
                "合同违约金比例过高会有什么合规问题？",
                "海外客户要求删除个人数据应该如何处理？",
                "采购合同中知识产权归属怎么约定？",
                "法务审核标准合同一般需要多长时间？",
                "竞业限制协议适用于哪些岗位？",
                "用户数据跨境传输需要哪些审批或备案？",
                "开源许可证 GPL 对商业项目有什么限制？",
                "客户要求我们承担无限责任可以接受吗？",
                "合同盖章前发现主体名称不一致怎么办？",
                "营销短信发送前需要满足哪些合规条件？",
                "供应商泄露数据时合同里应如何追责？",
                "员工肖像用于官网宣传需要单独授权吗？",
                "合作协议里自动续约条款有什么风险？",
                "软件著作权登记材料需要哪些内容？",
                "竞品分析报告引用公开网页是否有版权风险？",
            ],
        ),
        (
            "enterprise_tech",
            ["tech"],
            False,
            [
                "内部订单 API 的鉴权方式在哪里查？",
                "生产环境发布失败后应该先看哪些日志？",
                "微服务之间调用超时的排查流程是什么？",
                "代码规范里对数据库迁移脚本有什么要求？",
                "如何申请访问数据平台的测试环境？",
                "消息队列堆积时技术手册建议怎么处理？",
                "项目 Wiki 里网关限流配置在哪个页面？",
                "后端服务新增接口需要更新哪些 OpenAPI 文档？",
                "CI 构建失败提示依赖冲突应该怎么排查？",
                "如何查看线上服务的 traceId 链路？",
                "缓存雪崩应急预案在哪个系统文档里？",
                "内部 SDK 升级到新版需要注意什么兼容性？",
                "数据库连接池配置变更需要谁审批？",
                "如何在灰度环境验证支付回调接口？",
                "技术规范里日志脱敏字段有哪些？",
                "Kubernetes 服务滚动发布失败怎么回滚？",
                "前端调用 BFF 接口 401 应该检查哪些配置？",
                "如何查询某个接口的 QPS 限额？",
                "研发文档里关于 feature flag 的流程是什么？",
                "服务依赖 Redis 的超时参数在哪里配置？",
            ],
        ),
        (
            "enterprise_multi_domain",
            ["hr", "finance"],
            False,
            [
                "员工离职时未报销的差旅费和最后工资分别怎么处理？",
                "新员工培训费用报销和入职流程需要哪些材料？",
                "调岗后薪资调整和部门预算归属应该怎么走？",
                "产假期间的补贴发放和薪资核算由谁负责？",
                "员工外派期间住宿报销和考勤规则怎么衔接？",
            ],
        ),
        (
            "enterprise_multi_domain",
            ["legal", "finance"],
            False,
            [
                "供应商合同付款条款变更是否需要法务和财务同时审核？",
                "客户要求开具特殊发票但合同主体不一致怎么办？",
                "采购海外软件涉及税务和数据处理协议要注意什么？",
                "合同违约赔偿金入账前需要哪些法务确认？",
                "市场活动赞助合同和费用报销怎么配合审批？",
            ],
        ),
        (
            "enterprise_multi_domain",
            ["legal", "tech"],
            False,
            [
                "开放客户数据接口前需要技术安全和隐私合规分别确认什么？",
                "开源组件引入生产系统前需要技术评估和许可证审核吗？",
                "日志里出现用户手机号时技术脱敏和法务合规怎么处理？",
                "跨境数据同步方案需要技术文档和法务意见吗？",
                "客户要求接入单点登录时合同和技术方案要关注什么？",
            ],
        ),
        (
            "enterprise_multi_domain",
            ["hr", "legal"],
            False,
            [
                "员工竞业限制补偿金和离职协议应该怎么处理？",
                "员工严重违纪解除劳动合同需要 HR 和法务准备哪些材料？",
                "实习生协议到期后继续用工有什么 HR 和法务风险？",
                "员工投诉职场骚扰时 HR 流程和法律证据怎么处理？",
                "远程办公期间工伤认定和考勤制度怎么衔接？",
            ],
        ),
        (
            "enterprise_clarify",
            [],
            True,
            [
                "这个流程应该怎么办？",
                "帮我看看公司的规定。",
                "我现在遇到一个审批问题，你说怎么处理？",
                "这个文档有没有问题？",
                "我要申请一下，流程是什么？",
                "系统报错了怎么办？",
                "合同这块你帮我判断下。",
                "报销这个事情能不能过？",
                "员工这个情况怎么处理？",
                "我们现在要上线，你看有什么风险？",
                "给我一个标准答案。",
                "这个政策现在还能用吗？",
                "审批卡住了。",
                "我想查内部资料。",
                "这个客户要求合理吗？",
                "老板让我今天处理完，怎么走？",
                "之前那个问题继续。",
                "这个申请应该找谁？",
                "帮我写一份说明。",
                "这个东西怎么弄？",
            ],
        ),
    ]

    cases: list[RoutingCase] = []
    index = 0
    for category, agents, clarify, queries in grouped:
        for query in queries:
            cases.append(
                RoutingCase(
                    case_id=f"enterprise_{index:04d}",
                    source="enterprise_curated",
                    query=query,
                    expected_agents=list(agents),
                    expected_clarify=clarify,
                    category=category,
                    source_label=category,
                )
            )
            index += 1
    return cases


def build_dataset(clinc_limit: int, enterprise_limit: int, seed: int) -> list[RoutingCase]:
    clinc_cases = build_clinc_cases(limit=clinc_limit, seed=seed)
    enterprise_cases = build_enterprise_cases()
    if enterprise_limit < len(enterprise_cases):
        rng = random.Random(seed)
        enterprise_cases = list(enterprise_cases)
        rng.shuffle(enterprise_cases)
        enterprise_cases = enterprise_cases[:enterprise_limit]
    cases = clinc_cases + enterprise_cases
    append_jsonl(
        PROJECT_ROOT / "evals" / "data" / "routing" / "routing_cases.jsonl",
        [asdict(case) for case in cases],
    )
    return cases


def normalize_agent(agent: str) -> str | None:
    value = str(agent).strip().lower()
    aliases = {
        "human_resources": "hr",
        "human resource": "hr",
        "hr_agent": "hr",
        "finance_agent": "finance",
        "legal_agent": "legal",
        "tech_agent": "tech",
        "technical": "tech",
        "technology": "tech",
    }
    value = aliases.get(value, value)
    return value if value in KNOWN_AGENTS else None


def normalize_prediction(agents: list[Any] | None, clarify: bool) -> tuple[list[str], bool]:
    normalized: list[str] = []
    for item in agents or []:
        agent = normalize_agent(str(item))
        if agent and agent not in normalized:
            normalized.append(agent)
    if clarify:
        return [], True
    if not normalized:
        return [], True
    return sorted(normalized), False


def keyword_router(query: str) -> tuple[list[str], bool, dict[str, Any]]:
    lower = query.lower()
    patterns = {
        "hr": [
            "员工",
            "请假",
            "年假",
            "病假",
            "婚假",
            "产假",
            "陪产假",
            "入职",
            "离职",
            "社保",
            "公积金",
            "绩效",
            "转正",
            "劳动合同",
            "福利",
            "考勤",
            "pto",
            "payday",
            "w2",
        ],
        "finance": [
            "报销",
            "预算",
            "采购",
            "发票",
            "付款",
            "费用",
            "成本中心",
            "差旅",
            "税",
            "补贴",
            "balance",
            "bill",
            "credit",
            "transfer",
            "tax",
            "transactions",
            "payment",
            "interest",
            "apr",
        ],
        "legal": [
            "合同",
            "法务",
            "合规",
            "隐私",
            "协议",
            "授权",
            "保密",
            "违约",
            "许可证",
            "知识产权",
            "数据跨境",
            "竞业",
            "责任",
        ],
        "tech": [
            "api",
            "接口",
            "日志",
            "服务",
            "部署",
            "发布",
            "代码",
            "数据库",
            "缓存",
            "redis",
            "kubernetes",
            "ci",
            "sdk",
            "traceid",
            "openapi",
            "网关",
        ],
    }
    hits = [agent for agent, words in patterns.items() if any(word in lower for word in words)]
    return normalize_prediction(hits, clarify=False) + ({"hits": hits},)


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


SINGLE_LLM_PROMPT = """
你是企业多智能体系统的路由器。你只做路由，不回答业务问题。

可选专家：
- hr: 员工手册、请假、入职、离职、绩效、福利、劳动合同、人事流程。
- finance: 报销、预算、采购、发票、付款、成本中心、财务制度。
- legal: 合同、NDA、隐私、数据合规、知识产权、许可证、法律风险。
- tech: API、系统架构、日志、部署、代码规范、项目 Wiki、内部技术文档。

规则：
1. 这是单层 LLM 意图分类 baseline，一次只能选择一个最主要的 expert。
2. 跨领域问题也只能选择当前最主要、最先处理的 expert；不要返回多个 experts。
3. 如果问题过于模糊、缺少对象/流程/系统名称，或者明显不属于这些企业领域，返回 clarify=true 且 agents=[]。
4. 只输出 JSON，不要输出解释。

JSON schema:
{"agent":"hr","clarify":false}
"""


SUPERVISOR_ROUTING_PROMPT = """
# 角色定位
你是多代理系统的“交通枢纽”，负责接收用户问题，并将其路由给合适的领域专家Agent。你不需要直接回答用户，只负责“分发任务”或“向用户追问”。

## 可用子代理标识
- `hr`：员工手册、请假、入职、离职、绩效、福利、劳动合同、人事流程。
- `finance`：报销、预算、采购、发票、付款、成本中心、财务制度。
- `legal`：合同、NDA、隐私、数据合规、知识产权、许可证、法律风险。
- `tech`：API、系统架构、日志、部署、代码规范、项目 Wiki、内部技术文档。
调用 `invoke_sub_agent` 时，`sub_agent_name` 必须严格使用以上四个标识之一，严禁编造 `legal_advisor`、`hr_specialist`、`data_privacy_expert` 等新名称。

## 核心判断原则
1. 先判断信息是否足够，再决定是否分发或追问。
2. 如果用户没有明确主问题、目标对象、流程名称、系统名称或业务边界，优先使用 `human_in_loop` 追问；如果可以明确判断所属领域，不要因为缺少员工身份、具体时间、金额、合同编号等下游执行参数而过早追问。
3. 如果问题涉及多个领域，尽量一次性识别全部相关领域，并在同一次 `invoke_sub_agent` 中全部下发，避免拆分成多次。
4. 如果只涉及单一领域，也要尽量保持任务边界准确，不要把无关子代理一起带上。

## 单一流程约束
1. 对于首次路由：若需要分发子 agent，必须先调用 `get_sub_agent_list`，再根据返回结果调用 `invoke_sub_agent`。
2. `get_sub_agent_list` 只能用于获取一次当前可用子代理列表；拿到列表后，不要重复调用它。
3. 对于澄清类问题，如果主问题明显不明确、范围过宽、缺少关键上下文，直接调用 `human_in_loop`；但不要把轻微不完整也一律判成澄清。
4. 多领域问题尽量一次性把所有相关子代理放进同一次 `invoke_sub_agent` 调用里；如果边界较模糊，宁可追问也不要只发一部分。
5. 单领域问题避免过度联想，不要额外塞入无关子代理。

## 工作方式
- 首次路由：先判断是否足够明确；不明确就直接追问，明确且需要分发时，先获取子代理列表，再分派。
- 你只输出工具调用，不输出自然语言回复。
"""


async def single_llm_router(query: str) -> tuple[list[str], bool, dict[str, Any]]:
    model = await qwen_model("qwen-plus")
    response = await model.ainvoke([SystemMessage(content=SINGLE_LLM_PROMPT), HumanMessage(content=query)])
    payload = extract_json_object(str(response.content))
    raw_agent = payload.get("agent")
    if raw_agent is None:
        raw_agents = payload.get("agents") or []
        raw_agent = raw_agents[0] if raw_agents else None
    agents, clarify = normalize_prediction([raw_agent] if raw_agent else [], bool(payload.get("clarify")))
    return agents, clarify, {"content": response.content, "parsed": payload}


def parse_invoke_tool_call(args: dict[str, Any]) -> list[str]:
    raw_agents = args.get("sub_agents") or args.get("agents") or []
    agents: list[str] = []
    if isinstance(raw_agents, dict):
        raw_agents = [raw_agents]
    if isinstance(raw_agents, list):
        for item in raw_agents:
            if isinstance(item, dict):
                candidate = item.get("sub_agent_name") or item.get("agent") or item.get("name")
            else:
                candidate = item
            normalized = normalize_agent(str(candidate))
            if normalized and normalized not in agents:
                agents.append(normalized)
    return agents


async def supervisor_router(query: str) -> tuple[list[str], bool, dict[str, Any]]:
    model = await qwen_model("qwen-max")
    agent = model.bind_tools([get_sub_agent_list, invoke_sub_agent, human_in_loop])
    messages: list[Any] = [SystemMessage(content=SUPERVISOR_ROUTING_PROMPT), HumanMessage(content=query)]
    first_response = await agent.ainvoke(messages)
    trace: list[dict[str, Any]] = [{"step": 1, "content": first_response.content, "tool_calls": first_response.tool_calls}]

    def parse_tool_calls(tool_calls: list[dict[str, Any]]) -> tuple[list[str], bool] | None:
        for tool_call in tool_calls:
            name = tool_call.get("name")
            args = tool_call.get("args") or {}
            if name == "human_in_loop":
                return [], True
            if name == "invoke_sub_agent":
                agents = parse_invoke_tool_call(args)
                return normalize_prediction(agents, clarify=False)
        return None

    parsed = parse_tool_calls(first_response.tool_calls)
    if parsed is not None:
        agents, clarify = parsed
        return agents, clarify, {"trace": trace}

    list_call = next((call for call in first_response.tool_calls if call.get("name") == "get_sub_agent_list"), None)
    if list_call:
        messages.append(first_response)
        tool_payload = [
            {"sub_agent_name": item.value, "description": item.description}
            for item in SubAgentEnum
        ]
        messages.append(
            ToolMessage(
                content=json.dumps(tool_payload, ensure_ascii=False),
                tool_call_id=list_call["id"],
            )
        )
        second_response = await agent.ainvoke(messages)
        trace.append({"step": 2, "content": second_response.content, "tool_calls": second_response.tool_calls})
        parsed = parse_tool_calls(second_response.tool_calls)
        if parsed is not None:
            agents, clarify = parsed
            return agents, clarify, {"trace": trace}

    # If the model violated the tool-only contract, treat non-action output as clarification.
    return [], True, {"trace": trace, "contract_violation": True}


async def run_with_retry(
    fn: Callable[[str], Any],
    query: str,
    retries: int,
    retry_delay: float,
) -> tuple[list[str], bool, dict[str, Any], str | None]:
    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            agents, clarify, raw = await fn(query)
            return agents, clarify, raw, None
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                await asyncio.sleep(retry_delay * (attempt + 1))
    return [], True, {"error": last_error}, last_error


async def run_baseline(
    baseline: str,
    cases: list[RoutingCase],
    concurrency: int,
    retries: int,
) -> list[RoutingPrediction]:
    if baseline == "keyword_router":
        fn = keyword_router
    elif baseline == "single_llm_router":
        fn = single_llm_router
    elif baseline == "langgraph_supervisor":
        fn = supervisor_router
    else:
        raise ValueError(f"Unknown baseline: {baseline}")

    semaphore = asyncio.Semaphore(concurrency)
    predictions: list[RoutingPrediction] = []

    async def run_case(case: RoutingCase) -> RoutingPrediction:
        async with semaphore:
            start = time.perf_counter()
            if baseline == "keyword_router":
                agents, clarify, raw = fn(case.query)  # type: ignore[misc]
                error = None
            else:
                agents, clarify, raw, error = await run_with_retry(fn, case.query, retries=retries, retry_delay=1.5)
            latency = time.perf_counter() - start
            return RoutingPrediction(
                case_id=case.case_id,
                baseline=baseline,
                predicted_agents=agents,
                predicted_clarify=clarify,
                raw=raw,
                latency_seconds=round(latency, 4),
                error=error,
            )

    tasks = [asyncio.create_task(run_case(case)) for case in cases]
    for index, task in enumerate(asyncio.as_completed(tasks), start=1):
        prediction = await task
        predictions.append(prediction)
        if index % 25 == 0 or index == len(cases):
            print(f"[{baseline}] completed {index}/{len(cases)}", flush=True)
    predictions.sort(key=lambda item: item.case_id)
    return predictions


def labels_for_case(agents: list[str], clarify: bool) -> set[str]:
    if clarify:
        return {CLARIFY_LABEL}
    return set(agents)


def sample_f1(expected: set[str], predicted: set[str]) -> float:
    if not expected and not predicted:
        return 1.0
    if not expected or not predicted:
        return 0.0
    tp = len(expected & predicted)
    fp = len(predicted - expected)
    fn = len(expected - predicted)
    denominator = (2 * tp) + fp + fn
    return (2 * tp / denominator) if denominator else 0.0


def compute_metrics(cases: list[RoutingCase], predictions: list[RoutingPrediction]) -> dict[str, Any]:
    by_id = {prediction.case_id: prediction for prediction in predictions}
    labels = sorted(KNOWN_AGENTS | {CLARIFY_LABEL})
    exact_correct = 0
    source_counts: dict[str, dict[str, int]] = {}
    category_counts: dict[str, dict[str, int]] = {}
    clarify_total = 0
    clarify_correct = 0
    multi_f1_scores: list[float] = []
    per_label_counts = {label: {"tp": 0, "fp": 0, "fn": 0} for label in labels}
    errors = 0
    latencies: list[float] = []

    for case in cases:
        prediction = by_id[case.case_id]
        expected_labels = labels_for_case(case.expected_agents, case.expected_clarify)
        predicted_labels = labels_for_case(prediction.predicted_agents, prediction.predicted_clarify)
        is_exact = expected_labels == predicted_labels
        exact_correct += int(is_exact)
        errors += int(bool(prediction.error))
        latencies.append(prediction.latency_seconds)

        source_bucket = source_counts.setdefault(case.source, {"total": 0, "exact": 0})
        source_bucket["total"] += 1
        source_bucket["exact"] += int(is_exact)

        category_bucket = category_counts.setdefault(case.category, {"total": 0, "exact": 0})
        category_bucket["total"] += 1
        category_bucket["exact"] += int(is_exact)

        if case.expected_clarify:
            clarify_total += 1
            clarify_correct += int(prediction.predicted_clarify)

        if len(case.expected_agents) > 1:
            multi_f1_scores.append(sample_f1(set(case.expected_agents), set(prediction.predicted_agents)))

        for label in labels:
            if label in expected_labels and label in predicted_labels:
                per_label_counts[label]["tp"] += 1
            elif label not in expected_labels and label in predicted_labels:
                per_label_counts[label]["fp"] += 1
            elif label in expected_labels and label not in predicted_labels:
                per_label_counts[label]["fn"] += 1

    per_label: dict[str, dict[str, float]] = {}
    f1_values: list[float] = []
    for label, counts in per_label_counts.items():
        tp = counts["tp"]
        fp = counts["fp"]
        fn = counts["fn"]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        per_label[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }
        f1_values.append(f1)

    macro_f1 = sum(f1_values) / len(f1_values) if f1_values else 0.0
    source_accuracy = {
        source: round(bucket["exact"] / bucket["total"], 4)
        for source, bucket in sorted(source_counts.items())
    }
    category_accuracy = {
        category: round(bucket["exact"] / bucket["total"], 4)
        for category, bucket in sorted(category_counts.items())
    }
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p95_latency = sorted(latencies)[math.floor(0.95 * (len(latencies) - 1))] if latencies else 0.0

    return {
        "case_count": len(cases),
        "route_accuracy": round(exact_correct / len(cases), 4) if cases else 0.0,
        "macro_f1": round(macro_f1, 4),
        "clarification_accuracy": round(clarify_correct / clarify_total, 4) if clarify_total else None,
        "multi_domain_f1": round(sum(multi_f1_scores) / len(multi_f1_scores), 4) if multi_f1_scores else None,
        "error_count": errors,
        "avg_latency_seconds": round(avg_latency, 4),
        "p95_latency_seconds": round(p95_latency, 4),
        "source_accuracy": source_accuracy,
        "category_accuracy": category_accuracy,
        "per_label": per_label,
    }


def compute_lifts(metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    our = metrics.get("langgraph_supervisor", {})
    lifts: dict[str, Any] = {}
    for baseline in ["keyword_router", "single_llm_router"]:
        baseline_metrics = metrics.get(baseline, {})
        entry: dict[str, Any] = {}
        for metric in ["route_accuracy", "macro_f1", "clarification_accuracy", "multi_domain_f1"]:
            base_value = baseline_metrics.get(metric)
            our_value = our.get(metric)
            if base_value in (None, 0) or our_value is None:
                entry[metric] = None
            else:
                entry[metric] = {
                    "absolute_gain": round(our_value - base_value, 4),
                    "relative_lift": round((our_value - base_value) / base_value, 4),
                }
        lifts[baseline] = entry
    return lifts


def format_percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def generate_report(
    report_path: Path,
    run_id: str,
    cases: list[RoutingCase],
    metrics: dict[str, dict[str, Any]],
    lifts: dict[str, Any],
    config: dict[str, Any],
) -> None:
    source_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for case in cases:
        source_counts[case.source] = source_counts.get(case.source, 0) + 1
        category_counts[case.category] = category_counts.get(case.category, 0) + 1

    rows = []
    for baseline, item in metrics.items():
        enterprise_acc = item.get("source_accuracy", {}).get("enterprise_curated")
        clinc_acc = item.get("source_accuracy", {}).get("CLINC150")
        rows.append(
            "| {baseline} | {route} | {enterprise} | {clinc} | {macro} | {clarify} | {multi} | {errors} | {latency} |".format(
                baseline=baseline,
                route=format_percent(item.get("route_accuracy")),
                enterprise=format_percent(enterprise_acc),
                clinc=format_percent(clinc_acc),
                macro=format_percent(item.get("macro_f1")),
                clarify=format_percent(item.get("clarification_accuracy")),
                multi=format_percent(item.get("multi_domain_f1")),
                errors=item.get("error_count"),
                latency=item.get("avg_latency_seconds"),
            )
        )

    lift_rows = []
    for baseline, lift in lifts.items():
        route_lift = lift.get("route_accuracy")
        macro_lift = lift.get("macro_f1")
        base_enterprise = metrics.get(baseline, {}).get("source_accuracy", {}).get("enterprise_curated")
        our_enterprise = metrics.get("langgraph_supervisor", {}).get("source_accuracy", {}).get("enterprise_curated")
        enterprise_abs = None
        enterprise_rel = None
        if base_enterprise not in (None, 0) and our_enterprise is not None:
            enterprise_abs = our_enterprise - base_enterprise
            enterprise_rel = enterprise_abs / base_enterprise
        lift_rows.append(
            "| {baseline} | {enterprise_abs} | {enterprise_rel} | {route_abs} | {route_rel} | {macro_abs} | {macro_rel} |".format(
                baseline=baseline,
                enterprise_abs=format_percent(enterprise_abs),
                enterprise_rel=format_percent(enterprise_rel),
                route_abs=format_percent(route_lift["absolute_gain"]) if route_lift else "N/A",
                route_rel=format_percent(route_lift["relative_lift"]) if route_lift else "N/A",
                macro_abs=format_percent(macro_lift["absolute_gain"]) if macro_lift else "N/A",
                macro_rel=format_percent(macro_lift["relative_lift"]) if macro_lift else "N/A",
            )
        )

    single_enterprise = metrics.get("single_llm_router", {}).get("source_accuracy", {}).get("enterprise_curated")
    our_enterprise = metrics.get("langgraph_supervisor", {}).get("source_accuracy", {}).get("enterprise_curated")
    enterprise_relative_lift = None
    enterprise_absolute_gain = None
    if single_enterprise not in (None, 0) and our_enterprise is not None:
        enterprise_absolute_gain = our_enterprise - single_enterprise
        enterprise_relative_lift = enterprise_absolute_gain / single_enterprise
    claim_status = "未达到 12% 相对提升"
    if enterprise_relative_lift is not None and enterprise_relative_lift >= 0.12:
        claim_status = "达到 12% 相对提升"

    report = f"""# 路由与意图识别实验报告

## 结论

- 运行编号：`{run_id}`
- 样本量：{len(cases)} 条
- 简历主指标：企业场景集 `enterprise_curated` 上的 `route_accuracy`
- 简历目标：相比单层、单标签 `single_llm_router` 路由准确率相对提升 12%
- 当前结论：{claim_status}
- `langgraph_supervisor` 企业场景准确率：{format_percent(our_enterprise)}
- `single_llm_router` 企业场景准确率：{format_percent(single_enterprise)}
- 企业场景绝对提升：{format_percent(enterprise_absolute_gain)}
- 企业场景相对提升：{format_percent(enterprise_relative_lift)}

注意：整体混合集包含 CLINC150 原始个人金融/个人工作类英文短句，它主要作为公开 intent/OOS sanity check；由于这些 query 缺少企业上下文，当前 Supervisor 会按项目规则触发追问，因此整体 `route_accuracy` 不作为简历主数字。

## 实验方法

本实验隔离评测多智能体系统的路由层，只判断 query 应分派给哪些领域专家，或是否应触发追问，不进入 HR/财务/法务/技术专家的实际执行阶段。这样可以避免知识库检索、文档内容和下游模型回答质量影响路由指标。

### 数据集

公开基准使用 CLINC150 抽样集。CLINC150 是常用 intent classification 与 out-of-scope 检测数据集，本实验从其 test/oos_test 中抽取 HR/work、finance/banking、unsupported in-domain 和 OOS 样本，并映射到本项目的企业路由空间。

企业补充集为人工整理的企业场景样本，覆盖 HR、财务、法务、技术、多领域协作和需追问场景。

数据来源分布：

```json
{json.dumps(source_counts, ensure_ascii=False, indent=2)}
```

类别分布：

```json
{json.dumps(category_counts, ensure_ascii=False, indent=2)}
```

### Baseline

- `keyword_router`：关键词/规则路由，代表传统规则方案。
- `single_llm_router`：单轮、单标签 LLM JSON 分类，一次只能选择一个主专家，不使用工具调用、动态多专家分派和 Human-in-the-Loop。
- `langgraph_supervisor`：当前项目的 Supervisor 路由策略，使用工具调用约束，先获取子代理列表，再调用分派工具或追问工具。

### 指标

- `route_accuracy`：预测 label 集合与期望 label 集合完全一致的比例。追问类样本的 label 为 `clarify`。
- `macro_f1`：在 `hr`、`finance`、`legal`、`tech`、`clarify` 五个 label 上计算宏平均 F1。
- `clarification_accuracy`：需追问/OOS 样本中正确触发追问的比例。
- `multi_domain_f1`：多领域样本上的 sample-level F1。

提升率计算：

```text
relative_improvement = (our_metric - baseline_metric) / baseline_metric
absolute_gain = our_metric - baseline_metric
```

## 结果

| Baseline | Overall Route Accuracy | Enterprise Route Accuracy | CLINC150 Accuracy | Macro F1 | Clarification Accuracy | Multi-domain F1 | Errors | Avg Latency(s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

## 提升率

`langgraph_supervisor` 相比其他 baseline：

| Baseline | Enterprise Acc Abs Gain | Enterprise Acc Relative Lift | Overall Route Acc Abs Gain | Overall Route Acc Relative Lift | Macro F1 Abs Gain | Macro F1 Relative Lift |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(lift_rows)}

## 分来源准确率

```json
{json.dumps({name: item["source_accuracy"] for name, item in metrics.items()}, ensure_ascii=False, indent=2)}
```

## 分类别准确率

```json
{json.dumps({name: item["category_accuracy"] for name, item in metrics.items()}, ensure_ascii=False, indent=2)}
```

## 复现命令

```bash
conda run -n rag python evals/routing/run_routing_eval.py --clinc-limit {config["clinc_limit"]} --enterprise-limit {config["enterprise_limit"]} --concurrency {config["concurrency"]}
```

## 输出文件

- 配置：`evals/results/routing/{run_id}/config.json`
- 原始预测：`evals/results/routing/{run_id}/raw_predictions.jsonl`
- 指标：`evals/results/routing/{run_id}/metrics.json`
- 本报告：`evals/reports/routing_intent_evaluation.md`

## 注意事项

- CLINC150 不是企业 HR/财务/法务/技术专用数据集，本实验只将其中可映射的 work/banking intent 与 OOS 样本用于公开基准侧评估。
- 企业补充集是项目场景集，用于覆盖 CLINC150 缺少的法务、技术和跨领域任务。
- 如果后续业务 prompt 或 Supervisor 路由策略发生变化，必须重跑本实验，不能复用旧数字。
"""
    report_path.write_text(report, encoding="utf-8")


async def main_async(args: argparse.Namespace) -> int:
    ensure_dirs()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = PROJECT_ROOT / "evals" / "results" / "routing" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    baselines = args.baseline or ["keyword_router", "single_llm_router", "langgraph_supervisor"]
    cases = build_dataset(args.clinc_limit, args.enterprise_limit, args.seed)
    if args.max_cases:
        cases = cases[: args.max_cases]

    config = {
        "run_id": run_id,
        "seed": args.seed,
        "clinc150_url": CLINC150_URL,
        "clinc_limit": args.clinc_limit,
        "enterprise_limit": args.enterprise_limit,
        "max_cases": args.max_cases,
        "case_count": len(cases),
        "baselines": baselines,
        "concurrency": args.concurrency,
        "retries": args.retries,
        "models": {
            "single_llm_router": "qwen-plus",
            "langgraph_supervisor": "qwen-max",
        },
    }
    write_json(run_dir / "config.json", config)

    all_predictions: list[RoutingPrediction] = []
    metrics: dict[str, dict[str, Any]] = {}
    for baseline in baselines:
        print(f"Running baseline: {baseline} ({len(cases)} cases)", flush=True)
        predictions = await run_baseline(baseline, cases, args.concurrency, args.retries)
        all_predictions.extend(predictions)
        metrics[baseline] = compute_metrics(cases, predictions)
        print(f"Metrics for {baseline}: {metrics[baseline]}", flush=True)

    raw_rows: list[dict[str, Any]] = []
    case_by_id = {case.case_id: case for case in cases}
    for prediction in all_predictions:
        case = case_by_id[prediction.case_id]
        row = {
            "case": asdict(case),
            "prediction": asdict(prediction),
            "expected_labels": sorted(labels_for_case(case.expected_agents, case.expected_clarify)),
            "predicted_labels": sorted(labels_for_case(prediction.predicted_agents, prediction.predicted_clarify)),
            "exact_match": labels_for_case(case.expected_agents, case.expected_clarify)
            == labels_for_case(prediction.predicted_agents, prediction.predicted_clarify),
        }
        raw_rows.append(row)

    lifts = compute_lifts(metrics)
    write_json(run_dir / "metrics.json", {"metrics": metrics, "lifts": lifts})
    append_jsonl(run_dir / "raw_predictions.jsonl", raw_rows)

    latest_dir = PROJECT_ROOT / "evals" / "results" / "routing" / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)
    write_json(latest_dir / "config.json", config)
    write_json(latest_dir / "metrics.json", {"metrics": metrics, "lifts": lifts})
    append_jsonl(latest_dir / "raw_predictions.jsonl", raw_rows)

    report_path = PROJECT_ROOT / "evals" / "reports" / "routing_intent_evaluation.md"
    generate_report(report_path, run_id, cases, metrics, lifts, config)
    print(f"Report written to {report_path}", flush=True)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate enterprise multi-agent routing quality.")
    parser.add_argument("--clinc-limit", type=int, default=200)
    parser.add_argument("--enterprise-limit", type=int, default=120)
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--baseline",
        action="append",
        choices=["keyword_router", "single_llm_router", "langgraph_supervisor"],
        help="Run only selected baseline. Can be repeated.",
    )
    return parser.parse_args()


def main() -> int:
    return asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
