import asyncio
import logging

from multi_domain_enterprise_project.mcp_server.server_mcp_tools import build_mcp_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    logger.info("🔄 正在初始化企业知识库 MCP 服务...")
    mcp_app = await build_mcp_server()

    logger.info("🚀 服务已启动！监听 8010 端口 (streamable-http Transport)")

    await mcp_app.run_async(
        transport="streamable-http",
        host="127.0.0.1", port=8010,
        show_banner=True,
        log_level='debug',
        path='/rag-retriever'
    )


if __name__ == "__main__":
    asyncio.run(main())
