from __future__ import annotations

from pathlib import Path

import pytest

from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError
from multi_domain_enterprise_project.rag.documentParser.parser_route import DocumentParserRouter


class FailingLocalParser:
    async def parse_file(self, _file_path: str) -> str:
        raise RuntimeError("local parser failed")


class RecordingCloudParser:
    def __init__(self) -> None:
        self.calls = 0

    async def parse_file(self, _file_path: str) -> str:
        self.calls += 1
        return "cloud result"


@pytest.mark.asyncio
async def test_parser_failure_does_not_silently_fallback_to_cloud(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = tmp_path / "sample.pdf"
    document.write_bytes(b"%PDF-placeholder")
    router = DocumentParserRouter(mode="auto")
    cloud = RecordingCloudParser()
    router._pymupdf_parser = FailingLocalParser()
    router._llama_parser = cloud
    monkeypatch.setattr(router, "_probe_pdf", lambda _path: "simple")

    with pytest.raises(DocumentParsingError, match="路由解析任务中断") as exc_info:
        await router.route_and_parse(str(document))
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "local parser failed"
    assert cloud.calls == 0
