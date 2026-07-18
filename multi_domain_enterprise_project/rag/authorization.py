from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from multi_domain_enterprise_project.rag.exceptions import RetrievalAuthorizationError

_AUTH_FILTER_KEYS = {"tenant_id", "user_id", "owner_id", "acl", "acl_list"}


def normalize_acl(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values: Iterable[Any] = re.split(r"[|,\s]+", value)
    elif isinstance(value, Iterable):
        values = value
    else:
        values = (value,)
    return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


@dataclass(frozen=True)
class RetrievalAuthorization:
    tenant_id: str
    user_id: str
    acl: tuple[str, ...]

    @classmethod
    def from_filters(cls, filters: dict[str, Any] | None) -> RetrievalAuthorization:
        values = filters or {}
        tenant_id = str(values.get("tenant_id") or "").strip()
        user_id = str(values.get("user_id") or values.get("owner_id") or "").strip()
        if not tenant_id or not user_id:
            raise RetrievalAuthorizationError("检索必须提供 tenant_id 和 user_id")
        return cls(
            tenant_id=tenant_id,
            user_id=user_id,
            acl=normalize_acl(values.get("acl", values.get("acl_list"))),
        )

    @property
    def shared_acl(self) -> tuple[str, ...]:
        return tuple(item for item in self.acl if item.lower() != "private")


def build_authorized_filter_branches(
    filters: dict[str, Any] | None,
) -> tuple[RetrievalAuthorization, list[Any]]:
    """构建 tenant AND (owner OR ACL) 的两个后端过滤分支。"""
    from llama_index.core.vector_stores import (
        FilterCondition,
        FilterOperator,
        MetadataFilter,
        MetadataFilters,
    )

    scope = RetrievalAuthorization.from_filters(filters)
    extra_filters = []
    for key, value in (filters or {}).items():
        if key in _AUTH_FILTER_KEYS or value is None:
            continue
        operator = FilterOperator.IN if isinstance(value, (list, tuple, set)) else FilterOperator.EQ
        extra_filters.append(MetadataFilter(key=str(key), value=value, operator=operator))

    tenant_filter = MetadataFilter(
        key="tenant_id", value=scope.tenant_id, operator=FilterOperator.EQ
    )
    owner_branch = MetadataFilters(
        filters=[
            tenant_filter,
            MetadataFilter(key="owner_id", value=scope.user_id, operator=FilterOperator.EQ),
            *extra_filters,
        ],
        condition=FilterCondition.AND,
    )
    branches = [owner_branch]
    if scope.shared_acl:
        branches.append(
            MetadataFilters(
                filters=[
                    tenant_filter,
                    MetadataFilter(
                        key="acl", value=list(scope.shared_acl), operator=FilterOperator.IN
                    ),
                    *extra_filters,
                ],
                condition=FilterCondition.AND,
            )
        )
    return scope, branches


def _node_metadata(item: Any) -> dict[str, Any]:
    node = getattr(item, "node", item)
    metadata = getattr(node, "metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def is_metadata_authorized(metadata: dict[str, Any], scope: RetrievalAuthorization) -> bool:
    if str(metadata.get("tenant_id") or "") != scope.tenant_id:
        return False
    if str(metadata.get("owner_id") or "") == scope.user_id:
        return True
    document_acl = {
        item for item in normalize_acl(metadata.get("acl")) if item.lower() != "private"
    }
    return bool(document_acl.intersection(scope.shared_acl))


def filter_authorized_nodes(nodes: Sequence[Any], scope: RetrievalAuthorization) -> list[Any]:
    return [item for item in nodes if is_metadata_authorized(_node_metadata(item), scope)]
