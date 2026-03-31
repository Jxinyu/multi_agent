from typing import TypedDict

from langchain.agents import create_agent
from langchain_core.output_parsers import PydanticOutputParser
from langgraph.constants import END
from langgraph.graph import StateGraph
from langchain_openai import ChatOpenAI
from pydantic import Field, BaseModel

from config import settings

model = ChatOpenAI(
        model='gpt-3.5-turbo',
        api_key=settings.llm_key.xiaoAi,
        base_url='https://xiaoai.plus/v1',
    )


class State(TypedDict):
    joker: str  # 生成冷笑话内容
    topic: str  # 用户制定的主题
    feedback: str  # 改进建议
    funny_or_not: int  # 幽默评级


class EvaluatorOutput(BaseModel):
    feedback: str = Field(..., description="改进建议")
    funny_or_not: int = Field(..., description="幽默评级")


def generator(state: State):
    prompt = (
        f"根据反馈改进笑话：{state['feedback']} \n 主题：{state['topic']}"
        if state.get('feedback', None) else f"请生成一个关于{state['topic']}幽默的笑话"
    )
    resp = model.invoke(prompt)
    return {
        'joker': resp.content,
    }


def evaluator(state: State):
    prompt = (
        f"请对笑话进行评分：{state['joker']} \n 评分标准：1-10"
    )
    llm = model.with_structured_output(EvaluatorOutput)
    resp = llm.invoke(prompt)
    return {
        'feedback': resp.feedback,
        'funny_or_not': resp.funny_or_not,
    }


def router(state: State):
    if state['funny_or_not'] <= 7:
        return "generator"
    else:
        return "end"


builder = StateGraph(State)

builder.add_node("generator", generator)
builder.add_node("evaluator", evaluator)

builder.set_entry_point("generator")
builder.add_edge("generator", "evaluator")
builder.add_conditional_edges(
    source="evaluator",
    path=router,
    path_map={
        "generator": "generator",
        "end": END,
    }
)

agent = builder.compile()













