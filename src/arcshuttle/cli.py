"""Command-line interface and orchestration for ArcShuttle."""

from __future__ import annotations

import argparse
import sys
import threading
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from .config import Config, resolve_config
from .input import collect_paths, normalize_paths
from .manifest import PlanningResult, make_plan, validate_manifest
from .multipart import canonicalize
from .output import create_staging, finalize, resolve_existing, retain_failed
from .results import result_exit_code, summary_record
from .scheduler import ResourceScheduler, ScheduledJob, SchedulerEvent
from .sevenzip import ProcessOutcome, SevenZip, find_executable
from .util import UsageError, emit_jsonl, isoformat, read_json_lines, utc_now


class Parser(argparse.ArgumentParser):
    """Argument parser that maps usage failures to ArcShuttle exit code 64."""

    def error(self, message: str) -> None:
        raise UsageError(message)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--7z", dest="sevenzip", metavar="PATH", default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--existing", choices=("fail", "skip", "rename"), default=None)
    parser.add_argument("--cpu-budget", default=None, metavar="N|auto")
    parser.add_argument("--max-processes", type=int, default=None)
    parser.add_argument("--storage-profile", choices=("auto", "hdd", "ssd", "nvme"), default=None)
    parser.add_argument("--io-slots", type=int, default=None)
    parser.add_argument("--heavy-threads", type=int, default=None)
    parser.add_argument("--small-threshold", default=None, metavar="SIZE")
    parser.add_argument("--inspect-threshold", default=None, metavar="SIZE")
    parser.add_argument("--inspect-timeout", type=float, default=None, metavar="SECONDS")
    parser.add_argument("--reservation-delay", type=float, default=None, metavar="SECONDS")
    parser.add_argument("--sequential-if-total-below", default=None, metavar="SIZE")
    parser.add_argument("--log-dir", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true", default=None)
    parser.add_argument("--fail-fast", action="store_true", default=None)
    parser.add_argument("--allow-changed", action="store_true", default=None)
    parser.add_argument("--on-input-error", choices=("fail", "skip"), default=None)


def _add_input(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("paths", nargs="*", metavar="PATH")
    parser.add_argument("--files-from", metavar="FILE")
    parser.add_argument("--files0-from", metavar="FILE")


def build_parser(*, program_name: str = "arcshuttle") -> argparse.ArgumentParser:
    """Build the public CLI parser."""

    parser = Parser(
        prog=program_name,
        description="Resource-aware archive creation and extraction backed by 7-Zip",
    )
    parser.add_argument("--version", action="version", version=f"{program_name} 0.2.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="inspect inputs and emit a JSON Lines manifest")
    _add_common(plan)
    _add_input(plan)

    run = subparsers.add_parser("run", help="execute a complete JSON Lines manifest")
    _add_common(run)
    run.add_argument("--manifest", required=True, metavar="FILE")

    extract = subparsers.add_parser("extract", help="plan and run in one invocation")
    _add_common(extract)
    _add_input(extract)
    return parser


def _config_from_args(args: argparse.Namespace) -> Config:
    ignored = {"command", "paths", "files_from", "files0_from", "manifest", "config"}
    values = {key: value for key, value in vars(args).items() if key not in ignored}
    return resolve_config(values, config_path=args.config)


def _open_manifest(path: str) -> tuple[TextIO, bool]:
    if path == "-":
        return sys.stdin, False
    try:
        return Path(path).open("r", encoding="utf-8"), True
    except OSError as exc:
        raise UsageError(f"cannot read manifest {path}: {exc}") from exc


def _show_sevenzip(sevenzip: SevenZip, quiet: bool, program_name: str) -> None:
    if not quiet:
        print(
            f"{program_name}: 7-Zip: {sevenzip.executable} ({sevenzip.version()})",
            file=sys.stderr,
        )


def _plan(
    args: argparse.Namespace, config: Config, sevenzip: SevenZip
) -> tuple[PlanningResult, bool]:
    raw_paths = collect_paths(args.paths, files_from=args.files_from, files0_from=args.files0_from)
    if not raw_paths:
        result = PlanningResult([], ["input contains no paths"], [])
        return result, config.on_input_error == "skip"
    normalized, errors = normalize_paths(raw_paths)
    multipart, multipart_errors = canonicalize(normalized)
    result = make_plan(multipart, config, sevenzip.inspect)
    all_errors = [*errors, *multipart_errors, *result.errors]
    result.errors = all_errors
    if all_errors and config.on_input_error == "fail":
        return result, False
    return result, True


def _base_result(
    *,
    job: dict[str, Any],
    run_id: str,
    status: str,
    started_at: str,
    finished_at: str,
    duration_ms: int,
    exit_code: int | None,
    output_dir: Path,
    staging_dir: Path | None,
    log_path: Path | None,
    warnings: list[str],
) -> dict[str, Any]:
    schedule = job["scheduling"]
    return {
        "schema_version": 1,
        "record_type": "result",
        "run_id": run_id,
        "job_id": job["job_id"],
        "path": job["path"],
        "status": status,
        "exit_code": exit_code,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "assigned_cpu_tokens": schedule["cpu_tokens"],
        "assigned_threads": schedule["threads"],
        "output_dir": str(output_dir),
        "staging_dir": str(staging_dir) if staging_dir is not None else None,
        "log_path": str(log_path) if log_path is not None else None,
        "warnings": warnings,
    }


def _execute_job(
    scheduled: ScheduledJob[dict[str, Any]],
    stop_event: threading.Event,
    *,
    config: Config,
    sevenzip: SevenZip,
    run_id: str,
    log_root: Path,
    progress_lock: threading.Lock,
    program_name: str,
) -> dict[str, Any]:
    job = scheduled.payload
    started_dt = utc_now()
    started = isoformat(started_dt)
    start_clock = time.monotonic()
    desired = Path(job["output_dir"])
    final = desired
    staging: Path | None = None
    log_path = log_root / job["job_id"]
    warnings = list(job["warnings"])

    def finish(status: str, exit_code: int | None, *, error: str | None = None) -> dict[str, Any]:
        if error:
            warnings.append(error)
        finished = isoformat(utc_now())
        duration_ms = round((time.monotonic() - start_clock) * 1000)
        result = _base_result(
            job=job,
            run_id=run_id,
            status=status,
            started_at=started,
            finished_at=finished,
            duration_ms=duration_ms,
            exit_code=exit_code,
            output_dir=final,
            staging_dir=staging,
            log_path=log_path if log_path.exists() else None,
            warnings=warnings,
        )
        if not config.quiet:
            with progress_lock:
                print(
                    f"{program_name}: {status} {duration_ms / 1000:.2f}s {job['path']}",
                    file=sys.stderr,
                )
        return result

    if stop_event.is_set():
        return finish("interrupted", None, error="not started after interruption")
    if job["archive"].get("encrypted") is True:
        return finish("failed", None, error="encrypted archives are not supported in version 1")
    try:
        stat = Path(job["path"]).stat()
    except OSError as exc:
        return finish("failed", None, error=f"cannot stat source before extraction: {exc}")
    source = job["source"]
    if stat.st_size != source["size"] or stat.st_mtime_ns != source["mtime_ns"]:
        message = "source size or modification time changed after planning"
        if not config.allow_changed:
            return finish("failed", None, error=message)
        warnings.append(message + "; continuing because --allow-changed was supplied")
    try:
        final, skipped = resolve_existing(desired, config.existing)
    except FileExistsError as exc:
        return finish("failed", None, error=str(exc))
    if skipped:
        return finish("skipped", None, error="output already exists")
    try:
        staging = create_staging(final, job["job_id"])
    except OSError as exc:
        return finish("failed", None, error=f"cannot create staging directory: {exc}")

    outcome: ProcessOutcome = sevenzip.extract(
        archive=Path(job["path"]),
        staging=staging,
        threads=job["scheduling"]["threads"],
        log_directory=log_path,
        cpu_tokens=job["scheduling"]["cpu_tokens"],
        stop_event=stop_event,
    )
    if outcome.interrupted:
        try:
            staging = retain_failed(staging)
        except OSError as exc:
            warnings.append(str(exc))
        return finish("interrupted", outcome.exit_code, error=outcome.error)
    if outcome.error is not None or outcome.exit_code is None or outcome.exit_code >= 2:
        try:
            staging = retain_failed(staging)
        except OSError as exc:
            warnings.append(str(exc))
        return finish("failed", outcome.exit_code, error=outcome.error)
    if outcome.exit_code == 1:
        try:
            staging = retain_failed(staging)
        except OSError as exc:
            warnings.append(str(exc))
        return finish("warning", 1, error="7-Zip completed with warnings; partial output retained")

    if final.exists() and config.existing == "rename":
        final, _ = resolve_existing(final, "rename")
    try:
        finalize(staging, final)
        staging = None
    except OSError as exc:
        try:
            staging = retain_failed(staging)
        except OSError as retain_exc:
            warnings.append(str(retain_exc))
        return finish("failed", 0, error=f"cannot finalize output: {exc}")
    return finish("success", 0)


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

    def worker(job: ScheduledJob[dict[str, Any]], stop: threading.Event) -> dict[str, Any]:
        return _execute_job(
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
            value = _base_result(
                job=job,
                run_id=run_id,
                status="failed",
                started_at=now,
                finished_at=now,
                duration_ms=0,
                exit_code=None,
                output_dir=Path(job["output_dir"]),
                staging_dir=None,
                log_path=None,
                warnings=[*job["warnings"], f"worker failed: {value}"],
            )
        results.append(value)

    for scheduled in scheduled_jobs:
        if scheduled.job_id in completed_ids:
            continue
        job = scheduled.payload
        now = isoformat(utc_now())
        interrupted = report.interrupted
        status = "interrupted" if interrupted else "skipped"
        reason = (
            "not started after interruption" if interrupted else "not started due to --fail-fast"
        )
        results.append(
            _base_result(
                job=job,
                run_id=run_id,
                status=status,
                started_at=now,
                finished_at=now,
                duration_ms=0,
                exit_code=None,
                output_dir=Path(job["output_dir"]),
                staging_dir=None,
                log_path=None,
                warnings=[*job["warnings"], reason],
            )
        )

    duration_ms = round((time.monotonic() - run_started) * 1000)
    summary = summary_record(run_id, results, duration_ms)
    return results, summary, result_exit_code(results)


def _run_command(
    args: argparse.Namespace, config: Config, sevenzip: SevenZip, program_name: str
) -> int:
    stream, should_close = _open_manifest(args.manifest)
    try:
        records = read_json_lines(stream, args.manifest)
    finally:
        if should_close:
            stream.close()
    jobs = validate_manifest(records, config)
    results, summary, exit_code = execute_manifest(
        jobs, config, sevenzip, program_name=program_name
    )
    for record in results:
        emit_jsonl(record)
    emit_jsonl(summary)
    return exit_code


def _report_plan_diagnostics(result: PlanningResult, program_name: str) -> None:
    for warning in result.warnings:
        print(f"{program_name}: warning: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"{program_name}: input error: {error}", file=sys.stderr)


def main(argv: Sequence[str] | None = None, *, program_name: str = "arcshuttle") -> int:
    """Run the CLI and return the documented process exit code."""

    try:
        args = build_parser(program_name=program_name).parse_args(argv)
        config = _config_from_args(args)
        sevenzip = SevenZip(find_executable(config.sevenzip))
        _show_sevenzip(sevenzip, config.quiet, program_name)
        if args.command == "run":
            return _run_command(args, config, sevenzip, program_name)

        planning, usable = _plan(args, config, sevenzip)
        _report_plan_diagnostics(planning, program_name)
        if not usable:
            return 64
        if args.command == "plan":
            for job in planning.jobs:
                emit_jsonl(job)
            return 1 if planning.errors or planning.warnings else 0

        jobs = validate_manifest(planning.jobs, config) if planning.jobs else []
        if not jobs:
            return 1 if planning.errors else 64
        results, summary, exit_code = execute_manifest(
            jobs, config, sevenzip, program_name=program_name
        )
        for record in results:
            emit_jsonl(record)
        emit_jsonl(summary)
        if planning.errors and exit_code == 0:
            return 1
        return exit_code
    except UsageError as exc:
        print(f"{program_name}: error: {exc}", file=sys.stderr)
        return 64
    except KeyboardInterrupt:
        print(f"{program_name}: interrupted", file=sys.stderr)
        return 130
