from langchain_mcp_adapters.client import MultiServerMCPClient


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
                        "Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJocnwxfDIiLCJpc3MiOiJodHRwczovL3hpbnl1LmNvbSIsImlhdCI6MTc3NDE2OTA2OSwiZXhwIjoxNzc0NzczODY5LCJhdWQiOiJteS1kZXYtc2VydmVyIiwidGVuYW50IjoiaHIiLCJhY2wiOiIxfDIifQ.dzoUgcGt5v-aYLTXnM4UaewyeTYIMT3Dhfxf1gEQEFyTW47_vEwMEvYUzVRwKimI1WBu608iDqrWpzu_eJc2GbHjlHXzQznyvK6CjEGwh2YMrbJfSDApcsgCqsQxyY_aWHMfwuVMmJWKCaHaADFLmHaozW4AU2SOsEPGfxFpHKbSjM9dd91_q6xLVBV1TusG9KVuBkGjT4jjlr_VFSK3kDNLmGOdtiQbOv7LDzY7Ykp0vaqHdw-LWX-8uSgPQiSJQmDSfAXgsG0lXgGjWBPC1LmeIbmK-UZDs0ofw6DwtdcliL1Cx_Vi87d73pX3avz1GAVBN6Al9MhETSIoGJx0xw",
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
                    "Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJocnwxfDIiLCJpc3MiOiJodHRwczovL3hpbnl1LmNvbSIsImlhdCI6MTc3NDE2OTA2OSwiZXhwIjoxNzc0NzczODY5LCJhdWQiOiJteS1kZXYtc2VydmVyIiwidGVuYW50IjoiaHIiLCJhY2wiOiIxfDIifQ.dzoUgcGt5v-aYLTXnM4UaewyeTYIMT3Dhfxf1gEQEFyTW47_vEwMEvYUzVRwKimI1WBu608iDqrWpzu_eJc2GbHjlHXzQznyvK6CjEGwh2YMrbJfSDApcsgCqsQxyY_aWHMfwuVMmJWKCaHaADFLmHaozW4AU2SOsEPGfxFpHKbSjM9dd91_q6xLVBV1TusG9KVuBkGjT4jjlr_VFSK3kDNLmGOdtiQbOv7LDzY7Ykp0vaqHdw-LWX-8uSgPQiSJQmDSfAXgsG0lXgGjWBPC1LmeIbmK-UZDs0ofw6DwtdcliL1Cx_Vi87d73pX3avz1GAVBN6Al9MhETSIoGJx0xw",
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
                        "Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJocnwxfDIiLCJpc3MiOiJodHRwczovL3hpbnl1LmNvbSIsImlhdCI6MTc3NDE2OTA2OSwiZXhwIjoxNzc0NzczODY5LCJhdWQiOiJteS1kZXYtc2VydmVyIiwidGVuYW50IjoiaHIiLCJhY2wiOiIxfDIifQ.dzoUgcGt5v-aYLTXnM4UaewyeTYIMT3Dhfxf1gEQEFyTW47_vEwMEvYUzVRwKimI1WBu608iDqrWpzu_eJc2GbHjlHXzQznyvK6CjEGwh2YMrbJfSDApcsgCqsQxyY_aWHMfwuVMmJWKCaHaADFLmHaozW4AU2SOsEPGfxFpHKbSjM9dd91_q6xLVBV1TusG9KVuBkGjT4jjlr_VFSK3kDNLmGOdtiQbOv7LDzY7Ykp0vaqHdw-LWX-8uSgPQiSJQmDSfAXgsG0lXgGjWBPC1LmeIbmK-UZDs0ofw6DwtdcliL1Cx_Vi87d73pX3avz1GAVBN6Al9MhETSIoGJx0xw",
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
                        "Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJocnwxfDIiLCJpc3MiOiJodHRwczovL3hpbnl1LmNvbSIsImlhdCI6MTc3NDE2OTA2OSwiZXhwIjoxNzc0NzczODY5LCJhdWQiOiJteS1kZXYtc2VydmVyIiwidGVuYW50IjoiaHIiLCJhY2wiOiIxfDIifQ.dzoUgcGt5v-aYLTXnM4UaewyeTYIMT3Dhfxf1gEQEFyTW47_vEwMEvYUzVRwKimI1WBu608iDqrWpzu_eJc2GbHjlHXzQznyvK6CjEGwh2YMrbJfSDApcsgCqsQxyY_aWHMfwuVMmJWKCaHaADFLmHaozW4AU2SOsEPGfxFpHKbSjM9dd91_q6xLVBV1TusG9KVuBkGjT4jjlr_VFSK3kDNLmGOdtiQbOv7LDzY7Ykp0vaqHdw-LWX-8uSgPQiSJQmDSfAXgsG0lXgGjWBPC1LmeIbmK-UZDs0ofw6DwtdcliL1Cx_Vi87d73pX3avz1GAVBN6Al9MhETSIoGJx0xw",
                    }
                },
        }
    )
    return mcp_client
