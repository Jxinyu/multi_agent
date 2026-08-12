from __future__ import annotations

from typing import Any


class RAGDataError(RuntimeError):
    """RAG 数据链路基础异常。"""


class EmptyDocumentError(RAGDataError):
    """文档解析后没有可入库内容。"""


class RetrievalAuthorizationError(RAGDataError):
    """检索请求缺少强制授权上下文。"""


class RetrievalTimeoutError(RAGDataError):
    """检索后端或重排超过配置时限。"""


class BackendOperationError(RAGDataError):
    operation = "backend_operation"

    def __init__(self, backend_status: dict[str, dict[str, Any]]):
        self.backend_status = backend_status
        summary = ", ".join(
            f"{backend}={status.get('status')}"
            for backend, status in backend_status.items()
        )
        super().__init__(f"{self.operation} failed: {summary}")


class DualWriteError(BackendOperationError):
    operation = "dual_write"


class BackendDeleteError(BackendOperationError):
    operation = "backend_delete"
