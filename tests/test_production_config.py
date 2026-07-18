from pathlib import Path

import pytest

from config import settings
from config.config import load_setting, validate_runtime_settings
from multi_domain_enterprise_project.rag.runtime import get_reranker


def test_production_config_requires_model_credentials() -> None:
    candidate = settings.model_copy(deep=True)
    candidate.runtime.environment = "production"
    candidate.auth.mode = "public_key"
    candidate.database.url = "postgresql+psycopg://rag:secret@postgres/rag"
    candidate.neo4j.password = "secret"
    candidate.llm_key.qwen = ""
    candidate.llm_key.llamaParse = ""
    candidate.reranker.model_path = ""

    with pytest.raises(RuntimeError) as exc_info:
        validate_runtime_settings(candidate)

    message = str(exc_info.value)
    assert "QWEN_API_KEY" in message
    assert "LLAMA_PARSE_API_KEY" in message
    assert "RERANKER_MODEL_PATH" in message


def test_reranker_fp16_environment_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("reranker:\n  use_fp16: true\n", encoding="utf-8")
    monkeypatch.setenv("RERANKER_USE_FP16", "false")

    loaded = load_setting(config_path)

    assert loaded.reranker.use_fp16 is False


def test_reranker_rejects_missing_local_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.reranker, "model_path", "/missing/reranker-model")
    get_reranker.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="模型目录不存在"):
            get_reranker()
    finally:
        get_reranker.cache_clear()
