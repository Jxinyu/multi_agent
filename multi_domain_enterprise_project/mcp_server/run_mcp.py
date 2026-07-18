import asyncio
import logging

from config import settings, validate_runtime_settings
from multi_domain_enterprise_project.mcp_server.server_mcp_tools import build_mcp_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    validate_runtime_settings(settings)
    logger.info("正在初始化企业知识库 MCP 服务")
    mcp_app = await build_mcp_server()

    logger.info("MCP 服务启动 host=%s port=%s", settings.mcp.host, settings.mcp.port)

    await mcp_app.run_async(
        transport="streamable-http",
        host=settings.mcp.host,
        port=settings.mcp.port,
        show_banner=settings.runtime.environment != "production",
        log_level=settings.mcp.log_level,
        path='/rag-retriever'
    )


if __name__ == "__main__":
    asyncio.run(main())
