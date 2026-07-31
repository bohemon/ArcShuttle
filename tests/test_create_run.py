from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from arcshuttle.config import Config
from arcshuttle.manifest import validate_manifest
from arcshuttle.operations.create import make_create_plan
from arcshuttle.runner import execute_manifest
from arcshuttle.sevenzip import ProcessOutcome
from arcshuttle.staging import finalize_archive


class StubCreateSevenZip:
    def __init__(
        self,
        create_outcome: ProcessOutcome | None = None,
        test_outcome: ProcessOutcome | None = None,
        *,
        write_archive: bool = True,
        remove_marker: bool = False,
    ) -> None:
        self.create_outcome = create_outcome or ProcessOutcome(0, False)
        self.test_outcome = test_outcome or ProcessOutcome(0, False)
        self.write_archive = write_archive
        self.remove_marker = remove_marker
        self.create_calls: list[dict[str, Any]] = []
        self.test_calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> ProcessOutcome:
        self.create_calls.append(kwargs)
        archive = kwargs["archive"]
        log_directory = kwargs["log_directory"]
        log_directory.mkdir(parents=True, exist_ok=True)
        (log_directory / "create.stdout.log").write_text("create", encoding="utf-8")
        (log_directory / "create.stderr.log").write_text("", encoding="utf-8")
        if self.write_archive:
            archive.write_bytes(b"archive")
        if self.remove_marker:
            (archive.parent / ".arcshuttle-owned").unlink()
        return self.create_outcome

    def test(self, **kwargs: Any) -> ProcessOutcome:
        self.test_calls.append(kwargs)
        log_directory = kwargs["log_directory"]
        (log_directory / "test.stdout.log").write_text("test", encoding="utf-8")
        (log_directory / "test.stderr.log").write_text("", encoding="utf-8")
        return self.test_outcome

    def interrupt_all(self) -> None:
        pass


def base_config(root: Path, **changes: object) -> Config:
    config = replace(
        Config(),
        output_dir=root / "outputs",
        log_dir=root / "logs",
        small_threshold=0,
        cpu_budget=2,
        max_processes=1,
        io_slots=1,
        heavy_threads=2,
        quiet=True,
    )
    return replace(config, **changes)


def create_job(
    root: Path, config: Config, *, directory: bool = False
) -> tuple[Path, dict[str, Any]]:
    source = root / ("source" if directory else "source.dat")
    if directory:
        (source / "nested" / "empty").mkdir(parents=True)
        (source / "nested" / "data.txt").write_text("data", encoding="utf-8")
    else:
        source.write_bytes(b"source")
    planning = make_create_plan([source], config)
    assert planning.errors == []
    return source, validate_manifest(planning.jobs, config)[0]


def test_success_verifies_then_commits_and_preserves_source(tmp_path: Path) -> None:
    config = base_config(tmp_path)
    source, job = create_job(tmp_path, config, directory=True)
    runner = StubCreateSevenZip()

    results, summary, code = execute_manifest([job], config, runner)

    result = results[0]
    assert (code, result["status"], summary["success"]) == (0, "success", 1)
    assert result["create_exit_code"] == result["test_exit_code"] == 0
    assert Path(result["output_dir"]).read_bytes() == b"archive"
    assert result["staging_dir"] is None
    assert (source / "nested" / "empty").is_dir()
    assert (source / "nested" / "data.txt").read_text(encoding="utf-8") == "data"
    assert len(runner.create_calls) == len(runner.test_calls) == 1
    assert runner.create_calls[0]["threads"] == 2


@pytest.mark.parametrize(
    ("outcome", "status", "code"),
    [
        (ProcessOutcome(1, False), "warning", 1),
        (ProcessOutcome(2, False), "failed", 2),
        (ProcessOutcome(None, True, "stopped"), "interrupted", 130),
    ],
)
def test_create_warning_failure_and_interrupt_retain_staging(
    tmp_path: Path, outcome: ProcessOutcome, status: str, code: int
) -> None:
    config = base_config(tmp_path)
    _, job = create_job(tmp_path, config)
    runner = StubCreateSevenZip(create_outcome=outcome)

    results, _, actual_code = execute_manifest([job], config, runner)

    result = results[0]
    assert (actual_code, result["status"], result["create_exit_code"]) == (
        code,
        status,
        outcome.exit_code,
    )
    assert Path(result["staging_dir"]).name.endswith(".failed")
    assert not Path(result["output_dir"]).exists()
    assert runner.test_calls == []


