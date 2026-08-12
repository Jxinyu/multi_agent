import asyncio
from types import SimpleNamespace

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from multi_domain_enterprise_project.rag.authorization import (
    RetrievalAuthorization,
    build_authorized_filter_branches,
    filter_authorized_nodes,
)
from multi_domain_enterprise_project.rag.exceptions import RetrievalAuthorizationError
from multi_domain_enterprise_project.rag.graph import ingestion_graph


def _result(node_id: str, tenant: str, owner: str, acl: str, score: float = 0.8):
    return NodeWithScore(
        node=TextNode(
            id_=node_id,
            text=node_id,
            metadata={
                "tenant_id": tenant,
                "owner_id": owner,
                "acl": acl,
                "document_id": node_id,
                "version": 1,
                "chunk_index": 0,
            },
        ),
        score=score,
    )


def test_authorization_requires_tenant_and_user():
    with pytest.raises(RetrievalAuthorizationError):
        RetrievalAuthorization.from_filters({"tenant_id": "tenant-a", "acl": ["team"]})
    with pytest.raises(RetrievalAuthorizationError):
        RetrievalAuthorization.from_filters({"user_id": "user-a", "acl": ["team"]})


def test_authorized_filter_branches_are_always_tenant_scoped():
    scope, branches = build_authorized_filter_branches(
        {
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "acl": ["private", "team-a"],
            "title": "Policy",
        }
    )

    assert scope.shared_acl == ("team-a",)
    assert len(branches) == 2
    branch_values = [{item.key: item.value for item in branch.filters} for branch in branches]
    assert all(values["tenant_id"] == "tenant-a" for values in branch_values)
    assert branch_values[0]["owner_id"] == "user-a"
    assert branch_values[1]["acl"] == ["team-a"]
    assert all(values["title"] == "Policy" for values in branch_values)


def test_application_filter_enforces_tenant_owner_and_acl():
    scope = RetrievalAuthorization("tenant-a", "user-a", ("private", "team-a"))
    nodes = [
        _result("owned", "tenant-a", "user-a", "private"),
        _result("shared", "tenant-a", "other", "team-a"),
        _result("private-other", "tenant-a", "other", "private"),
        _result("wrong-tenant", "tenant-b", "user-a", "team-a"),
    ]

    assert [item.node.node_id for item in filter_authorized_nodes(nodes, scope)] == [
        "owned",
        "shared",
    ]


def test_graph_retrieval_uses_only_filtered_vector_branches(monkeypatch):
    observed_filters = []
    candidates = [
        _result("owned", "tenant-a", "user-a", "private"),
        _result("shared", "tenant-a", "other", "team-a"),
        _result("forbidden", "tenant-b", "user-a", "team-a"),
    ]

    class FakeVectorRetriever:
        def __init__(self, graph_store, **kwargs):
            observed_filters.append(kwargs["filters"])

        async def aretrieve(self, query):
            return candidates

    async def identity_reranker(query, nodes):
        return nodes

    monkeypatch.setattr(ingestion_graph, "VectorContextRetriever", FakeVectorRetriever)
    service = ingestion_graph.GraphRetrieverService.__new__(
        ingestion_graph.GraphRetrieverService
    )
    service.index = SimpleNamespace(property_graph_store=object())
    service.embed_model = object()
    monkeypatch.setattr(ingestion_graph, "rerank_nodes", identity_reranker)

    results = asyncio.run(
        service.retrieve_nodes(
            "query",
            {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
                "acl": ["private", "team-a"],
            },
        )
    )

    assert [item.node.node_id for item in results] == ["owned", "shared"]
    assert len(observed_filters) == 2
    for filters in observed_filters:
        assert any(item.key == "tenant_id" and item.value == "tenant-a" for item in filters.filters)
    assert not hasattr(ingestion_graph, "LLMSynonymRetriever")
