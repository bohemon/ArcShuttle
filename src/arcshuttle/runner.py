"""Shared resource-constrained manifest execution."""

from __future__ import annotations

import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .config import Config
from .operations.create import execute_job as execute_create_job
from .operations.extract import execute_job as execute_extract_job
from .results import job_result, result_exit_code, summary_record
from .scheduler import ResourceScheduler, ScheduledJob, SchedulerEvent
from .sevenzip import SevenZip
from .util import isoformat, utc_now


def execute_manifest(
    jobs: list[dict[str, Any]],
    config: Config,
    sevenzip: SevenZip,
    *,
    program_name: str = "arcshuttle",
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    """Execute validated jobs and return result records, summary, and exit code."""

    run_id = utc_now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_started = time.monotonic()
    log_base = config.log_dir or (Path.cwd() / ".arcshuttle" / "logs")
    log_root = log_base / run_id
    progress_lock = threading.Lock()
    max_processes = config.max_processes
    io_slots = config.io_slots
    if config.sequential_if_total_below > 0:
        total_size = sum(job["source"]["size"] for job in jobs)
        if total_size <= config.sequential_if_total_below:
            max_processes = 1
            io_slots = 1

    scheduled_jobs = [
        ScheduledJob(
            job_id=job["job_id"],
            payload=job,
            profile=job["scheduling"]["profile"],
            priority=job["scheduling"]["priority"],
            estimated_weight=job["scheduling"]["estimated_weight"],
            plan_index=job["plan_index"],
            cpu_tokens=job["scheduling"]["cpu_tokens"],
            io_tokens=job["scheduling"]["io_tokens"],
        )
        for job in jobs
    ]
    started_count = 0

    def on_event(event: SchedulerEvent) -> None:
        nonlocal started_count
        if event.kind == "started":
            started_count += 1
            if not config.quiet:
                with progress_lock:
                    print(
                        f"[{started_count}/{len(jobs)}] running={event.running} "
                        f"cpu={event.used_cpu}/{config.cpu_budget} io={event.used_io}/{io_slots} "
                        f"started {event.job_id}",
                        file=sys.stderr,
                    )

    scheduler: ResourceScheduler[dict[str, Any], dict[str, Any]] = ResourceScheduler(
        cpu_budget=config.cpu_budget,
        max_processes=max_processes,
        io_slots=io_slots,
        reservation_delay=config.reservation_delay,
        on_event=on_event,
    )
    executors = {"extract": execute_extract_job, "create": execute_create_job}

    def worker(job: ScheduledJob[dict[str, Any]], stop: threading.Event) -> dict[str, Any]:
        executor = executors[job.payload["operation"]]
        return executor(
            job,
            stop,
            config=config,
            sevenzip=sevenzip,
            run_id=run_id,
            log_root=log_root,
            progress_lock=progress_lock,
            program_name=program_name,
        )

    report = scheduler.run(
        scheduled_jobs,
        worker,
        fail_fast_predicate=(
            (lambda value: isinstance(value, BaseException) or value.get("status") == "failed")
            if config.fail_fast
            else None
        ),
        interrupt=sevenzip.interrupt_all,
    )
    results: list[dict[str, Any]] = []
    completed_ids: set[str] = set()
    for scheduled, value in report.results:
        completed_ids.add(scheduled.job_id)
        if isinstance(value, BaseException):
            job = scheduled.payload
            now = isoformat(utc_now())
            value = job_result(
                job=job,
                run_id=run_id,
                status="failed",
                started_at=now,
                finished_at=now,
                duration_ms=0,
                exit_code=None,
                output_path=job["destination"]["path"],
                staging_path=None,
                log_path=None,
                warnings=[*job["warnings"], f"worker failed: {value}"],
            )
        results.append(value)

    for scheduled in scheduled_jobs:
        if scheduled.job_id in completed_ids:
            continue
        job = scheduled.payload
        now = isoformat(utc_now())
        status = "interrupted" if report.interrupted else "skipped"
        reason = (
            "not started after interruption"
            if report.interrupted
            else "not started due to --fail-fast"
        )
        results.append(
            job_result(
                job=job,
                run_id=run_id,
                status=status,
                started_at=now,
                finished_at=now,
                duration_ms=0,
                exit_code=None,
                output_path=job["destination"]["path"],
                staging_path=None,
                log_path=None,
                warnings=[*job["warnings"], reason],
            )
        )

    if any(job.get("_input_schema_version") != 1 for job in jobs):
        manifest_order = {
            job["job_id"]: (job["plan_index"], index) for index, job in enumerate(jobs)
        }
        results.sort(key=lambda result: manifest_order[result["job_id"]])

    duration_ms = round((time.monotonic() - run_started) * 1000)
    schema_version = 1 if all(job.get("_input_schema_version") == 1 for job in jobs) else 2
    summary = summary_record(run_id, results, duration_ms, schema_version=schema_version)
    return results, summary, result_exit_code(results)
