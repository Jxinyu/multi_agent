import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMKeySetting(BaseModel):
    """大模型的key"""
    deepseek: str = ""
    xiaoAi: str = ""
    qwen: str = ""
    llamaParse: str = ""
    redis: str = "redis://127.0.0.1:6379"


class LlamaParseSetting(BaseModel):
    """llamaParse的配置"""
    invalidate_cache: bool = True  # 是否失效缓存
    tier: Literal["fast", "cost_effective", "agentic", "agentic_plus"] = "agentic"
    version: str = "latest"
    timeout_seconds: int = 180
    max_retries: int = 2


class MilvusSetting(BaseModel):
    """milvus的配置"""
    uri: str = 'http://127.0.0.1:19530'
    dims: int = 2560


class Neo4jSetting(BaseModel):
    """Neo4j 图数据库配置"""
    url: str = "bolt://127.0.0.1:7687"
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
    web_search_url: str = ""
    finance_chart_url: str = ""
    legal_url: str = ""
    host: str = "127.0.0.1"
    port: int = 8010
    log_level: str = "info"


class AuthSetting(BaseModel):
    """API 身份认证配置。"""

    mode: Literal["development", "public_key", "oidc"] = "development"
    issuer: str = "https://rag-upper.local"
    audience: str = "rag-upper-api"
    jwks_url: str = ""
    public_key_path: str = "multi_domain_enterprise_project/mcp_server/public_key"
    private_key_path: str = "multi_domain_enterprise_project/mcp_server/private_key"
    algorithms: list[str] = ["RS256"]
    development_user_id: str = "user_admin_001"
    development_username: str = "admin"
    development_tenant_id: str = "tenant_default"
    development_role: str = "admin"
    development_permissions: list[str] = ["chat:use", "kb:read", "kb:write", "kb:delete"]
    token_ttl_seconds: int = 900


class DatabaseSetting(BaseModel):
    """业务元数据数据库配置。"""

    url: str = "sqlite+aiosqlite:///./data/rag_upper.db"
    echo: bool = False


class UploadSetting(BaseModel):
    """上传容量与格式边界。"""

    max_file_size_bytes: int = 50 * 1024 * 1024
    max_attachment_size_bytes: int = 10 * 1024 * 1024
    max_files_per_request: int = 10
    max_attachments_per_request: int = 5
    allowed_extensions: list[str] = [
        ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".csv", ".json"
    ]


