import asyncio

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from multi_domain_enterprise_project.rag import rag_service, runtime
from multi_domain_enterprise_project.rag.exceptions import BackendDeleteError
from multi_domain_enterprise_project.rag.graph import ingestion_graph
from multi_domain_enterprise_project.rag.milvus import ingestion_milvus
from multi_domain_enterprise_project.rag.retrieval import fuse_backend_results


def _result(node_id: str, score: float, content: str = "shared text"):
    return NodeWithScore(
        node=TextNode(
            id_=node_id,
            text=content,
            metadata={
                "file_name": "doc.txt",
                "tenant_id": "tenant-a",
                "owner_id": "user-a",
                "acl": "private",
                "document_id": "document-a",
                "version": 1,
                "chunk_index": 0,
            },
        ),
        score=score,
    )


def test_structured_fusion_deduplicates_and_keeps_backend_provenance():
    fused = fuse_backend_results(
        {"milvus": [_result("milvus-id", 0.7)], "neo4j": [_result("graph-id", 0.9)]}
    )

    assert len(fused) == 1
    assert fused[0].score == 0.9
    assert fused[0].backends == ("milvus", "neo4j")


def test_mg_retrieval_runs_concurrently_and_formats_fused_results(monkeypatch):
    state = {"active": 0, "maximum": 0}

    class Retriever:
        def __init__(self, result):
            self.result = result

        async def retrieve_nodes(self, query, filters):
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
            await asyncio.sleep(0.03)
            state["active"] -= 1
            return [self.result]

    monkeypatch.setattr(
        rag_service,
        "get_milvus_retriever_service",
        lambda: Retriever(_result("milvus-id", 0.7)),
    )
    monkeypatch.setattr(
        rag_service,
        "get_graph_retriever_service",
        lambda: Retriever(_result("graph-id", 0.9)),
    )

    answer = asyncio.run(
        rag_service.retrieve_service(
            "query",
            tenant_id="tenant-a",
            user_id="user-a",
            acl_list=["private"],
            mode="mg",
        )
    )

    assert state["maximum"] == 2
    assert answer.count("shared text") == 1
    assert "milvus, neo4j" in answer


def test_service_and_reranker_factories_reuse_instances(monkeypatch):
    class FakeService:
        def __init__(self, *args, **kwargs):
            self.args = args

    class FakeReranker:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    ingestion_milvus.get_milvus_retriever_service.cache_clear()
    ingestion_graph.get_graph_retriever_service.cache_clear()
    runtime.get_reranker.cache_clear()
    monkeypatch.setattr(ingestion_milvus, "MilvusRetrieverService", FakeService)
    monkeypatch.setattr(ingestion_graph, "GraphRetrieverService", FakeService)
    monkeypatch.setattr(runtime, "FlagEmbeddingReranker", FakeReranker)
    try:
        assert (
            ingestion_milvus.get_milvus_retriever_service()
            is ingestion_milvus.get_milvus_retriever_service()
        )
        assert (
            ingestion_graph.get_graph_retriever_service()
            is ingestion_graph.get_graph_retriever_service()
        )
        assert runtime.get_reranker() is runtime.get_reranker()
    finally:
        ingestion_milvus.get_milvus_retriever_service.cache_clear()
        ingestion_graph.get_graph_retriever_service.cache_clear()
        runtime.get_reranker.cache_clear()


def test_unified_delete_calls_both_backends(monkeypatch):
    calls = []

    class Backend:
        def __init__(self, name, error=None):
            self.name = name
            self.error = error

        async def delete_document(self, tenant_id, document_id):
            calls.append((self.name, tenant_id, document_id))
            if self.error:
                raise self.error

    monkeypatch.setattr(
        rag_service,
        "get_milvus_store_pipeline_service",
        lambda: Backend("milvus"),
    )
    monkeypatch.setattr(
        rag_service,
        "get_graph_store_pipeline_service",
        lambda: Backend("neo4j"),
    )

    status = asyncio.run(rag_service.delete_document_data("tenant-a", "document-a"))

    assert status == {
        "milvus": {"status": "success", "error": None},
        "neo4j": {"status": "success", "error": None},
    }
    assert set(calls) == {
        ("milvus", "tenant-a", "document-a"),
        ("neo4j", "tenant-a", "document-a"),
    }


def test_unified_delete_partial_failure_exposes_status(monkeypatch):
    class Backend:
        def __init__(self, error=None):
            self.error = error

        async def delete_document(self, tenant_id, document_id):
            if self.error:
                raise self.error

    monkeypatch.setattr(
        rag_service,
        "get_milvus_store_pipeline_service",
        lambda: Backend(),
    )
    monkeypatch.setattr(
        rag_service,
        "get_graph_store_pipeline_service",
        lambda: Backend(RuntimeError("delete failed")),
    )

    with pytest.raises(BackendDeleteError) as caught:
        asyncio.run(rag_service.delete_document_data("tenant-a", "document-a"))

    assert caught.value.backend_status["milvus"]["status"] == "success"
    assert caught.value.backend_status["neo4j"] == {
        "status": "failed",
        "error": "delete failed",
    }
