import json

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from typing import Annotated
from fastmcp import FastMCP
from mcp.types import PromptMessage, TextContent

server = FastMCP(name='老黄的MCP', instructions="老黄的python代码实现MCP服务器")


@server.tool()
def generate_blessings(query: Annotated[str, "祝福语的主题"]):
    """
    生成一段祝福语
    """
    return f"愿您天天开心，永远幸福"


@server.tool()
def say_hello(name: str):
    """
    给制定用户打招呼
    """
    return f"你好，{name}。今天，天气不错"


@server.prompt()
def ask_about_topic(topic: str):
    """生成请求解释特定主题的用户消息模板"""
    return f'能否请你解释一些 {topic} 的概念？'


@server.prompt()
def generate_code_request(language: str, task_description: str):
    """生成代码编写请求的用户消息模板"""
    content = f'请编写一个 {language} 的程序，完成以下任务：{task_description}'
    return PromptMessage(
        role='user',
        content=TextContent(type='text', text=content)
    )


@server.resource("resource://config")
def get_config():
    """以json格式返回应用配置"""
    config_dict = {
        "theme": 'dark',
        "language": 'zh-CN',
        "version": '1.0.0'
    }
    return json.dumps(config_dict, ensure_ascii=False)


