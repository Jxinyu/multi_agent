from langchain_mcp_adapters.client import MultiServerMCPClient

from config import settings


def _document_server_config() -> dict:
    config = {
        "transport": "streamable-http",
        "url": settings.mcp.rag_url,
    }
    if settings.mcp.document_token:
        config["headers"] = {"Authorization": f"Bearer {settings.mcp.document_token}"}
    return config

async def finance_mcp_client():
    """可视化图表"""
    servers = {"文档检索": _document_server_config()}
    if settings.mcp.finance_chart_url:
        servers["可视化图表"] = {
            "transport": "streamable_http",
            "url": settings.mcp.finance_chart_url,
        }
    mcp_client = MultiServerMCPClient(servers)
    return mcp_client


async def document_retriever_mcp_client():
    """企业内部文档检索"""
    mcp_client = MultiServerMCPClient(
        {"文档检索": _document_server_config()}
    )
    return mcp_client


async def tech_mcp_client():
    """网络搜索"""
    servers = {"文档检索": _document_server_config()}
    if settings.mcp.web_search_url:
        servers["网络搜索"] = {
            "transport": "streamable-http",
            "url": settings.mcp.web_search_url,
        }
    mcp_client = MultiServerMCPClient(servers)
    return mcp_client


async def legal_mcp_client():
    """法律法规"""
    servers = {"文档检索": _document_server_config()}
    if settings.mcp.legal_url:
        servers["法务"] = {
            "transport": "streamable-http",
            "url": settings.mcp.legal_url,
        }
    mcp_client = MultiServerMCPClient(servers)
    return mcp_client
