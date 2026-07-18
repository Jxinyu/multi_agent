from types import SimpleNamespace

import pytest

from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError
from multi_domain_enterprise_project.rag.documentParser.llamaparser import EnterpriseDocParser


def test_cloud_parser_prefers_full_markdown() -> None:
    result = SimpleNamespace(markdown_full="  # 标题\n正文  ", markdown=None)

    assert EnterpriseDocParser._markdown_from_result(result) == "# 标题\n正文"


def test_cloud_parser_joins_successful_pages() -> None:
    result = SimpleNamespace(
        markdown_full=None,
        markdown=SimpleNamespace(
            pages=[
                SimpleNamespace(success=True, page_number=1, markdown="第一页"),
                SimpleNamespace(success=True, page_number=2, markdown="第二页"),
            ]
        ),
    )

    assert EnterpriseDocParser._markdown_from_result(result) == "第一页\n\n第二页"


def test_cloud_parser_rejects_failed_pages() -> None:
    result = SimpleNamespace(
        markdown_full=None,
        markdown=SimpleNamespace(
            pages=[
                SimpleNamespace(success=True, page_number=1, markdown="第一页"),
                SimpleNamespace(success=False, page_number=2, markdown=""),
            ]
        ),
    )

    with pytest.raises(DocumentParsingError, match="2"):
        EnterpriseDocParser._markdown_from_result(result)