class RuntimeSetting(BaseModel):
    """应用运行与交付配置。"""

    environment: Literal["development", "test", "production"] = "development"
    request_rate_limit_per_minute: int = 60
    worker_max_attempts: int = 3
    worker_block_ms: int = 5000
    cors_origins: list[str] = []
    service_name: str = "rag-upper-api"
    otel_endpoint: str = ""


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
    auth: AuthSetting = AuthSetting()
    database: DatabaseSetting = DatabaseSetting()
    upload: UploadSetting = UploadSetting()
    runtime: RuntimeSetting = RuntimeSetting()


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
        "REDIS_URL": ("llm_key", "redis"),
        "LLAMA_PARSE_INVALIDATE_CACHE": ("llama_parser", "invalidate_cache"),
        "LLAMA_PARSE_TIER": ("llama_parser", "tier"),
        "LLAMA_PARSE_VERSION": ("llama_parser", "version"),
        "LLAMA_PARSE_TIMEOUT_SECONDS": ("llama_parser", "timeout_seconds"),
        "LLAMA_PARSE_MAX_RETRIES": ("llama_parser", "max_retries"),
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
        "RERANKER_USE_FP16": ("reranker", "use_fp16"),
        "MCP_RAG_URL": ("mcp", "rag_url"),
        "MCP_WEB_SEARCH_URL": ("mcp", "web_search_url"),
        "MCP_FINANCE_CHART_URL": ("mcp", "finance_chart_url"),
        "MCP_LEGAL_URL": ("mcp", "legal_url"),
        "MCP_HOST": ("mcp", "host"),
        "MCP_PORT": ("mcp", "port"),
        "MCP_LOG_LEVEL": ("mcp", "log_level"),
        "AUTH_MODE": ("auth", "mode"),
        "AUTH_ISSUER": ("auth", "issuer"),
        "AUTH_AUDIENCE": ("auth", "audience"),
        "AUTH_JWKS_URL": ("auth", "jwks_url"),
        "AUTH_PUBLIC_KEY_PATH": ("auth", "public_key_path"),
        "AUTH_PRIVATE_KEY_PATH": ("auth", "private_key_path"),
        "AUTH_ALGORITHMS": ("auth", "algorithms"),
        "AUTH_DEV_USER_ID": ("auth", "development_user_id"),
        "AUTH_DEV_USERNAME": ("auth", "development_username"),
        "AUTH_DEV_TENANT_ID": ("auth", "development_tenant_id"),
        "AUTH_DEV_ROLE": ("auth", "development_role"),
        "AUTH_DEV_PERMISSIONS": ("auth", "development_permissions"),
        "AUTH_TOKEN_TTL_SECONDS": ("auth", "token_ttl_seconds"),
        "DATABASE_URL": ("database", "url"),
        "DATABASE_ECHO": ("database", "echo"),
        "MAX_FILE_SIZE_BYTES": ("upload", "max_file_size_bytes"),
        "MAX_ATTACHMENT_SIZE_BYTES": ("upload", "max_attachment_size_bytes"),
        "MAX_FILES_PER_REQUEST": ("upload", "max_files_per_request"),
        "MAX_ATTACHMENTS_PER_REQUEST": ("upload", "max_attachments_per_request"),
        "ALLOWED_UPLOAD_EXTENSIONS": ("upload", "allowed_extensions"),
        "APP_ENV": ("runtime", "environment"),
        "REQUEST_RATE_LIMIT_PER_MINUTE": ("runtime", "request_rate_limit_per_minute"),
        "WORKER_MAX_ATTEMPTS": ("runtime", "worker_max_attempts"),
        "WORKER_BLOCK_MS": ("runtime", "worker_block_ms"),
        "CORS_ORIGINS": ("runtime", "cors_origins"),
        "OTEL_SERVICE_NAME": ("runtime", "service_name"),
        "OTEL_EXPORTER_OTLP_ENDPOINT": ("runtime", "otel_endpoint"),
    }

    for env_name, path in env_map.items():
        raw_value = os.getenv(env_name)
        if raw_value is None:
            continue
        value: Any = raw_value
        if env_name in {
            "MILVUS_DIMS", "RERANKER_TOP_N", "MCP_PORT", "AUTH_TOKEN_TTL_SECONDS",
            "LLAMA_PARSE_TIMEOUT_SECONDS", "LLAMA_PARSE_MAX_RETRIES",
            "MAX_FILE_SIZE_BYTES", "MAX_ATTACHMENT_SIZE_BYTES", "MAX_FILES_PER_REQUEST",
            "MAX_ATTACHMENTS_PER_REQUEST", "REQUEST_RATE_LIMIT_PER_MINUTE",
            "WORKER_MAX_ATTEMPTS", "WORKER_BLOCK_MS",
        }:
            value = int(raw_value)
        elif env_name in {"LLAMA_PARSE_INVALIDATE_CACHE", "DATABASE_ECHO", "RERANKER_USE_FP16"}:
            value = raw_value.strip().lower() in {"1", "true", "yes", "on"}
        elif env_name in {"AUTH_ALGORITHMS", "AUTH_DEV_PERMISSIONS", "ALLOWED_UPLOAD_EXTENSIONS", "CORS_ORIGINS"}:
            value = [item.strip() for item in raw_value.split(",") if item.strip()]
        _set_nested(config, path, value)

    return config


def load_setting(config_path):
    _load_dotenv(Path(".env"))
    path = Path(config_path)
    if path.exists():
        with open(path, encoding='utf-8') as f:
            config_data = yaml.safe_load(f) or {}
    else:
        config_data = {}
    return AppSettings.model_validate(_apply_env_overrides(config_data))


def validate_runtime_settings(settings: AppSettings) -> None:
    """在生产启动前拒绝不安全或不可持久化的配置。"""
    if settings.runtime.environment != "production":
        return
    problems: list[str] = []
    if settings.auth.mode == "development":
        problems.append("production 禁止 AUTH_MODE=development")
    if settings.database.url.startswith("sqlite"):
        problems.append("production 必须使用 PostgreSQL DATABASE_URL")
    if not settings.auth.issuer or not settings.auth.audience:
        problems.append("AUTH_ISSUER 与 AUTH_AUDIENCE 必须配置")
    if settings.auth.mode == "oidc" and not settings.auth.jwks_url:
        problems.append("AUTH_MODE=oidc 时必须配置 AUTH_JWKS_URL")
    if settings.auth.mode == "public_key" and not settings.auth.public_key_path:
        problems.append("AUTH_MODE=public_key 时必须配置 AUTH_PUBLIC_KEY_PATH")
    if not settings.neo4j.password:
        problems.append("NEO4J_PASSWORD 必须配置")
    if not settings.llm_key.qwen:
        problems.append("QWEN_API_KEY 必须配置")
    if not settings.llm_key.llamaParse:
        problems.append("LLAMA_PARSE_API_KEY 必须配置")
    if not settings.reranker.model_path.strip():
        problems.append("RERANKER_MODEL_PATH 必须配置")
    if problems:
        raise RuntimeError("生产配置校验失败: " + "; ".join(problems))


if __name__ == '__main__':
    setting = load_setting('config.yaml')
    print(setting.llm_key.xiaoAi)
