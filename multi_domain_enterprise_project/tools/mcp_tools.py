from langchain_mcp_adapters.client import MultiServerMCPClient

dq = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJocnwxfDIiLCJpc3MiOiJodHRwczovL3hpbnl1LmNvbSIsImlhdCI6MTc3NDk2MTE1OSwiZXhwIjoxNzc1NTY1OTU5LCJhdWQiOiJteS1kZXYtc2VydmVyIiwidGVuYW50IjoiaHIiLCJhY2wiOiIxfDIifQ.JLB72JbStZYNDc-WIb2rLvO09BfUSh6WVR4yfyblMnIpQ8qdyp-Qx4YL2dks7YY_v3NkhQPi9ohaCQZUPpDrizL38sbKwhWRiFWWcuzdTOdF9Y22d_3IyjxPkrm3oZxDEn2MEvWMtkEwuQnolK7kaJCvY68GEZ8-P2JeoJxdlPwPWEGCteSA2apy4R7rQ-iGhJQT39lB2f5dUD59IVAw_Ro4hvajmHnfssv0JFXWF5nm20jfDS70Gerf5HdLAC-8YlU4oGqgCH8f_d5MJingb1xyenAfcsxSjJVLszFZb9k3pejk5aGSGAj5JKAzVSw-Y-GTWDExMiU39jyUMhV8aA"


async def finance_mcp_client():
    """可视化图表"""
    mcp_client = MultiServerMCPClient(
        {
            "可视化图表":
                {  # 可视化图表-MCP-Server
                    "transport": "streamable_http",
                    "url": "https://mcp.api-inference.modelscope.net/dfedfd3e16d04b/mcp"
                },
            "文档检索":
                {  # 文档检索
                    "transport": "streamable-http",
                    "url": "http://127.0.0.1:8000/rag-retriever",
                    "headers": {
                        "Authorization": f"Bearer {dq}"
                    }
                },
        },
    )
    return mcp_client


async def document_retriever_mcp_client():
    """企业内部文档检索"""
    mcp_client = MultiServerMCPClient(
        {"文档检索":
            {  # 文档检索
                "transport": "streamable-http",
                "url": "http://127.0.0.1:8000/rag-retriever",
                "headers": {
                    "Authorization": f"Bearer {dq}"
                }
            },
        }
    )
    return mcp_client


async def tech_mcp_client():
    """网络搜索"""
    mcp_client = MultiServerMCPClient(
        {
            "网络搜索":
                {  # 网络搜索
                    "transport": "streamable-http",
                    "url": "https://open.bigmodel.cn/api/mcp-broker/proxy/web-search/mcp?Authorization=163af72ae3d34e2ebb81919e05b5879b.6QoCjMulVygVKHtu"
                },
            "文档检索":
                {  # 文档检索
                    "transport": "streamable-http",
                    "url": "http://127.0.0.1:8000/rag-retriever",
                    "headers": {
                        "Authorization": f"Bearer {dq}"
                    }
                },
        }
    )
    return mcp_client


async def legal_mcp_client():
    """法律法规"""
    mcp_client = MultiServerMCPClient(
        {
            "法务":
                {  # 法务
                    "transport": "streamable-http",
                    "url": "https://mcp.api-inference.modelscope.net/cb5e7d8119b04f/mcp"
                },
            "文档检索":
                {  # 文档检索
                    "transport": "streamable-http",
                    "url": "http://127.0.0.1:8000/rag-retriever",
                    "headers": {
                        "Authorization": f"Bearer {dq}"
                    }
                },
        }
    )
    return mcp_client
