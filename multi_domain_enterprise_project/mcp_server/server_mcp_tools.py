import asyncio
from typing import Annotated, Literal
from pathlib import Path

from fastmcp import FastMCP, Context
from fastmcp.server.auth.providers.jwt import RSAKeyPair, JWTVerifier
from pydantic import SecretStr, Field
import logging
import aiofiles

from config import settings
from multi_domain_enterprise_project.rag.rag_main import query_milvus_pipeline, get_all_documents_name
from multi_domain_enterprise_project.rag.rag_service import retrieve_service

logger = logging.getLogger(__name__)


def _key_path(configured_path: str, file_name: str) -> Path:
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return Path(__file__).resolve().parent / file_name


async def get_public_key():
    async with aiofiles.open(_key_path(settings.mcp.public_key_path, "public_key"), "r") as f:
        return await f.read()


async def get_private_key():
    async with aiofiles.open(_key_path(settings.mcp.private_key_path, "private_key"), "r") as f:
        return await f.read()


async def get_auth():
    # 配置认证提供方
    auth = JWTVerifier(
        public_key=await get_public_key(),  # 公钥用于校验签名
        issuer='https://xinyu.com',  # 令牌签发方标识
        audience='my-dev-server',  # 令牌接收方标识
    )
    return auth


async def build_mcp_server() -> FastMCP:
    """
    MCP 注册中心工厂函数。
    在这里集中注册所有的业务函数，将其暴露为 MCP Tools。
    """
    mcp = FastMCP("企业知识库检索服务", instructions="提供混合检索能力，并支持按元数据过滤的知识库。",
                  auth=await get_auth())

    # 注册 RAG 工具
    @mcp.tool()
    async def query_document(query_str: Annotated[str, Field(..., description="检索的内容（必须提供）")], ctx: Context,
                             title: Annotated[str, Field(..., description="可选，指定文档标题（精确匹配）。")] = None,
                             mode: Annotated[Literal['milvus', 'graph', 'mg'],
                             Field(...,
                                   description="默认是 'milvus'。"
                                               "'milvus' 表示检索向量数据库；"
                                               "'graph' 表示检索知识图谱; "
                                               "'mg': 表示检索向量数据库+知识图谱;")] = 'milvus'
                             ) -> str:
        """
        在企业知识库中检索信息。
        """
        # tenant_id: 租户id  部门
        # acl: 访问控制列表（通过用户的职别控制）

        # 1. 从 MCP Context 中获取经过验证的 Token 信息
        # 注：根据 FastMCP 版本不同，auth 的获取路径可能略有差异，通常在 ctx.request 或者直接封装在 ctx 中
        # 如果 JWTVerifier 验证成功，它会将解析后的 subject 存入上下文
        try:
            # 获取签发时填入的 subject
            claims = ctx.request_context.request.user.access_token.claims  # 假设 subject 为 "hr|1,2"
            logger.warning(f"ctx.request_context.request.user.access_token.claims: {claims}")
            tenant_id = claims.get("tenant", None)
            acl_str = claims.get("acl", None)
            if (not tenant_id) or (not acl_str):
                return "检索失败：系统无法识别您的租户身份权限。"
            acl_list = acl_str.split("|") if acl_str else []
        except Exception as e:
            logger.error(f"认证失败：{e}")
            return "检索失败：系统无法识别您的租户身份权限。"

        logger.info(f"拦截到合法请求 -> Tenant: {tenant_id}, ACL: {acl_list}, Query: {query_str}")

        try:
            # 将参数发往底层 Pipeline
            return await retrieve_service(
                query_str=query_str,
                title=title,
                tenant_id=tenant_id,
                acl_list=acl_list,
                mode=mode
            )
        except:
            return "服务器内部错误"

    # @mcp.tool()
    # async def get_documents_list():
    #     """
    #     获取企业内容的所有文档名称和简要概述
    #     :return:
    #     """
    #     return await get_all_documents_name("hr", "1")

    # 可以在这里继续注册其他工具...
    # @mcp.tool()
    # async def other_tool(...): pass

    return mcp


async def create_mcp_token(tenant: str, acl: str):
    """
    注册令牌
    acl: 1|2|3
    """

    key_pair = RSAKeyPair(private_key=SecretStr(await get_private_key()), public_key=await get_public_key())

    subject_payload = f"{tenant}|{acl}"

    return key_pair.create_token(
        subject=subject_payload,  # 用户唯一标识符
        issuer='https://xinyu.com',  # 令牌签发方标识
        audience='my-dev-server',  # 令牌接收方标识
        expires_in_seconds=3600 * 24 * 365,  # 令牌有效期
        additional_claims={"tenant": tenant, "acl": acl}
    )


if __name__ == '__main__':
    res = asyncio.run(create_mcp_token("hr", '1|2'))
    print(res)
