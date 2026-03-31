from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from config import settings


async def qwen_model(model: str = 'qwen-plus') -> BaseChatModel:
    """获取qwen实例"""
    model = ChatOpenAI(
        model=model,
        api_key=settings.llm_key.qwen,
        base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
    )
    return model
