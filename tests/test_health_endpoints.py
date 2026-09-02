from types import SimpleNamespace

import pytest

from multi_domain_enterprise_project.api import health


class _Redis:
    async def ping(self):
        return True


class _ScalarResult:
    def scalar_one(self):
        return 1


class _Session:
    async def execute(self, statement):
        return _ScalarResult()


class _SessionContext:
    async def __aenter__(self):
        return _Session()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.mark.asyncio
async def test_readiness_combines_app_state_database_and_external_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_checks(names):
        assert names == {"milvus", "neo4j", "ollama", "mcp-rag"}
        return [SimpleNamespace(name=name, ok=True) for name in sorted(names)]

    monkeypatch.setattr(health, "SessionFactory", _SessionContext)
    monkeypatch.setattr(health, "run_checks", fake_checks)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(redis=_Redis(), checkpointer=object())),
    )

    ready, checks = await health._readiness_payload(request)

    assert ready is True
    assert checks == {
        "redis": True,
        "database": True,
        "checkpointer": True,
        "mcp-rag": True,
        "milvus": True,
        "neo4j": True,
        "ollama": True,
    }
