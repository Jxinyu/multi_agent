import json

from typing import Annotated
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import RSAKeyPair, JWTVerifier, AccessToken
from fastmcp.server.dependencies import get_access_token
from mcp.types import PromptMessage, TextContent

# 生成密钥对
key_pair = RSAKeyPair.generate()  # 生成密钥对
print(key_pair.public_key)  # 获取公钥
print(key_pair.private_key)  # 获取私钥
# 配置认证提供方
auth = JWTVerifier(
    public_key=key_pair.public_key,  # 公钥用于校验签名
    issuer='http://xinyu.com',  # 令牌签发方标识
    audience='my-dev-server',  # 令牌接收方标识
)

# 服务器，生成一个token
token = key_pair.create_token(
    subject='dev_user',
    issuer='http://xinyuu.com',
    audience='my-dev-server',
    scopes=['xinyu', 'invoker_tools'],
    expires_in_seconds=3600
)
print(token)

server = FastMCP(
    name='老黄的MCP',
    instructions="老黄的python代码实现MCP服务器",
    auth=auth,  # 服务器用于校验token
)


@server.tool()
def generate_blessings(query: Annotated[str, "祝福语的主题"]):
    """
    生成一段祝福语
    """
    access_token: AccessToken = get_access_token()
    try:
        if access_token:
            print(access_token)
            print(access_token.client_id)
            print(access_token.scopes)
    except:
        print("没有 scopes")

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


