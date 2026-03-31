from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # 自动处理消息历史
    messages: Annotated[Sequence[BaseMessage], add_messages]
    # 租户隔离标识
    tenant_id: str
    # 业务上下文（如：RAG 查询结果、用户画像）
    context_data: dict

