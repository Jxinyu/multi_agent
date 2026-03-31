from typing import List, Annotated

from langchain_core.tools import tool, BaseTool
from pydantic import Field


def all_tools() -> List[BaseTool]:

    @tool
    def search_wealth(city: Annotated[str, Field(description="输入城市名称")]):
        """查询天气"""
        return f'{city} 天气晴朗'

    @tool
    def search_population(city: Annotated[str, Field(description="输入城市名称")]):
        """查询人口"""
        return f'{city} 人口 1000万'

    return [search_wealth, search_population]














