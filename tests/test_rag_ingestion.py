import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from multi_domain_enterprise_project.rag import document_in_database
from multi_domain_enterprise_project.rag.chunker import (
    EnterpriseDocumentChunker,
    stable_node_id,
)
from multi_domain_enterprise_project.rag.documentParser.exception_handling import (
    DocumentParsingError,
)
from multi_domain_enterprise_project.rag.exceptions import DualWriteError, EmptyDocumentError


def _metadata(tmp_path: Path) -> dict:
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    return {
        "file_name": source.name,
        "file_path": str(source),
        "tenant_id": "tenant-a",
        "owner_id": "user-a",
        "document_id": "document-a",
        "version": 3,
        "title": "Title",
        "acl": "team-a",
    }


def test_chunk_ids_ignore_random_paths_and_other_metadata():
    text = "# Header\n" + "Stable sentence. " * 80
    first_metadata = {
        "tenant_id": "tenant-a",
        "document_id": "document-a",
        "version": 7,
        "file_path_md": "random/111.md",
        "upload_time": "first",
    }
    second_metadata = {
        **first_metadata,
        "file_path_md": "random/" + "9" * 500 + ".md",
        "upload_time": "second",
    }

    first = EnterpriseDocumentChunker(128, 16).split_text(text, first_metadata)
    second = EnterpriseDocumentChunker(128, 16).split_text(text, second_metadata)

    assert [node.node_id for node in first] == [node.node_id for node in second]
    assert [node.get_content() for node in first] == [node.get_content() for node in second]
    assert first[0].node_id == stable_node_id("tenant-a", "document-a", 7, 0)
    assert [node.metadata["chunk_index"] for node in first] == list(range(len(first)))


def test_chunker_rejects_empty_or_unidentified_documents():
    chunker = EnterpriseDocumentChunker()
    with pytest.raises(EmptyDocumentError):
        chunker.split_text(" ", {"tenant_id": "tenant-a", "document_id": "doc"})
    with pytest.raises(ValueError, match="document_id"):
        chunker.split_text("content", {"tenant_id": "tenant-a"})


def test_clean_document_str_propagates_parser_failure(monkeypatch, tmp_path):
    class FailingRouter:
        async def route_and_parse(self, file_path):
            raise RuntimeError("parser unavailable")

    monkeypatch.setattr(
        document_in_database,
        "DocumentParserRouter",
        lambda mode: FailingRouter(),
    )

    with pytest.raises(DocumentParsingError, match="文档解析失败") as exc_info:
        asyncio.run(document_in_database.clean_document_str(str(tmp_path / "a.txt"), "t"))
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "parser unavailable"


def test_clean_document_str_rejects_empty_parse_result(monkeypatch, tmp_path):
    class EmptyRouter:
        async def route_and_parse(self, file_path):
            return "  "

    monkeypatch.setattr(
        document_in_database,
        "DocumentParserRouter",
        lambda mode: EmptyRouter(),
    )

    with pytest.raises(DocumentParsingError, match="解析结果为空"):
        asyncio.run(document_in_database.clean_document_str(str(tmp_path / "a.txt"), "t"))


def test_insert_document_returns_real_chunk_count(monkeypatch, tmp_path):
    metadata = _metadata(tmp_path)
    nodes = [object(), object(), object()]
    backend = type("Backend", (), {"insert_nodes": AsyncMock(return_value=None)})()

    monkeypatch.setattr(
        document_in_database,
        "clean_document_str",
        AsyncMock(return_value=("parsed", tmp_path / "parsed.md")),
    )
    monkeypatch.setattr(
        document_in_database,
        "EnterpriseDocumentChunker",
        lambda **kwargs: type("Chunker", (), {"split_text": lambda self, text, metadata: nodes})(),
    )
    monkeypatch.setattr(
        document_in_database,
        "get_milvus_store_pipeline_service",
        lambda: backend,
    )

    result = asyncio.run(document_in_database.insert_document(metadata, "milvus"))

    assert result == 3
    assert metadata["chunk_count"] == 3
    backend.insert_nodes.assert_awaited_once_with(nodes)


def test_insert_document_rejects_zero_chunks(monkeypatch, tmp_path):
    metadata = _metadata(tmp_path)
    monkeypatch.setattr(
        document_in_database,
        "clean_document_str",
        AsyncMock(return_value=("parsed", tmp_path / "parsed.md")),
    )
    monkeypatch.setattr(
        document_in_database,
        "EnterpriseDocumentChunker",
        lambda **kwargs: type("Chunker", (), {"split_text": lambda self, text, metadata: []})(),
    )

    with pytest.raises(EmptyDocumentError):
        asyncio.run(document_in_database.insert_document(metadata, "milvus"))


def test_dual_write_partial_failure_exposes_backend_status(monkeypatch, tmp_path):
    metadata = _metadata(tmp_path)

    class Backend:
        def __init__(self, error=None):
            self.error = error

        async def insert_nodes(self, nodes):
            if self.error:
                raise self.error

    monkeypatch.setattr(
        document_in_database,
        "clean_document_str",
        AsyncMock(return_value=("parsed", tmp_path / "parsed.md")),
    )
    monkeypatch.setattr(
        document_in_database,
        "EnterpriseDocumentChunker",
        lambda **kwargs: type("Chunker", (), {"split_text": lambda self, text, metadata: [object()]})(),
    )
    monkeypatch.setattr(
        document_in_database,
        "get_milvus_store_pipeline_service",
        lambda: Backend(),
    )
    monkeypatch.setattr(
        document_in_database,
        "get_graph_store_pipeline_service",
        lambda: Backend(RuntimeError("neo4j down")),
    )

    with pytest.raises(DualWriteError) as caught:
        asyncio.run(document_in_database.insert_document(metadata, "mg"))

    assert caught.value.backend_status == {
        "milvus": {"status": "success", "error": None},
        "neo4j": {"status": "failed", "error": "neo4j down"},
    }
    assert metadata["backend_status"] == caught.value.backend_status
