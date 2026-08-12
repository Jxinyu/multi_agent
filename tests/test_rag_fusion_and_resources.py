import asyncio
import threading
import time

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from multi_domain_enterprise_project.rag import rag_service, runtime
from multi_domain_enterprise_project.rag.exceptions import BackendDeleteError, RetrievalTimeoutError
from multi_domain_enterprise_project.rag.graph import ingestion_graph
from multi_domain_enterprise_project.rag.milvus import ingestion_milvus
from multi_domain_enterprise_project.rag.retrieval import format_fused_context, fuse_backend_results


def _result(
    node_id: str,
    score: float,
    content: str = "shared text",
    *,
    document_id: str = "document-a",
    chunk_index: int = 0,
):
    return NodeWithScore(
        node=TextNode(
            id_=node_id,
            text=content,
            metadata={
                "file_name": "doc.txt",
                "tenant_id": "tenant-a",
                "owner_id": "user-a",
                "acl": "private",
                "document_id": document_id,
                "version": 1,
                "chunk_index": chunk_index,
            },
        ),
        score=score,
    )


def test_structured_fusion_deduplicates_and_keeps_backend_provenance():
    fused = fuse_backend_results(
        {"milvus": [_result("milvus-id", 0.7)], "neo4j": [_result("graph-id", 0.9)]}
    )

    assert len(fused) == 1
    assert fused[0].score == 0.7
    assert fused[0].backends == ("milvus", "neo4j")
    assert fused[0].fusion_score == pytest.approx(2 / 61)


def test_rrf_rewards_cross_backend_consensus_without_comparing_raw_scores():
    consensus_milvus = _result("m-consensus", 0.1, document_id="consensus")
    consensus_graph = _result("g-consensus", 99.0, document_id="consensus")
    milvus_only = _result("m-only", 0.99, document_id="milvus-only")
    graph_only = _result("g-only", 100.0, document_id="graph-only")

    fused = fuse_backend_results(
        {
            "milvus": [milvus_only, consensus_milvus],
            "neo4j": [graph_only, consensus_graph],
        },
        rrf_k=60,
    )

    assert fused[0].node.metadata["document_id"] == "consensus"
    assert fused[0].backends == ("milvus", "neo4j")


def test_mg_retrieval_runs_concurrently_and_formats_fused_results(monkeypatch):
    state = {"active": 0, "maximum": 0, "rerank_calls": 0, "rerank_candidates": 0}

    class Retriever:
        def __init__(self, result):
            self.result = result

        async def retrieve_candidates(self, query, filters):
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
            await asyncio.sleep(0.03)
            state["active"] -= 1
            return [self.result]

    async def rerank(query, nodes):
        state["rerank_calls"] += 1
        state["rerank_candidates"] = len(nodes)
        return nodes

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
    monkeypatch.setattr(rag_service, "rerank_nodes", rerank)

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
    assert state["rerank_calls"] == 1
    assert state["rerank_candidates"] == 1
    assert answer.count("shared text") == 1
    assert "milvus, neo4j" in answer


def test_mg_retrieval_fails_explicitly_when_backend_times_out(monkeypatch):
    class SlowRetriever:
        async def retrieve_candidates(self, query, filters):
            await asyncio.sleep(0.05)
            return []

    monkeypatch.setattr(rag_service.settings.retrieval, "timeout_seconds", 0.01)
    monkeypatch.setattr(rag_service, "get_milvus_retriever_service", SlowRetriever)
    monkeypatch.setattr(rag_service, "get_graph_retriever_service", SlowRetriever)

    with pytest.raises(RetrievalTimeoutError, match="检索超过"):
        asyncio.run(
            rag_service.retrieve_service(
                "query",
                tenant_id="tenant-a",
                user_id="user-a",
                acl_list=["private"],
                mode="mg",
            )
        )


def test_retrieval_fails_explicitly_when_reranker_times_out(monkeypatch):
    class Retriever:
        async def retrieve_candidates(self, query, filters):
            return [_result("candidate", 0.9)]

    async def slow_rerank(query, nodes):
        await asyncio.sleep(0.05)
        return nodes

    monkeypatch.setattr(rag_service.settings.retrieval, "timeout_seconds", 0.01)
    monkeypatch.setattr(rag_service, "get_milvus_retriever_service", Retriever)
    monkeypatch.setattr(rag_service, "rerank_nodes", slow_rerank)

    with pytest.raises(RetrievalTimeoutError, match="重排超过"):
        asyncio.run(
            rag_service.retrieve_service(
                "query",
                tenant_id="tenant-a",
                user_id="user-a",
                acl_list=["private"],
                mode="milvus",
            )
        )


def test_reranker_uses_dedicated_thread_without_blocking_event_loop(monkeypatch):
    caller_thread = threading.get_ident()
    worker_threads = []
    event_loop_progress = []

    class FakeReranker:
        def postprocess_nodes(self, nodes, query_bundle):
            worker_threads.append(threading.get_ident())
            time.sleep(0.03)
            return nodes

    async def exercise():
        rerank_task = asyncio.create_task(runtime.rerank_nodes("query", [_result("candidate", 0.9)]))
        await asyncio.sleep(0.005)
        event_loop_progress.append(True)
        await rerank_task

    monkeypatch.setattr(runtime, "get_reranker", lambda: FakeReranker())
    asyncio.run(exercise())

    assert event_loop_progress == [True]
    assert worker_threads and worker_threads[0] != caller_thread


def test_context_budget_limits_document_dominance_and_total_length():
    results = fuse_backend_results(
        {
            "milvus": [
                _result("a-0", 0.9, "A" * 100, document_id="a", chunk_index=0),
                _result("a-1", 0.8, "A" * 100, document_id="a", chunk_index=1),
                _result("b-0", 0.7, "B" * 100, document_id="b", chunk_index=0),
            ]
        }
    )

    context = format_fused_context(results, max_chars=500, max_chunks_per_document=1)

    assert context.count("A" * 100) == 1
    assert context.count("B" * 100) == 1
    assert len(context) <= 500


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
