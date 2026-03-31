from typing import Optional, Dict, List, Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph import MessagesState, add_messages
from pydantic import BaseModel


def merge_dict(old_tasks: Dict[str, Any], new_tasks: Dict[str, Any]) -> Dict[str, Any]:
    """字典合并函数"""
    if old_tasks is None:
        old_tasks = {}
    if new_tasks is None:
        return {}
    merged = old_tasks.copy()
    merged.update(new_tasks)
    return merged


class State(BaseModel):
    messages: Annotated[list[BaseMessage], add_messages]
    sub_agent_input_content: Annotated[Dict[str, Any], merge_dict]  # 给子Agent的输入
    sub_agent_messages: Annotated[Dict[str, Any], merge_dict]  # 子Agent的messages消息
    sub_agent_response: Annotated[Dict[str, Any], merge_dict]  # 子Agent的输出
    audit_feedback: Optional[Any] = None  # 审计反馈
    result: Optional[Any] = None
    retry_count: int = 0  # 当前重试次数
    max_retries: int = 3  # 最大重试次数
