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


def replace_dict(old_tasks: Dict[str, Any], new_tasks: Dict[str, Any]) -> Dict[str, Any]:
    """替代字典"""
    if new_tasks is None:
        return {}
    return new_tasks


def update_finished_sub_agents(old_tasks: List[str], new_tasks: List[str] | str):
    """更新已经完成的子agent列表的reducer"""
    if old_tasks is None:  # 旧任务列表为空
        return []
    if new_tasks is None:  # 新任务列表为空
        return old_tasks
    if isinstance(new_tasks, str):
        return old_tasks + [new_tasks]
    if new_tasks not in old_tasks:  #
        return old_tasks + new_tasks
    return old_tasks


def update_pending_sub_agents(old_tasks: List[str], new_tasks: List[str] | str):
    """
    更新需要执行的子agent列表的reducer
    list；新增任务列表
    str：删除已经完成的任务
    """
    if old_tasks is None:  # 旧任务列表为空
        return []
    if new_tasks is None:  # 新任务列表为空
        return old_tasks
    if isinstance(new_tasks, str):  # 删除已经完成的任务
        if new_tasks in old_tasks:
            old_tasks.remove(new_tasks)
            return old_tasks
    if new_tasks not in old_tasks:  # 添加新的任务
        return old_tasks + new_tasks
    return old_tasks


class State(BaseModel):
    messages: Annotated[list[BaseMessage], add_messages]

    pending_sub_agents: List[str] = []  # 待处理的子代理任务
    finished_sub_agents: Annotated[List[str], update_finished_sub_agents] = []  # 已完成的子代理任务

    sub_agent_input_content: Annotated[Dict[str, Any], merge_dict]  # 子代理的输入内容
    sub_agent_messages: Annotated[Dict[str, list], replace_dict]  # 子Agent的messages消息
    sub_agent_response: Annotated[Dict[str, Any], merge_dict]  # 子Agent的输出

    audit_feedback: Optional[Any] = None  # 审计反馈
    result: Optional[Any] = None  # 返回给用户的最终结果

    retry_count: int = 0  # 当前重试次数
    max_retries: int = 3  # 最大重试次数































