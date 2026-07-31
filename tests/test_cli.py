from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from arcshuttle import cli, compat
from arcshuttle.config import Config
from arcshuttle.manifest import make_plan
from arcshuttle.multipart import MultipartInfo
from arcshuttle.sevenzip import ProcessOutcome


class PlanningSevenZip:
    executable = Path("fake-7z")

    def version(self) -> str:
        return "fake"

    def inspect(self, path: Path, timeout: float):
        raise AssertionError("inspection was not expected")


class FullSevenZip(PlanningSevenZip):
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
        log_directory.mkdir(parents=True)
        (log_directory / "stdout.log").write_text("ok", encoding="utf-8")
        (staging / "payload.txt").write_text("ok", encoding="utf-8")
        return ProcessOutcome(0, False)

    def interrupt_all(self) -> None:
        pass


def patch_sevenzip(monkeypatch: pytest.MonkeyPatch, instance: PlanningSevenZip) -> None:
    monkeypatch.setattr(cli, "find_executable", lambda configured: Path("fake"))
    monkeypatch.setattr(cli, "SevenZip", lambda executable: instance)


def test_plan_outputs_only_json_lines_to_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "空 白.zip"
    archive.write_bytes(b"zip")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(["plan", "--small-threshold", "1M", str(archive)])
    captured = capsys.readouterr()

    assert code == 0
    record = json.loads(captured.out)
    assert record["path"] == str(archive.resolve())
    assert "7-Zip" in captured.err


def test_no_implicit_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(["plan"])
    captured = capsys.readouterr()

    assert code == 64
    assert captured.out == ""


def test_explicit_empty_input_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = tmp_path / "paths.txt"
    paths.write_text("", encoding="utf-8")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(["plan", "--files-from", str(paths)])
    captured = capsys.readouterr()

    assert code == 64
    assert captured.out == ""


def test_input_failure_emits_no_partial_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "good.zip"
    archive.write_bytes(b"zip")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(["plan", str(archive), str(tmp_path / "missing.zip")])
    captured = capsys.readouterr()

    assert code == 64
    assert captured.out == ""
    assert "input error" in captured.err


def test_skip_input_errors_outputs_valid_jobs_and_returns_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "good.zip"
    archive.write_bytes(b"zip")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(
        [
            "plan",
            "--on-input-error",
            "skip",
            str(archive),
            str(tmp_path / "missing.zip"),
        ]
    )
    captured = capsys.readouterr()

    assert code == 1
    assert json.loads(captured.out)["record_type"] == "job"


def test_files_from_is_exclusive_with_paths(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(["plan", "--files-from", "-", "a.zip"])
    capsys.readouterr()

    assert code == 64


def test_malformed_manifest_is_cli_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("not json\n", encoding="utf-8")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(["run", "--manifest", str(manifest)])
    capsys.readouterr()

    assert code == 64


def test_plan_filter_run_contract_emits_result_then_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "archive.zip"
    archive.write_bytes(b"zip")
    config = Config(output_dir=tmp_path / "out", inspect_threshold=1000, small_threshold=1000)
    planning = make_plan([MultipartInfo(archive, False)], config, PlanningSevenZip().inspect)
    planning.jobs[0]["tags"] = ["filtered"]
    manifest = tmp_path / "plan.jsonl"
    manifest.write_text(json.dumps(planning.jobs[0]) + "\n", encoding="utf-8")
    patch_sevenzip(monkeypatch, FullSevenZip())

    code = compat.parxtract_main(
        ["run", "--quiet", "--manifest", str(manifest), "--log-dir", str(tmp_path / "logs")]
    )
    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.splitlines()]

    assert code == 0
    assert [record["record_type"] for record in records] == ["result", "summary"]
    assert records[0]["status"] == "success"


def test_extract_convenience_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "archive.zip"
    archive.write_bytes(b"zip")
    patch_sevenzip(monkeypatch, FullSevenZip())

    code = compat.parxtract_main(
        [
            "extract",
            "--quiet",
            "--output-dir",
            str(tmp_path / "out"),
            "--log-dir",
            str(tmp_path / "logs"),
            str(archive),
        ]
    )
    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.splitlines()]

    assert (code, records[0]["status"]) == (0, "success")
    assert (tmp_path / "out" / "archive" / "payload.txt").is_file()
