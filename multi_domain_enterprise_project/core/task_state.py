from enum import Enum
from typing import Annotated, Any, Dict, List, Optional
import operator

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from pydantic import BaseModel, Field


def merge_unique(existing: list[str] | None, incoming: list[str] | None) -> list[str]:
    """合并列表并去重，避免并发 step 下重复写入冲突。"""
    existing = existing or []
    incoming = incoming or []
    merged = list(existing)
    for item in incoming:
        if item not in merged:
            merged.append(item)
    return merged


class TaskStatus(str, Enum):
    """任务状态机的阶段枚举。"""

    IDLE = "idle"  # 空闲：当前没有正在处理的任务
    ROUTING = "routing"  # 路由中：supervisor 正在判断该派发给哪些子代理
    WAITING_HUMAN = "waiting_human"  # 等待人工：当前需要用户补充信息
    DISPATCHED = "dispatched"  # 已派发：任务已登记，等待进入执行阶段
    EXECUTING = "executing"  # 执行中：一个或多个子代理正在处理
    AGGREGATING = "aggregating"  # 汇总中：正在合并各子代理结果
    AUDITING = "auditing"  # 审核中：正在进行最终审查
    RETRYING = "retrying"  # 重试中：审计未通过，准备重新派发
    COMPLETED = "completed"  # 已完成：任务成功结束
    FAILED = "failed"  # 失败：任务异常终止或不可恢复


class TaskState(BaseModel):
    """多代理任务状态机的统一状态容器。"""

    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)  # 对话消息列表，作为图运行的主消息通道

    task_status: TaskStatus = TaskStatus.IDLE  # 当前任务所处的状态阶段
    task_id: Optional[str] = None  # 当前任务唯一标识，便于跨轮追踪和排障
    requested_agents: Annotated[List[str], merge_unique] = Field(default_factory=list)  # 本轮被请求过的子代理名称列表
    pending_sub_agents: Annotated[List[str], merge_unique] = Field(default_factory=list)  # 仍待执行或待完成的子代理名称列表
    finished_sub_agents: Annotated[List[str], merge_unique] = Field(default_factory=list)  # 已完成的子代理名称列表

    sub_agent_input_content: Dict[str, Any] = Field(default_factory=dict)  # 每个子代理对应的输入任务内容
    sub_agent_messages: Annotated[Dict[str, list], operator.or_] = Field(default_factory=dict)  # 每个子代理的历史消息记录
    sub_agent_response: Annotated[Dict[str, Any], operator.or_] = Field(default_factory=dict)  # 子代理输出的中间结果与汇总结果

    audit_feedback: Optional[Dict[str, Any]] = None  # 审计反馈，失败时保存修正意见；成功时为 None
    result: Optional[Dict[str, Any]] = None  # 最终返回给用户的结构化结果

    retry_count: int = 0  # 当前重试次数
    max_retries: int = 3  # 最大允许重试次数

    def reset_round(self) -> None:
        """重置一轮任务的运行状态，但保留会话消息。"""
        self.task_status = TaskStatus.ROUTING
        self.requested_agents = []
        self.pending_sub_agents = []
        self.finished_sub_agents = []
        self.sub_agent_input_content = {}
        self.sub_agent_messages = {}
        self.sub_agent_response = {}
        self.audit_feedback = None
        self.result = None
        self.retry_count = 0
