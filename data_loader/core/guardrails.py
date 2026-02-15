from __future__ import annotations

import os
import re
from dataclasses import dataclass


BANNED_SQL_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy)\b",
    flags=re.IGNORECASE,
)


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _to_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except Exception:
        return default


def _to_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {x.strip().lower() for x in value.split(",") if x.strip()}


@dataclass
class Guardrails:
    max_query_rows: int
    max_query_seconds: int
    allow_only_select: bool
    allowed_src_hosts: set[str]
    allowed_dst_hosts: set[str]
    allowed_src_dbs: set[str]
    allowed_dst_dbs: set[str]


@dataclass
class RoleLimits:
    max_rows: int | None
    max_seconds: int | None


def load_guardrails() -> Guardrails:
    return Guardrails(
        max_query_rows=_to_int(os.getenv("DL_MAX_QUERY_ROWS"), 5_000_000),
        max_query_seconds=_to_int(os.getenv("DL_MAX_QUERY_SECONDS"), 1_800),
        allow_only_select=_to_bool(os.getenv("DL_QUERY_ALLOW_ONLY_SELECT"), True),
        allowed_src_hosts=_to_set(os.getenv("DL_ALLOWED_SOURCE_HOSTS")),
        allowed_dst_hosts=_to_set(os.getenv("DL_ALLOWED_DEST_HOSTS")),
        allowed_src_dbs=_to_set(os.getenv("DL_ALLOWED_SOURCE_DBS")),
        allowed_dst_dbs=_to_set(os.getenv("DL_ALLOWED_DEST_DBS")),
    )


def role_limits(role: str) -> RoleLimits:
    if role == "admin":
        return RoleLimits(max_rows=None, max_seconds=None)
    # loader defaults
    return RoleLimits(max_rows=50_000_000, max_seconds=10_800)


def enforce_allowlist(name: str, value: str, allowlist: set[str]) -> None:
    if not allowlist:
        return
    if (value or "").strip().lower() not in allowlist:
        raise ValueError(f"{name} is not in allowlist: {value}")


def validate_sql(sql: str, allow_only_select: bool) -> str:
    cleaned = (sql or "").strip()
    if not cleaned:
        raise ValueError("SQL is empty.")

    if ";" in cleaned[:-1]:
        raise ValueError("Only one SQL statement is allowed.")

    if allow_only_select:
        first = cleaned.split(None, 1)[0].lower() if cleaned.split() else ""
        if first not in {"select", "with"}:
            raise ValueError("Only SELECT/WITH queries are allowed.")

    if BANNED_SQL_RE.search(cleaned):
        raise ValueError("SQL contains blocked keywords.")

    return cleaned.rstrip(";")


def validate_cap(limit_rows: int, max_rows: int) -> int:
    if limit_rows < 0:
        raise ValueError("Row limit must be >= 0.")
    if limit_rows > max_rows:
        raise ValueError(f"Row limit exceeds guardrail ({max_rows}).")
    return limit_rows


def require_clear_confirm(clear_before: bool, table: str, confirm_text: str) -> None:
    if not clear_before:
        return
    if not table:
        raise ValueError("Destination table is required for clear_before.")
    if (confirm_text or "").strip() != table:
        raise ValueError("Clear confirmation mismatch. Type destination table name exactly.")
