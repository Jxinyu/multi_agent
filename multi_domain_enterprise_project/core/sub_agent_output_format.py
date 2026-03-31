from typing import Annotated, Any

from pydantic import BaseModel, Field


class SubAgentOutputFormat(BaseModel):
    result: Annotated[str, Field(...,description="最后的回复")]
    references: Annotated[list[Any], Field(..., description="""列出所有通过文档检索到的上下文，例如：['xxx', 'xxxxx']""")]
