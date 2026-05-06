import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMKeySetting(BaseModel):
    """大模型的key"""
    deepseek: str = ""
    xiaoAi: str = ""
    qwen: str = ""
    llamaParse: str = ""
    postgressql: str = "postgresql://postgres:123123@127.0.0.1:5432/langgraph-multi"
    redis: str = "redis://127.0.0.1:6379"


class LlamaParseSetting(BaseModel):
    """llamaParse的配置"""
    invalidate_cache: bool = True  # 是否失效缓存


class MilvusSetting(BaseModel):
    """milvus的配置"""
    uri: str = 'http://127.0.0.1:19530'
    dims: int = 2560


class Neo4jSetting(BaseModel):
    """Neo4j 图数据库配置"""
    url: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = ""


class OllamaSetting(BaseModel):
    """Ollama 本地模型配置"""
    base_url: str = "http://127.0.0.1:11434"
    embedding_model: str = "qwen3-embedding:4b"
    vlm_model: str = "qwen2.5vl:3b"


class RerankerSetting(BaseModel):
    """重排模型配置"""
    model_path: str = "D:/Environment/model/bge-reranker-v2-m3"
    top_n: int = 3
    use_fp16: bool = True


class MCPSetting(BaseModel):
    """MCP 服务配置"""
    rag_url: str = "http://127.0.0.1:8010/rag-retriever"
    document_token: str = ""
    web_search_url: str = ""
    finance_chart_url: str = ""
    legal_url: str = ""
    public_key_path: str = ""
    private_key_path: str = ""


class AppSettings(BaseSettings):
    """app配置"""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_key: LLMKeySetting = LLMKeySetting()
    llama_parser: LlamaParseSetting = LlamaParseSetting()
    milvus: MilvusSetting = MilvusSetting()
    neo4j: Neo4jSetting = Neo4jSetting()
    ollama: OllamaSetting = OllamaSetting()
    reranker: RerankerSetting = RerankerSetting()
    mcp: MCPSetting = MCPSetting()


def _set_nested(config: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = config
    for key in path[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[path[-1]] = value


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    env_map: dict[str, tuple[str, ...]] = {
        "LLAMA_PARSE_API_KEY": ("llm_key", "llamaParse"),
        "DEEPSEEK_API_KEY": ("llm_key", "deepseek"),
        "XIAOAI_API_KEY": ("llm_key", "xiaoAi"),
        "QWEN_API_KEY": ("llm_key", "qwen"),
        "POSTGRES_URL": ("llm_key", "postgressql"),
        "REDIS_URL": ("llm_key", "redis"),
        "LLAMA_PARSE_INVALIDATE_CACHE": ("llama_parser", "invalidate_cache"),
        "MILVUS_URI": ("milvus", "uri"),
        "MILVUS_DIMS": ("milvus", "dims"),
        "NEO4J_URL": ("neo4j", "url"),
        "NEO4J_USERNAME": ("neo4j", "username"),
        "NEO4J_PASSWORD": ("neo4j", "password"),
        "OLLAMA_BASE_URL": ("ollama", "base_url"),
        "OLLAMA_EMBEDDING_MODEL": ("ollama", "embedding_model"),
        "OLLAMA_VLM_MODEL": ("ollama", "vlm_model"),
        "RERANKER_MODEL_PATH": ("reranker", "model_path"),
        "RERANKER_TOP_N": ("reranker", "top_n"),
        "MCP_RAG_URL": ("mcp", "rag_url"),
        "MCP_DOCUMENT_TOKEN": ("mcp", "document_token"),
        "MCP_WEB_SEARCH_URL": ("mcp", "web_search_url"),
        "MCP_FINANCE_CHART_URL": ("mcp", "finance_chart_url"),
        "MCP_LEGAL_URL": ("mcp", "legal_url"),
        "MCP_PUBLIC_KEY_PATH": ("mcp", "public_key_path"),
        "MCP_PRIVATE_KEY_PATH": ("mcp", "private_key_path"),
    }

    for env_name, path in env_map.items():
        raw_value = os.getenv(env_name)
        if raw_value is None:
            continue
        value: Any = raw_value
        if env_name in {"MILVUS_DIMS", "RERANKER_TOP_N"}:
            value = int(raw_value)
        elif env_name == "LLAMA_PARSE_INVALIDATE_CACHE":
            value = raw_value.strip().lower() in {"1", "true", "yes", "on"}
        _set_nested(config, path, value)

    return config


def load_setting(config_path):
    _load_dotenv(Path(".env"))
    path = Path(config_path)
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f) or {}
    else:
        config_data = {}
    return AppSettings.model_validate(_apply_env_overrides(config_data))


if __name__ == '__main__':
    setting = load_setting('config.yaml')
    print(setting.llm_key.xiaoAi)
