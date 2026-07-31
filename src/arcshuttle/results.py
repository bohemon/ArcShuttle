"""Result-record construction and exit-status policy."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any


def summary_record(
    run_id: str,
    results: Iterable[dict[str, Any]],
    duration_ms: int,
    *,
    schema_version: int,
) -> dict[str, Any]:
    """Aggregate result statuses into the final JSON Lines summary."""

    records = list(results)
    counts = Counter(record["status"] for record in records)
    return {
        "schema_version": schema_version,
        "record_type": "summary",
        "run_id": run_id,
        "total": len(records),
        "success": counts["success"],
        "warning": counts["warning"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "interrupted": counts["interrupted"],
        "duration_ms": duration_ms,
    }


def result_exit_code(results: Iterable[dict[str, Any]]) -> int:
    """Map job statuses to the documented process exit codes."""

    records = list(results)
    statuses = {record["status"] for record in records}
    if "interrupted" in statuses:
        return 130
    if "failed" in statuses:
        return 2
    if statuses & {"warning", "skipped"} or any(record.get("warnings") for record in records):
        return 1
    return 0
