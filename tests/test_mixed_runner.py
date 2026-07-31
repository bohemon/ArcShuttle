from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from arcshuttle import cli, runner
from arcshuttle.config import Config
from arcshuttle.manifest import (
    calculate_integrity,
    deterministic_job_id,
    source_identity,
    validate_manifest,
)
from arcshuttle.multipart import MultipartInfo
from arcshuttle.operations.extract import make_legacy_plan
from arcshuttle.results import job_result
from arcshuttle.scheduler import ScheduledJob, ScheduleReport


class DummySevenZip:
    executable = Path("fake-7z")

    def __init__(self) -> None:
        self.interrupt_calls = 0

    def version(self) -> str:
        return "fake"

    def interrupt_all(self) -> None:
        self.interrupt_calls += 1


def mixed_config(root: Path, **changes: object) -> Config:
    config = replace(
        Config(),
        log_dir=root / "logs",
        cpu_budget=3,
        max_processes=2,
        io_slots=2,
        quiet=True,
        reservation_delay=0,
    )
    return replace(config, **changes)


def v2_job(
    root: Path,
    operation: str,
    plan_index: int,
    *,
    cpu_tokens: int,
    priority: int = 0,
) -> dict[str, Any]:
    source = root / f"{operation}-{plan_index}.src"
    source.write_bytes(f"unchanged-{operation}-{plan_index}".encode())
    metadata = source.stat()
    identity = source_identity(
        kind="file", size=metadata.st_size, mtime_ns=metadata.st_mtime_ns, entry_count=1
    )
    destination = root / (
        f"extract-{plan_index}" if operation == "extract" else f"create-{plan_index}.7z"
    )
    job: dict[str, Any] = {
        "schema_version": 2,
        "record_type": "job",
        "operation": operation,
        "job_id": deterministic_job_id(operation, source, identity),
        "plan_index": plan_index,
        "source": {
            "path": str(source),
            "kind": "file",
            "size": metadata.st_size,
            "mtime_ns": metadata.st_mtime_ns,
            "entry_count": 1,
            "identity": identity,
        },
        "destination": {
            "path": str(destination),
            "kind": "directory" if operation == "extract" else "archive",
        },
        "archive": (
            {"format": "zip", "encrypted": False}
            if operation == "extract"
            else {"format": "7z", "method": "LZMA2", "compression_level": 5}
        ),
        "scheduling": {
            "profile": "heavy-scalable" if cpu_tokens > 1 else "small",
            "profile_source": "auto",
            "classification_reason": "mixed-runner-test",
            "priority": priority,
            "estimated_weight": metadata.st_size,
            "cpu_tokens": cpu_tokens,
            "threads": cpu_tokens,
            "io_tokens": 1,
        },
        "tags": [],
        "warnings": [],
    }
    job["integrity"] = calculate_integrity(job)
    return job


