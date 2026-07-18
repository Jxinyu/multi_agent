from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

import httpx
from redis.asyncio import Redis

from config import settings


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


async def check_redis() -> CheckResult:
    try:
        client = Redis.from_url(settings.llm_key.redis)
        try:
            pong = await client.ping()
        finally:
            await client.aclose()
        return CheckResult("redis", bool(pong), "ping ok" if pong else "ping failed")
    except Exception as exc:
        return CheckResult("redis", False, str(exc))


async def check_mcp() -> CheckResult:
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            response = await client.get(settings.mcp.rag_url)
        # FastMCP streamable-http endpoints may reject GET or require auth, but should still answer.
        ok = response.status_code in {200, 400, 401, 403, 405}
        return CheckResult("mcp-rag", ok, f"HTTP {response.status_code}")
    except Exception as exc:
        return CheckResult("mcp-rag", False, str(exc))


async def check_ollama() -> CheckResult:
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            response = await client.get(f"{settings.ollama.base_url.rstrip('/')}/api/tags")
        response.raise_for_status()
        models = response.json().get("models", [])
        model_names = {item.get("name") for item in models}
        expected = settings.ollama.embedding_model
        if expected in model_names:
            return CheckResult("ollama", True, f"model available: {expected}")
        return CheckResult("ollama", False, f"model missing: {expected}")
    except Exception as exc:
        return CheckResult("ollama", False, str(exc))


async def check_milvus() -> CheckResult:
    def probe() -> int:
        from pymilvus import MilvusClient

        client = MilvusClient(uri=settings.milvus.uri)
        return len(client.list_collections())

    try:
        collection_count = await asyncio.wait_for(asyncio.to_thread(probe), timeout=5)
        return CheckResult("milvus", True, f"{collection_count} collections")
    except Exception as exc:
        return CheckResult("milvus", False, str(exc))


async def check_neo4j() -> CheckResult:
    if not settings.neo4j.password:
        return CheckResult("neo4j", False, "NEO4J_PASSWORD is not configured")
    def probe() -> int:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            settings.neo4j.url,
            auth=(settings.neo4j.username, settings.neo4j.password),
            connection_timeout=3,
        )
        try:
            with driver.session() as session:
                value = session.run("RETURN 1 AS ok").single()["ok"]
        finally:
            driver.close()
        return value

    try:
        value = await asyncio.wait_for(asyncio.to_thread(probe), timeout=5)
        return CheckResult("neo4j", value == 1, "query ok" if value == 1 else "query failed")
    except Exception as exc:
        return CheckResult("neo4j", False, str(exc))


async def run_checks(names: set[str] | None = None) -> list[CheckResult]:
    checks = {
        "redis": check_redis,
        "mcp-rag": check_mcp,
        "ollama": check_ollama,
        "milvus": check_milvus,
        "neo4j": check_neo4j,
    }
    selected = {name: fn for name, fn in checks.items() if not names or name in names}
    return await asyncio.gather(*(fn() for fn in selected.values()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local services required by the multi-agent RAG project.")
    parser.add_argument("--only", nargs="*", choices=["redis", "mcp-rag", "ollama", "milvus", "neo4j"])
    args = parser.parse_args()

    results = asyncio.run(run_checks(set(args.only or [])))
    for result in results:
        status = "OK" if result.ok else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")
    return 0 if all(item.ok for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
