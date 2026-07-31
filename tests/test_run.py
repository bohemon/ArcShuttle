from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

import pytest

from arcshuttle.cli import execute_manifest
from arcshuttle.config import Config
from arcshuttle.manifest import calculate_integrity, make_plan, validate_manifest
from arcshuttle.multipart import MultipartInfo
from arcshuttle.sevenzip import ProcessOutcome


class StubSevenZip:
    def __init__(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.calls = 0

    def extract(
        self,
        *,
        archive: Path,
        staging: Path,
        threads: int,
        log_directory: Path,
        cpu_tokens: int,
        stop_event: threading.Event,
    ) -> ProcessOutcome:
        self.calls += 1
        log_directory.mkdir(parents=True)
        (log_directory / "stdout.log").write_text("stub", encoding="utf-8")
        (staging / "payload.txt").write_text("created", encoding="utf-8")
        return ProcessOutcome(self.exit_code, False)

    def interrupt_all(self) -> None:
        pass


def base_config(root: Path, **changes: object) -> Config:
    base = replace(
        Config(),
        output_dir=root / "outputs",
        log_dir=root / "logs",
        inspect_threshold=1000,
        small_threshold=1000,
        cpu_budget=2,
        max_processes=2,
        io_slots=2,
        quiet=True,
    )
    return replace(base, **changes)


def create_job(root: Path, config: Config) -> tuple[Path, dict[str, object]]:
    archive = root / "archive.zip"
    archive.write_bytes(b"archive")
    result = make_plan(
        [MultipartInfo(archive, False)],
        config,
        lambda path, timeout: (_ for _ in ()).throw(AssertionError("unexpected inspection")),
    )
    return archive, validate_manifest(result.jobs, config)[0]


def test_success_commits_staging(tmp_path: Path) -> None:
    config = base_config(tmp_path)
    _, job = create_job(tmp_path, config)

    results, summary, code = execute_manifest([job], config, StubSevenZip())

    assert (code, results[0]["status"], summary["success"]) == (0, "success", 1)
    output = Path(results[0]["output_dir"])
    assert (output / "payload.txt").is_file()
    assert results[0]["staging_dir"] is None


@pytest.mark.parametrize(
    ("exit_code", "status", "expected_code"),
    [(1, "warning", 1), (2, "failed", 2)],
)
def test_warning_and_failure_retain_staging(
    tmp_path: Path, exit_code: int, status: str, expected_code: int
) -> None:
    config = base_config(tmp_path)
    _, job = create_job(tmp_path, config)

    results, _, code = execute_manifest([job], config, StubSevenZip(exit_code))

    assert (results[0]["status"], code) == (status, expected_code)
    assert Path(results[0]["staging_dir"]).is_dir()
    assert not Path(results[0]["output_dir"]).exists()


def test_changed_source_fails_without_starting_process(tmp_path: Path) -> None:
    config = base_config(tmp_path)
    archive, job = create_job(tmp_path, config)
    archive.write_bytes(b"changed size")
    runner = StubSevenZip()

    results, _, code = execute_manifest([job], config, runner)

    assert (code, results[0]["status"], runner.calls) == (2, "failed", 0)
    assert "changed" in " ".join(results[0]["warnings"])


def test_allow_changed_continues_with_warning(tmp_path: Path) -> None:
    config = base_config(tmp_path, allow_changed=True)
    archive, job = create_job(tmp_path, config)
    archive.write_bytes(b"changed size")

    results, _, code = execute_manifest([job], config, StubSevenZip())

    assert code == 1
    assert "continuing" in " ".join(results[0]["warnings"])


@pytest.mark.parametrize(
    ("policy", "status", "expected_code"),
    [("fail", "failed", 2), ("skip", "skipped", 1), ("rename", "success", 0)],
)
def test_existing_policies(tmp_path: Path, policy: str, status: str, expected_code: int) -> None:
    config = base_config(tmp_path, existing=policy)
    _, job = create_job(tmp_path, config)
    Path(job["destination"]["path"]).mkdir(parents=True)

    results, _, actual_code = execute_manifest([job], config, StubSevenZip())

    assert (results[0]["status"], actual_code) == (status, expected_code)
    if policy == "rename":
        assert Path(results[0]["output_dir"]).name == "archive (2)"


def test_encrypted_archive_is_rejected(tmp_path: Path) -> None:
    config = base_config(tmp_path)
    _, job = create_job(tmp_path, config)
    job["archive"]["encrypted"] = True
    job["integrity"] = calculate_integrity(job)
    runner = StubSevenZip()

    results, _, code = execute_manifest([job], config, runner)

    assert (code, runner.calls, results[0]["status"]) == (2, 0, "failed")


def test_fail_fast_marks_unstarted_jobs_skipped(tmp_path: Path) -> None:
    config = base_config(tmp_path, fail_fast=True, max_processes=1, cpu_budget=1, io_slots=1)
    _, first = create_job(tmp_path, config)
    second_archive = tmp_path / "second.zip"
    second_archive.write_bytes(b"second")
    second = validate_manifest(
        make_plan([MultipartInfo(second_archive, False)], config, lambda path, timeout: None).jobs,
        config,
    )[0]

    results, summary, code = execute_manifest([first, second], config, StubSevenZip(2))

    assert code == 2
    assert {result["status"] for result in results} == {"failed", "skipped"}
    assert summary["total"] == 2
