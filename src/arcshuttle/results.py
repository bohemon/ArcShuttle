"""Result-record construction and exit-status policy."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any


def job_result(
    *,
    job: dict[str, Any],
    run_id: str,
    status: str,
    started_at: str,
    finished_at: str,
    duration_ms: int,
    exit_code: int | None,
    output_path: str,
    staging_path: str | None,
    log_path: str | None,
    warnings: list[str],
    create_exit_code: int | None = None,
    verification_exit_code: int | None = None,
) -> dict[str, Any]:
    """Build a schema-compatible result record for one normalized job."""

    schedule = job["scheduling"]
    schema_version = job.get("_input_schema_version", 2)
    result = {
        "schema_version": schema_version,
        "record_type": "result",
        "run_id": run_id,
        "job_id": job["job_id"],
        "path": job["source"]["path"],
        "status": status,
        "exit_code": exit_code,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "assigned_cpu_tokens": schedule["cpu_tokens"],
        "assigned_threads": schedule["threads"],
        "output_dir": output_path,
        "staging_dir": staging_path,
        "log_path": log_path,
        "warnings": warnings,
    }
    if schema_version == 2:
        result["operation"] = job["operation"]
        result["output_path"] = output_path
        result["staging_path"] = staging_path
        if job["operation"] == "create":
            result["create_exit_code"] = create_exit_code
            result["verification_exit_code"] = verification_exit_code
    return result


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
