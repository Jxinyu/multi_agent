from __future__ import annotations

import contextvars
import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime

from fastapi import Request
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

HTTP_REQUESTS = Counter(
    "rag_upper_http_requests_total",
    "HTTP 请求数量",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "rag_upper_http_request_duration_seconds",
    "HTTP 请求耗时",
    ["method", "route"],
)
INGESTION_JOBS = Counter(
    "rag_upper_ingestion_jobs_total",
    "文档任务处理数量",
    ["operation", "status"],
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def configure_tracing() -> None:
    if not settings.runtime.otel_endpoint:
        return
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: settings.runtime.service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.runtime.otel_endpoint))
    )
    trace.set_tracer_provider(provider)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request_id = supplied_request_id if REQUEST_ID_PATTERN.fullmatch(supplied_request_id) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        tracer = trace.get_tracer(settings.runtime.service_name)
        with tracer.start_as_current_span(f"{request.method} {request.url.path}") as span:
            span.set_attribute("http.request.method", request.method)
            span.set_attribute("http.request_id", request_id)
            try:
                response = await call_next(request)
                status_code = response.status_code
                response.headers["X-Request-ID"] = request_id
                return response
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                route = request.scope.get("route")
                route_path = getattr(route, "path", request.url.path)
                span.set_attribute("http.route", route_path)
                span.set_attribute("http.response.status_code", status_code)
                HTTP_REQUESTS.labels(request.method, route_path, str(status_code)).inc()
                HTTP_LATENCY.labels(request.method, route_path).observe(time.perf_counter() - started)
                request_id_var.reset(token)
