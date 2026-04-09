from langchain_mcp_adapters.client import MultiServerMCPClient

dq = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJocnwxfDIiLCJpc3MiOiJodHRwczovL3hpbnl1LmNvbSIsImlhdCI6MTc3NTczMzk3MiwiZXhwIjoxODA3MjY5OTcyLCJhdWQiOiJteS1kZXYtc2VydmVyIiwidGVuYW50IjoiaHIiLCJhY2wiOiIxfDIifQ.EaV_3dbUg5M19q8UFk_b0SpXd_62ZpiTNBBuMva-qnzprpMV5msWb4lhluXtdU4A8clAYBSS5DXhLwH9fAuHnfxcDk5xZ-CtVKcjehccLVfwe0ll87gupYXelRP4OFEY-xvH9FtKgNlC91hYLOsGn1bO1wk2CAegiUVck4l0viFXrka4saO63BbaTQUyloVNP8E53800kNyERxqPj33QOZefdld0SlHLVRKJiRlrOFox-dEM9oUQ8N4WnxTW9MG3-zFIdUI0l2VTUic6dC4ytPW-Xp2LNjJOPWcrXHYBraIfHbuq8A9g7lGE21eO-hj6ZN_H9k6L7G5iY56q-5mfGA"

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
