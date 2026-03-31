import asyncio

from fastmcp.server.auth.providers.jwt import RSAKeyPair
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from pymilvus import MilvusClient

from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.rag.rag_main import query_milvus_pipeline, upload_file_to_milvus_pipeline
from multi_domain_enterprise_project.rag.rag_service import retrieve_service, insert_service
from multi_domain_enterprise_project.tools.mcp_tools import document_retriever_mcp_client, finance_mcp_client

import os

# 将相关域名加入白名单，强制直连（不走VPN代理）
os.environ["NO_PROXY"] = "localhost,127.0.0.1,modelscope.net,bigmodel.cn,xiaoai.plus,dashscope.aliyuncs.com"


def clear_milvus_collection():
    client = MilvusClient("http://127.0.0.1:19530")
    print(client.list_collections())
    client.drop_collection("company_knowledge_base")


def query():
    key_pair = RSAKeyPair.generate()  # 生成密钥对
    print(key_pair.public_key)  # 获取公钥
    print(key_pair.private_key.get_secret_value())  # 获取私钥


async def mcp_to():
    client = await document_retriever_mcp_client()
    mcp_tools = await client.get_tools()
    agent = create_agent(
        model=await qwen_model(),
        system_prompt="""所有回答都需要检索内部知识库""",
        tools=mcp_tools,
    )

    res = await agent.ainvoke(input={"messages": [{"role": "user", "content": "请给我一个关于公司业务范围的报告"}]})

    print(res)


async def mcpclient():
    m = await finance_mcp_client()
    tools = await m.get_tools()
    print(tools)

    pass


def insert_file():
    test_files = [
        # r"D:\学习笔记\langchain\rag_upper\document\7181-attention-is-all-you-need.pdf",
        # r"D:\学习笔记\langchain\rag_upper\document\小论文内容整理.docx",
        # r"D:\学习笔记\langchain\rag_upper\document\transformer.png",
        r"D:\学习笔记\langchain\rag_upper\document\rag中处理excel表格.txt"
    ]

    for f in test_files:
        if os.path.exists(f):
            res = asyncio.run(insert_service(f, "hr", "admin", "excel", "1", "milvus"))
            print(res)
        else:
            print(f"文件不存在: {f}")


async def rag():
    res = await retrieve_service(
        query_str="rag",
        mode="mg"
    )
    print(f"result: {res}")


def qwen():
    """获取qwen实例"""
    model = ChatOpenAI(
        model='qwen-plus',
        api_key='sk-145ba571895d4d5bbf739dc695fa4b65',
        base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
    )
    agent = create_agent(
        model=model,
        system_prompt="""所有回答都需要检索内部知识库""",
    )
    response = agent.invoke(input={"messages": [{"role": "user", "content": "你好"}]})
    print(response)


if __name__ == '__main__':
    # clear_milvus_collection()
    # insert_file()
    # asyncio.run(rag())
    # asyncio.run(mcpclient())
    qwen()

    pass



