class ResourceTracker:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = 0
        self.cpu = 0
        self.io = 0
        self.max_running = 0
        self.max_cpu = 0
        self.max_io = 0
        self.operations: list[str] = []

    def worker(
        self,
        scheduled: ScheduledJob[dict[str, Any]],
        stop_event: threading.Event,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del stop_event, kwargs
        with self.lock:
            self.running += 1
            self.cpu += scheduled.cpu_tokens
            self.io += scheduled.io_tokens
            self.max_running = max(self.max_running, self.running)
            self.max_cpu = max(self.max_cpu, self.cpu)
            self.max_io = max(self.max_io, self.io)
            self.operations.append(scheduled.payload["operation"])
        time.sleep(0.02 * (4 - min(scheduled.plan_index, 3)))
        with self.lock:
            self.running -= 1
            self.cpu -= scheduled.cpu_tokens
            self.io -= scheduled.io_tokens
        job = scheduled.payload
        return job_result(
            job=job,
            run_id="test-run",
            status="success",
            started_at="2026-01-01T00:00:00.000Z",
            finished_at="2026-01-01T00:00:00.001Z",
            duration_ms=1,
            exit_code=0,
            output_path=job["destination"]["path"],
            staging_path=None,
            log_path=None,
            warnings=[],
            create_exit_code=0 if job["operation"] == "create" else None,
            verification_exit_code=0 if job["operation"] == "create" else None,
        )


def patch_executors(monkeypatch: pytest.MonkeyPatch, tracker: ResourceTracker) -> None:
    monkeypatch.setattr(runner, "execute_extract_job", tracker.worker)
    monkeypatch.setattr(runner, "execute_create_job", tracker.worker)


def test_mixed_jobs_share_budgets_and_v2_results_are_in_plan_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = mixed_config(tmp_path)
    raw_jobs = [
        v2_job(tmp_path, "create", 3, cpu_tokens=2),
        v2_job(tmp_path, "extract", 0, cpu_tokens=1),
        v2_job(tmp_path, "create", 2, cpu_tokens=2),
        v2_job(tmp_path, "extract", 1, cpu_tokens=1),
    ]
    original_sources = {
        job["source"]["path"]: Path(job["source"]["path"]).read_bytes() for job in raw_jobs
    }
    jobs = validate_manifest(raw_jobs, config)
    tracker = ResourceTracker()
    patch_executors(monkeypatch, tracker)

    results, summary, code = runner.execute_manifest(jobs, config, DummySevenZip())

    assert code == 0
    assert summary["total"] == summary["success"] == 4
    assert (tracker.max_cpu, tracker.max_running, tracker.max_io) == (3, 2, 2)
    assert set(tracker.operations) == {"extract", "create"}
    assert [result["job_id"] for result in results] == [
        job["job_id"] for job in sorted(jobs, key=lambda job: job["plan_index"])
    ]
    for result in results:
        assert result["output_path"] == result["output_dir"]
        assert result["staging_path"] == result["staging_dir"]
        if result["operation"] == "create":
            assert result["create_exit_code"] == result["verification_exit_code"] == 0
    assert {path: Path(path).read_bytes() for path in original_sources} == original_sources


def test_sequential_threshold_applies_to_mixed_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = mixed_config(tmp_path, sequential_if_total_below=1_000_000)
    jobs = validate_manifest(
        [
            v2_job(tmp_path, "create", 0, cpu_tokens=2),
            v2_job(tmp_path, "extract", 1, cpu_tokens=1),
        ],
        config,
    )
    tracker = ResourceTracker()
    patch_executors(monkeypatch, tracker)

    runner.execute_manifest(jobs, config, DummySevenZip())

    assert tracker.max_running == tracker.max_io == 1


def test_mixed_fail_fast_marks_later_operation_unstarted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = mixed_config(tmp_path, fail_fast=True, cpu_budget=1, max_processes=1, io_slots=1)
    jobs = validate_manifest(
        [
            v2_job(tmp_path, "create", 0, cpu_tokens=1, priority=10),
            v2_job(tmp_path, "extract", 1, cpu_tokens=1),
        ],
        config,
    )
    calls: list[str] = []

    def fail_create(
        scheduled: ScheduledJob[dict[str, Any]], stop_event: threading.Event, **kwargs: Any
    ) -> dict[str, Any]:
        del stop_event, kwargs
        calls.append(scheduled.payload["operation"])
        job = scheduled.payload
        return job_result(
            job=job,
            run_id="test",
            status="failed",
            started_at="now",
            finished_at="now",
            duration_ms=0,
            exit_code=2,
            output_path=job["destination"]["path"],
            staging_path=None,
            log_path=None,
            warnings=["expected failure"],
        )

    monkeypatch.setattr(runner, "execute_create_job", fail_create)
    monkeypatch.setattr(
        runner,
        "execute_extract_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not start")),
    )

    results, summary, code = runner.execute_manifest(jobs, config, DummySevenZip())

    assert calls == ["create"]
    assert [result["status"] for result in results] == ["failed", "skipped"]
    assert (summary["failed"], summary["skipped"], code) == (1, 1, 2)
    assert results[1]["operation"] == "extract"


def test_runner_interruption_marks_all_unstarted_mixed_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = mixed_config(tmp_path)
    jobs = validate_manifest(
        [
            v2_job(tmp_path, "create", 0, cpu_tokens=1),
            v2_job(tmp_path, "extract", 1, cpu_tokens=1),
        ],
        config,
    )
    backend = DummySevenZip()

    class InterruptedScheduler:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def run(
            self, jobs: object, worker: object, **kwargs: Any
        ) -> ScheduleReport[dict[str, Any]]:
            del jobs, worker
            kwargs["interrupt"]()
            return ScheduleReport(interrupted=True)

    monkeypatch.setattr(runner, "ResourceScheduler", InterruptedScheduler)

    results, summary, code = runner.execute_manifest(jobs, config, backend)

    assert backend.interrupt_calls == 1
    assert [result["status"] for result in results] == ["interrupted", "interrupted"]
    assert (summary["interrupted"], code) == (2, 130)


def test_legacy_v1_result_shape_remains_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "legacy.zip"
    archive.write_bytes(b"archive")
    config = mixed_config(tmp_path, inspect_threshold=1_000, small_threshold=1_000)
    raw = make_legacy_plan(
        [MultipartInfo(archive, False)],
        config,
        lambda path, timeout: (_ for _ in ()).throw(AssertionError("unexpected inspection")),
    ).jobs
    jobs = validate_manifest(raw, config)
    tracker = ResourceTracker()
    patch_executors(monkeypatch, tracker)

    results, summary, code = runner.execute_manifest(jobs, config, DummySevenZip())

    assert (code, summary["schema_version"], results[0]["schema_version"]) == (0, 1, 1)
    assert "operation" not in results[0]
    assert "output_path" not in results[0]
    assert "staging_path" not in results[0]


def test_cli_run_emits_ordered_mixed_json_lines_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    raw_jobs = [
        v2_job(tmp_path, "create", 1, cpu_tokens=1),
        v2_job(tmp_path, "extract", 0, cpu_tokens=1),
    ]
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "".join(json.dumps(job, separators=(",", ":")) + "\n" for job in raw_jobs),
        encoding="utf-8",
    )
    tracker = ResourceTracker()
    patch_executors(monkeypatch, tracker)
    backend = DummySevenZip()
    monkeypatch.setattr(cli, "find_executable", lambda configured: Path("fake"))
    monkeypatch.setattr(cli, "SevenZip", lambda executable: backend)

    code = cli.main(["run", "--manifest", str(manifest), "--quiet"])
    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.splitlines()]

    assert code == 0
    assert captured.err == ""
    assert [record["record_type"] for record in records] == ["result", "result", "summary"]
    assert [record["operation"] for record in records[:-1]] == ["extract", "create"]