@pytest.mark.parametrize(
    ("outcome", "status", "code"),
    [
        (ProcessOutcome(1, False), "warning", 1),
        (ProcessOutcome(2, False), "failed", 2),
        (ProcessOutcome(None, True, "stopped"), "interrupted", 130),
    ],
)
def test_verification_warning_failure_and_interrupt_retain_staging(
    tmp_path: Path, outcome: ProcessOutcome, status: str, code: int
) -> None:
    config = base_config(tmp_path)
    _, job = create_job(tmp_path, config)
    runner = StubCreateSevenZip(test_outcome=outcome)

    results, _, actual_code = execute_manifest([job], config, runner)

    result = results[0]
    assert (actual_code, result["status"], result["test_exit_code"]) == (
        code,
        status,
        outcome.exit_code,
    )
    assert result["create_exit_code"] == 0
    assert Path(result["staging_dir"]).name.endswith(".failed")
    assert not Path(result["output_dir"]).exists()


def test_reported_success_without_archive_is_a_failure(tmp_path: Path) -> None:
    config = base_config(tmp_path)
    _, job = create_job(tmp_path, config)

    results, _, code = execute_manifest([job], config, StubCreateSevenZip(write_archive=False))

    assert (code, results[0]["status"]) == (2, "failed")
    assert "did not create" in " ".join(results[0]["warnings"])


def test_changed_directory_fails_before_start_unless_allowed(tmp_path: Path) -> None:
    config = base_config(tmp_path)
    source, job = create_job(tmp_path, config, directory=True)
    (source / "new.txt").write_text("changed", encoding="utf-8")
    runner = StubCreateSevenZip()

    results, _, code = execute_manifest([job], config, runner)

    assert (code, results[0]["status"], runner.create_calls) == (2, "failed", [])
    assert "identity changed" in " ".join(results[0]["warnings"])

    allowed = replace(config, allow_changed=True)
    results, _, code = execute_manifest([job], allowed, runner)
    assert (code, results[0]["status"]) == (1, "success")
    assert "continuing" in " ".join(results[0]["warnings"])


@pytest.mark.parametrize(
    ("policy", "status", "code", "name"),
    [
        ("fail", "failed", 2, "source.dat.7z"),
        ("skip", "skipped", 1, "source.dat.7z"),
        ("rename", "success", 0, "source.dat (2).7z"),
    ],
)
def test_existing_archive_policies(
    tmp_path: Path, policy: str, status: str, code: int, name: str
) -> None:
    config = base_config(tmp_path, existing=policy)
    _, job = create_job(tmp_path, config)
    existing = Path(job["destination"]["path"])
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"existing")

    results, _, actual_code = execute_manifest([job], config, StubCreateSevenZip())

    assert (actual_code, results[0]["status"]) == (code, status)
    assert Path(results[0]["output_dir"]).name == name
    assert existing.read_bytes() == b"existing"


def test_executor_rejects_edited_destination_inside_directory_source(tmp_path: Path) -> None:
    config = base_config(tmp_path)
    source, job = create_job(tmp_path, config, directory=True)
    job["destination"]["path"] = str(source / "unsafe.7z")
    job = validate_manifest([job], config)[0]
    runner = StubCreateSevenZip()

    results, _, code = execute_manifest([job], config, runner)

    assert (code, results[0]["status"], runner.create_calls) == (2, "failed", [])
    assert "inside the source" in " ".join(results[0]["warnings"])


def test_unowned_staging_is_never_moved_or_deleted(tmp_path: Path) -> None:
    config = base_config(tmp_path)
    _, job = create_job(tmp_path, config)
    runner = StubCreateSevenZip(create_outcome=ProcessOutcome(2, False), remove_marker=True)

    results, _, code = execute_manifest([job], config, runner)

    staging = Path(results[0]["staging_dir"])
    assert (code, results[0]["status"]) == (2, "failed")
    assert staging.name.endswith(".tmp")
    assert staging.is_dir()
    assert "unowned" in " ".join(results[0]["warnings"])


def test_finalize_archive_refuses_to_clobber_or_use_unowned_staging(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    staged = staging / "archive.7z"
    staged.write_bytes(b"new")
    final = tmp_path / "final.7z"

    with pytest.raises(OSError, match="unowned"):
        finalize_archive(staging, staged, final, "job")
    assert staged.read_bytes() == b"new"

    (staging / ".arcshuttle-owned").write_text("job\n", encoding="utf-8")
    final.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        finalize_archive(staging, staged, final, "job")
    assert final.read_bytes() == b"old"


def test_success_metadata_records_both_processes_and_commit(tmp_path: Path) -> None:
    config = base_config(tmp_path)
    _, job = create_job(tmp_path, config)

    results, _, _ = execute_manifest([job], config, StubCreateSevenZip())

    metadata = json.loads(
        (Path(results[0]["log_path"]) / "metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["commit"]["status"] == "committed"
    assert metadata["commit"]["final_path"] == results[0]["output_dir"]
